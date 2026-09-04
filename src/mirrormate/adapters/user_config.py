from __future__ import annotations

import configparser
import io
import re
from pathlib import Path
from typing import Any

from ..errors import UsageError
from ..io import capture_file
from ..models import ChangePlan, Mirror, PlannedFile
from .base import Adapter


class UserConfigAdapter(Adapter):
    config_path: Path

    def _planned_file(self, content: str) -> PlannedFile:
        state = capture_file(self.config_path)
        return PlannedFile(
            path=self.config_path,
            content=content.encode("utf-8"),
            mode=state.mode if state.existed else 0o600,
            uid=self.user.uid,
            gid=self.user.gid,
        )

    def _read(self) -> str:
        try:
            return self.config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except (OSError, UnicodeDecodeError) as exc:
            raise UsageError(f"Cannot read {self.config_path}: {exc}") from exc


class PythonAdapter(UserConfigAdapter):
    category = "python"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config_path = self.user.home / ".config/pip/pip.conf"

    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        if mirror.type != self.category or not mirror.url:
            raise UsageError("A Python mirror URL is required")
        parser = configparser.RawConfigParser()
        current = self._read()
        if current:
            try:
                parser.read_string(current)
            except configparser.Error as exc:
                raise UsageError(f"Cannot parse {self.config_path}: {exc}") from exc
        if not parser.has_section("global"):
            parser.add_section("global")
        parser.set("global", "index-url", mirror.url)
        buffer = io.StringIO()
        parser.write(buffer)
        return ChangePlan(
            self.category,
            mirror,
            [self._planned_file(buffer.getvalue())],
            f"Set pip index-url to {mirror.url}",
        )

    def status(self) -> dict[str, Any]:
        value = None
        parser = configparser.RawConfigParser()
        current = self._read()
        if current:
            try:
                parser.read_string(current)
                value = parser.get("global", "index-url", fallback=None)
            except configparser.Error:
                value = None
        return {"type": self.category, "path": str(self.config_path), "url": value}


def _replace_assignment(content: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=).*$", re.MULTILINE)
    replacement = rf"\g<1>{value}"
    if pattern.search(content):
        updated = pattern.sub(replacement, content)
    else:
        separator = "" if not content or content.endswith("\n") else "\n"
        updated = f"{content}{separator}{key}={value}\n"
    return updated


def _read_assignment(content: str, key: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", re.MULTILINE)
    match = pattern.search(content)
    return match.group(1) if match else None


class NpmAdapter(UserConfigAdapter):
    category = "npm"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config_path = self.user.home / ".npmrc"

    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        if mirror.type != self.category or not mirror.url:
            raise UsageError("An NPM mirror URL is required")
        content = _replace_assignment(self._read(), "registry", mirror.url)
        return ChangePlan(
            self.category,
            mirror,
            [self._planned_file(content)],
            f"Set NPM registry to {mirror.url}",
        )

    def status(self) -> dict[str, Any]:
        return {
            "type": self.category,
            "path": str(self.config_path),
            "url": _read_assignment(self._read(), "registry"),
        }


class GoAdapter(UserConfigAdapter):
    category = "go"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config_path = self.user.home / ".config/go/env"

    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        if mirror.type != self.category or not mirror.url:
            raise UsageError("A Go proxy URL is required")
        content = _replace_assignment(self._read(), "GOPROXY", mirror.url)
        return ChangePlan(
            self.category,
            mirror,
            [self._planned_file(content)],
            f"Set GOPROXY to {mirror.url}",
        )

    def status(self) -> dict[str, Any]:
        return {
            "type": self.category,
            "path": str(self.config_path),
            "url": _read_assignment(self._read(), "GOPROXY"),
        }
