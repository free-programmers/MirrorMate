from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .errors import MirrorMateError, PermissionDeniedError
from .io import FileState, atomic_write, capture_file, restore_file, sha256_bytes
from .platform import UserContext


def user_backup_root(user: UserContext) -> Path:
    return user.home / ".local/state/mirrormate/backups"


def system_backup_root(root: Path = Path("/")) -> Path:
    return root / "var/lib/mirrormate/backups"


def backup_root(category: str, user: UserContext, root: Path = Path("/")) -> Path:
    return system_backup_root(root) if category in {"apt", "docker"} else user_backup_root(user)


def snapshot_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(3)}"


def create_snapshot(
    category: str,
    paths: Iterable[Path],
    *,
    user: UserContext,
    root: Path = Path("/"),
) -> str:
    identifier = snapshot_id()
    destination = backup_root(category, user, root) / identifier
    files_dir = destination / "files"
    files_dir.mkdir(parents=True, exist_ok=False)
    entries = []
    for index, path in enumerate(dict.fromkeys(paths)):
        state = capture_file(path)
        stored = None
        checksum = None
        if state.existed:
            stored = f"files/{index:04d}"
            atomic_write(destination / stored, state.content, mode=0o600)
            checksum = sha256_bytes(state.content)
        entries.append(
            {
                "path": str(path),
                "existed": state.existed,
                "stored": stored,
                "sha256": checksum,
                "mode": state.mode,
                "uid": state.uid,
                "gid": state.gid,
            }
        )
    manifest = {
        "schema_version": 1,
        "id": identifier,
        "category": category,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": entries,
    }
    atomic_write(
        destination / "manifest.json",
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        mode=0o644 if category in {"apt", "docker"} else 0o600,
    )
    if category not in {"apt", "docker"} and os.geteuid() == 0:
        for path in [destination, files_dir, *destination.rglob("*")]:
            try:
                os.chown(path, user.uid, user.gid)
            except OSError:
                pass
    return identifier


def _manifest_paths(user: UserContext, root: Path) -> list[Path]:
    roots = [user_backup_root(user)]
    system = system_backup_root(root)
    if system not in roots:
        roots.append(system)
    manifests: list[Path] = []
    for base in roots:
        if base.is_dir():
            manifests.extend(base.glob("*/manifest.json"))
    return manifests


def list_snapshots(user: UserContext, root: Path = Path("/")) -> list[dict[str, object]]:
    result = []
    for manifest_path in _manifest_paths(user, root):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        result.append(
            {
                "id": manifest.get("id"),
                "category": manifest.get("category"),
                "created_at": manifest.get("created_at"),
                "path": str(manifest_path.parent),
            }
        )
    return sorted(result, key=lambda item: str(item.get("created_at", "")), reverse=True)


def _allowed_restore_path(category: str, path: Path, user: UserContext, root: Path) -> bool:
    resolved = path.resolve(strict=False)
    if category == "apt":
        apt_root = (root / "etc/apt").resolve(strict=False)
        state_file = (root / "var/lib/mirrormate/state.json").resolve(strict=False)
        return resolved == state_file or resolved == apt_root or apt_root in resolved.parents
    if category == "docker":
        return resolved in {
            (root / "etc/docker/daemon.json").resolve(strict=False),
            (root / "var/lib/mirrormate/state.json").resolve(strict=False),
        }
    allowed = {
        "python": user.home / ".config/pip/pip.conf",
        "npm": user.home / ".npmrc",
        "go": user.home / ".config/go/env",
    }.get(category)
    return allowed is not None and resolved == allowed.resolve(strict=False)


def _find_manifest(identifier: str, user: UserContext, root: Path) -> Path:
    if not identifier or "/" in identifier or identifier.startswith("."):
        raise MirrorMateError("Invalid backup id")
    for base in (user_backup_root(user), system_backup_root(root)):
        candidate = base / identifier / "manifest.json"
        if candidate.is_file():
            return candidate
    raise MirrorMateError(f"Backup not found: {identifier}")


def restore_snapshot(
    identifier: str,
    *,
    user: UserContext,
    root: Path = Path("/"),
    after_restore: Callable[[str], list[str]] | None = None,
) -> dict[str, object]:
    manifest_path = _find_manifest(identifier, user, root)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MirrorMateError(f"Cannot read backup {identifier}: {exc}") from exc
    if manifest.get("schema_version") != 1 or manifest.get("id") != identifier:
        raise MirrorMateError("Unsupported or invalid backup manifest")
    category = str(manifest.get("category"))
    system_root = system_backup_root(root).resolve(strict=False)
    manifest_is_system = system_root in manifest_path.resolve(strict=False).parents
    if category in {"apt", "docker"} and not manifest_is_system:
        raise MirrorMateError("System backups can only be restored from the protected system backup directory")
    if category not in {"apt", "docker"} and manifest_is_system:
        raise MirrorMateError("User backups cannot be restored from the system backup directory")
    if category in {"apt", "docker"} and os.geteuid() != 0:
        raise PermissionDeniedError(f"Restoring {category} requires root; rerun with sudo")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise MirrorMateError("Backup manifest has no files array")
    states: list[FileState] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise MirrorMateError("Invalid file entry in backup manifest")
        path = Path(entry["path"])
        if not _allowed_restore_path(category, path, user, root):
            raise MirrorMateError(f"Backup contains a path outside the allowed area: {path}")
        existed = bool(entry.get("existed"))
        content = b""
        if existed:
            stored = entry.get("stored")
            if not isinstance(stored, str) or Path(stored).is_absolute() or ".." in Path(stored).parts:
                raise MirrorMateError("Invalid stored path in backup manifest")
            content = (manifest_path.parent / stored).read_bytes()
            if sha256_bytes(content) != entry.get("sha256"):
                raise MirrorMateError(f"Checksum mismatch in backup for {path}")
        states.append(
            FileState(
                path=path,
                existed=existed,
                content=content,
                mode=int(entry.get("mode") or 0o644) & 0o777,
                uid=user.uid if category not in {"apt", "docker"} else entry.get("uid"),
                gid=user.gid if category not in {"apt", "docker"} else entry.get("gid"),
            )
        )
    previous = [capture_file(state.path) for state in states]
    warnings: list[str] = []
    try:
        for state in states:
            restore_file(state)
        if after_restore:
            warnings = after_restore(category)
    except BaseException:
        for state in reversed(previous):
            restore_file(state)
        raise
    return {
        "id": identifier,
        "category": category,
        "restored_files": len(states),
        "warnings": warnings,
    }
