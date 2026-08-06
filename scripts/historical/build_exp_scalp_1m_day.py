#!/usr/bin/env python3
"""Build historical_data.test_exp_scalp_1m_<YYYYMMDD> for an Eastern trading day.

For each KXBTC15M cycle, take the final-minute 1m candlestick (market close bar,
not the post-close summary), then:

- tradeable_1m: True if YES ask or NO ask (= 1 - yes_bid) was in [0.90, 0.99]
- proj_trades: ordered rising-edge sequence of band entries (Y/N/YN/NY/…)
  reconstructed from final-minute OHLC path (ordering matters).

Example:
  PYTHONPATH=$(pwd) venv/bin/python scripts/historical/build_exp_scalp_1m_day.py \\
    --date 2026-08-02
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.btc15m_cycle_candles import (  # noqa: E402
    contract_label_from_15m_ticker,
    settlement_end_utc_iso_from_ticker,
)
from backend.core.config.database import get_system_postgresql_connection  # noqa: E402
from backend.core.kalshi_event_market_fetch import kalshi_trade_api_base  # noqa: E402
from backend.core.trade_history_detail import fetch_kalshi_market  # noqa: E402
from scripts.backtest.helpers.kalshi_ticker_construct import (  # noqa: E402
    kalshi_15m_market_tickers_for_eastern_date,
    parse_eastern_trading_day_arg,
)

SERIES = "KXBTC15M"
EASTERN = ZoneInfo("America/New_York")
MIN_ASK = Decimal("0.90")
MAX_ASK = Decimal("0.99")


def D(v: Any) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def utc_iso_z_from_unix(ts: int | float) -> str:
    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _http_json(url: str, *, retries: int = 6) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "rec_io_exp_scalp_1m/1.0"},
    )
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code != 429 or attempt + 1 >= retries:
                raise
            sleep_s = min(30.0, 2.0 ** attempt)
            print(f"HTTP 429; retry in {sleep_s:.1f}s ({attempt + 1}/{retries})", file=sys.stderr)
            time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc


def _nested(obj: Any, field: str) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    v = obj.get(field)
    return None if v is None else str(v)


def in_band(ask: Optional[Decimal]) -> bool:
    return ask is not None and MIN_ASK <= ask <= MAX_ASK


def yes_ok(yes_ask: Optional[Decimal]) -> bool:
    return in_band(yes_ask)


def no_ok(yes_bid: Optional[Decimal]) -> bool:
    if yes_bid is None:
        return False
    return in_band(Decimal("1") - yes_bid)


def sample_pair_path(
    bid_o: Decimal,
    bid_h: Decimal,
    bid_l: Decimal,
    bid_c: Decimal,
    ask_o: Decimal,
    ask_h: Decimal,
    ask_l: Decimal,
    ask_c: Decimal,
) -> list[tuple[Decimal, Decimal]]:
    """
    Walk bid+ask together along a shared OHLC skeleton.

    Path rule (per series): if close < open then O->H->L->C else O->L->H->C.
    Densify each segment so band crossings are observed in chronological order.
    """
    if bid_c < bid_o:
        bid_skel = [bid_o, bid_h, bid_l, bid_c]
    else:
        bid_skel = [bid_o, bid_l, bid_h, bid_c]
    if ask_c < ask_o:
        ask_skel = [ask_o, ask_h, ask_l, ask_c]
    else:
        ask_skel = [ask_o, ask_l, ask_h, ask_c]

    pairs: list[tuple[Decimal, Decimal]] = []
    steps = 20
    for i in range(len(ask_skel)):
        b0, a0 = bid_skel[i], ask_skel[i]
        if not pairs:
            pairs.append((b0, a0))
            continue
        b_prev, a_prev = pairs[-1]
        for s in range(1, steps + 1):
            t = Decimal(s) / Decimal(steps)
            b = b_prev + (b0 - b_prev) * t
            a = a_prev + (a0 - a_prev) * t
            pairs.append((b, a))
    return pairs


def _rising_edge_side_seq(
    pairs: list[tuple[Decimal, Decimal]],
) -> str:
    """Rising-edge Y/N sequence; Y before N on same sample; collapse same-side reentry."""
    prev_y = False
    prev_n = False
    letters: list[str] = []
    for bid, ask in pairs:
        y = yes_ok(ask)
        n = no_ok(bid)
        for side, active, prev in (("Y", y, prev_y), ("N", n, prev_n)):
            if active and not prev:
                if not letters or letters[-1] != side:
                    letters.append(side)
        prev_y, prev_n = y, n
    return "".join(letters)


def sample_open_close_path(
    bid_o: Decimal,
    bid_c: Decimal,
    ask_o: Decimal,
    ask_c: Decimal,
    *,
    steps: int = 40,
) -> list[tuple[Decimal, Decimal]]:
    """Linear open→close path only (no H/L wicks)."""
    pairs: list[tuple[Decimal, Decimal]] = [(bid_o, ask_o)]
    for s in range(1, steps + 1):
        t = Decimal(s) / Decimal(steps)
        pairs.append((bid_o + (bid_c - bid_o) * t, ask_o + (ask_c - ask_o) * t))
    return pairs


def proj_trades_from_final_minute(candle: dict[str, Any]) -> tuple[bool, str]:
    """Opportunity map: rising-edge Y/N from full final-minute OHLC (includes H/L)."""
    bid_o = D(candle.get("yes_bid_open_dollars"))
    bid_h = D(candle.get("yes_bid_high_dollars"))
    bid_l = D(candle.get("yes_bid_low_dollars"))
    bid_c = D(candle.get("yes_bid_close_dollars"))
    ask_o = D(candle.get("yes_ask_open_dollars"))
    ask_h = D(candle.get("yes_ask_high_dollars"))
    ask_l = D(candle.get("yes_ask_low_dollars"))
    ask_c = D(candle.get("yes_ask_close_dollars"))
    if None in (bid_o, bid_h, bid_l, bid_c, ask_o, ask_h, ask_l, ask_c):
        letters: list[str] = []
        if ask_o is not None and yes_ok(ask_o):
            letters.append("Y")
        if bid_o is not None and no_ok(bid_o):
            letters.append("N")
        seq = "".join(letters)
        return (bool(seq), seq)

    pairs = sample_pair_path(bid_o, bid_h, bid_l, bid_c, ask_o, ask_h, ask_l, ask_c)
    seq = _rising_edge_side_seq(pairs)
    return (bool(seq), seq)


def proj_trades_aes_from_final_minute(candle: dict[str, Any]) -> str:
    """
    AES-closer proxy from the same final-minute candle.

    Differs from proj_trades by ignoring H/L wicks and only walking open→close
    (what a ~1s scanner can follow as a continuous move, without counting
    intra-bar extremes that may never sit on a scan). Same rising-edge /
    collapse semantics (Y, N, YN, NY, …).
    """
    bid_o = D(candle.get("yes_bid_open_dollars"))
    bid_c = D(candle.get("yes_bid_close_dollars"))
    ask_o = D(candle.get("yes_ask_open_dollars"))
    ask_c = D(candle.get("yes_ask_close_dollars"))
    if None in (bid_o, bid_c, ask_o, ask_c):
        letters: list[str] = []
        if ask_o is not None and yes_ok(ask_o):
            letters.append("Y")
        if bid_o is not None and no_ok(bid_o):
            letters.append("N")
        return "".join(letters)

    pairs = sample_open_close_path(bid_o, bid_c, ask_o, ask_c, steps=40)
    return _rising_edge_side_seq(pairs)


def flatten_candle(ticker: str, c: dict[str, Any]) -> dict[str, Any]:
    price = c.get("price") or {}
    yes_bid = c.get("yes_bid") or {}
    yes_ask = c.get("yes_ask") or {}
    return {
        "ticker": ticker,
        "end_period_ts": utc_iso_z_from_unix(int(c["end_period_ts"])),
        "volume_fp": c.get("volume_fp"),
        "price_open_dollars": _nested(price, "open_dollars"),
        "price_high_dollars": _nested(price, "high_dollars"),
        "price_low_dollars": _nested(price, "low_dollars"),
        "price_close_dollars": _nested(price, "close_dollars"),
        "yes_bid_open_dollars": _nested(yes_bid, "open_dollars"),
        "yes_bid_high_dollars": _nested(yes_bid, "high_dollars"),
        "yes_bid_low_dollars": _nested(yes_bid, "low_dollars"),
        "yes_bid_close_dollars": _nested(yes_bid, "close_dollars"),
        "yes_ask_open_dollars": _nested(yes_ask, "open_dollars"),
        "yes_ask_high_dollars": _nested(yes_ask, "high_dollars"),
        "yes_ask_low_dollars": _nested(yes_ask, "low_dollars"),
        "yes_ask_close_dollars": _nested(yes_ask, "close_dollars"),
    }


def fetch_candles(ticker: str, market: dict[str, Any]) -> list[dict[str, Any]]:
    open_dt = datetime.fromisoformat(str(market["open_time"]).replace("Z", "+00:00"))
    close_dt = datetime.fromisoformat(str(market["close_time"]).replace("Z", "+00:00"))
    start_ts = int(open_dt.timestamp()) - 60
    end_ts = int(close_dt.timestamp()) + 60
    enc = urllib.parse.quote(ticker, safe="")
    base = kalshi_trade_api_base()
    url = (
        f"{base}/series/{SERIES}/markets/{enc}/candlesticks"
        f"?start_ts={start_ts}&end_ts={end_ts}&period_interval=1"
    )
    payload = _http_json(url)
    return list(payload.get("candlesticks") or [])


def pick_final_minute(
    rows: list[dict[str, Any]], close_time_iso: str
) -> Optional[dict[str, Any]]:
    close_dt = datetime.fromisoformat(str(close_time_iso).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )
    close_key = close_dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    for r in rows:
        if r["end_period_ts"] == close_key:
            return r
    if len(rows) >= 2:
        return rows[-2]
    return rows[-1] if rows else None


def table_name_for_day(day: date) -> str:
    return f"test_exp_scalp_1m_{day.strftime('%Y%m%d')}"


def ensure_table(cur: Any, table: str) -> None:
    cur.execute("CREATE SCHEMA IF NOT EXISTS historical_data")
    cur.execute(f"DROP TABLE IF EXISTS historical_data.{table}")
    cur.execute(
        f"""
        CREATE TABLE historical_data.{table} (
            "timestamp" TEXT NOT NULL,
            ticker TEXT NOT NULL,
            contract TEXT,
            market_result TEXT,
            final_minute_end_period_ts TEXT,
            yes_bid_open_dollars TEXT,
            yes_bid_high_dollars TEXT,
            yes_bid_low_dollars TEXT,
            yes_bid_close_dollars TEXT,
            yes_ask_open_dollars TEXT,
            yes_ask_high_dollars TEXT,
            yes_ask_low_dollars TEXT,
            yes_ask_close_dollars TEXT,
            price_open_dollars TEXT,
            price_high_dollars TEXT,
            price_low_dollars TEXT,
            price_close_dollars TEXT,
            volume_fp TEXT,
            tradeable_1m BOOLEAN NOT NULL,
            proj_trades TEXT NOT NULL,
            proj_trades_aes TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (ticker)
        )
        """
    )
    cur.execute(
        f'CREATE INDEX IF NOT EXISTS idx_{table}_timestamp '
        f'ON historical_data.{table} ("timestamp")'
    )


INSERT_TMPL = """
INSERT INTO historical_data.{table} (
    "timestamp", ticker, contract, market_result, final_minute_end_period_ts,
    yes_bid_open_dollars, yes_bid_high_dollars, yes_bid_low_dollars, yes_bid_close_dollars,
    yes_ask_open_dollars, yes_ask_high_dollars, yes_ask_low_dollars, yes_ask_close_dollars,
    price_open_dollars, price_high_dollars, price_low_dollars, price_close_dollars,
    volume_fp, tradeable_1m, proj_trades, proj_trades_aes
) VALUES (
    %(timestamp)s, %(ticker)s, %(contract)s, %(market_result)s, %(final_minute_end_period_ts)s,
    %(yes_bid_open_dollars)s, %(yes_bid_high_dollars)s, %(yes_bid_low_dollars)s, %(yes_bid_close_dollars)s,
    %(yes_ask_open_dollars)s, %(yes_ask_high_dollars)s, %(yes_ask_low_dollars)s, %(yes_ask_close_dollars)s,
    %(price_open_dollars)s, %(price_high_dollars)s, %(price_low_dollars)s, %(price_close_dollars)s,
    %(volume_fp)s, %(tradeable_1m)s, %(proj_trades)s, %(proj_trades_aes)s
)
"""


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", required=True, help="Eastern calendar day YYYY-MM-DD")
    p.add_argument("--sleep", type=float, default=0.15)
    p.add_argument("--progress-every", type=int, default=10)
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    day = parse_eastern_trading_day_arg(args.date)
    table = table_name_for_day(day)
    tickers = kalshi_15m_market_tickers_for_eastern_date(SERIES, day)
    print(f"day={day.isoformat()} count={len(tickers)} table=historical_data.{table}")

    conn = get_system_postgresql_connection()
    if not conn:
        print("No Postgres connection", file=sys.stderr)
        return 1

    ok = 0
    fail = 0
    try:
        with conn.cursor() as cur:
            ensure_table(cur, table)
        conn.commit()

        for i, ticker in enumerate(tickers):
            if i and args.sleep > 0:
                time.sleep(args.sleep)
            try:
                market, src = fetch_kalshi_market(ticker)
                sticks = fetch_candles(ticker, market)
                rows = [flatten_candle(ticker, c) for c in sticks]
                rows.sort(key=lambda r: r["end_period_ts"])
                final = pick_final_minute(rows, str(market["close_time"]))
                if final is None:
                    raise RuntimeError("no final minute candle")
                tradeable, proj = proj_trades_from_final_minute(final)
                proj_aes = proj_trades_aes_from_final_minute(final)
                mr = market.get("result") or market.get("market_result")
                mr = str(mr).strip() if mr is not None and str(mr).strip() else None
                payload = {
                    "timestamp": settlement_end_utc_iso_from_ticker(ticker),
                    "ticker": ticker,
                    "contract": contract_label_from_15m_ticker(ticker, symbol="BTC"),
                    "market_result": mr,
                    "final_minute_end_period_ts": final["end_period_ts"],
                    "yes_bid_open_dollars": final["yes_bid_open_dollars"],
                    "yes_bid_high_dollars": final["yes_bid_high_dollars"],
                    "yes_bid_low_dollars": final["yes_bid_low_dollars"],
                    "yes_bid_close_dollars": final["yes_bid_close_dollars"],
                    "yes_ask_open_dollars": final["yes_ask_open_dollars"],
                    "yes_ask_high_dollars": final["yes_ask_high_dollars"],
                    "yes_ask_low_dollars": final["yes_ask_low_dollars"],
                    "yes_ask_close_dollars": final["yes_ask_close_dollars"],
                    "price_open_dollars": final["price_open_dollars"],
                    "price_high_dollars": final["price_high_dollars"],
                    "price_low_dollars": final["price_low_dollars"],
                    "price_close_dollars": final["price_close_dollars"],
                    "volume_fp": final["volume_fp"],
                    "tradeable_1m": tradeable,
                    "proj_trades": proj,
                    "proj_trades_aes": proj_aes,
                }
                with conn.cursor() as cur:
                    cur.execute(INSERT_TMPL.format(table=table), payload)
                conn.commit()
                ok += 1
                if (
                    args.progress_every <= 0
                    or (i + 1) % args.progress_every == 0
                    or i == 0
                    or i + 1 == len(tickers)
                ):
                    print(
                        f"[{i + 1}/{len(tickers)}] {ticker} tradeable={tradeable} "
                        f"proj={proj!r} aes={proj_aes!r} result={mr} src={src}"
                    )
            except Exception as exc:
                fail += 1
                try:
                    conn.rollback()
                except Exception:
                    pass
                print(f"FAIL {ticker}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE tradeable_1m),
                       COUNT(*) FILTER (WHERE proj_trades = 'Y'),
                       COUNT(*) FILTER (WHERE proj_trades = 'N'),
                       COUNT(*) FILTER (WHERE proj_trades = 'YN'),
                       COUNT(*) FILTER (WHERE proj_trades = 'NY'),
                       COUNT(*) FILTER (WHERE length(proj_trades) > 2),
                       COUNT(*) FILTER (WHERE proj_trades_aes = 'Y'),
                       COUNT(*) FILTER (WHERE proj_trades_aes = 'N'),
                       COUNT(*) FILTER (WHERE proj_trades_aes = 'YN'),
                       COUNT(*) FILTER (WHERE proj_trades_aes = 'NY')
                FROM historical_data.{table}
                """
            )
            print(
                "summary count/tradeable/Y/N/YN/NY/longer | aes Y/N/YN/NY",
                cur.fetchone(),
            )
            cur.execute(
                f"""
                SELECT ticker, contract, tradeable_1m, proj_trades, proj_trades_aes, market_result
                FROM historical_data.{table}
                WHERE ticker IN (
                    'KXBTC15M-26AUG020130-30',
                    'KXBTC15M-26AUG020300-00',
                    'KXBTC15M-26AUG020600-00',
                    'KXBTC15M-26AUG021215-15',
                    'KXBTC15M-26AUG021230-30',
                    'KXBTC15M-26AUG021245-45'
                )
                ORDER BY "timestamp"
                """
            )
            print("known checks:")
            for r in cur.fetchall():
                print(" ", r)
    finally:
        conn.close()

    print(f"done ok={ok} fail={fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
