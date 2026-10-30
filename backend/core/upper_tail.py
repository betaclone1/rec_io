"""
Upper Tail membership — exclude from unified AES.

Config rule:
  market=15m, strategy=Upper Tail, symbol has a 15m series and
  live_data_level full or market (public tape exists)

Entry is a live public-trade trigger in upper_tail_agent, not AES→TM→TE.
One GTC limit on the side whose print is at or above the monitor target.
ATS supervises the open leg with the Expiration Scalp floor stop and flip sell.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

STRATEGY_NAME = "Upper Tail"
CUTOUT_MARKET = "15m"


def upper_tail_symbols() -> frozenset[str]:
    """15m underlyings whose live feed includes the public tape.

    ``full`` and ``market`` both carry public trades. ``price_only`` and
    ``none`` do not, so an Upper Tail monitor on those symbols stays outside
    this agent (and outside the AES cutout) until the level changes.
    """
    from backend.core.live_data_level import market_feed_symbols
    from backend.core.market_watchdog.venues.kalshi.schedule import SERIES_15M_BY_SYMBOL

    return frozenset(s for s in market_feed_symbols() if s in SERIES_15M_BY_SYMBOL)


def upper_tail_series_tickers() -> list[str]:
    from backend.core.lower_tail_open import series_15m_for_symbol

    out: list[str] = []
    for sym in sorted(upper_tail_symbols()):
        ser = series_15m_for_symbol(sym)
        if ser:
            out.append(ser)
    return out


def is_upper_tail_symbol(symbol: Any) -> bool:
    return str(symbol or "").strip().upper() in upper_tail_symbols()


def is_upper_tail_row(row: Dict[str, Any]) -> bool:
    sym = str(row.get("symbol") or "").strip().upper()
    mkt = str(row.get("market") or "").strip().lower()
    strat = str(row.get("strategy") or "").strip()
    return (
        mkt == CUTOUT_MARKET
        and strat == STRATEGY_NAME
        and sym in upper_tail_symbols()
    )


def filter_out_upper_tail_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if not is_upper_tail_row(r)]


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


def upper_tail_side_from_print(
    *,
    yes_price: Optional[float],
    no_price: Optional[float],
    limit_px: float,
) -> Optional[str]:
    """Side whose public print is at or above the target.

    Both sides at/above the target on one print is not a binary trade.
    Prefer ``upper_tail_side_from_bbo`` for live entry (earlier than tape).
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


def upper_tail_side_from_bbo(
    *,
    yes_ask: Optional[float],
    no_ask: Optional[float],
    limit_px: float,
) -> Optional[str]:
    """Side whose best ask has reached the target rail (e.g. YES ask = $0.99).

    Same comparison as a print at ``limit_px``: first time the offer is at/above
    ``L`` on exactly one side. Mid-book asks (0.50) do not qualify.
    """
    return upper_tail_side_from_print(
        yes_price=yes_ask, no_price=no_ask, limit_px=limit_px
    )


def ttc_in_entry_window(*, ttc: Optional[float], min_time: int, max_time: int) -> bool:
    """True when TTC is inside the monitor window (inclusive)."""
    if ttc is None:
        return False
    try:
        t = float(ttc)
    except (TypeError, ValueError):
        return False
    return int(min_time) <= t <= int(max_time)


def _sql_symbol_in_clause() -> Optional[Tuple[str, Tuple[str, ...]]]:
    syms = tuple(sorted(upper_tail_symbols()))
    if not syms:
        return None
    placeholders = ", ".join(["%s"] * len(syms))
    return placeholders, syms


def list_active_upper_tail_monitor_rows() -> List[Dict[str, Any]]:
    """Active 15m Upper Tail monitors with the settings the agent places from."""
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
