"""
Shared strike ladder fetch from ``live_data`` (hourly + 15m).

Used by ``auto_entry_supervisor``, ``active_trade_supervisor``, and ``strike_snapshot_publisher``
so one SQL definition feeds direct reads and Redis snapshots.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from backend.core.config.database import get_system_postgresql_connection
from backend.core.exchange_ids import normalize_exchange

logger = logging.getLogger(__name__)


def strike_table_name_for_market(symbol: str, market: str) -> str:
    """Same naming rules as auto_entry_supervisor.get_strike_table_name (symbol unused for hourly)."""
    m = (market or "hourly").strip().lower()
    if m not in ("hourly", "15m"):
        m = "hourly"
    if m == "15m":
        src = os.getenv("STRIKE_TABLE_15M_SOURCE", "legacy").strip().lower()
        if src == "ws":
            return "strike_table_ws_15m"
        return "strike_table_15m"
    return "strike_table_hourly"


def fetch_strike_ladder_prefer_snapshot(
    current_symbol: str,
    current_market: str,
    exchange: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Redis snapshot when fresh (same wall-second payload for all workers), else ``live_data`` ladder."""
    ex = normalize_exchange(exchange)
    from backend.core.strike_snapshot_redis import get_strike_ladder_from_snapshot

    snap = get_strike_ladder_from_snapshot(ex, current_market, current_symbol)
    if snap is not None:
        return snap
    return fetch_strike_ladder_payload_from_db(current_symbol, current_market, ex)


def _coerce_prob_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def find_ladder_strike_by_ticker(
    ladder: Optional[Dict[str, Any]],
    ticker: str,
) -> Optional[Dict[str, Any]]:
    if not ladder or not ticker:
        return None
    t = str(ticker).strip()
    for s in ladder.get("strikes") or []:
        if str(s.get("ticker") or "").strip() == t:
            return s
    return None


def probability_from_strike_row_side_aware(
    row: Dict[str, Any],
    market: str,
    trade_side: Optional[str],
) -> Optional[float]:
    """Match ``active_trade_supervisor.get_current_probability_from_live_strike_table`` semantics."""
    mkt = (market or "hourly").strip().lower()
    su = (trade_side or "").strip().upper()
    if su == "YES":
        su = "Y"
    if su == "NO":
        su = "N"
    yh = _coerce_prob_float(row.get("yes_prob_hourly"))
    nh = _coerce_prob_float(row.get("no_prob_hourly"))
    ph = _coerce_prob_float(row.get("probability_hourly"))
    y15 = _coerce_prob_float(row.get("yes_prob_15m"))
    n15 = _coerce_prob_float(row.get("no_prob_15m"))
    p15 = _coerce_prob_float(row.get("probability_15m"))
    v: Optional[float] = None
    if su == "Y":
        if mkt == "15m":
            v = y15 if y15 is not None else p15
        else:
            v = yh if yh is not None else ph
    elif su == "N":
        if mkt == "15m":
            v = n15 if n15 is not None else p15
        else:
            v = nh if nh is not None else ph
    else:
        return None
    if v is None:
        v = _coerce_prob_float(row.get("probability"))
    return v


def probability_from_ladder_by_strike(
    ladder: Optional[Dict[str, Any]],
    strike: float,
    market: str,
) -> Optional[float]:
    """Strike-keyed ``probability_hourly`` / ``probability_15m`` from ladder (snapshot or DB)."""
    if not ladder:
        return None
    sk = int(round(float(strike)))
    mkt = (market or "hourly").strip().lower()
    pc = "probability_15m" if mkt == "15m" else "probability_hourly"
    for r in ladder.get("strikes") or []:
        if r.get("strike") is None:
            continue
        try:
            if int(round(float(r["strike"]))) != sk:
                continue
        except (TypeError, ValueError):
            continue
        v = _coerce_prob_float(r.get(pc))
        if v is None:
            v = _coerce_prob_float(r.get("probability"))
        return v
    return None


