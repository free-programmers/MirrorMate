from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from .adapters import AptAdapter, DockerAdapter, GoAdapter, NpmAdapter, PythonAdapter
from .adapters.base import Adapter
from .backup import create_snapshot, restore_snapshot
from .errors import UsageError
from .io import atomic_write, capture_file, restore_file
from .models import ChangePlan, DistroInfo, Mirror
from .platform import UserContext, detect_distro, ensure_supported, require_root
from .runner import CommandRunner


ADAPTERS: dict[str, type[Adapter]] = {
    "apt": AptAdapter,
    "python": PythonAdapter,
    "npm": NpmAdapter,
    "go": GoAdapter,
    "docker": DockerAdapter,
}


class MirrorService:
    def __init__(
        self,
        *,
        catalog: list[Mirror],
        user: UserContext,
        root: Path = Path("/"),
        runner: CommandRunner | None = None,
        distro: DistroInfo | None = None,
    ) -> None:
        self.catalog = catalog
        self.user = user
        self.root = root
        self.runner = runner or CommandRunner()
        self._distro = distro

    def distro(self) -> DistroInfo:
        if self._distro is None:
            self._distro = detect_distro(self.root)
        return self._distro

    def adapter(self, category: str) -> Adapter:
        adapter_type = ADAPTERS.get(category)
        if adapter_type is None:
            raise UsageError(f"Unsupported mirror type: {category}")
        distro = self.distro() if category == "apt" else None
        if distro is not None:
            ensure_supported(distro)
        return adapter_type(
            root=self.root,
            user=self.user,
            runner=self.runner,
            distro=distro,
            catalog=self.catalog,
        )

    def status(self, category: str) -> dict[str, Any]:
        return self.adapter(category).status()

    def restore(self, identifier: str, *, no_refresh: bool = False) -> dict[str, object]:
        def activate(category: str) -> list[str]:
            if category == "apt":
                if no_refresh:
                    return ["APT metadata refresh was skipped"]
                if not self.runner.which("apt-get"):
                    raise UsageError("apt-get is required to validate restored APT sources")
                self.runner.run(["apt-get", "update"])
                return []
            if category == "docker":
                adapter = DockerAdapter(
                    root=self.root,
                    user=self.user,
                    runner=self.runner,
                    catalog=self.catalog,
                )
            else:
                adapter = self.adapter(category)
            placeholder = Mirror(
                id="restored-backup",
                type=category,
                name="Restored backup",
                url="https://invalid.local" if category != "apt" else None,
            )
            return adapter.activate(ChangePlan(category, placeholder, [], "Restore backup"))

        return restore_snapshot(
            identifier,
            user=self.user,
            root=self.root,
            after_restore=activate,
        )

    @staticmethod
    def _diff(plan: ChangePlan) -> str:
        output = []
        for item in plan.files:
            try:
                before = item.path.read_text(encoding="utf-8").splitlines(keepends=True)
            except FileNotFoundError:
                before = []
            except UnicodeDecodeError:
                before = ["<binary content>\n"]
            try:
                after = item.content.decode("utf-8").splitlines(keepends=True)
            except UnicodeDecodeError:
                after = ["<binary content>\n"]
            output.extend(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=str(item.path),
                    tofile=str(item.path),
                )
            )
        return "".join(output)

    def plan(self, category: str, mirror: Mirror, **options: Any) -> ChangePlan:
        return self.adapter(category).plan(mirror, **options)

    def apply(
        self,
        category: str,
        mirror: Mirror,
        *,
        backup: bool = False,
        dry_run: bool = False,
        no_refresh: bool = False,
        allow_insecure: bool = False,
    ) -> dict[str, Any]:
        adapter = self.adapter(category)
        if adapter.requires_root and not dry_run:
            require_root(f"Changing {category} configuration")
        plan = adapter.plan(mirror, allow_insecure=allow_insecure)
        plan.files = [item for item in plan.files if capture_file(item.path).content != item.content]
        diff = self._diff(plan)
        result: dict[str, Any] = {
            "type": category,
            "mirror_id": mirror.id,
            "mirror_name": mirror.name,
            "summary": plan.summary,
            "changed_files": [str(item.path) for item in plan.files],
            "dry_run": dry_run,
            "backup_id": None,
            "warnings": [],
        }
        if dry_run or not plan.files:
            result["diff"] = diff
            return result
        states = [capture_file(item.path) for item in plan.files]
        if backup:
            result["backup_id"] = create_snapshot(
                category,
                [item.path for item in plan.files],
                user=self.user,
                root=self.root,
            )
        try:
            for item in plan.files:
                atomic_write(
                    item.path,
                    item.content,
                    mode=item.mode,
                    uid=item.uid,
                    gid=item.gid,
                )
            result["warnings"] = adapter.activate(plan, no_refresh=no_refresh)
        except BaseException:
            for state in reversed(states):
                restore_file(state)
            raise
        return result
