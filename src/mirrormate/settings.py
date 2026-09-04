from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import UsageError
from .io import atomic_write
from .platform import UserContext
from .themes import DEFAULT_THEME, THEMES


SCHEMA_VERSION = 1
ALLOWED_ATTEMPTS = (1, 3, 5)
ALLOWED_TIMEOUTS = (2.0, 3.0, 5.0, 10.0)


@dataclass(frozen=True, slots=True)
class TuiSettings:
    auto_benchmark: bool = False
    benchmark_attempts: int = 3
    benchmark_timeout: float = 3.0
    sort_by_speed: bool = True
    theme: str = DEFAULT_THEME

    def to_document(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


def settings_path(user: UserContext) -> Path:
    return user.home / ".config/mirrormate/settings.json"


def _validated_document(raw: Any) -> TuiSettings:
    if not isinstance(raw, dict):
        raise UsageError("TUI settings must be a JSON object")
    allowed = {
        "schema_version",
        "auto_benchmark",
        "benchmark_attempts",
        "benchmark_timeout",
        "sort_by_speed",
        "theme",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise UsageError(f"Unknown TUI settings: {', '.join(unknown)}")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise UsageError(
            f"Unsupported TUI settings schema_version: {raw.get('schema_version')!r}"
        )

    auto_benchmark = raw.get("auto_benchmark", False)
    sort_by_speed = raw.get("sort_by_speed", True)
    attempts = raw.get("benchmark_attempts", 3)
    timeout = raw.get("benchmark_timeout", 3.0)
    theme = raw.get("theme", DEFAULT_THEME)
    if not isinstance(auto_benchmark, bool) or not isinstance(sort_by_speed, bool):
        raise UsageError("TUI auto_benchmark and sort_by_speed must be true or false")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts not in ALLOWED_ATTEMPTS:
        choices = ", ".join(str(item) for item in ALLOWED_ATTEMPTS)
        raise UsageError(f"TUI benchmark_attempts must be one of: {choices}")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise UsageError("TUI benchmark_timeout must be a number")
    timeout = float(timeout)
    if timeout not in ALLOWED_TIMEOUTS:
        choices = ", ".join(f"{item:g}" for item in ALLOWED_TIMEOUTS)
        raise UsageError(f"TUI benchmark_timeout must be one of: {choices}")
    if not isinstance(theme, str) or theme not in THEMES:
        choices = ", ".join(THEMES)
        raise UsageError(f"TUI theme must be one of: {choices}")
    return TuiSettings(auto_benchmark, attempts, timeout, sort_by_speed, theme)


def load_settings(user: UserContext) -> TuiSettings:
    path = settings_path(user)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return TuiSettings()
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"Cannot read TUI settings {path}: {exc}") from exc
    return _validated_document(raw)


def save_settings(settings: TuiSettings, user: UserContext) -> Path:
    validated = _validated_document(settings.to_document())
    path = settings_path(user)
    content = (json.dumps(validated.to_document(), indent=2, sort_keys=True) + "\n").encode()
    atomic_write(path, content, mode=0o600, uid=user.uid, gid=user.gid)
    return path