def fetch_strike_ladder_payload_from_db(
    current_symbol: str,
    current_market: str,
    exchange: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load ladder snapshot: same shape as legacy ``_fetch_master_strike_table_data``."""
    ex = normalize_exchange(exchange)
    sym_u = (current_symbol or "").upper().strip()
    if not sym_u:
        return None
    current_market = (current_market or "hourly").strip().lower()
    if current_market not in ("hourly", "15m"):
        current_market = "hourly"

    conn = get_system_postgresql_connection()
    if not conn:
        logger.warning("strike_ladder_fetch: no system PostgreSQL connection")
        return None

    try:
        with conn.cursor() as cursor:
            table_name = strike_table_name_for_market(sym_u, current_market)
            ttc_column = "ttc_15m" if current_market == "15m" else "ttc_hourly"

            if current_market == "15m":
                table_15m = strike_table_name_for_market(sym_u, "15m")
                cursor.execute(
                    f"""
                    SELECT
                        symbol,
                        current_price,
                        {ttc_column},
                        event_ticker,
                        market_title,
                        strike_tier,
                        market_status,
                        timestamp
                    FROM live_data.{table_15m}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (ex, sym_u),
                )
                header_data = cursor.fetchone()
                if not header_data:
                    conn.close()
                    return None
                table_15m_for_strikes = table_15m
            else:
                cursor.execute(
                    f"""
                    SELECT
                        symbol,
                        current_price,
                        {ttc_column},
                        ttc_15m,
                        event_ticker,
                        market_title,
                        strike_tier,
                        market_status
                    FROM live_data.{table_name}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (ex, sym_u),
                )
                header_data = cursor.fetchone()
                if not header_data:
                    conn.close()
                    return None
                table_15m_for_strikes = table_name

            if current_market == "15m" and str(header_data[0] or "").upper() != sym_u:
                conn.close()
                return None

            # Per-ticker row: omit duplicate {prob_column} — both probability_hourly and probability_15m
            # are listed once (avoids "ambiguous column" when prob_column matched one of those names).
            strikes_sql = f"""
                    SELECT
                        strike,
                        buffer,
                        buffer_pct,
                        yes_ask_dollars,
                        no_ask_dollars,
                        volume_fp,
                        open_interest_fp,
                        ticker,
                        yes_diff,
                        no_diff,
                        active_side,
                        yes_price_spread,
                        no_price_spread,
                        yes_ask_range_15m,
                        no_ask_range_15m,
                        yes_prob_hourly,
                        no_prob_hourly,
                        probability_hourly,
                        yes_prob_15m,
                        no_prob_15m,
                        probability_15m
                    FROM (
                        SELECT DISTINCT ON (ticker)
                            strike,
                            buffer,
                            buffer_pct,
                            yes_ask_dollars,
                            no_ask_dollars,
                            volume_fp,
                            open_interest_fp,
                            ticker,
                            yes_diff,
                            no_diff,
                            active_side,
                            yes_price_spread,
                            no_price_spread,
                            yes_ask_range_15m,
                            no_ask_range_15m,
                            yes_prob_hourly,
                            no_prob_hourly,
                            probability_hourly,
                            yes_prob_15m,
                            no_prob_15m,
                            probability_15m,
                            timestamp
                        FROM live_data.{{tbl}}
                        WHERE exchange = %s AND symbol = %s
                        ORDER BY ticker, timestamp DESC
                    ) latest_per_ticker
                    ORDER BY strike
                    """
            if current_market == "15m":
                cursor.execute(
                    strikes_sql.format(tbl=table_15m_for_strikes),
                    (ex, sym_u),
                )
            else:
                cursor.execute(
                    strikes_sql.format(tbl=table_name),
                    (ex, sym_u),
                )

            strikes_data = cursor.fetchall()
            if current_market == "hourly":
                response: Dict[str, Any] = {
                    "symbol": header_data[0],
                    "current_price": float(header_data[1]) if header_data[1] else None,
                    "ttc": int(header_data[2]) if header_data[2] else None,
                    "ttc_15m": int(header_data[3]) if header_data[3] is not None else None,
                    "event_ticker": header_data[4],
                    "market_title": header_data[5],
                    "strike_tier": header_data[6],
                    "market_status": header_data[7],
                    "strikes": [],
                }
            else:
                response: Dict[str, Any] = {
                    "symbol": header_data[0],
                    "current_price": float(header_data[1]) if header_data[1] else None,
                    "ttc": int(header_data[2]) if header_data[2] else None,
                    "event_ticker": header_data[3],
                    "market_title": header_data[4],
                    "strike_tier": header_data[5],
                    "market_status": header_data[6],
                    "strikes": [],
                }
                response["ttc_15m"] = response["ttc"]
            for strike_row in strikes_data:
                ph = float(strike_row[17]) if strike_row[17] is not None else None
                p15 = float(strike_row[20]) if strike_row[20] is not None else None
                market_prob = p15 if current_market == "15m" else ph
                strike_data = {
                    "strike": float(strike_row[0]) if strike_row[0] else None,
                    "buffer": float(strike_row[1]) if strike_row[1] else None,
                    "buffer_pct": float(strike_row[2]) if strike_row[2] else None,
                    "probability": market_prob,
                    "yes_ask_dollars": strike_row[3],
                    "no_ask_dollars": strike_row[4],
                    "volume_fp": strike_row[5] if strike_row[5] is None else str(strike_row[5]).strip(),
                    "open_interest_fp": strike_row[6] if strike_row[6] is None else str(strike_row[6]).strip(),
                    "ticker": strike_row[7],
                    "yes_diff": float(strike_row[8]) if strike_row[8] else None,
                    "no_diff": float(strike_row[9]) if strike_row[9] else None,
                    "active_side": strike_row[10],
                    "yes_price_spread": float(strike_row[11]) if strike_row[11] is not None else None,
                    "no_price_spread": float(strike_row[12]) if strike_row[12] is not None else None,
                    "yes_ask_range_15m": float(strike_row[13]) if strike_row[13] is not None else None,
                    "no_ask_range_15m": float(strike_row[14]) if strike_row[14] is not None else None,
                    "yes_prob_hourly": float(strike_row[15]) if strike_row[15] is not None else None,
                    "no_prob_hourly": float(strike_row[16]) if strike_row[16] is not None else None,
                    "probability_hourly": ph,
                    "yes_prob_15m": float(strike_row[18]) if strike_row[18] is not None else None,
                    "no_prob_15m": float(strike_row[19]) if strike_row[19] is not None else None,
                    "probability_15m": p15,
                }
                response["strikes"].append(strike_data)

            conn.close()
            return response
    except Exception as e:
        logger.warning("strike_ladder_fetch: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return None
