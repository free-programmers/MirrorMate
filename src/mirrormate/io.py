from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FileState:
    path: Path
    existed: bool
    content: bytes = b""
    mode: int = 0o644
    uid: int | None = None
    gid: int | None = None


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def capture_file(path: Path) -> FileState:
    try:
        stat = path.stat()
        return FileState(
            path=path,
            existed=True,
            content=path.read_bytes(),
            mode=stat.st_mode & 0o7777,
            uid=stat.st_uid,
            gid=stat.st_gid,
        )
    except FileNotFoundError:
        return FileState(path=path, existed=False)


def atomic_write(
    path: Path,
    content: bytes,
    *,
    mode: int = 0o644,
    uid: int | None = None,
    gid: int | None = None,
) -> None:
    missing_parents = []
    cursor = path.parent
    while not cursor.exists():
        missing_parents.append(cursor)
        cursor = cursor.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    if uid is not None or gid is not None:
        for directory in reversed(missing_parents):
            os.chown(directory, -1 if uid is None else uid, -1 if gid is None else gid)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        if uid is not None or gid is not None:
            os.chown(temp_path, -1 if uid is None else uid, -1 if gid is None else gid)
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def restore_file(state: FileState) -> None:
    if not state.existed:
        try:
            state.path.unlink()
        except FileNotFoundError:
            pass
        return
    atomic_write(
        state.path,
        state.content,
        mode=state.mode,
        uid=state.uid,
        gid=state.gid,
    )
