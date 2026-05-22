"""Live_state hot path — ON by default (v3.7+). Opt out only for local/debug."""

from __future__ import annotations

import os


def _explicitly_off(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("0", "false", "no", "off")


def _explicitly_on(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def live_state_cache_enabled() -> bool:
    """Redis live_state is the production hot path unless explicitly disabled."""
    if _explicitly_off("LIVE_STATE_CACHE_ENABLED"):
        return False
    if _explicitly_on("LIVE_STATE_CACHE_ENABLED"):
        return True
    return True


def live_state_pg_writes_enabled() -> bool:
    """Dual-write to PG is opt-in only (off by default)."""
    if _truthy_legacy("LIVE_STATE_PG_WRITES"):
        return True
    if os.getenv("LIVE_STATE_PG_WRITES", "").strip() == "":
        return _explicitly_on("LIVE_STATE_DUAL_WRITE_PG")
    return False


def live_state_spool_enabled() -> bool:
    """Async tick spool is opt-in only."""
    if _truthy_legacy("LIVE_STATE_SPOOL"):
        return True
    return _explicitly_on("LIVE_STATE_SPOOL_ENABLED")


def live_state_use_tick_buffer() -> bool:
    """In-process tick ring for symbol hot path (no per-tick PG reads)."""
    if not live_state_cache_enabled():
        return False
    if _explicitly_off("LIVE_STATE_USE_TICK_BUFFER"):
        return False
    return True


def probability_lookup_ram_enabled() -> bool:
    """In-process probability tables for strike gen (no per-strike PG lookups)."""
    if _explicitly_off("PROBABILITY_LOOKUP_RAM"):
        return False
    return True


def _truthy_legacy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")
