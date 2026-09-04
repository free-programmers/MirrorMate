from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .errors import MirrorMateError
from .platform import UserContext


class CommandRunner:
    def which(self, command: str) -> str | None:
        return shutil.which(command)

    def run(
        self,
        args: list[str],
        *,
        user: UserContext | None = None,
        check: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        kwargs: dict[str, object] = {
            "args": args,
            "check": False,
            "capture_output": capture_output,
            "text": True,
            "env": env,
        }
        if user is not None:
            env["HOME"] = str(user.home)
            env["USER"] = user.name
            env["LOGNAME"] = user.name
            if os.geteuid() == 0 and user.uid != 0:
                kwargs.update(user=user.uid, group=user.gid, extra_groups=[])
        process = subprocess.run(**kwargs)  # type: ignore[arg-type]
        if check and process.returncode != 0:
            detail = (process.stderr or process.stdout or "").strip()
            suffix = f": {detail}" if detail else ""
            raise MirrorMateError(f"Command failed ({' '.join(args)}){suffix}")
        return process
