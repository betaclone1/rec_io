"""
Lower Tail membership — exclude from unified AES/ATS.

Config rule (not hard-coded monitor ids):
  market=15m, strategy=Lower Tail, symbol in lower_tail_symbols()
  (every tracked asset with a Kalshi 15m series — same universe as Upper Tail)

Entry place/cancel runs in lower_tail_agent, not AES→TM→TE.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

STRATEGY_NAME = "Lower Tail"
CUTOUT_MARKET = "15m"
# Back-compat alias (older call sites / docs).
CUTOUT_SYMBOL = "BTC"


def lower_tail_symbols() -> frozenset[str]:
    """Tracked underlyings with a Kalshi 15m series (full or market live feed).

    Same membership rule as Upper Tail: ``symbols_list`` feed level is
    ``full`` or ``market``, and the symbol is in ``SERIES_15M_BY_SYMBOL``.
    """
    from backend.core.live_data_level import market_feed_symbols
    from backend.core.market_watchdog.venues.kalshi.schedule import SERIES_15M_BY_SYMBOL

    return frozenset(s for s in market_feed_symbols() if s in SERIES_15M_BY_SYMBOL)


def is_lower_tail_symbol(symbol: Any) -> bool:
    return str(symbol or "").strip().upper() in lower_tail_symbols()


def is_lower_tail_row(row: Dict[str, Any]) -> bool:
    sym = str(row.get("symbol") or "").strip().upper()
    mkt = str(row.get("market") or "").strip().lower()
    strat = str(row.get("strategy") or "").strip()
    return (
        sym in lower_tail_symbols()
        and mkt == CUTOUT_MARKET
        and strat == STRATEGY_NAME
    )


def row_matches_lower_tail_fields(
    *,
    symbol: Any,
    market: Any,
    strategy: Any,
) -> bool:
    return is_lower_tail_row(
        {"symbol": symbol, "market": market, "strategy": strategy}
    )


def filter_out_lower_tail_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if not is_lower_tail_row(r)]


def filter_lower_tail_rows_only(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if is_lower_tail_row(r)]


def _sql_symbol_in_clause() -> Optional[Tuple[str, Tuple[str, ...]]]:
    syms = tuple(sorted(lower_tail_symbols()))
    if not syms:
        return None
    placeholders = ", ".join(["%s"] * len(syms))
    return placeholders, syms


def list_active_lower_tail_monitor_rows() -> List[Dict[str, Any]]:
    """Active 15m Lower Tail monitors (tracked 15m symbols) with settings needed by the agent."""
    from backend.core.config.database import get_postgresql_connection
    from backend.core.port_config import default_pool_user_number
    from backend.core.tenant_legacy_sql import legacy_users_monitor_list

    un = default_pool_user_number()
    conn = get_postgresql_connection()
    if not conn:
        return []
    out: List[Dict[str, Any]] = []
    try:
        ml = legacy_users_monitor_list(un)
        clause = _sql_symbol_in_clause()
        if clause is None:
            return []
        sym_ph, syms = clause
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id,
                       name,
                       symbol,
                       COALESCE(NULLIF(TRIM(market), ''), 'hourly') AS market,
                       COALESCE(strategy, '') AS strategy,
                       COALESCE(auto_trade, FALSE) AS auto_trade,
                       min_time,
                       max_time,
                       min_ask,
                       max_ask,
                       total_position,
                       COALESCE(subaccount, 1) AS subaccount,
                       COALESCE(paper_trade, FALSE) AS paper_trade,
                       COALESCE(test_filter, FALSE) AS test_filter,
                       bankroll_allotment_total
                FROM {ml}
                WHERE status = 'active'
                  AND LOWER(TRIM(COALESCE(NULLIF(TRIM(market), ''), 'hourly'))) = '15m'
                  AND UPPER(TRIM(symbol)) IN ({sym_ph})
                  AND TRIM(strategy) = %s
                ORDER BY id
                """,
                (*syms, STRATEGY_NAME),
            )
            for row in cur.fetchall():
                br = row[14]
                try:
                    br_f = float(br) if br is not None else None
                except (TypeError, ValueError):
                    br_f = None
                out.append(
                    {
                        "user_number": un,
                        "monitor_id": str(row[0]),
                        "db_id": row[0],
                        "name": row[1],
                        "symbol": row[2],
                        "market": row[3],
                        "strategy": row[4],
                        "auto_trade": bool(row[5]),
                        "min_time": row[6],
                        "max_time": row[7],
                        "min_ask": row[8],
                        "max_ask": row[9],
                        "total_position": row[10],
                        "subaccount": int(row[11] or 1),
                        "paper_trade": bool(row[12]),
                        "test_filter": bool(row[13]),
                        "bankroll_allotment_total": br_f,
                    }
                )
    finally:
        conn.close()
    return out


_id_cache_lock = threading.Lock()
_id_cache: Dict[str, Any] = {"ts": 0.0, "ids": set()}


def active_lower_tail_monitor_ids(*, max_age_sec: float = 5.0) -> Set[str]:
    now = time.monotonic()
    with _id_cache_lock:
        if now - float(_id_cache["ts"]) <= max_age_sec:
            return set(_id_cache["ids"])
    ids = {
        str(r["monitor_id"])
        for r in list_active_lower_tail_monitor_rows()
        if r.get("auto_trade")
    }
    with _id_cache_lock:
        _id_cache["ts"] = now
        _id_cache["ids"] = ids
    return set(ids)


def resolve_monitor_limit_dollars(row: Dict[str, Any]) -> Optional[float]:
    """
    Single limit L for both BID and ASK rests.
    Require min_ask == max_ask when both present; otherwise accept the one that is set.
    """
    try:
        mn = float(row["min_ask"]) if row.get("min_ask") is not None else None
    except (TypeError, ValueError):
        mn = None
    try:
        mx = float(row["max_ask"]) if row.get("max_ask") is not None else None
    except (TypeError, ValueError):
        mx = None
    if mn is not None and mx is not None:
        if abs(mn - mx) > 1e-9:
            return None
        return round(mn, 4)
    if mn is not None:
        return round(mn, 4)
    if mx is not None:
        return round(mx, 4)
    return None
