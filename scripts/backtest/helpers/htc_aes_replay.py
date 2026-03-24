"""
Replay Hourly HTC auto-entry **strike gates** using ``backend.util.auto_entry_htc_gates``,
which intentionally **mirrors** (does not import) ``check_auto_entry_conditions_hourly_htc``
in ``auto_entry_supervisor.py`` so backtests never load or alter production supervisors.

Callers supply per-minute strike rows in the same shape as
``get_master_strike_table_data`` / ``live_data`` strike tables (including
``yes_diff``, ``no_diff``, ``active_side`` from the strike table generator).

TTC: use ``seconds_to_next_15m_boundary_ny`` to mirror
``strike_table_generator._seconds_to_next_15m_boundary_est`` for ``ttc_15m``-style
windows. Hourly contract replay uses ``seconds_to_next_hour_boundary_ny`` to mirror
``StrikeTableGenerator.calculate_ttc_seconds`` for hourly interval (next top-of-hour in ET).

**Kalshi ticker → contract interval (backtests):** if the ticker contains ``15M`` (case-insensitive),
e.g. ``KXBTC15M-...``, treat as **15m**; otherwise **hourly** (e.g. ``KXBTCD-...``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal, Mapping, Optional, Sequence

KalshiContractMarket = Literal["15m", "hourly"]

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

from backend.util.auto_entry_htc_gates import try_hourly_htc_strike_entry_payload


def infer_contract_market_from_kalshi_ticker(ticker: str) -> KalshiContractMarket:
    """
    Heuristic aligned with product naming: **15m** contracts include ``15M`` in the ticker
    (series prefix, e.g. ``KXBTC15M-26MAR220430-30``). **Hourly** (non-15m) contracts do not
    (e.g. ``KXBTCD-26MAR2205-T68899.99``).
    """
    if not ticker or not str(ticker).strip():
        raise ValueError("ticker is required")
    return "15m" if "15M" in str(ticker).strip().upper() else "hourly"


def seconds_to_next_15m_boundary_ny(as_of: datetime) -> int:
    """
    Seconds until the next :00 / :15 / :30 / :45 boundary in America/New_York.
    Matches ``StrikeTableGenerator._seconds_to_next_15m_boundary_est`` logic.
    """
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo is required")
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    ny = ZoneInfo("America/New_York")
    now = as_of.astimezone(ny)
    minute = now.minute
    next_min = ((minute // 15) + 1) * 15
    if next_min >= 60:
        next_boundary = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        next_boundary = now.replace(minute=next_min, second=0, microsecond=0)
    return max(0, int((next_boundary - now).total_seconds()))


def seconds_to_next_hour_boundary_ny(as_of: datetime) -> int:
    """
    Seconds until the next top-of-hour in America/New_York.
    Matches hourly branch of ``StrikeTableGenerator.calculate_ttc_seconds`` (wall-clock hour).
    """
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo is required")
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    ny = ZoneInfo("America/New_York")
    now = as_of.astimezone(ny)
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(0, int((next_hour - now).total_seconds()))


def ttc_seconds_in_window(ttc: int, min_time: Any, max_time: Any) -> bool:
    return int(min_time) <= int(ttc) <= int(max_time)


def first_hourly_htc_entry_payload_ordered(
    strikes: Sequence[Mapping[str, Any]],
    settings: Mapping[str, Any],
    *,
    spike_alert_active: bool = False,
) -> Optional[dict[str, Any]]:
    """
    Scan strikes in **list order** (same as AES ``ORDER BY strike``) and return
    the first ``strike_data`` dict that passes Hourly HTC gates.

    Does not apply cooldown, duplicate DB trade checks, or TTC — only the pure
    gates in ``try_hourly_htc_strike_entry_payload``.
    """
    for row in strikes:
        payload = try_hourly_htc_strike_entry_payload(
            settings,
            row,
            spike_alert_active=spike_alert_active,
        )
        if payload is not None:
            return payload
    return None
