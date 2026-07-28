"""Strategy-agnostic cycle-package replay (parity-first + live diagnostics).

Replay-vs-live entry/exit gaps are investigation inputs for the live stack
(feed, ladder, AES cadence). Do not add silent lag padding; see
``docs/BACKTESTING.md`` §2.3.
"""

from __future__ import annotations

from backend.util.cycle_replay.runner import ReplayResult, run_cycle_replay
from backend.util.cycle_replay.types import EntryEvent, ExitEvent, ReplayPosition

__all__ = [
    "EntryEvent",
    "ExitEvent",
    "ReplayPosition",
    "ReplayResult",
    "run_cycle_replay",
]
