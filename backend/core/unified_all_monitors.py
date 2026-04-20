"""
Active 15m + hourly monitors for a single unified AES/ATS process (legacy ``users.monitor_list_<slot>`` SQL).
"""
from __future__ import annotations

from typing import Iterator, List, Tuple

from backend.core.unified_15m_monitors import iter_active_15m_monitor_bindings, list_active_15m_monitor_rows
from backend.core.unified_hourly_monitors import iter_active_hourly_monitor_bindings, list_active_hourly_monitor_rows


def list_active_unified_monitor_rows() -> List[dict]:
    """All active monitors that use the unified AES/ATS pool (15m and non-15m / hourly ladder)."""
    return list_active_15m_monitor_rows() + list_active_hourly_monitor_rows()


def iter_active_unified_monitor_bindings() -> Iterator[Tuple[str, str]]:
    """Yield (user_number, monitor_id) for every active 15m then hourly-pool monitor."""
    yield from iter_active_15m_monitor_bindings()
    yield from iter_active_hourly_monitor_bindings()
