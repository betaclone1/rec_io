#!/usr/bin/env python3
"""Compare legacy and WS 15m strike-table outputs for cutover readiness."""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.core.config.database import get_postgresql_connection


def _rows_by_strike(rows: List[Tuple[Any, ...]]) -> Dict[float, Tuple[Any, ...]]:
    out: Dict[float, Tuple[Any, ...]] = {}
    for row in rows:
        strike = row[0]
        if strike is None:
            continue
        out[float(strike)] = row
    return out


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _compare_symbol(
    cursor, symbol: str, exchange: str, max_prob_delta: float
) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT MAX(timestamp) FROM live_data.strike_table_15m
        WHERE exchange = %s AND symbol = %s
        """,
        (exchange, symbol),
    )
    legacy_ts = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT MAX(timestamp) FROM live_data.strike_table_ws_15m
        WHERE exchange = %s AND symbol = %s
        """,
        (exchange, symbol),
    )
    ws_ts = cursor.fetchone()[0]

    if not legacy_ts or not ws_ts:
        return {
            "symbol": symbol,
            "status": "missing_batch",
            "legacy_ts": str(legacy_ts) if legacy_ts else None,
            "ws_ts": str(ws_ts) if ws_ts else None,
        }

    cursor.execute(
        """
        SELECT strike, yes_ask_dollars, no_ask_dollars, probability_15m, ttc_15m, ticker
        FROM live_data.strike_table_15m
        WHERE exchange = %s AND symbol = %s AND timestamp = %s
        ORDER BY strike
        """,
        (exchange, symbol, legacy_ts),
    )
    legacy_rows = cursor.fetchall()

    cursor.execute(
        """
        SELECT strike, yes_ask_dollars, no_ask_dollars, probability_15m, ttc_15m, ticker
        FROM live_data.strike_table_ws_15m
        WHERE exchange = %s AND symbol = %s AND timestamp = %s
        ORDER BY strike
        """,
        (exchange, symbol, ws_ts),
    )
    ws_rows = cursor.fetchall()

    legacy_map = _rows_by_strike(legacy_rows)
    ws_map = _rows_by_strike(ws_rows)
    legacy_strikes = set(legacy_map.keys())
    ws_strikes = set(ws_map.keys())

    missing_in_ws = sorted(legacy_strikes - ws_strikes)
    extra_in_ws = sorted(ws_strikes - legacy_strikes)

    ask_mismatch = 0
    ttc_mismatch = 0
    prob_delta_exceeds = 0
    max_prob_seen = 0.0
    for strike in sorted(legacy_strikes & ws_strikes):
        lrow = legacy_map[strike]
        wrow = ws_map[strike]
        if (lrow[1] != wrow[1]) or (lrow[2] != wrow[2]):
            ask_mismatch += 1
        if lrow[4] != wrow[4]:
            ttc_mismatch += 1
        lp = _safe_float(lrow[3])
        wp = _safe_float(wrow[3])
        if lp is not None and wp is not None:
            d = abs(lp - wp)
            max_prob_seen = max(max_prob_seen, d)
            if d > max_prob_delta:
                prob_delta_exceeds += 1

    return {
        "symbol": symbol,
        "status": "ok",
        "legacy_ts": str(legacy_ts),
        "ws_ts": str(ws_ts),
        "legacy_rows": len(legacy_rows),
        "ws_rows": len(ws_rows),
        "missing_in_ws": len(missing_in_ws),
        "extra_in_ws": len(extra_in_ws),
        "ask_mismatch": ask_mismatch,
        "ttc_mismatch": ttc_mismatch,
        "prob_delta_exceeds": prob_delta_exceeds,
        "max_prob_delta": round(max_prob_seen, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check parity between strike_table_15m and strike_table_ws_15m."
    )
    parser.add_argument("--exchange", default="kalshi")
    parser.add_argument("--symbols", default="BTC,ETH,SOL,XRP,DOGE")
    parser.add_argument("--max-prob-delta", type=float, default=2.0)
    parser.add_argument("--max-row-diff", type=int, default=0)
    parser.add_argument("--max-ask-mismatch", type=int, default=0)
    parser.add_argument("--max-ttc-mismatch", type=int, default=0)
    parser.add_argument("--max-missing-in-ws", type=int, default=0)
    parser.add_argument("--max-extra-in-ws", type=int, default=0)
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    conn = get_postgresql_connection()
    if not conn:
        print("ERROR: could not connect to PostgreSQL", file=sys.stderr)
        return 2

    results: List[Dict[str, Any]] = []
    failed_symbols: List[str] = []
    try:
        with conn.cursor() as cursor:
            for symbol in symbols:
                r = _compare_symbol(cursor, symbol, args.exchange, args.max_prob_delta)
                results.append(r)
                if r.get("status") != "ok":
                    failed_symbols.append(symbol)
                    continue
                row_diff = abs(int(r["legacy_rows"]) - int(r["ws_rows"]))
                if (
                    row_diff > args.max_row_diff
                    or int(r["ask_mismatch"]) > args.max_ask_mismatch
                    or int(r["ttc_mismatch"]) > args.max_ttc_mismatch
                    or int(r["missing_in_ws"]) > args.max_missing_in_ws
                    or int(r["extra_in_ws"]) > args.max_extra_in_ws
                    or int(r["prob_delta_exceeds"]) > 0
                ):
                    failed_symbols.append(symbol)
    finally:
        conn.close()

    summary = {
        "exchange": args.exchange,
        "symbols": symbols,
        "thresholds": {
            "max_prob_delta": args.max_prob_delta,
            "max_row_diff": args.max_row_diff,
            "max_ask_mismatch": args.max_ask_mismatch,
            "max_ttc_mismatch": args.max_ttc_mismatch,
            "max_missing_in_ws": args.max_missing_in_ws,
            "max_extra_in_ws": args.max_extra_in_ws,
        },
        "failed_symbols": failed_symbols,
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    return 1 if failed_symbols else 0


if __name__ == "__main__":
    raise SystemExit(main())
