from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from ..errors import UsageError
from ..io import capture_file
from ..models import ChangePlan, Mirror, PlannedFile
from .base import Adapter


class DockerAdapter(Adapter):
    category = "docker"
    requires_root = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config_path = self.root / "etc/docker/daemon.json"
        self.state_path = self.root / "var/lib/mirrormate/state.json"

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise UsageError(f"Cannot parse {self.config_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise UsageError(f"{self.config_path} must contain a JSON object")
        return raw

    def _read_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        if mirror.type != "docker" or not mirror.url:
            raise UsageError("A Docker mirror URL is required")
        state = capture_file(self.config_path)
        config = self._read()
        program_state = self._read_state()
        docker_state = program_state.get("docker", {})
        previous_insecure = (
            docker_state.get("managed_insecure_host") if isinstance(docker_state, dict) else None
        )
        insecure = config.get("insecure-registries", [])
        if not isinstance(insecure, list) or not all(isinstance(item, str) for item in insecure):
            raise UsageError("Docker insecure-registries must be an array of strings")
        if previous_insecure in insecure:
            insecure.remove(previous_insecure)
        if mirror.default:
            config.pop("registry-mirrors", None)
            summary = "Restore Docker Hub's default registry behavior"
        else:
            config["registry-mirrors"] = [mirror.url]
            summary = f"Set Docker registry mirror to {mirror.url}"
        if mirror.insecure:
            if not options.get("allow_insecure"):
                raise UsageError(
                    "This mirror is marked insecure; pass --allow-insecure to add it to insecure-registries"
                )
            host = urlparse(mirror.url).netloc
            if host not in insecure:
                insecure.append(host)
        if insecure:
            config["insecure-registries"] = insecure
        else:
            config.pop("insecure-registries", None)
        content = (
            state.content
            if mirror.default and not state.existed and not config
            else (json.dumps(config, indent=2, sort_keys=True) + "\n").encode()
        )
        planned = [
            PlannedFile(
                self.config_path,
                content,
                state.mode if state.existed else 0o644,
                state.uid,
                state.gid,
            )
        ]
        if not mirror.default or "docker" in program_state:
            program_state["schema_version"] = 1
            program_state["docker"] = {
                "mirror_id": mirror.id,
                "managed_insecure_host": urlparse(mirror.url).netloc if mirror.insecure else None,
            }
            old_program_state = capture_file(self.state_path)
            planned.append(
                PlannedFile(
                    self.state_path,
                    (json.dumps(program_state, indent=2, sort_keys=True) + "\n").encode(),
                    old_program_state.mode if old_program_state.existed else 0o600,
                    old_program_state.uid,
                    old_program_state.gid,
                )
            )
        return ChangePlan(
            "docker",
            mirror,
            planned,
            summary,
        )

    def activate(self, plan: ChangePlan, **options: Any) -> list[str]:
        warnings = []
        if self.runner.which("dockerd"):
            self.runner.run(
                ["dockerd", "--validate", "--config-file", str(self.config_path)],
                check=True,
            )
        if self.runner.which("systemctl"):
            active = self.runner.run(
                ["systemctl", "is-active", "--quiet", "docker"],
                check=False,
            )
            if active.returncode == 0:
                reloaded = self.runner.run(["systemctl", "reload", "docker"], check=False)
                if reloaded.returncode != 0:
                    warnings.append("Docker is active but could not be reloaded; reload or restart it manually")
            else:
                warnings.append("Docker is not active; the new configuration will apply on its next start")
        else:
            warnings.append("No systemd was found; reload the Docker daemon manually")
        return warnings

    def status(self) -> dict[str, Any]:
        config = self._read()
        return {
            "type": "docker",
            "path": str(self.config_path),
            "registry_mirrors": config.get("registry-mirrors", []),
            "insecure_registries": config.get("insecure-registries", []),
        }
