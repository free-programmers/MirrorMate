from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


MIRROR_TYPES = ("apt", "python", "npm", "go", "docker")
DISTROS = ("ubuntu", "debian")


@dataclass(frozen=True, slots=True)
class Mirror:
    id: str
    type: str
    name: str
    url: str | None = None
    distro: str | None = None
    archive_url: str | None = None
    security_url: str | None = None
    probe_url: str | None = None
    architectures: tuple[str, ...] = ()
    insecure: bool = False
    default: bool = False
    source: str = "custom"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["architectures"] = list(self.architectures)
        return {key: value for key, value in data.items() if value not in (None, (), [], False)}


@dataclass(frozen=True, slots=True)
class DistroInfo:
    id: str
    version_id: str
    codename: str
    architecture: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class PlannedFile:
    path: Path
    content: bytes
    mode: int = 0o644
    uid: int | None = None
    gid: int | None = None


@dataclass(slots=True)
class ChangePlan:
    category: str
    mirror: Mirror
    files: list[PlannedFile]
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    mirror_id: str
    name: str
    url: str
    healthy: bool
    median_ms: float | None
    attempts: int
    successful_attempts: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
