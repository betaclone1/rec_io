"""Feature flags for live_state Redis hot path."""

from __future__ import annotations

import os


def _truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def live_state_cache_enabled() -> bool:
    return _truthy("LIVE_STATE_CACHE_ENABLED", "0")


def live_state_pg_writes_enabled() -> bool:
    """When false with cache on, strike/market hot paths skip direct PG DML."""
    if _truthy("LIVE_STATE_PG_WRITES", ""):
        return True
    if os.getenv("LIVE_STATE_PG_WRITES", "").strip() == "":
        return _truthy("LIVE_STATE_DUAL_WRITE_PG", "0")
    return False


def live_state_spool_enabled() -> bool:
    if _truthy("LIVE_STATE_SPOOL", ""):
        return True
    return _truthy("LIVE_STATE_SPOOL_ENABLED", "0")


def live_state_use_tick_buffer() -> bool:
    return _truthy("LIVE_STATE_USE_TICK_BUFFER", "0")


def probability_lookup_ram_enabled() -> bool:
    return _truthy("PROBABILITY_LOOKUP_RAM", "0")
