from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..models import ChangePlan, Mirror
from ..platform import DistroInfo, UserContext
from ..runner import CommandRunner


class Adapter(ABC):
    category: str
    requires_root = False

    def __init__(
        self,
        *,
        root: Path,
        user: UserContext,
        runner: CommandRunner,
        distro: DistroInfo | None = None,
        catalog: list[Mirror] | None = None,
    ) -> None:
        self.root = root
        self.user = user
        self.runner = runner
        self.distro = distro
        self.catalog = catalog or []

    @abstractmethod
    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    def activate(self, plan: ChangePlan, **options: Any) -> list[str]:
        return []
