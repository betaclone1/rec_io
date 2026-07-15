"""
Build ``backtest.tick_backtest_<slug>`` — one row per **1s symbol tick** during the Kalshi market
window. ``timestamp`` is stored as **Eastern wall clock** (``TIMESTAMP WITHOUT TIME ZONE``), not UTC,
so SQL clients and exports show session times that match Kalshi ET (same pattern as ``backtest_1m_*``).
Each row mirrors **the same columns as** ``live_data.strike_table_15m`` (unified Kalshi
strike snapshot shape): spot, TTCs, strike/buffer, lookup probabilities, momentum/vol/movement from
the 1s log, YES/NO **ask** fields follow the **last trade at or before** that tick; when a second has no new
print (or missing dollar fields on the last trade), **previous** YES/NO dollar values are carried
forward (bids unknown → NULL; spreads NULL). ``volume_fp`` / ``open_interest_fp`` come from
``backtest.backtest_1m_<slug>`` 1m candles (same minute repeated for each tick in that minute).

**Data sources**
- ``live_data.live_price_log_1s_<symbol>`` — ``current_price``, momentum, volatility, movement
  (same as live strike generator).
- ``backtest.kalshi_historical_trades_api`` — trade YES/NO dollar fields as ask proxies.
- ``backtest.backtest_1m_<slug>`` — optional; ingest via ``core_backtester --ingest-kalshi-tickers``
  for volume / open interest.
- **Archive path:** ``historical_data.strike_table_master`` (``build_tick_backtest_from_strike_archive`` /
  ``core_backtester --build-tick-backtest-from-archive``) copies live-archived strike rows into the
  same ``tick_backtest_*`` shape (Eastern-naive ``timestamp`` / ``created_at``; one row per archive
  instant; collapses duplicate Eastern seconds to the latest ``timestamptz``).

Probability and buffer math follow ``backend/strike_table_generator.generate_strike_table``;
``yes_prob_15m`` / ``no_prob_15m`` (and hourly legs when applicable) use the same **active-side
complement** as ``compute_minute_strike_span`` / ``_corner_yes_no_probs`` in
``backtest_strike_span`` (geometry from spot vs strike: yes / no / cross). ``probability_15m``
remains the selected model leg for that row.

**Audit vs live / trades:** Compare ``probability_15m`` to the trade row’s model prob (same as AES).
Do not expect ``yes_prob_15m`` / ``no_prob_15m`` here to match ``live_data`` strike columns of the
same names: production stores **raw** lookup legs; this table stores **corner-complemented** YES/NO
for the span convention. Rebuilds use ``LookupProbabilityCalculator``; set env
``REC_PROBABILITY_LOOKUP_TABLE`` to a concrete ``analytics.probability_lookup_*_master_*`` name to
match the calibration from when the trade happened (default is latest table by name, which drifts).

min/max/range columns use ``final_quarter_ask_tracking_fields`` with trade-based asks.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from zoneinfo import ZoneInfo

from backend.strike_table_generator import (
    BUFFER_PCT_DECIMAL_PLACES_ALT,
    HOURLY_FINAL_QUARTER_TRACKING_SEC,
    StrikeTableGenerator,
    final_quarter_ask_tracking_fields,
    round_price_buffer,
    uses_high_precision_price,
)
from backend.util.auto_entry_htc_gates import money_line_diffs_and_active_side
from scripts.backtest.helpers.kalshi_candles_1m import (
    backtest_candles_relname,
    fetch_market_window,
    resolve_floor_strike_and_market_result,
    ticker_slug,
    validate_kalshi_market_ticker,
)
from scripts.backtest.helpers.htc_aes_replay import (
    infer_contract_market_from_kalshi_ticker,
    seconds_to_next_15m_boundary_ny,
    seconds_to_next_hour_boundary_ny,
)
from scripts.backtest.helpers.backtest_strike_span import (
    _corner_yes_no_probs,
    probability_symbol_from_kalshi_ticker,
)

_EASTERN = ZoneInfo("America/New_York")

_TICK_REL_RE = re.compile(r"^tick_backtest_[a-z0-9_]+$")

_SYMBOL_TO_LIVE_TABLE = {
    "btc": "live_price_log_1s_btc",
    "eth": "live_price_log_1s_eth",
    "sol": "live_price_log_1s_sol",
    "xrp": "live_price_log_1s_xrp",
    "doge": "live_price_log_1s_doge",
}

_EXCHANGE = "kalshi"


def tick_backtest_relname(market_ticker: str) -> str:
    t = validate_kalshi_market_ticker(market_ticker)
    rel = f"tick_backtest_{ticker_slug(t)}"
    if not _TICK_REL_RE.fullmatch(rel):
        raise ValueError(f"invalid tick backtest relation name: {rel!r}")
    return rel


def _live_table_for_ticker(market_ticker: str) -> str:
    sym = probability_symbol_from_kalshi_ticker(market_ticker)
    if not sym or sym not in _SYMBOL_TO_LIVE_TABLE:
        raise ValueError(
            f"tick backtest only supports KXBTC/KXETH/KXSOL/KXXRP/KXDOGE-style tickers; got {market_ticker!r}"
        )
    return _SYMBOL_TO_LIVE_TABLE[sym]


def _parse_ts(val: Any) -> datetime:
    """
    Normalize to US Eastern **naive** wall time (``America/New_York``), matching the live 1s log
    contract and Kalshi session windows.
    """
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val
        return val.astimezone(_EASTERN).replace(tzinfo=None)
    s = str(val).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"bad timestamp: {val!r}") from None
    if dt.tzinfo is not None:
        dt = dt.astimezone(_EASTERN).replace(tzinfo=None)
    return dt


def _event_ticker_from_market_ticker(market_ticker: str) -> str:
    parts = str(market_ticker).strip().rsplit("-", 1)
    return parts[0] if len(parts) == 2 else str(market_ticker)


def _strike_display(sym: str, floor_strike: float) -> float:
    if uses_high_precision_price(sym):
        return round_price_buffer(float(floor_strike))
    return float(int(round(float(floor_strike))))


def _buffer_and_pct(sym: str, spot: float, strike: float) -> tuple[float, Optional[float]]:
    raw_buf = abs(float(spot) - float(strike))
    buf = round_price_buffer(raw_buf) if uses_high_precision_price(sym) else raw_buf
    bp = (float(buf) / float(spot)) * 100 if spot else None
    if bp is not None and uses_high_precision_price(sym):
        bp = round(float(bp), BUFFER_PCT_DECIMAL_PLACES_ALT)
    return buf, bp


def _d52(val: Optional[float]) -> Optional[Decimal]:
    if val is None:
        return None
    return Decimal(str(round(float(val), 2)))


def _fp_to_text(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def ensure_tick_backtest_table(conn: Any, rel: str) -> None:
    """Create ``backtest.{rel}`` with the same column set as ``live_data.strike_table_15m`` (minus ``id``)."""
    if not _TICK_REL_RE.match(rel):
        raise ValueError(f"bad rel: {rel!r}")
    esc = "tick_backtest_build"
    ddl = f"""
    CREATE TABLE IF NOT EXISTS backtest.{rel} (
        "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        symbol VARCHAR(10) NOT NULL,
        exchange VARCHAR(20) NOT NULL,
        market TEXT DEFAULT '15m',
        current_price NUMERIC(18,5),
        ttc_hourly INTEGER,
        ttc_15m INTEGER,
        event_ticker VARCHAR(50),
        market_title TEXT,
        strike_tier INTEGER,
        market_status VARCHAR(20),
        strike NUMERIC(18,5),
        buffer NUMERIC(18,5),
        buffer_pct NUMERIC(12,6),
        probability_hourly DECIMAL(5,2),
        probability_15m DECIMAL(5,2),
        yes_prob_hourly DECIMAL(5,2),
        no_prob_hourly DECIMAL(5,2),
        yes_prob_15m DECIMAL(5,2),
        no_prob_15m DECIMAL(5,2),
        yes_ask_dollars TEXT,
        no_ask_dollars TEXT,
        yes_bid_dollars TEXT,
        no_bid_dollars TEXT,
        yes_price_spread NUMERIC(6,4),
        no_price_spread NUMERIC(6,4),
        yes_diff DECIMAL(5,2),
        no_diff DECIMAL(5,2),
        volume_fp TEXT,
        open_interest_fp TEXT,
        ticker VARCHAR(50),
        active_side VARCHAR(10),
        momentum_weighted_score DECIMAL(5,3),
        momentum_percentile DECIMAL(5,1),
        volatility NUMERIC(10,6),
        volatility_percentile NUMERIC(5,1),
        movement NUMERIC(10,4),
        movement_percentile NUMERIC(5,1),
        yes_ask_min_15m NUMERIC(18,4),
        yes_ask_max_15m NUMERIC(18,4),
        no_ask_min_15m NUMERIC(18,4),
        no_ask_max_15m NUMERIC(18,4),
        yes_ask_range_15m NUMERIC(18,4),
        no_ask_range_15m NUMERIC(18,4),
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        PRIMARY KEY ("timestamp")
    );
    COMMENT ON TABLE backtest.{rel} IS %s;
    """
    comment = (
        "Tick-level strike-table-shaped backtest (columns align with live_data.strike_table_15m). "
        "\"timestamp\" / created_at are US Eastern wall clock (naive TIMESTAMP; same convention as "
        "historical_data price_history / backtest_1m). Not UTC. "
        f"Built by tick_backtest_build ({esc})."
    )
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS backtest;")
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'backtest' AND table_name = %s
            """,
            (rel,),
        )
        if cur.fetchone():
            cur.execute(
                """
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = 'backtest' AND table_name = %s AND column_name = 'timestamp'
                """,
                (rel,),
            )
            ts_row = cur.fetchone()
            ts_typ = (ts_row[0] or "").lower() if ts_row else ""
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'backtest' AND table_name = %s AND column_name = 'yes_prob_15m'
                """,
                (rel,),
            )
            has_yes_prob = cur.fetchone()
            if (not has_yes_prob) or (ts_typ == "timestamp with time zone"):
                cur.execute(f"DROP TABLE IF EXISTS backtest.{rel};")
        cur.execute(ddl, (comment,))


def _load_trades_for_ticker(conn: Any, market_ticker: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT trade_id, ticker, count_fp, yes_price_dollars, no_price_dollars,
                   taker_side, created_time
            FROM backtest.kalshi_historical_trades_api
            WHERE ticker = %s
            ORDER BY created_time ASC
            """,
            (market_ticker,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _load_live_rows(
    conn: Any,
    live_rel: str,
    t_start_naive: datetime,
    t_end_naive: datetime,
) -> list[dict[str, Any]]:
    fq = f"live_data.{live_rel}"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT "timestamp", price, momentum,
                   momentum_percentile, volatility, volatility_percentile,
                   movement, movement_percentile
            FROM {fq}
            WHERE "timestamp"::timestamp >= %s::timestamp
              AND "timestamp"::timestamp <= %s::timestamp
            ORDER BY "timestamp"::timestamp ASC
            """,
            (t_start_naive, t_end_naive),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _trade_time_naive(tr: dict[str, Any]) -> datetime:
    """``created_time`` from API/DB as Eastern-naive for ordering against live 1s ticks."""
    ct = tr["created_time"]
    if isinstance(ct, datetime):
        if ct.tzinfo is None:
            return ct
        return ct.astimezone(_EASTERN).replace(tzinfo=None)
    return _parse_ts(ct)


def _load_candle_volume_oi_by_minute(
    conn: Any,
    market_ticker: str,
    t_start_naive: datetime,
    t_end_naive: datetime,
) -> dict[datetime, tuple[Optional[str], Optional[str]]]:
    rel = backtest_candles_relname(market_ticker)
    out: dict[datetime, tuple[Optional[str], Optional[str]]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'backtest' AND table_name = %s
            """,
            (rel,),
        )
        if cur.fetchone() is None:
            return out
        cur.execute(
            f"""
            SELECT "timestamp", volume_fp, open_interest_fp
            FROM backtest.{rel}
            WHERE "timestamp" >= %s AND "timestamp" <= %s
            ORDER BY "timestamp" ASC
            """,
            (t_start_naive, t_end_naive),
        )
        for ts, vf, oi in cur.fetchall():
            if isinstance(ts, datetime):
                mn = ts.replace(second=0, microsecond=0) if ts.tzinfo is None else ts.astimezone(_EASTERN).replace(tzinfo=None).replace(second=0, microsecond=0)
            else:
                mn = _parse_ts(ts).replace(second=0, microsecond=0)
            out[mn] = (_fp_to_text(vf), _fp_to_text(oi))
    return out


