#!/usr/bin/env python3
"""
Standalone **one-market** entry simulator: walk 1m Kalshi candle rows for a ticker,
join BTC spot from ``historical_data.btc_price_history``, rebuild a single-strike row
per minute (probability via the same **analytics** lookup path as ``strike_table_generator``),
and apply **Hourly HTC** gates from ``backend.util.auto_entry_htc_gates`` (AES mirror).

Does **not** import ``auto_entry_supervisor``. Read-only on DB except optional candle upsert.

**Run with the project venv** (``psycopg2`` lives there — not system ``python3``)::

  REC_IO_BACKTEST_DB=local .venv/bin/python3 scripts/backtest/backtest_market_simulator.py ...

**Local default storage:** ``--storage testing`` writes/reads ``testing.\"candlesticks_1m_<ticker>\"``
(same layout as ``scripts/testing/populate_kalshi_testing_candles_1m.py``). For the default ticker,
apply migration ``20260322_1420_testing_candlesticks_1m_kxbtc15m_26mar191745_45`` on your local DB
before the first ``--fetch-candles``. Other tickers need their own testing-table migration or use
``--storage scratch`` + ``historical_data.kalshi_candles_1m_*``.

**First-test ticker (default):** ``KXBTC15M-26MAR191745-45``

**Live stack parity (15m):** each minute uses BTC **close** as spot, **strike** =
``int(floor_strike)`` chosen like ``StrikeTableGenerator`` (closest to spot when
multiple markets), **buffer** = ``int(abs(spot - strike))``,
**momentum_bucket** = ``round(momentum_percentile)``, **TTC** = seconds to next
:00/:15/:30/:45 in US/Eastern (same as ``ttc_15m`` / 15m ``calculate_ttc_seconds``),
**Hourly HTC TTC window** when no ``--monitor-row-id``: **60–900s** (1m through 15m of time
remaining; ``min_time``/``max_time`` from a monitor row override this).

**Contract interval (15m vs hourly):** default ``--market auto`` infers from the ticker: if it
contains ``15M`` (e.g. ``KXBTC15M-...``) → **15m** (``ttc_15m`` + ``probability_15m``-style lookup);
otherwise **hourly** (e.g. ``KXBTCD-...`` → ``ttc_hourly`` + hourly probability). Override with
``--market 15m`` or ``--market hourly`` when needed.

**Gate profile:** ``--htc-gate-mode full`` matches ``check_auto_entry_conditions_hourly_htc``.
``--htc-gate-mode simulated-15m`` matches ``check_simulated_15m_entry_hourly_htc`` (uses ``ttc_15m``
for the TTC window even on hourly contracts, and 15m-style probability — same as live reading the
hourly strike table’s ``ttc_15m`` / ``probability_15m``).

Then **two**
``get_probability`` calls and ``probability_15m or probability`` as in
``strike_table_generator.generate_strike_table``. ``--mock-probability`` skips
lookup entirely (debug only).

**After the first qualifying entry (in-window gate pass):** the script sizes contracts as
``floor((bankroll * allotment_pct/100) / buy_price)`` (defaults: ``--bankroll-dollars 5000``,
``--allotment-pct 25``), estimates **open** taker fees via ``estimate_kalshi_taker_fee``, settles at
``market.close_time`` (BTC row in ``historical_data.btc_price_history``) with the same YES/NO vs
strike rules as ``trade_manager`` paper expiry (1.0 / 0.0 payout, **no** close fee), prints PnL,
return % vs bankroll (same ``ret_pct`` shape as trades: bankroll in cents in the formula), and ROI
on premium deployed.

Prerequisites
-------------
- Postgres via ``scripts/backtest/helpers/db.py`` — for local work set ``REC_IO_BACKTEST_DB=local``.
- BTC rows in ``historical_data.btc_price_history`` (naive US Eastern ``timestamp`` aligned to candles).
- ``analytics.probability_lookup_btc_master_*`` on that DB (unless ``--mock-probability``).

Examples::

  REC_IO_BACKTEST_DB=local .venv/bin/python3 scripts/db/run_migration.py up 20260322_1420_testing_candlesticks_1m_kxbtc15m_26mar191745_45

  REC_IO_BACKTEST_DB=local .venv/bin/python3 scripts/backtest/backtest_market_simulator.py --fetch-candles

  # Ephemeral scratch table on prod-style DB (optional)
  REC_IO_BACKTEST_DB=prod .venv/bin/python3 scripts/backtest/backtest_market_simulator.py --storage scratch --fetch-candles --as-of 2026-03-21
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.util.auto_entry_htc_gates import (  # noqa: E402
    evaluate_hourly_htc_strike_entry,
    money_line_diffs_and_active_side,
)
from scripts.backtest.helpers.constants import MONITOR_LIST_TABLE  # noqa: E402
from scripts.backtest.helpers.db import get_connection  # noqa: E402
from scripts.backtest.helpers.hypothetical_trades import estimate_kalshi_taker_fee  # noqa: E402
from scripts.backtest.helpers.htc_aes_replay import (  # noqa: E402
    infer_contract_market_from_kalshi_ticker,
    seconds_to_next_15m_boundary_ny,
    seconds_to_next_hour_boundary_ny,
    ttc_seconds_in_window,
)
from scripts.backtest.helpers.kalshi_candles_1m import (  # noqa: E402
    ensure_historical_schema,
    ensure_scratch_table,
    fetch_markets_payload,
    infer_series_ticker,
    quoted_table_for_ticker,
    run_fill,
    scratch_table_name,
    scratch_table_qualified,
    validate_kalshi_market_ticker,
)

DEFAULT_TICKER = "KXBTC15M-26MAR191745-45"

# Identifier injection guard: only our scratch naming convention.
_SCRATCH_QUALIFIED_RE = re.compile(
    r"^historical_data\.kalshi_candles_1m_[a-z0-9_]+_\d{8}$"
)
_MONITOR_TABLE_RE = re.compile(r"^users\.monitor_list_[0-9]+$")


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def _naive_ts_to_aware_et(ts: datetime) -> datetime:
    from zoneinfo import ZoneInfo

    if ts.tzinfo is not None:
        return ts
    return ts.replace(tzinfo=ZoneInfo("America/New_York"))


def _iso_z_to_naive_eastern(s: str) -> datetime:
    """Kalshi API ISO time → US Eastern wall clock naive (matches btc / candle ``timestamp``)."""
    from zoneinfo import ZoneInfo

    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)


def settlement_is_winner(*, side: str, strike: float, symbol_close: float) -> bool:
    """
    Same rules as ``trade_manager`` paper settlement (expired → closed):
    YES wins if symbol_close >= strike; NO wins if symbol_close <= strike.
    """
    s = (side or "").strip().lower()
    if s in ("yes", "y"):
        return float(symbol_close) >= float(strike)
    if s in ("no", "n"):
        return float(symbol_close) <= float(strike)
    raise ValueError(f"invalid side for settlement: {side!r}")


def _float_or_none(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _dollars_pair_from_candle(row: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """YES ask / NO ask in dollars from 1m candle close legs; NO ≈ 1 - YES bid when bid present."""
    ya = _float_or_none(row.get("yes_ask_close_dollars"))
    yb = _float_or_none(row.get("yes_bid_close_dollars"))
    no_a: Optional[float] = None
    if yb is not None:
        no_a = max(0.001, min(0.999, 1.0 - yb))
    return ya, no_a


def _testing_candles_table_exists(conn: Any, ticker: str) -> bool:
    validate_kalshi_market_ticker(ticker)
    reg = f'testing."candlesticks_1m_{ticker}"'
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (reg,))
        row = cur.fetchone()
    return bool(row and row[0])


def _load_candles(conn: Any, from_clause: str, ticker: str) -> list[dict[str, Any]]:
    """``from_clause`` is a validated table reference (testing quoted id or historical_data.name)."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT "timestamp", end_period_ts, market_ticker,
                   yes_ask_close_dollars, yes_bid_close_dollars,
                   price_close_dollars, volume_fp
            FROM {from_clause}
            WHERE market_ticker = %s
            ORDER BY "timestamp" ASC
            """,
            (ticker,),
        )
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            out.append(dict(zip(cols, r)))
    return out


def _load_btc_close_and_momentum(conn: Any, ts_naive: datetime) -> tuple[Optional[float], Optional[float]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT close, momentum_percentile
            FROM historical_data.btc_price_history
            WHERE "timestamp" = %s
            LIMIT 1
            """,
            (ts_naive,),
        )
        row = cur.fetchone()
    if not row:
        return None, None
    return _float_or_none(row[0]), _float_or_none(row[1])


