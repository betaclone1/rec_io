"""
Build the trade-monitor orderbook JSON payload from live_data (market_kalshi_* + per-ticker orderbook tables).
Matches the shape consumed by frontend/js/orderbook-redis-ui.js (same as legacy Redis UI).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2 import errors as pg_errors

from backend.core.exchange_ids import DEFAULT_EXCHANGE
from backend.core.kalshi_contract_settlement import kalshi_contract_settlement_end_est
from backend.core.kalshi_live_orderbook_sidecar import physical_table_name, quoted_table
from backend.core.kalshi_market_normalize import format_floor_strike_usd_comma_cents
from backend.core.strike_ladder_fetch import fetch_strike_ladder_payload_from_db
from backend.core.strike_snapshot_redis import get_strike_ladder_from_snapshot

EST = ZoneInfo("America/New_York")

_WS_TABLE_15M = "live_data.market_kalshi_15m"
_WS_TABLE_HOURLY = "live_data.market_kalshi_hourly"

_STRIKE_TABLE_15M = "live_data.strike_table_15m"
_STRIKE_TABLE_HOURLY = "live_data.strike_table_hourly"


def _parse_15m_ticker_end_est(market_ticker: str) -> Optional[datetime]:
    m = re.match(
        r"^KX(?:BTC|ETH|SOL|XRP)15M-(\d{2}[A-Z]{3}\d{2}\d{4})-(\d{2})$",
        str(market_ticker).strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    token = m.group(1)
    try:
        return datetime.strptime(token, "%y%b%d%H%M").replace(tzinfo=EST)
    except Exception:
        return None


def _fmt_ampm_no_leading_zero(dt: datetime) -> str:
    s = dt.strftime("%I:%M %p")
    if s.startswith("0"):
        s = s[1:]
    return s


def _market_window_label_eastern(market_ticker: str) -> str:
    end_est = _parse_15m_ticker_end_est(market_ticker)
    if not end_est:
        return ""
    start_est = end_est - timedelta(minutes=15)
    a = start_est.astimezone(EST)
    b = end_est.astimezone(EST)
    tz = a.tzname() or "ET"
    return f"{a.strftime('%B')} {a.day}, {_fmt_ampm_no_leading_zero(a)}–{_fmt_ampm_no_leading_zero(b)} {tz}"


def _d(v: Any) -> Decimal:
    return Decimal(str(v))


def _fmt(v: Decimal, q: str = "0.0000") -> str:
    return str(v.quantize(Decimal(q)))


def _book_rows_near_touch(
    levels: dict[Decimal, Decimal], *, is_ask: bool, limit: Optional[int] = None
) -> list[dict[str, str]]:
    prices = sorted([p for p, sz in levels.items() if sz > 0])
    if not prices:
        return []
    if is_ask:
        best = prices[:limit] if limit is not None else prices
        display = list(reversed(best))
    else:
        best = prices[-limit:] if limit is not None else prices
        display = list(reversed(best))
    out: list[dict[str, str]] = []
    for price in display:
        size = levels[price]
        out.append(
            {
                "price": _fmt(price),
                "size_fp": _fmt(size, "0.01"),
                "total_dollars": _fmt(price * size),
            }
        )
    return out


def _transform_complement_levels(levels: dict[Decimal, Decimal]) -> dict[Decimal, Decimal]:
    transformed: dict[Decimal, Decimal] = {}
    for p, sz in levels.items():
        cp = Decimal("1") - p
        transformed[cp] = transformed.get(cp, Decimal("0")) + sz
    return transformed


def _rollback_connection_safe(cur) -> None:
    """Clear aborted transaction state so further queries work (required after caught PG errors)."""
    try:
        cur.connection.rollback()
    except Exception:
        pass


def _load_yes_no_levels(cur, market_ticker: str) -> tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]]:
    qtbl = quoted_table(market_ticker)
    cur.execute(
        f"""
        SELECT side, price_dollars, size_fp
        FROM {qtbl}
        WHERE size_fp > 0
        """
    )
    yes_levels: dict[Decimal, Decimal] = {}
    no_levels: dict[Decimal, Decimal] = {}
    for side, price, size_fp in cur.fetchall():
        s = str(side or "").strip().lower()
        try:
            p = _d(price)
            sz = _d(size_fp)
        except Exception:
            continue
        if s == "yes":
            yes_levels[p] = sz
        elif s == "no":
            no_levels[p] = sz
    return yes_levels, no_levels


def _last_trade_cents(last_price_dollars: Any) -> tuple[str, str]:
    yes_cents = ""
    no_cents = ""
    if last_price_dollars is None or str(last_price_dollars).strip() == "":
        return yes_cents, no_cents
    try:
        d_yes = Decimal(str(last_price_dollars).strip())
        qy = (d_yes * Decimal("100")).quantize(Decimal("0.01"))
        sy = str(qy)
        if "." in sy:
            sy = sy.rstrip("0").rstrip(".")
        yes_cents = f"{sy}¢"
        d_no = (Decimal("1") - d_yes).quantize(Decimal("0.0001"))
        qn = (d_no * Decimal("100")).quantize(Decimal("0.01"))
        sn = str(qn)
        if "." in sn:
            sn = sn.rstrip("0").rstrip(".")
        no_cents = f"{sn}¢"
    except Exception:
        pass
    return yes_cents, no_cents


def _fetch_market_title_from_strike_table(
    cur,
    *,
    symbol: str,
    market: str,
    market_ticker: Optional[str] = None,
) -> Optional[str]:
    """``market_title`` for the current Kalshi market row in the unified strike table."""
    sym_u = str(symbol or "BTC").strip().upper() or "BTC"
    mkt = str(market or "15m").strip().lower()
    tbl = _STRIKE_TABLE_HOURLY if mkt == "hourly" else _STRIKE_TABLE_15M
    mt = str(market_ticker or "").strip()
    if mt:
        cur.execute(
            f"""
            SELECT market_title FROM {tbl}
            WHERE exchange = 'kalshi' AND UPPER(TRIM(symbol::text)) = %s AND market = %s
              AND ticker = %s AND market_status = 'active'
            ORDER BY "timestamp" DESC NULLS LAST
            LIMIT 1
            """,
            (sym_u, mkt, mt),
        )
        r = cur.fetchone()
        if not r or not (r[0] or "").strip():
            cur.execute(
                f"""
                SELECT market_title FROM {tbl}
                WHERE exchange = 'kalshi' AND UPPER(TRIM(symbol::text)) = %s AND market = %s
                  AND ticker = %s
                ORDER BY "timestamp" DESC NULLS LAST
                LIMIT 1
                """,
                (sym_u, mkt, mt),
            )
            r = cur.fetchone()
    else:
        cur.execute(
            f"""
            SELECT market_title FROM {tbl}
            WHERE exchange = 'kalshi' AND UPPER(TRIM(symbol::text)) = %s AND market = %s
            ORDER BY "timestamp" DESC NULLS LAST
            LIMIT 1
            """,
            (sym_u, mkt),
        )
        r = cur.fetchone()
    if not r or r[0] is None:
        return None
    s = str(r[0]).strip()
    return s or None


def _capitalize_leading_price_word(s: str) -> str:
    """Kalshi copy often starts with ``price``; normalize to ``Price`` for UI."""
    t = (s or "").strip()
    if not t:
        return ""
    m = re.match(r"^price\b(.*)$", t, re.IGNORECASE)
    if m:
        return "Price" + m.group(1)
    return t


def _headline_tail_from_market_title(
    sym: str, interval_label: str, market_title: Optional[str]
) -> Optional[str]:
    """
    Build the fragment after ``SYM interval ·`` from strike-table ``market_title``:
    strip leading symbol, then strip a redundant leading ``interval ·`` so we do not
    duplicate ``BTC 15 min · 15 min · …``.
    """
    raw = (market_title or "").strip()
    if not raw:
        return None
    t = re.sub(rf"^{re.escape(sym)}\s+", "", raw, flags=re.IGNORECASE).strip()
    if not t:
        t = raw
    il = interval_label.strip()
    t2 = re.sub(rf"^{re.escape(il)}\s*[·•]\s*", "", t, flags=re.IGNORECASE).strip()
    return t2 or t or None


def _strike_display_from_row(strike_raw: Any) -> str:
    """UI strike as ``$76,876.92`` (commas + two decimals), even when DB text already has ``$``."""
    if strike_raw is None or str(strike_raw).strip() == "":
        return ""
    s = str(strike_raw).strip()
    inner = s[1:].replace(",", "").strip() if s.startswith("$") else s.replace(",", "").strip()
    if not inner:
        return ""
    out = format_floor_strike_usd_comma_cents(inner)
    return out if out else (s if s.startswith("$") else f"${inner}")


def _resolve_market_ticker_and_table(
    cur,
    *,
    market_ticker: Optional[str],
    symbol: str,
    market: str,
) -> tuple[Optional[str], Optional[str], Optional[dict[str, Any]]]:
    """Return (market_ticker, ws_table_name, row_dict) or (None, None, None)."""
    sym_u = str(symbol or "BTC").strip().upper() or "BTC"
    mkt = str(market or "15m").strip().lower()
    table = _WS_TABLE_HOURLY if mkt == "hourly" else _WS_TABLE_15M
    mcol = "hourly" if mkt == "hourly" else "15m"

    if market_ticker and str(market_ticker).strip():
        mt = str(market_ticker).strip()
        for tbl in (_WS_TABLE_15M, _WS_TABLE_HOURLY):
            cur.execute(
                f"""
                SELECT symbol, event_ticker, market_ticker, market, strike,
                       yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars,
                       last_price_dollars, volume_fp, open_interest_fp, updated_at
                FROM {tbl}
                WHERE exchange = 'kalshi' AND market_ticker = %s
                LIMIT 1
                """,
                (mt,),
            )
            row = cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                return mt, tbl, dict(zip(cols, row))
        return mt, None, None

    cur.execute(
        f"""
        SELECT market_ticker FROM {table}
        WHERE exchange = 'kalshi' AND UPPER(TRIM(symbol::text)) = %s AND market = %s
        ORDER BY updated_at DESC NULLS LAST
        LIMIT 1
        """,
        (sym_u, mcol),
    )
    r0 = cur.fetchone()
    if not r0 or not r0[0]:
        return None, None, None
    mt = str(r0[0]).strip()
    cur.execute(
        f"""
        SELECT symbol, event_ticker, market_ticker, market, strike,
               yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars,
               last_price_dollars, volume_fp, open_interest_fp, updated_at
        FROM {table}
        WHERE exchange = 'kalshi' AND market_ticker = %s
        LIMIT 1
        """,
        (mt,),
    )
    row = cur.fetchone()
    if not row:
        return mt, table, None
    cols = [d[0] for d in cur.description]
    return mt, table, dict(zip(cols, row))


def build_trade_monitor_orderbook_payload(
    cur,
    *,
    market_ticker: Optional[str] = None,
    symbol: str = "BTC",
    market: str = "15m",
) -> dict[str, Any]:
    mt, _tbl_used, row = _resolve_market_ticker_and_table(
        cur, market_ticker=market_ticker, symbol=symbol, market=market
    )
    if not mt:
        return {"error": "no_market_row"}
    if not row:
        return {"error": "no_market_row", "market_ticker": mt}

    orderbook_table_ready = True
    try:
        yes_levels, no_levels = _load_yes_no_levels(cur, mt)
    except pg_errors.UndefinedTable:
        # After rollover, ``market_kalshi_*`` updates before the first WS orderbook_snapshot
        # creates ``live_data.orderbook_kalshi_*``. Return full UI shape with empty ladders.
        yes_levels, no_levels = {}, {}
        orderbook_table_ready = False
        _rollback_connection_safe(cur)
    except psycopg2.Error:
        _rollback_connection_safe(cur)
        return {"error": "orderbook_read_failed", "market_ticker": mt}

    yes_bids = _book_rows_near_touch(yes_levels, is_ask=False)
    no_bids = _book_rows_near_touch(no_levels, is_ask=False)
    yes_asks = _book_rows_near_touch(_transform_complement_levels(no_levels), is_ask=True)
    no_asks = _book_rows_near_touch(_transform_complement_levels(yes_levels), is_ask=True)

    strike_txt = _strike_display_from_row(row.get("strike"))
    sym = str(row.get("symbol") or symbol or "BTC").strip().upper()
    mkt_label = str(row.get("market") or market or "15m").strip().lower()
    interval_label = "15 min" if mkt_label == "15m" else "hourly" if mkt_label == "hourly" else mkt_label

    market_title_row: Optional[str] = None
    try:
        market_title_row = _fetch_market_title_from_strike_table(
            cur, symbol=sym, market=mkt_label, market_ticker=mt
        )
    except Exception:
        _rollback_connection_safe(cur)
        market_title_row = None
    title_tail = _headline_tail_from_market_title(sym, interval_label, market_title_row)
    if title_tail:
        title_tail = _capitalize_leading_price_word(title_tail)
        headline = f"{sym} {interval_label} • {title_tail}"
        target_display = title_tail
    else:
        headline = f"{sym} {interval_label}"
        target_display = ""

    window = _market_window_label_eastern(mt) if mkt_label == "15m" else ""

    yes_cents, no_cents = _last_trade_cents(row.get("last_price_dollars"))

    ticker_ws: dict[str, Any] = {
        "market_ticker": mt,
        "price_dollars": row.get("last_price_dollars"),
        "yes_bid_dollars": row.get("yes_bid_dollars"),
        "yes_ask_dollars": row.get("yes_ask_dollars"),
        "no_bid_dollars": row.get("no_bid_dollars"),
        "no_ask_dollars": row.get("no_ask_dollars"),
        "volume_fp": row.get("volume_fp"),
        "open_interest_fp": row.get("open_interest_fp"),
    }

    # TTC from strike ladder: Redis snapshot (with wall_second for smooth UI), else DB ladder.
    ttc_seconds_out: Optional[int] = None
    ttc_wall_second_out: Optional[int] = None
    try:
        snap_ladder = get_strike_ladder_from_snapshot(DEFAULT_EXCHANGE, mkt_label, sym)
        if snap_ladder and snap_ladder.get("ttc") is not None:
            ttc_seconds_out = max(0, int(snap_ladder["ttc"]))
            ttc_wall_second_out = None
        else:
            ladder = fetch_strike_ladder_payload_from_db(sym, mkt_label, DEFAULT_EXCHANGE)
            if ladder and ladder.get("ttc") is not None:
                ttc_seconds_out = max(0, int(ladder["ttc"]))
                ttc_wall_second_out = None
    except Exception:
        ttc_seconds_out = None
        ttc_wall_second_out = None

    settle_end = kalshi_contract_settlement_end_est(mt)
    settlement_end_ms = int(settle_end.timestamp() * 1000) if settle_end else None

    return {
        "market_ticker": mt,
        "header": {
            "symbol": sym,
            "kicker": "Crypto · 15min" if mkt_label == "15m" else "Crypto · hourly",
            "headline": headline,
            "window": window,
            "strike": strike_txt,
            "target_display": target_display,
            "subtitle": "",
            "ttc_seconds": ttc_seconds_out,
            "ttc_wall_second": ttc_wall_second_out,
            "settlement_end_ms": settlement_end_ms,
        },
        "last_trade": {"yes_cents": yes_cents, "no_cents": no_cents},
        "ticker_ws": ticker_ws,
        "trade_yes": {"asks": yes_asks, "bids": yes_bids},
        "trade_no": {"asks": no_asks, "bids": no_bids},
        "_source": {
            "live_data_market_table": _tbl_used or (
                _WS_TABLE_HOURLY if str(market).strip().lower() == "hourly" else _WS_TABLE_15M
            ),
            "live_data_orderbook_table": physical_table_name(mt),
            "orderbook_table_ready": orderbook_table_ready,
        },
    }


def build_trade_monitor_orderbook_liquidity_map(
    cur,
    *,
    market_tickers: list[str],
) -> dict[str, bool]:
    """
    Batch liquidity probe for trade-monitor rows.

    A ticker is considered liquid only when both YES and NO books have
    at least one ask and one bid (same rule as frontend hasAsksAndBids checks).
    """
    out: dict[str, bool] = {}
    if not market_tickers:
        return out
    for raw in market_tickers:
        mt = str(raw or "").strip()
        if not mt:
            continue
        if mt in out:
            continue
        try:
            yes_levels, no_levels = _load_yes_no_levels(cur, mt)
        except pg_errors.UndefinedTable:
            _rollback_connection_safe(cur)
            out[mt] = False
            continue
        except psycopg2.Error:
            _rollback_connection_safe(cur)
            out[mt] = False
            continue
        yes_bids = _book_rows_near_touch(yes_levels, is_ask=False, limit=1)
        yes_asks = _book_rows_near_touch(_transform_complement_levels(no_levels), is_ask=True, limit=1)
        no_bids = _book_rows_near_touch(no_levels, is_ask=False, limit=1)
        no_asks = _book_rows_near_touch(_transform_complement_levels(yes_levels), is_ask=True, limit=1)
        out[mt] = bool(yes_bids and yes_asks and no_bids and no_asks)
    return out