def build_tick_backtest_table(
    conn: Any,
    market_ticker: str,
    *,
    truncate: bool = True,
) -> dict[str, Any]:
    """
    Populate ``backtest.tick_backtest_<slug>`` for ``market_ticker`` (strike-table column layout).
    """
    t = validate_kalshi_market_ticker(market_ticker)
    rel = tick_backtest_relname(t)
    floor_strike, _market_result, _src = resolve_floor_strike_and_market_result(t)
    if floor_strike is None:
        raise RuntimeError(f"floor_strike missing for {t!r}")

    sym = probability_symbol_from_kalshi_ticker(t)
    if not sym:
        raise ValueError(f"unsupported symbol for tick backtest: {t!r}")
    strike_col = _strike_display(sym, float(floor_strike))
    contract = infer_contract_market_from_kalshi_ticker(t)
    market_label = "15m" if contract == "15m" else "hourly"
    st_gen = StrikeTableGenerator(
        sym,
        interval=market_label,
        unified_15m=(contract == "15m"),
        database_conn=conn,
    )
    ev_ticker = _event_ticker_from_market_ticker(t)
    market_title = st_gen.generate_market_title(ev_ticker)

    open_u, close_u = fetch_market_window(t)
    t_start = datetime.fromtimestamp(open_u, tz=ZoneInfo("UTC")).astimezone(_EASTERN).replace(tzinfo=None)
    t_end = datetime.fromtimestamp(close_u, tz=ZoneInfo("UTC")).astimezone(_EASTERN).replace(tzinfo=None)

    live_rel = _live_table_for_ticker(t)
    live_rows = _load_live_rows(conn, live_rel, t_start, t_end)
    trades = _load_trades_for_ticker(conn, t)
    if not trades:
        raise RuntimeError(
            "no rows in backtest.kalshi_historical_trades_api for this ticker — run:\n"
            f"  .venv/bin/python3 scripts/backtest/fetch_kalshi_historical_trades_to_backtest.py "
            f"--ticker {t} --endpoint markets"
        )

    candle_by_minute = _load_candle_volume_oi_by_minute(conn, t, t_start, t_end)

    ensure_tick_backtest_table(conn, rel)
    if truncate:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE backtest.{rel};")

    calc = st_gen.calculator
    ti = 0
    last_tr: Optional[dict[str, Any]] = None
    carried_yes: Optional[str] = None
    carried_no: Optional[str] = None
    prev_6: Optional[tuple[Any, ...]] = None
    batch: list[tuple[Any, ...]] = []

    for row in live_rows:
        ts_naive = _parse_ts(row["timestamp"])
        while ti < len(trades) and _trade_time_naive(trades[ti]) <= ts_naive:
            last_tr = trades[ti]
            ti += 1

        spot = row.get("price")
        if spot is None:
            continue
        try:
            spot_f = float(spot)
        except (TypeError, ValueError):
            continue

        if last_tr:
            yd = last_tr.get("yes_price_dollars")
            nd = last_tr.get("no_price_dollars")
            if yd and nd:
                carried_yes = str(yd).strip()
                carried_no = str(nd).strip()

        if not carried_yes or not carried_no:
            continue

        buf, buf_pct = _buffer_and_pct(sym, spot_f, strike_col)
        aw = ts_naive.replace(tzinfo=_EASTERN)
        ttc_15m = seconds_to_next_15m_boundary_ny(aw)
        if contract == "15m":
            ttc_h: Optional[int] = None
            ttc_primary = ttc_15m
        else:
            ttc_h = seconds_to_next_hour_boundary_ny(aw)
            ttc_primary = int(ttc_h)

        # Same rule as ``strike_table_generator.generate_strike_table``:
        # ``momentum_bucket = round(momentum_percentile)``; missing → 0.0 (see ``get_current_market_data``).
        mom = row.get("momentum_percentile")
        try:
            mp_for_bucket = float(mom) if mom is not None else 0.0
        except (TypeError, ValueError):
            mp_for_bucket = 0.0
        m_bucket = round(mp_for_bucket)

        if contract == "15m":
            pos_prob, neg_prob = calc.get_probability(int(ttc_15m), float(buf), m_bucket, conn=conn)
            pos_15, neg_15 = pos_prob, neg_prob
        else:
            pos_prob, neg_prob = calc.get_probability(int(ttc_primary), float(buf), m_bucket, conn=conn)
            pos_15, neg_15 = calc.get_probability(int(ttc_15m), float(buf), m_bucket, conn=conn)

        if (
            pos_prob is None
            or neg_prob is None
            or pos_15 is None
            or neg_15 is None
        ):
            continue

        if strike_col > spot_f:
            geom_active = "no"
        elif strike_col < spot_f:
            geom_active = "yes"
        else:
            geom_active = "cross"

        if strike_col < spot_f:
            probability_15m = pos_15
            prob_for_diff = pos_15 if contract == "15m" else pos_prob
            probability_hourly_v = pos_prob if contract == "hourly" else None
        else:
            probability_15m = neg_15
            prob_for_diff = neg_15 if contract == "15m" else neg_prob
            probability_hourly_v = neg_prob if contract == "hourly" else None

        yp15_c, np15_c = _corner_yes_no_probs(
            float(pos_15) if pos_15 is not None else None,
            float(neg_15) if neg_15 is not None else None,
            geom_active,
        )
        if contract == "hourly":
            yph_c, nph_c = _corner_yes_no_probs(
                float(pos_prob) if pos_prob is not None else None,
                float(neg_prob) if neg_prob is not None else None,
                geom_active,
            )
            yes_prob_hourly = yph_c
            no_prob_hourly = nph_c
        else:
            yes_prob_hourly = None
            no_prob_hourly = None

        yes_ask_s = carried_yes
        no_ask_s = carried_no
        yes_bid_s: Optional[str] = None
        no_bid_s: Optional[str] = None
        yes_spread = None
        no_spread = None

        ml = money_line_diffs_and_active_side(
            float(strike_col),
            spot_f,
            float(prob_for_diff),
            yes_ask_s,
            no_ask_s,
        )
        if not ml:
            continue
        yes_diff_f, no_diff_f, active_side = ml

        ymn, ymx, nmn, nmx, yrg, nrg = final_quarter_ask_tracking_fields(
            event_ticker=ev_ticker,
            ticker=t,
            yes_ask_dollars=yes_ask_s,
            no_ask_dollars=no_ask_s,
            prev=prev_6,
        )
        prev_6 = (ev_ticker, t, ymn, ymx, nmn, nmx)

        if contract == "hourly" and ttc_h is not None and ttc_h > HOURLY_FINAL_QUARTER_TRACKING_SEC:
            ymn = ymx = nmn = nmx = yrg = nrg = None  # match strike_table_generator hourly rule

        minute_key = ts_naive.replace(second=0, microsecond=0)
        vol_t, oi_t = candle_by_minute.get(minute_key, (None, None))

        mom_raw = row.get("momentum")
        try:
            momentum_score = float(mom_raw) if mom_raw is not None else 0.0
        except (TypeError, ValueError):
            momentum_score = 0.0
        try:
            mom_pct = float(row["momentum_percentile"]) if row.get("momentum_percentile") is not None else 0.0
        except (TypeError, ValueError):
            mom_pct = 0.0
        vol = row.get("volatility")
        vol_pct = row.get("volatility_percentile")
        mov = row.get("movement")
        mov_pct = row.get("movement_percentile")

        batch.append(
            (
                ts_naive,
                sym.upper(),
                _EXCHANGE,
                market_label,
                Decimal(str(round(spot_f, 5))),
                int(ttc_h) if ttc_h is not None else None,
                int(ttc_15m),
                ev_ticker,
                market_title,
                0,
                None,
                Decimal(str(round(float(strike_col), 5))),
                Decimal(str(round(float(buf), 5))),
                Decimal(str(buf_pct)) if buf_pct is not None else None,
                _d52(probability_hourly_v),
                _d52(float(probability_15m)),
                _d52(yes_prob_hourly),
                _d52(no_prob_hourly),
                _d52(yp15_c),
                _d52(np15_c),
                yes_ask_s,
                no_ask_s,
                yes_bid_s,
                no_bid_s,
                yes_spread,
                no_spread,
                _d52(yes_diff_f),
                _d52(no_diff_f),
                vol_t,
                oi_t,
                t,
                active_side,
                Decimal(str(round(momentum_score, 3))),
                Decimal(str(round(mom_pct, 1))),
                Decimal(str(vol)) if vol is not None else None,
                Decimal(str(vol_pct)) if vol_pct is not None else None,
                Decimal(str(mov)) if mov is not None else None,
                Decimal(str(mov_pct)) if mov_pct is not None else None,
                Decimal(str(ymn)) if ymn is not None else None,
                Decimal(str(ymx)) if ymx is not None else None,
                Decimal(str(nmn)) if nmn is not None else None,
                Decimal(str(nmx)) if nmx is not None else None,
                Decimal(str(yrg)) if yrg is not None else None,
                Decimal(str(nrg)) if nrg is not None else None,
                ts_naive,
            )
        )

    ins = f"""
        INSERT INTO backtest.{rel} (
            "timestamp", symbol, exchange, market, current_price, ttc_hourly, ttc_15m,
            event_ticker, market_title, strike_tier, market_status, strike, buffer, buffer_pct,
            probability_hourly, probability_15m, yes_prob_hourly, no_prob_hourly,
            yes_prob_15m, no_prob_15m,
            yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
            yes_price_spread, no_price_spread, yes_diff, no_diff,
            volume_fp, open_interest_fp, ticker, active_side,
            momentum_weighted_score, momentum_percentile, volatility, volatility_percentile,
            movement, movement_percentile,
            yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
            yes_ask_range_15m, no_ask_range_15m,
            created_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s
        )
    """
    with conn.cursor() as cur:
        cur.executemany(ins, batch)
    conn.commit()

    pinned = bool((os.environ.get("REC_PROBABILITY_LOOKUP_TABLE") or "").strip())
    return {
        "ok": True,
        "table": f"backtest.{rel}",
        "market_ticker": t,
        "probability_lookup_table": getattr(calc, "lookup_table_name", None),
        "probability_lookup_pinned": pinned,
        "live_rows": len(live_rows),
        "trade_rows_source": len(trades),
        "rows_inserted": len(batch),
        "candle_minutes_loaded": len(candle_by_minute),
        "window_et_naive": [t_start.isoformat(), t_end.isoformat()],
        "time_zone": "America/New_York",
    }