def _load_monitor_settings(conn: Any, table_fq: str, row_id: int) -> dict[str, Any]:
    """table_fq e.g. users.monitor_list_<slot> (validated)."""
    if not _MONITOR_TABLE_RE.fullmatch(table_fq.strip()):
        raise ValueError(f"invalid monitor table (expected users.monitor_list_<digits>): {table_fq!r}")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT min_probability, max_probability, min_differential, max_differential,
                   min_time, max_time, min_volume, max_ask, prob_adj
            FROM {table_fq}
            WHERE id = %s
            """,
            (row_id,),
        )
        r = cur.fetchone()
    if not r:
        raise RuntimeError(f"no monitor row id={row_id} in {table_fq}")
    return {
        "min_probability": float(r[0]) if r[0] is not None else 95.0,
        "max_probability": float(r[1]) if r[1] is not None else 100.0,
        "min_differential": float(r[2]) if r[2] is not None else 0.0,
        "max_differential": float(r[3]) if r[3] is not None else None,
        "min_time": r[4],
        "max_time": r[5],
        "min_volume": int(r[6]) if r[6] is not None else 1000,
        "max_ask": float(r[7]) if r[7] is not None else 0.98,
        "prob_adj": float(r[8]) if r[8] is not None else 5.0,
    }


def _default_settings() -> dict[str, Any]:
    return {
        "min_probability": 95.0,
        "max_probability": 100.0,
        "min_differential": 0.25,
        "max_differential": None,
        "min_time": 60,
        "max_time": 900,
        "min_volume": 1000,
        "max_ask": 0.98,
        "prob_adj": 5.0,
    }


def _floor_strike_to_scalar(fs: Any) -> float:
    if fs is None:
        raise ValueError("missing floor_strike")
    if isinstance(fs, dict):
        inner = fs.get("value") or fs.get("dollars")
        if inner is None:
            raise ValueError(f"unexpected floor_strike shape: {fs!r}")
        fs = inner
    return float(fs)


def strike_int_15m_closest_to_spot(api_payload: Mapping[str, Any], current_price: float) -> int:
    """
    Match ``StrikeTableGenerator`` 15m branch: collect ``int(floor_strike)`` from
    ``markets`` (or the single ``market``), sort by ``abs(strike - spot)``, take first.
    """
    strikes: list[int] = []
    for mm in api_payload.get("markets") or []:
        fs = mm.get("floor_strike")
        if fs is not None:
            strikes.append(int(_floor_strike_to_scalar(fs)))
    if not strikes:
        m = api_payload.get("market") or {}
        fs = m.get("floor_strike")
        if fs is None:
            raise RuntimeError(f"no floor_strike in API payload: {api_payload!r}")
        strikes.append(int(_floor_strike_to_scalar(fs)))
    strikes.sort(key=lambda s: abs(float(s) - current_price))
    return strikes[0]


def lookup_probability_strike_table_15m(
    calc: Any,
    *,
    strike_int: int,
    current_price: float,
    ttc_seconds: int,
    ttc_15m_seconds: int,
    momentum_bucket: int,
    conn: Any,
) -> Optional[float]:
    """
    Same selection as ``generate_strike_table`` for ``interval == '15m'``:
    buffer = ``abs(spot - strike)``, two lookups, then ``probability_15m or probability``.
    """
    buffer = abs(current_price - strike_int)
    bpts = int(buffer)
    pos1, neg1 = calc.get_probability(ttc_seconds, bpts, momentum_bucket, conn=conn)
    pos15, neg15 = calc.get_probability(ttc_15m_seconds, bpts, momentum_bucket, conn=conn)
    if strike_int < current_price:
        prob = pos1
        prob_15m = pos15
    else:
        prob = neg1
        prob_15m = neg15
    if prob_15m is not None:
        return float(prob_15m)
    if prob is not None:
        return float(prob)
    return None


def lookup_probability_strike_table_hourly(
    calc: Any,
    *,
    strike_int: int,
    current_price: float,
    ttc_hourly: int,
    momentum_bucket: int,
    conn: Any,
) -> Optional[float]:
    """
    Same ``probability_hourly`` selection as ``generate_strike_table`` for ``interval == 'hourly'``:
    one ``get_probability(ttc_hourly, buffer_pts, momentum_bucket)`` by side.
    """
    bpts = int(abs(current_price - strike_int))
    pos, neg = calc.get_probability(ttc_hourly, bpts, momentum_bucket, conn=conn)
    if strike_int < current_price:
        return float(pos) if pos is not None else None
    return float(neg) if neg is not None else None


def _aes_window_ttc(
    *,
    contract_market: str,
    gate_profile: str,
    ts_et: datetime,
) -> tuple[int, str]:
    """
    Seconds compared to ``min_time``/``max_time`` (same shape as ``get_current_ttc()``).

    Simulated 15m path always uses ``ttc_15m`` from the hourly strike table; mirror that with
    the next :00/:15/:30/:45 boundary even when the contract is hourly.
    """
    if gate_profile == "simulated_15m":
        return seconds_to_next_15m_boundary_ny(ts_et), "ttc_15m"
    if contract_market == "15m":
        return seconds_to_next_15m_boundary_ny(ts_et), "ttc_15m"
    return seconds_to_next_hour_boundary_ny(ts_et), "ttc_hourly"


def _build_strike_row(
    *,
    strike: float,
    current_price: float,
    probability: float,
    yes_ask_d: float,
    no_ask_d: float,
    volume: int,
    ticker: str,
) -> Optional[dict[str, Any]]:
    diffs = money_line_diffs_and_active_side(
        strike, current_price, probability, yes_ask_d, no_ask_d
    )
    if diffs is None:
        return None
    yes_diff, no_diff, active_side = diffs
    return {
        "strike": strike,
        "buffer": abs(current_price - strike),
        "buffer_pct": (abs(current_price - strike) / current_price * 100) if current_price else None,
        "probability": probability,
        "yes_ask_dollars": yes_ask_d,
        "no_ask_dollars": no_ask_d,
        "volume_fp": str(int(volume)),
        "ticker": ticker,
        "yes_diff": yes_diff,
        "no_diff": no_diff,
        "active_side": active_side,
        "yes_price_spread": None,
        "no_price_spread": None,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Simulate one Kalshi market cycle with AES Hourly HTC gate mirror.")
    p.add_argument("--ticker", default=DEFAULT_TICKER, help="Kalshi market ticker")
    p.add_argument(
        "--storage",
        choices=("testing", "scratch"),
        default="testing",
        help="testing: testing.\"candlesticks_1m_<ticker>\" (local default). scratch: historical_data.kalshi_candles_1m_*",
    )
    p.add_argument(
        "--as-of",
        metavar="YYYY-MM-DD",
        default=None,
        help="With --storage scratch: UTC calendar date table suffix (default: UTC today). Ignored for testing.",
    )
    p.add_argument(
        "--scratch-table",
        default=None,
        help="With --storage scratch only: override historical_data table name",
    )
    p.add_argument("--fetch-candles", action="store_true", help="Upsert 1m candles via Kalshi API then simulate")
    p.add_argument("--symbol", default="btc", help="Probability lookup symbol (default btc)")
    p.add_argument(
        "--mock-probability",
        type=float,
        default=None,
        metavar="PCT",
        help="Debug only: fixed prob every minute (ignores buffer/momentum/TTC lookup; not live parity)",
    )
    p.add_argument(
        "--monitor-table",
        default=MONITOR_LIST_TABLE,
        help="Qualified monitor_list table for --monitor-row-id",
    )
    p.add_argument(
        "--monitor-row-id",
        type=int,
        default=None,
        help="Load min/max prob, diff, TTC window, volume, max_ask from this monitor row",
    )
    p.add_argument("--spike-alert", action="store_true", help="Treat spike cooldown as active (prob_adj on min_probability)")
    p.add_argument("--min-time", type=int, default=None, help="Override min_time seconds (TTC window)")
    p.add_argument("--max-time", type=int, default=None, help="Override max_time seconds (TTC window)")
    p.add_argument(
        "--no-gate-reasons",
        action="store_true",
        help="Omit first failing Hourly HTC gate reason on each line",
    )
    p.add_argument(
        "--market",
        choices=("auto", "15m", "hourly"),
        default="auto",
        help="auto: 15m if ticker contains 15M (e.g. KXBTC15M-...), else hourly (e.g. KXBTCD-...)",
    )
    p.add_argument(
        "--htc-gate-mode",
        choices=("full", "simulated-15m"),
        default="full",
        help=(
            "full: same gates as check_auto_entry_conditions_hourly_htc. "
            "simulated-15m: only prob (+spike) after TTC window; TTC window uses ttc_15m (15m boundary)"
        ),
    )
    p.add_argument(
        "--bankroll-dollars",
        type=float,
        default=5000.0,
        help="Bankroll in USD for ret_pct (same cents convention as trades.bankroll)",
    )
    p.add_argument(
        "--allotment-pct",
        type=float,
        default=25.0,
        help="Fraction of bankroll (0-100) allocated as premium budget for sizing contracts",
    )
    p.add_argument(
        "--emit-summary-json",
        action="store_true",
        help="Print one line SIM_SUMMARY_JSON {...} before exit (for batch / tooling)",
    )
    args = p.parse_args()

    as_of = _parse_date(args.as_of) if args.as_of else datetime.now(timezone.utc).date()
    ticker = validate_kalshi_market_ticker(args.ticker)
    if args.market == "auto":
        contract_market = infer_contract_market_from_kalshi_ticker(ticker)
        contract_market_source = "inferred"
    else:
        contract_market = args.market
        contract_market_source = "explicit"

    if args.storage == "testing":
        if args.scratch_table:
            p.error("--scratch-table is only valid with --storage scratch")
        candle_from = quoted_table_for_ticker(ticker)
        qualified_display = candle_from
        rel_only = None
    else:
        if args.scratch_table:
            rel = args.scratch_table.strip()
            if rel.startswith("historical_data."):
                qualified = rel
                rel_only = rel.split(".", 1)[1]
            else:
                rel_only = rel
                qualified = scratch_table_qualified(rel_only)
        else:
            rel_only = scratch_table_name(ticker, as_of)
            qualified = scratch_table_qualified(rel_only)
        if not _SCRATCH_QUALIFIED_RE.fullmatch(qualified):
            raise ValueError(f"refusing non-scratch table name: {qualified!r}")
        candle_from = qualified
        qualified_display = qualified

    def _emit_summary(payload: dict[str, Any]) -> None:
        if args.emit_summary_json:
            print("SIM_SUMMARY_JSON " + json.dumps(payload, separators=(",", ":")), flush=True)

    conn = get_connection()
    try:
        if args.storage == "testing" and not _testing_candles_table_exists(conn, ticker):
            print(
                "Missing testing candle table for this ticker. Add a migration (see scripts/migrations/*testing_candlesticks_1m*), "
                "then apply it. For the default ticker:",
                file=sys.stderr,
            )
            print(
                "  REC_IO_BACKTEST_DB=local .venv/bin/python3 scripts/db/run_migration.py up "
                "20260322_1420_testing_candlesticks_1m_kxbtc15m_26mar191745_45",
                file=sys.stderr,
            )
            _emit_summary({"ticker": ticker, "first_hit": False, "reason": "missing_testing_table"})
            return 1

        if args.fetch_candles:
            if args.storage == "testing":
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA IF NOT EXISTS testing")
                conn.commit()
                n = run_fill(
                    conn,
                    ticker,
                    infer_series_ticker(ticker),
                    target_table=candle_from,
                )[2]
            else:
                ensure_historical_schema(conn)
                ensure_scratch_table(conn, rel_only, ticker)
                n = run_fill(
                    conn,
                    ticker,
                    infer_series_ticker(ticker),
                    target_table=candle_from,
                )[2]
            conn.commit()
            print(f"Fetched and upserted {n} candle rows into {qualified_display}")

        market_payload = fetch_markets_payload(ticker)
        if args.mock_probability is not None:
            print(
                "WARNING: --mock-probability skips strike-table probability lookup; not live-stack parity.",
                file=sys.stderr,
            )

        if args.monitor_row_id is not None:
            settings = _load_monitor_settings(conn, args.monitor_table, args.monitor_row_id)
        else:
            settings = _default_settings()
        if args.min_time is not None:
            settings["min_time"] = args.min_time
        if args.max_time is not None:
            settings["max_time"] = args.max_time

        candles = _load_candles(conn, candle_from, ticker)
        if not candles:
            print(f"No rows in {qualified_display} for ticker {ticker}", file=sys.stderr)
            _emit_summary({"ticker": ticker, "first_hit": False, "reason": "no_candle_rows"})
            return 1

        calc = None
        if args.mock_probability is None:
            from backend.strike_table_generator import LookupProbabilityCalculator  # noqa: E402

            calc = LookupProbabilityCalculator(args.symbol.lower())

        first_hit: Optional[dict[str, Any]] = None
        spike_active = bool(args.spike_alert)
        mom_null_warned = False

        for i, cndl in enumerate(candles):
            ts_naive = cndl["timestamp"]
            if isinstance(ts_naive, datetime):
                pass
            else:
                ts_naive = datetime.combine(ts_naive, datetime.min.time())

            ts_et = _naive_ts_to_aware_et(ts_naive)
            gate_profile = "simulated_15m" if args.htc_gate_mode == "simulated-15m" else "full"
            ttc, ttc_role = _aes_window_ttc(
                contract_market=contract_market, gate_profile=gate_profile, ts_et=ts_et
            )
            in_win = ttc_seconds_in_window(ttc, settings["min_time"], settings["max_time"])

            btc_close, mom_pct = _load_btc_close_and_momentum(conn, ts_naive)
            if btc_close is None:
                print(f"  [{i+1}/{len(candles)}] {ts_naive} skip: no BTC row")
                continue

            strike_int = strike_int_15m_closest_to_spot(market_payload, btc_close)
            buffer_pts = int(abs(btc_close - strike_int))

            if mom_pct is None:
                if not mom_null_warned and args.mock_probability is None:
                    print(
                        "Note: BTC momentum_percentile is NULL; using momentum_bucket=0 for lookup (differs from live if missing).",
                        file=sys.stderr,
                    )
                    mom_null_warned = True
                momentum_bucket = 0
            else:
                momentum_bucket = int(round(mom_pct))

            yes_d, no_d = _dollars_pair_from_candle(cndl)
            if yes_d is None or no_d is None:
                print(f"  [{i+1}/{len(candles)}] {ts_naive} skip: missing yes ask / derivable no ask")
                continue

            vol_raw = cndl.get("volume_fp")
            if vol_raw is None:
                volume = 0
            else:
                try:
                    volume = int(Decimal(str(vol_raw)))
                except Exception:
                    volume = int(float(vol_raw))

            if args.mock_probability is not None:
                probability = float(args.mock_probability)
            else:
                if calc is None:
                    raise RuntimeError("internal: probability calculator missing")
                if gate_profile == "simulated_15m" or contract_market == "15m":
                    ttc_15m = seconds_to_next_15m_boundary_ny(ts_et)
                    probability = lookup_probability_strike_table_15m(
                        calc,
                        strike_int=strike_int,
                        current_price=btc_close,
                        ttc_seconds=ttc_15m,
                        ttc_15m_seconds=ttc_15m,
                        momentum_bucket=momentum_bucket,
                        conn=conn,
                    )
                else:
                    ttc_h = seconds_to_next_hour_boundary_ny(ts_et)
                    probability = lookup_probability_strike_table_hourly(
                        calc,
                        strike_int=strike_int,
                        current_price=btc_close,
                        ttc_hourly=ttc_h,
                        momentum_bucket=momentum_bucket,
                        conn=conn,
                    )
                if probability is None:
                    print(
                        f"  [{i+1}/{len(candles)}] {ts_naive} skip: lookup miss "
                        f"(ttc={ttc} {ttc_role}, buf={buffer_pts}, strike={strike_int}, mom={momentum_bucket})"
                    )
                    continue

            strike_row = _build_strike_row(
                strike=float(strike_int),
                current_price=btc_close,
                probability=probability,
                yes_ask_d=yes_d,
                no_ask_d=no_d,
                volume=volume,
                ticker=ticker,
            )
            if strike_row is None:
                print(f"  [{i+1}/{len(candles)}] {ts_naive} skip: could not build diffs")
                continue

            status = "in_ttc_window" if in_win else "outside_ttc_window"
            payload = None
            gate_detail = ""
            if in_win:
                payload, fail_reason = evaluate_hourly_htc_strike_entry(
                    settings,
                    strike_row,
                    spike_alert_active=spike_active,
                    gate_profile=gate_profile,
                )
                if payload and first_hit is None:
                    first_hit = {
                        "minute_index": i + 1,
                        "timestamp_et": ts_naive,
                        "ttc_seconds": ttc,
                        "payload": payload,
                        "strike_row": strike_row,
                        "btc_close": float(btc_close),
                    }
                if payload:
                    gate = "PASS"
                else:
                    gate = "fail"
                    if not args.no_gate_reasons and fail_reason:
                        gate_detail = f" | {fail_reason}"
                print(
                    f"  [{i+1}/{len(candles)}] {ts_naive} TTC={ttc}s ({ttc_role}) {status} | "
                    f"spot={btc_close:.2f} strike={strike_int} buf={buffer_pts} mom={momentum_bucket} "
                    f"side={strike_row.get('active_side')} prob={probability:.2f} | {gate}{gate_detail}"
                )
            else:
                _as = strike_row.get("active_side") if strike_row else "?"
                print(
                    f"  [{i+1}/{len(candles)}] {ts_naive} TTC={ttc}s ({ttc_role}) {status} | "
                    f"spot={btc_close:.2f} strike={strike_int} buf={buffer_pts} mom={momentum_bucket} "
                    f"side={_as} prob={probability:.2f} | (AES idle, gates not evaluated)"
                )

        print()
        print(
            f"Market: {ticker}  contract={contract_market} ({contract_market_source})  "
            f"storage={args.storage}  table={qualified_display}  "
            f"(strike closest to spot per minute, strike table generator parity)"
        )
        print(
            f"Settings: min/max prob {settings['min_probability']}/{settings['max_probability']}, "
            f"min_diff {settings['min_differential']}, TTC {settings['min_time']}-{settings['max_time']}s, "
            f"min_vol {settings.get('min_volume')}, max_ask {settings.get('max_ask')}  "
            f"| htc_gate_mode={args.htc_gate_mode}"
        )
        if first_hit:
            pl = first_hit["payload"]
            sr = first_hit["strike_row"]
            print(
                f"\nFirst qualifying minute (in TTC window): #{first_hit['minute_index']} at {first_hit['timestamp_et']} "
                f"(ttc={first_hit['ttc_seconds']}s)"
            )
            print(f"  side={pl['side']} buy_price={pl['buy_price']:.4f} prob={pl['probability']:.2f} ticker={pl.get('ticker')}")

            # --- Settlement & economics (trade_manager paper rules: open fee only at expiry) ---
            br_usd = float(args.bankroll_dollars)
            ap = float(args.allotment_pct)
            if br_usd <= 0 or ap <= 0:
                print("  Skipping settlement: --bankroll-dollars and --allotment-pct must be positive.", file=sys.stderr)
            else:
                buy_price = float(pl["buy_price"])
                side = str(pl["side"])
                strike_f = float(sr["strike"])
                allotment_usd = br_usd * (ap / 100.0)
                if buy_price <= 0 or buy_price >= 1:
                    print(f"  Skipping sizing: invalid buy_price {buy_price}", file=sys.stderr)
                else:
                    position = int(math.floor(allotment_usd / buy_price))
                    if position < 1:
                        print(
                            f"  Skipping settlement: allotment ${allotment_usd:.2f} cannot buy 1 contract at {buy_price:.4f}",
                            file=sys.stderr,
                        )
                    else:
                        premium_usd = round(position * buy_price, 2)
                        open_fee = estimate_kalshi_taker_fee(position, buy_price)

                        mkt = market_payload.get("market") or {}
                        close_iso = mkt.get("close_time")
                        settle_ts: Optional[datetime] = None
                        settle_source = ""
                        if close_iso:
                            try:
                                settle_ts = _iso_z_to_naive_eastern(str(close_iso))
                                settle_source = f"market.close_time → {settle_ts}"
                            except Exception as e:
                                print(f"  Warning: could not parse close_time {close_iso!r}: {e}", file=sys.stderr)
                        if settle_ts is None:
                            last_c = candles[-1]["timestamp"]
                            settle_ts = last_c if isinstance(last_c, datetime) else datetime.combine(last_c, datetime.min.time())
                            settle_source = f"last candle row → {settle_ts}"

                        btc_settle, _ = _load_btc_close_and_momentum(conn, settle_ts)
                        if btc_settle is None:
                            print(
                                f"  No BTC row at settlement {settle_ts} ({settle_source}); try aligning btc_price_history.",
                                file=sys.stderr,
                            )
                        else:
                            won = settlement_is_winner(side=side, strike=strike_f, symbol_close=float(btc_settle))
                            sell_price = 1.0 if won else 0.0
                            buy_value = round(buy_price * position, 2)
                            sell_value = round(sell_price * position, 2)
                            pnl = round(sell_value - buy_value - open_fee, 2)
                            bankroll_cents = int(round(br_usd * 100.0))
                            ret_pct = round((pnl / (bankroll_cents / 100.0)) * 100.0, 5) if bankroll_cents > 0 else None
                            roi_pct = round((pnl / buy_value) * 100.0, 5) if buy_value > 0 else None

                            print("\n--- Settlement & PnL (trade_manager paper rules) ---")
                            print(f"  Bankroll ${br_usd:,.2f}  allotment {ap:.1f}% → ${allotment_usd:,.2f} premium budget")
                            print(f"  Contracts {position} @ {buy_price:.4f} → premium ~${premium_usd:,.2f}")
                            print(f"  Open taker fee (estimate_kalshi_taker_fee): ${open_fee:.2f}  (no close fee at expiry)")
                            print(f"  Settlement: {settle_source}")
                            print(f"  BTC close at settlement: {btc_settle:.2f}  strike: {strike_f:.2f}")
                            print(
                                f"  Outcome: {'WIN' if won else 'LOSS'} "
                                f"({'YES' if side.lower() in ('yes', 'y') else 'NO'} vs strike per trade_manager)"
                            )
                            print(f"  Sell/settle price: {sell_price:.4f}  PnL: ${pnl:,.2f}")
                            if ret_pct is not None:
                                print(f"  Return on bankroll (trades ret_pct shape): {ret_pct:.5f}%")
                            if roi_pct is not None:
                                print(f"  ROI on premium deployed: {roi_pct:.5f}%")
        else:
            print("\nNo minute passed Hourly HTC gates inside the TTC window (or missing data).")

        _emit_summary(
            {
                "ticker": ticker,
                "contract_market": contract_market,
                "htc_gate_mode": args.htc_gate_mode,
                "first_hit": first_hit is not None,
                **(
                    {
                        "timestamp_et": (
                            first_hit["timestamp_et"].isoformat(sep=" ")
                            if isinstance(first_hit["timestamp_et"], datetime)
                            else str(first_hit["timestamp_et"])
                        ),
                        "minute_index": first_hit["minute_index"],
                        "buy_price": float(first_hit["payload"]["buy_price"]),
                        "strike_int": int(float(first_hit["strike_row"]["strike"])),
                        "btc_spot": float(first_hit["btc_close"]),
                        "side": str(first_hit["payload"].get("side") or ""),
                    }
                    if first_hit
                    else {}
                ),
            }
        )
        return 0
    except Exception as e:
        conn.rollback()
        print(e, file=sys.stderr)
        _emit_summary({"ticker": ticker, "first_hit": False, "error": str(e)})
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
