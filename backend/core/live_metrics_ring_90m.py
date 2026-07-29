"""
Rolling 90-minute PG metrics ring — profile-tied hot-path percentiles for backtesting.

Companion to live_price_ring_90m_* (same ISO-8601 UTC ``timestamp`` join key).
Stores only fields that cannot be reconstructed from the price series alone because
they depend on the analytics profile tables that change over time:

  momentum_percentile, volatility_percentile, movement_percentile,
  momentum_5s_avg, momentum_10s_avg, momentum_30s_avg, momentum_1m_avg,
  momentum_acceleration

Writes go to ``live_ring_pg_writer`` (single background thread, batched).
Must never block WS / live_state.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

from backend.core.live_ring_pg_writer import submit_upsert

logger = logging.getLogger("cfbenchmarks_price_watchdog")

_TABLE_BY_SYMBOL: Dict[str, str] = {
    "BTC": "live_metrics_ring_90m_btc",
    "ETH": "live_metrics_ring_90m_eth",
    "SOL": "live_metrics_ring_90m_sol",
    "XRP": "live_metrics_ring_90m_xrp",
    "DOGE": "live_metrics_ring_90m_doge",
}

_METRIC_KEYS: Tuple[str, ...] = (
    "momentum_percentile",
    "volatility_percentile",
    "movement_percentile",
    "momentum_5s_avg",
    "momentum_10s_avg",
    "momentum_30s_avg",
    "momentum_1m_avg",
    "momentum_acceleration",
)

def metrics_ring_pg_enabled() -> bool:
    raw = os.getenv("CFBENCHMARKS_METRICS_RING_PG", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _table_for_symbol(symbol: str) -> Optional[str]:
    return _TABLE_BY_SYMBOL.get(str(symbol or "").strip().upper())


def _optional_numeric(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _snapshot_metrics(tick_row: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Copy metric fields off the hot-path row before async handoff."""
    return {k: _optional_numeric(tick_row.get(k)) for k in _METRIC_KEYS}


def enqueue_metrics_ring_tick(
    symbol: str,
    timestamp: str,
    tick_row: Dict[str, Any],
) -> None:
    """
    Hand one metrics row to the off-loop writer.

    ``timestamp`` must be the same ISO-8601 UTC string used for the price ring row.
    Touches no database and never blocks the caller.
    """
    if not metrics_ring_pg_enabled():
        return
    sym = str(symbol or "").strip().upper()
    table = _table_for_symbol(sym)
    if not table or not timestamp or not isinstance(tick_row, dict):
        return
    snap = _snapshot_metrics(tick_row)
    submit_upsert(
        table,
        ("timestamp",) + _METRIC_KEYS,
        (timestamp,) + tuple(snap.get(k) for k in _METRIC_KEYS),
    )
