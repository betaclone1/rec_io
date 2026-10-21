"""
Taker Edge membership — exclude from unified AES/ATS.

Config rule:
  market=15m, strategy=Taker Edge, symbol in TAKER_EDGE_SYMBOLS

Entry is a live public-trade trigger in taker_edge_agent, not AES→TM→TE.
One GTC limit on the side whose print is at or above the monitor target.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

STRATEGY_NAME = "Taker Edge"
CUTOUT_MARKET = "15m"
TAKER_EDGE_SYMBOLS: frozenset[str] = frozenset(
    {"BTC", "ETH", "GOLD", "SILVER", "WTI"}
)


def is_taker_edge_symbol(symbol: Any) -> bool:
    return str(symbol or "").strip().upper() in TAKER_EDGE_SYMBOLS


def is_taker_edge_row(row: Dict[str, Any]) -> bool:
    sym = str(row.get("symbol") or "").strip().upper()
    mkt = str(row.get("market") or "").strip().lower()
    strat = str(row.get("strategy") or "").strip()
    return sym in TAKER_EDGE_SYMBOLS and mkt == CUTOUT_MARKET and strat == STRATEGY_NAME


def filter_out_taker_edge_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if not is_taker_edge_row(r)]


def floor_strike_from_market(market: Any) -> Optional[float]:
    """Kalshi market ``floor_strike`` (or ``strike``). None when the payload omits it."""
    if not isinstance(market, dict):
        return None
    for key in ("floor_strike", "strike"):
        raw = market.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def taker_edge_side_from_print(
    *,
    yes_price: Optional[float],
    no_price: Optional[float],
    limit_px: float,
) -> Optional[str]:
    """Side whose public print is at or above the target.

    Both sides at/above the target on one print is not a binary trade.
    """
    yes_hit = yes_price is not None and float(yes_price) + 1e-9 >= float(limit_px)
    no_hit = no_price is not None and float(no_price) + 1e-9 >= float(limit_px)
    if yes_hit and no_hit:
        return None
    if yes_hit:
        return "yes"
    if no_hit:
        return "no"
    return None


def ttc_in_entry_window(*, ttc: Optional[float], min_time: int, max_time: int) -> bool:
    """True when TTC is inside the monitor window (inclusive)."""
    if ttc is None:
        return False
    try:
        t = float(ttc)
    except (TypeError, ValueError):
        return False
    return int(min_time) <= t <= int(max_time)


def _sql_symbol_in_clause() -> Tuple[str, Tuple[str, ...]]:
    syms = tuple(sorted(TAKER_EDGE_SYMBOLS))
    placeholders = ", ".join(["%s"] * len(syms))
    return placeholders, syms


def list_active_taker_edge_monitor_rows() -> List[Dict[str, Any]]:
    """Active 15m Taker Edge monitors with the settings the agent places from."""
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
        sym_ph, syms = _sql_symbol_in_clause()
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
