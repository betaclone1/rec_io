"""
BTC 15m Expiration Scalp AES/ATS cutout membership.

Config/class rule (not hard-coded monitor ids):
  symbol=BTC, market=15m, strategy=Expiration Scalp
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional, Set

CUTOUT_STRATEGY = "Expiration Scalp"
CUTOUT_SYMBOL = "BTC"
CUTOUT_MARKET = "15m"
CUTOUT_ARGV = "btc15m_exp_scalp"

_cutout_id_cache_lock = threading.Lock()
_cutout_id_cache: Dict[str, Any] = {"ts": 0.0, "ids": set()}


def supervisor_log_numeric_monitor_id(filename: str, slot: str) -> Optional[str]:
    """
    Numeric monitor id from ``service_<slot>_<id>*.log``.

    Pool workers (``unified``, ``btc15m_exp_scalp``) are not monitor ids — return None
    so orphan-log cleanup does not archive their live files.
    """
    name = os.path.basename(filename)
    parts = name.split("_")
    try:
        idx_slot = parts.index(slot)
    except ValueError:
        return None
    if idx_slot + 1 >= len(parts):
        return None
    token = parts[idx_slot + 1].split(".")[0]
    if not token.isdigit():
        return None
    return token


def is_btc15m_exp_scalp_cutout_row(row: Dict[str, Any]) -> bool:
    sym = str(row.get("symbol") or "").strip().upper()
    mkt = str(row.get("market") or "").strip().lower()
    strat = str(row.get("strategy") or "").strip()
    return sym == CUTOUT_SYMBOL and mkt == CUTOUT_MARKET and strat == CUTOUT_STRATEGY


def row_matches_cutout_fields(
    *,
    symbol: Any,
    market: Any,
    strategy: Any,
) -> bool:
    return is_btc15m_exp_scalp_cutout_row(
        {"symbol": symbol, "market": market, "strategy": strategy}
    )


def filter_out_cutout_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if not is_btc15m_exp_scalp_cutout_row(r)]


def filter_cutout_rows_only(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if is_btc15m_exp_scalp_cutout_row(r)]


def list_active_btc15m_exp_scalp_cutout_rows() -> List[Dict[str, Any]]:
    from backend.core.unified_15m_monitors import list_active_15m_monitor_rows

    return filter_cutout_rows_only(list_active_15m_monitor_rows())


def active_cutout_monitor_ids(*, max_age_sec: float = 5.0) -> Set[str]:
    """Cached set of active cutout monitor_id strings for this tenant worker."""
    now = time.monotonic()
    with _cutout_id_cache_lock:
        if now - float(_cutout_id_cache["ts"]) <= max_age_sec:
            return set(_cutout_id_cache["ids"])
    ids = {str(r["monitor_id"]) for r in list_active_btc15m_exp_scalp_cutout_rows()}
    with _cutout_id_cache_lock:
        _cutout_id_cache["ts"] = now
        _cutout_id_cache["ids"] = ids
    return set(ids)


def monitor_matches_cutout_membership(
    *,
    symbol: Any,
    market: Any,
    strategy: Any,
) -> bool:
    return row_matches_cutout_fields(symbol=symbol, market=market, strategy=strategy)


def lookup_monitor_is_cutout(monitor_id: str) -> Optional[bool]:
    """
    True/False when monitor row is found; None when lookup unavailable.
    Uses active cutout cache first, then a direct monitor_list read.
    """
    mid = str(monitor_id or "").strip()
    if not mid:
        return False
    if mid in active_cutout_monitor_ids():
        return True
    try:
        from backend.core.config.database import get_postgresql_connection
        from backend.core.port_config import default_pool_user_number
        from backend.core.tenant_legacy_sql import legacy_users_monitor_list

        conn = get_postgresql_connection()
        if not conn:
            return None
        try:
            with conn.cursor() as cur:
                ml = legacy_users_monitor_list(default_pool_user_number())
                cur.execute(
                    f"""
                    SELECT symbol,
                           COALESCE(NULLIF(TRIM(market), ''), 'hourly') AS market,
                           COALESCE(strategy, '') AS strategy
                    FROM {ml}
                    WHERE id = %s
                    """,
                    (mid,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                return row_matches_cutout_fields(
                    symbol=row[0], market=row[1], strategy=row[2]
                )
        finally:
            conn.close()
    except Exception:
        return None