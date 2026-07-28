from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol

from backend.core.cycle_package import CyclePackage, CycleTick
from backend.util.cycle_replay.types import EntryEvent, ExitEvent, ReplayPosition


class StrategyAdapter(Protocol):
    """Pure offline strategy surface. No HTTP, no live supervisors."""

    name: str

    def would_enter(
        self,
        tick: CycleTick,
        pkg: CyclePackage,
        settings: Mapping[str, Any],
        *,
        already_in_position: bool,
    ) -> Optional[EntryEvent]:
        ...

    def would_exit(
        self,
        tick: CycleTick,
        pkg: CyclePackage,
        settings: Mapping[str, Any],
        position: ReplayPosition,
        *,
        floor_confirm_count: int,
    ) -> tuple[Optional[ExitEvent], int]:
        """Returns (exit_or_None, updated_floor_confirm_count)."""
        ...
