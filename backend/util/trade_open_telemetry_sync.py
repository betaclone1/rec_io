"""
Refresh live telemetry on open trades from latest strike rows (ATS path).

Writes: six final-quarter ask columns (15m trades only), unrealized pnl, ats_updated.
Hourly trades: ask min/max/range columns left NULL per product convention.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


def _strike_table_for_cadence(market: Optional[str]) -> str:
    m = (market or "hourly").strip().lower()
    return "strike_table_15m" if m == "15m" else "strike_table_hourly"


def _fetch_latest_strike_row(
    cursor,
    table: str,
    exchange: str,
    symbol: str,
    ticker: str,
) -> Optional[Tuple[Any, ...]]:
    cursor.execute(
        f"""
        SELECT yes_ask_dollars, no_ask_dollars,
               yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
               yes_ask_range_15m, no_ask_range_15m
        FROM live_data.{table}
        WHERE LOWER(TRIM(exchange)) = LOWER(TRIM(%s))
          AND UPPER(TRIM(symbol)) = UPPER(TRIM(%s))
          AND ticker = %s
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (exchange, symbol, ticker),
    )
    row = cursor.fetchone()
    return row


def _closing_price_from_strike_row(
    side: str,
    yes_ask_dollars: Optional[str],
    no_ask_dollars: Optional[str],
) -> Optional[float]:
    su = (side or "").strip().upper()
    if su in ("YES", "Y"):
        raw = no_ask_dollars
    elif su in ("NO", "N"):
        raw = yes_ask_dollars
    else:
        return None
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def refresh_open_trades_telemetry_for_user(user_number: str) -> int:
    """
    For all open trades in users.trades_<user>, join latest strike row and UPDATE telemetry.

    Returns count of trades successfully updated.
    """
    from backend.core.config.database import get_postgresql_connection

    conn = get_postgresql_connection()
    if not conn:
        logger.warning("trade_open_telemetry_sync: no DB connection")
        return 0

    trades_table = f"trades_{user_number}"
    updated = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, ticker, side, symbol, exchange, market, buy_price, "position", fees
                FROM users.{trades_table}
                WHERE status = 'open'
                """
            )
            rows = cur.fetchall()
            for (
                tid,
                ticker,
                side,
                symbol,
                exchange,
                market,
                buy_price,
                position,
                fees,
            ) in rows:
                if not ticker or not symbol:
                    continue
                ex = (exchange or "kalshi").strip().lower()
                sym = str(symbol).strip().upper()
                tt = str(ticker).strip()
                tbl = _strike_table_for_cadence(market)
                srow = _fetch_latest_strike_row(cur, tbl, ex, sym, tt)
                if not srow:
                    continue
                yes_ask_dollars, no_ask_dollars, ymn, ymx, nmn, nmx, yrg, nrg = srow
                close_px = _closing_price_from_strike_row(
                    side, yes_ask_dollars, no_ask_dollars
                )
                if close_px is None:
                    continue
                try:
                    bp = float(buy_price)
                    pos = int(position) if position is not None else 1
                except (TypeError, ValueError):
                    continue
                per = 1.0 - close_px - bp
                unrealized = round(per * pos, 2)
                fee_val = 0.0
                if fees is not None:
                    try:
                        fee_val = float(fees)
                    except (TypeError, ValueError):
                        fee_val = 0.0
                unrealized_net = round(unrealized - fee_val, 2)

                mkt = (market or "hourly").strip().lower()
                if mkt == "15m":
                    cur.execute(
                        f"""
                        UPDATE users.{trades_table}
                        SET pnl = %s,
                            yes_ask_min_15m = %s,
                            yes_ask_max_15m = %s,
                            no_ask_min_15m = %s,
                            no_ask_max_15m = %s,
                            yes_ask_range_15m = %s,
                            no_ask_range_15m = %s,
                            ats_updated = NOW()
                        WHERE id = %s AND status = 'open'
                        """,
                        (
                            unrealized_net,
                            ymn,
                            ymx,
                            nmn,
                            nmx,
                            yrg,
                            nrg,
                            tid,
                        ),
                    )
                else:
                    cur.execute(
                        f"""
                        UPDATE users.{trades_table}
                        SET pnl = %s,
                            ats_updated = NOW()
                        WHERE id = %s AND status = 'open'
                        """,
                        (unrealized_net, tid),
                    )
                if cur.rowcount:
                    updated += 1
        conn.commit()
    except Exception as e:
        logger.exception("refresh_open_trades_telemetry_for_user failed: %s", e)
        conn.rollback()
    finally:
        conn.close()
    return updated
