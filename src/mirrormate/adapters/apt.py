from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..errors import MirrorMateError, UsageError
from ..io import capture_file
from ..models import ChangePlan, Mirror, PlannedFile
from .base import Adapter


LIST_PATTERN = re.compile(
    r"^(?P<prefix>\s*deb(?:-src)?\s+(?:\[[^\]]+\]\s+)?)"
    r"(?P<uri>\S+)(?P<middle>\s+)(?P<suite>\S+)(?P<rest>.*)$"
)
FIELD_PATTERN = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9-]*):(?P<value>.*)$")


class AptAdapter(Adapter):
    category = "apt"
    requires_root = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if self.distro is None:
            raise UsageError("APT operations require detected distribution information")
        self.apt_root = self.root / "etc/apt"
        self.state_path = self.root / "var/lib/mirrormate/state.json"

    def _source_files(self) -> list[Path]:
        files = []
        main = self.apt_root / "sources.list"
        if main.is_file():
            files.append(main)
        directory = self.apt_root / "sources.list.d"
        if directory.is_dir():
            files.extend(sorted(directory.glob("*.list")))
            files.extend(sorted(directory.glob("*.sources")))
        return files

    def _read_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def _known_urls(self) -> set[str]:
        urls: set[str] = set()
        for mirror in self.catalog:
            if mirror.type == "apt" and mirror.distro == self.distro.id:
                if mirror.archive_url:
                    urls.add(mirror.archive_url.rstrip("/"))
                if mirror.security_url:
                    urls.add(mirror.security_url.rstrip("/"))
        state = self._read_state().get("apt", {})
        if isinstance(state, dict):
            for value in state.get("managed_urls", []):
                if isinstance(value, str):
                    urls.add(value.rstrip("/"))
        return urls

    def _suite_kind(self, suite: str) -> str | None:
        codename = self.distro.codename
        if suite == f"{codename}-security":
            return "security"
        allowed = {
            codename,
            f"{codename}-updates",
            f"{codename}-backports",
            f"{codename}-proposed",
        }
        return "archive" if suite in allowed else None

    def _looks_official(self, uri: str) -> bool:
        parsed = urlparse(uri)
        host = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/")
        if self.distro.id == "ubuntu":
            return (
                host in {"archive.ubuntu.com", "security.ubuntu.com", "ports.ubuntu.com"}
                or host.endswith(".archive.ubuntu.com")
            ) and (path.endswith("/ubuntu") or path.endswith("/ubuntu-ports"))
        return host in {
            "deb.debian.org",
            "security.debian.org",
            "ftp.debian.org",
        } and (path.endswith("/debian") or path.endswith("/debian-security"))

    def _is_candidate(self, uri: str, known_urls: set[str]) -> bool:
        return uri.rstrip("/") in known_urls or self._looks_official(uri)

    def _rewrite_list(
        self,
        content: str,
        mirror: Mirror,
        known_urls: set[str],
    ) -> tuple[str, int, set[str]]:
        changed = 0
        applied: set[str] = set()
        output = []
        for line in content.splitlines(keepends=True):
            raw = line.rstrip("\r\n")
            ending = line[len(raw) :]
            match = LIST_PATTERN.match(raw)
            if not match:
                output.append(line)
                continue
            kind = self._suite_kind(match.group("suite"))
            current_uri = match.group("uri")
            if kind is None or not self._is_candidate(current_uri, known_urls):
                output.append(line)
                continue
            target = mirror.security_url if kind == "security" else mirror.archive_url
            if not target:
                output.append(line)
                continue
            replacement = (
                f"{match.group('prefix')}{target}{match.group('middle')}"
                f"{match.group('suite')}{match.group('rest')}{ending}"
            )
            output.append(replacement)
            applied.add(target.rstrip("/"))
            if replacement != line:
                changed += 1
        return "".join(output), changed, applied

    @staticmethod
    def _deb822_fields(lines: list[str]) -> dict[str, tuple[int, list[int], list[str]]]:
        fields: dict[str, tuple[int, list[int], list[str]]] = {}
        index = 0
        while index < len(lines):
            stripped = lines[index].rstrip("\r\n")
            match = FIELD_PATTERN.match(stripped)
            if not match:
                index += 1
                continue
            name = match.group("name").lower()
            indices = [index]
            values = [match.group("value").strip()]
            cursor = index + 1
            while cursor < len(lines) and lines[cursor][:1].isspace():
                indices.append(cursor)
                values.append(lines[cursor].strip())
                cursor += 1
            fields[name] = (index, indices, values)
            index = cursor
        return fields

    def _rewrite_deb822_block(
        self,
        block: str,
        mirror: Mirror,
        known_urls: set[str],
    ) -> tuple[str, int, set[str]]:
        lines = block.splitlines(keepends=True)
        fields = self._deb822_fields(lines)
        if not {"types", "uris", "suites"}.issubset(fields):
            return block, 0, set()
        types = " ".join(fields["types"][2]).split()
        if "deb" not in types and "deb-src" not in types:
            return block, 0, set()
        enabled = " ".join(fields.get("enabled", (0, [], ["yes"]))[2]).strip().lower()
        if enabled == "no":
            return block, 0, set()
        suites = " ".join(fields["suites"][2]).split()
        kinds = {kind for suite in suites if (kind := self._suite_kind(suite))}
        if not kinds:
            return block, 0, set()
        uris = " ".join(fields["uris"][2]).split()
        if not uris or not all(self._is_candidate(uri, known_urls) for uri in uris):
            return block, 0, set()
        if len(kinds) > 1 and mirror.archive_url != mirror.security_url:
            raise UsageError(
                "An APT deb822 stanza mixes archive and security suites; split it into separate stanzas first"
            )
        kind = next(iter(kinds))
        target = mirror.security_url if kind == "security" else mirror.archive_url
        if not target:
            return block, 0, set()
        first, indices, _ = fields["uris"]
        newline = "\r\n" if lines[first].endswith("\r\n") else "\n"
        lines[first] = f"URIs: {target}{newline}"
        for index in indices[1:]:
            lines[index] = ""
        updated = "".join(lines)
        return updated, int(updated != block), {target.rstrip("/")}

    def _rewrite_sources(
        self,
        content: str,
        mirror: Mirror,
        known_urls: set[str],
    ) -> tuple[str, int, set[str]]:
        parts = re.split(r"(\r?\n[ \t]*\r?\n)", content)
        changed = 0
        applied: set[str] = set()
        for index in range(0, len(parts), 2):
            parts[index], count, used = self._rewrite_deb822_block(parts[index], mirror, known_urls)
            changed += count
            applied.update(used)
        return "".join(parts), changed, applied

    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        if mirror.type != "apt" or mirror.distro != self.distro.id or not mirror.archive_url:
            raise UsageError(f"An APT mirror for {self.distro.id} is required")
        if mirror.architectures and self.distro.architecture not in mirror.architectures:
            raise UsageError(f"Mirror {mirror.id} does not support {self.distro.architecture}")
        files = self._source_files()
        if not files:
            raise UsageError(f"No APT source files were found below {self.apt_root}")
        known_urls = self._known_urls()
        planned: list[PlannedFile] = []
        total_changed = 0
        applied: set[str] = set()
        for path in files:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise UsageError(f"Cannot read {path}: {exc}") from exc
            if path.suffix == ".sources":
                updated, changed, used = self._rewrite_sources(content, mirror, known_urls)
            else:
                updated, changed, used = self._rewrite_list(content, mirror, known_urls)
            if changed:
                state = capture_file(path)
                planned.append(
                    PlannedFile(path, updated.encode(), state.mode, state.uid, state.gid)
                )
                total_changed += changed
                applied.update(used)
        if not planned:
            raise UsageError(
                "No matching distribution sources were found; only official, catalog, or previously managed URLs are changed"
            )
        state = self._read_state()
        state["schema_version"] = 1
        state["apt"] = {
            "distro": self.distro.id,
            "codename": self.distro.codename,
            "mirror_id": mirror.id,
            "managed_urls": sorted(applied),
            "files": [str(item.path) for item in planned],
        }
        old_state = capture_file(self.state_path)
        planned.append(
            PlannedFile(
                self.state_path,
                (json.dumps(state, indent=2, sort_keys=True) + "\n").encode(),
                old_state.mode if old_state.existed else 0o600,
                old_state.uid,
                old_state.gid,
            )
        )
        return ChangePlan(
            "apt",
            mirror,
            planned,
            f"Update {total_changed} APT source entries to {mirror.name}",
            {"changed_entries": total_changed},
        )

    def activate(self, plan: ChangePlan, **options: Any) -> list[str]:
        if options.get("no_refresh"):
            return ["APT metadata refresh was skipped"]
        if not self.runner.which("apt-get"):
            raise MirrorMateError("apt-get is required to validate APT sources")
        self.runner.run(["apt-get", "update"])
        return []

    def _status_list(
        self, path: Path, content: str, known_urls: set[str]
    ) -> list[dict[str, str]]:
        entries = []
        for line in content.splitlines():
            match = LIST_PATTERN.match(line)
            if (
                match
                and self._suite_kind(match.group("suite"))
                and self._is_candidate(match.group("uri"), known_urls)
            ):
                entries.append(
                    {"path": str(path), "suite": match.group("suite"), "url": match.group("uri")}
                )
        return entries

    def _status_sources(
        self, path: Path, content: str, known_urls: set[str]
    ) -> list[dict[str, str]]:
        entries = []
        for block in re.split(r"\r?\n[ \t]*\r?\n", content):
            fields = self._deb822_fields(block.splitlines(keepends=True))
            if not {"uris", "suites"}.issubset(fields):
                continue
            suites = " ".join(fields["suites"][2]).split()
            if not any(self._suite_kind(suite) for suite in suites):
                continue
            for uri in " ".join(fields["uris"][2]).split():
                if self._is_candidate(uri, known_urls):
                    entries.append({"path": str(path), "suite": " ".join(suites), "url": uri})
        return entries

    def status(self) -> dict[str, Any]:
        entries: list[dict[str, str]] = []
        known_urls = self._known_urls()
        for path in self._source_files():
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if path.suffix == ".sources":
                entries.extend(self._status_sources(path, content, known_urls))
            else:
                entries.extend(self._status_list(path, content, known_urls))
        return {"type": "apt", "distro": self.distro.id, "entries": entries}
