from __future__ import annotations

import os
import platform as std_platform
import pwd
from dataclasses import dataclass
from pathlib import Path

from .errors import PermissionDeniedError, UsageError
from .models import DISTROS, DistroInfo


SUPPORTED_RELEASES = {
    "ubuntu": {"22.04", "24.04", "26.04"},
    "debian": {"12", "13"},
}


@dataclass(frozen=True, slots=True)
class UserContext:
    name: str
    uid: int
    gid: int
    home: Path


def _parse_os_release(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise UsageError(f"Cannot read {path}: {exc}") from exc
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def normalize_architecture(machine: str) -> str:
    aliases = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "i386": "i386",
        "i686": "i386",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armhf",
        "ppc64le": "ppc64el",
    }
    return aliases.get(machine.lower(), machine.lower())


def detect_distro(root: Path = Path("/"), architecture: str | None = None) -> DistroInfo:
    values = _parse_os_release(root / "etc/os-release")
    distro_id = values.get("ID", "").lower()
    codename = values.get("VERSION_CODENAME") or values.get("UBUNTU_CODENAME", "")
    version_id = values.get("VERSION_ID", "")
    if distro_id not in DISTROS:
        raise UsageError(f"Unsupported distribution: {distro_id or 'unknown'}")
    if not codename:
        raise UsageError("VERSION_CODENAME is missing from /etc/os-release")
    arch = normalize_architecture(architecture or std_platform.machine())
    return DistroInfo(distro_id, version_id, codename, arch)


def ensure_supported(distro: DistroInfo) -> None:
    supported = SUPPORTED_RELEASES.get(distro.id, set())
    if distro.version_id not in supported:
        versions = ", ".join(sorted(supported))
        raise UsageError(
            f"{distro.id} {distro.version_id or 'unknown'} is not supported; "
            f"supported versions: {versions}"
        )


def invoking_user(environ: dict[str, str] | None = None) -> UserContext:
    env = environ if environ is not None else os.environ
    uid = os.geteuid()
    if uid == 0 and env.get("SUDO_UID", "").isdigit():
        uid = int(env["SUDO_UID"])
    try:
        record = pwd.getpwuid(uid)
    except KeyError as exc:
        raise UsageError(f"Cannot resolve user for uid {uid}") from exc
    return UserContext(record.pw_name, record.pw_uid, record.pw_gid, Path(record.pw_dir))


def require_root(action: str) -> None:
    if os.geteuid() != 0:
        raise PermissionDeniedError(f"{action} requires root; rerun the command with sudo")


def rooted(root: Path, absolute_path: Path) -> Path:
    if not absolute_path.is_absolute():
        raise ValueError(f"Expected an absolute path: {absolute_path}")
    return root / absolute_path.relative_to("/")