def build_tick_backtest_from_strike_archive(
    conn: Any,
    market_ticker: str,
    *,
    truncate: bool = True,
    timestamp_start: Any = None,
    timestamp_end_exclusive: Any = None,
) -> dict[str, Any]:
    """
    Fill ``backtest.tick_backtest_<slug>`` from ``historical_data.strike_table_master`` for one
    ``market_ticker``.     Rows use the same column layout as the synthetic tick builder. Archive ``timestamp`` /
    ``created_at`` are already US Eastern **naive** (``timestamp without time zone``). When several
    archive rows share the same Eastern second, keep the row with the greatest ``id``.

    Optional ``timestamp_start`` / ``timestamp_end_exclusive`` filter archive rows on
    ``s."timestamp"`` (Eastern naive). Pass naive Eastern datetimes or values comparable to the
    stored wall times.
    """
    t = validate_kalshi_market_ticker(market_ticker)
    rel = tick_backtest_relname(t)
    ensure_tick_backtest_table(conn, rel)
    if truncate:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE backtest.{rel};")

    extra_where = ""
    params: list[Any] = [t]
    if timestamp_start is not None:
        extra_where += ' AND s."timestamp" >= %s'
        params.append(timestamp_start)
    if timestamp_end_exclusive is not None:
        extra_where += ' AND s."timestamp" < %s'
        params.append(timestamp_end_exclusive)

    ins_sql = f"""
        INSERT INTO backtest.{rel} (
            "timestamp", symbol, exchange, market, current_price, ttc_hourly, ttc_15m,
            event_ticker, market_title, strike_tier, market_status, strike, buffer, buffer_pct,
            probability_hourly, probability_15m, yes_prob_hourly, no_prob_hourly,
            yes_prob_15m, no_prob_15m,
            yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
            yes_price_spread, no_price_spread, yes_diff, no_diff,
            volume_fp, open_interest_fp, ticker, active_side,
            momentum_weighted_score, momentum_percentile, volatility, volatility_percentile,
            movement, movement_percentile,
            yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
            yes_ask_range_15m, no_ask_range_15m,
            created_at
        )
        SELECT DISTINCT ON (s."timestamp")
            s."timestamp" AS ts_naive,
            s.symbol, s.exchange, s.market, s.current_price, s.ttc_hourly, s.ttc_15m,
            s.event_ticker, s.market_title, s.strike_tier, s.market_status, s.strike, s.buffer, s.buffer_pct,
            s.probability_hourly, s.probability_15m, s.yes_prob_hourly, s.no_prob_hourly,
            s.yes_prob_15m, s.no_prob_15m,
            s.yes_ask_dollars, s.no_ask_dollars, s.yes_bid_dollars, s.no_bid_dollars,
            s.yes_price_spread, s.no_price_spread, s.yes_diff, s.no_diff,
            s.volume_fp, s.open_interest_fp,
            COALESCE(NULLIF(BTRIM(s.ticker::text), ''), s.market_ticker),
            s.active_side,
            s.momentum_weighted_score, s.momentum_percentile, s.volatility, s.volatility_percentile,
            s.movement, s.movement_percentile,
            s.yes_ask_min_15m, s.yes_ask_max_15m, s.no_ask_min_15m, s.no_ask_max_15m,
            s.yes_ask_range_15m, s.no_ask_range_15m,
            COALESCE(s.created_at, s."timestamp") AS created_naive
        FROM historical_data.strike_table_master s
        WHERE s.market_ticker = %s
        {extra_where}
        ORDER BY s."timestamp", s.id DESC
    """
    with conn.cursor() as cur:
        cur.execute(ins_sql, tuple(params))
        n = cur.rowcount
    conn.commit()

    out = {
        "ok": True,
        "source": "historical_data.strike_table_master",
        "table": f"backtest.{rel}",
        "market_ticker": t,
        "rows_inserted": int(n) if n is not None else 0,
        "time_zone": "America/New_York",
    }
    if timestamp_start is not None or timestamp_end_exclusive is not None:
        out["archive_timestamp_filter"] = {
            "start": str(timestamp_start) if timestamp_start is not None else None,
            "end_exclusive": str(timestamp_end_exclusive) if timestamp_end_exclusive is not None else None,
        }
    return out

