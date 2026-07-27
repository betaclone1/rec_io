#!/usr/bin/env python3
"""
Replay a testing BTC 15m orderbook cycle and check integrity.

Strong check (when mid-cycle resync snapshots exist):
  Start from snapshot A, apply all deltas tagged with snapshot_seq=A.seq
  in seq order; the reconstructed book must equal the next snapshot B.

Secondary check (always):
  After each applied delta, flag a Kalshi-style cross:
  best_yes_bid + best_no_bid > 1 (yes ask is complement of no bid).

Usage:
  .venv/bin/python scripts/testing/verify_cycle_orderbook.py \\
      KXBTC15M-26JUL252330-30

  .venv/bin/python scripts/testing/verify_cycle_orderbook.py \\
      --ticker KXBTC15M-26JUL252345-45 --max-cross-reports 20
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.config.database import get_system_postgresql_connection


def _qi(ident: str) -> str:
    return '"' + str(ident).replace('"', '""') + '"'


def _dec(v: Any) -> Decimal:
    return Decimal(str(v).strip())


def _apply_delta(
    yes: Dict[str, str], no: Dict[str, str], side: str, price: Any, delta: Any
) -> None:
    side_l = str(side).strip().lower()
    book = yes if side_l == "yes" else no
    px = str(_dec(price).quantize(Decimal("0.000001")))
    cur = _dec(book.get(px, "0"))
    new_sz = cur + _dec(delta)
    if new_sz <= 0:
        book.pop(px, None)
    else:
        book[px] = str(new_sz.quantize(Decimal("0.01")))


def _best_bid(levels: Dict[str, str]) -> Optional[Decimal]:
    if not levels:
        return None
    return max(_dec(p) for p in levels.keys())


def _cross_violation(yes: Dict[str, str], no: Dict[str, str]) -> Optional[str]:
    """Kalshi: yes ask ~= 1 - best no bid. Cross if best_yes + best_no > 1."""
    y = _best_bid(yes)
    n = _best_bid(no)
    if y is None or n is None:
        return None
    if y + n > Decimal("1"):
        return f"best_yes={y} best_no={n} sum={y + n}"
    return None


def _books_equal(a_yes: Dict[str, str], a_no: Dict[str, str], b_yes: Dict[str, str], b_no: Dict[str, str]) -> Tuple[bool, str]:
    def norm(d: Dict[str, str]) -> Dict[str, Decimal]:
        out: Dict[str, Decimal] = {}
        for p, s in d.items():
            sz = _dec(s)
            if sz > 0:
                out[str(_dec(p).quantize(Decimal("0.000001")))] = sz.quantize(Decimal("0.01"))
        return out

    ay, an, by, bn = norm(a_yes), norm(a_no), norm(b_yes), norm(b_no)
    if ay == by and an == bn:
        return True, ""
    only_a_y = sorted(set(ay) - set(by))[:5]
    only_b_y = sorted(set(by) - set(ay))[:5]
    diff_y = sorted(p for p in set(ay) & set(by) if ay[p] != by[p])[:5]
    only_a_n = sorted(set(an) - set(bn))[:5]
    only_b_n = sorted(set(bn) - set(an))[:5]
    diff_n = sorted(p for p in set(an) & set(bn) if an[p] != bn[p])[:5]
    return False, (
        f"yes only_a={only_a_y} only_b={only_b_y} size_diff={diff_y}; "
        f"no only_a={only_a_n} only_b={only_b_n} size_diff={diff_n}"
    )


def verify_cycle(ticker: str, *, max_cross_reports: int = 10) -> int:
    snap_t = f"{ticker}_snapshot"
    deltas_t = f"{ticker}_deltas"
    conn = get_system_postgresql_connection()
    if conn is None:
        print("ERROR: no DB connection", file=sys.stderr)
        return 2
    cur = conn.cursor()
    schema = None
    for sch in ("historical_data", "testing"):
        cur.execute(
            "SELECT to_regclass(%s), to_regclass(%s)",
            (f'{sch}."{snap_t}"', f'{sch}."{deltas_t}"'),
        )
        sreg, dreg = cur.fetchone()
        if sreg and dreg:
            schema = sch
            break
    if not schema:
        print(
            f'ERROR: missing "{snap_t}" / "{deltas_t}" in historical_data or testing',
            file=sys.stderr,
        )
        conn.close()
        return 2
    print(f"schema={schema}")

    cur.execute(
        f"""
        SELECT seq, received_at, reason, yes, no
        FROM {schema}.{_qi(snap_t)}
        ORDER BY received_at, seq
        """
    )
    snaps: List[dict] = []
    for seq, received_at, reason, yes, no in cur.fetchall():
        if isinstance(yes, str):
            yes = json.loads(yes)
        if isinstance(no, str):
            no = json.loads(no)
        snaps.append(
            {
                "seq": int(seq),
                "received_at": received_at,
                "reason": reason,
                "yes": {str(k): str(v) for k, v in (yes or {}).items()},
                "no": {str(k): str(v) for k, v in (no or {}).items()},
            }
        )

    print(f"ticker={ticker}")
    print(f"snapshots={len(snaps)}")
    for s in snaps:
        print(
            f"  snap seq={s['seq']} at={s['received_at']} reason={s['reason']} "
            f"yes_levels={len(s['yes'])} no_levels={len(s['no'])}"
        )

    failures = 0
    cross_reports = 0
    total_cross_events = 0
    eras_checked = 0

    for i, snap in enumerate(snaps):
        next_snap = snaps[i + 1] if i + 1 < len(snaps) else None
        cur.execute(
            f"""
            SELECT seq, received_at, side, price, delta, snapshot_seq
            FROM {schema}.{_qi(deltas_t)}
            WHERE snapshot_seq = %s
            ORDER BY seq, received_at
            """,
            (snap["seq"],),
        )
        rows = cur.fetchall()
        print(
            f"\nera snapshot_seq={snap['seq']}: deltas={len(rows)} "
            f"-> next_snap={'seq=' + str(next_snap['seq']) if next_snap else 'END'}"
        )
        if not rows:
            print("  (no deltas tagged to this snapshot)")
            continue

        yes = dict(snap["yes"])
        no = dict(snap["no"])
        seq_prev = None
        for seq, received_at, side, price, delta, snapshot_seq in rows:
            seq_i = int(seq)
            if seq_prev is not None and seq_i <= seq_prev:
                print(f"  FAIL seq not increasing: {seq_prev} -> {seq_i} at {received_at}")
                failures += 1
            seq_prev = seq_i
            _apply_delta(yes, no, side, price, delta)
            xv = _cross_violation(yes, no)
            if xv:
                total_cross_events += 1
                if cross_reports < max_cross_reports:
                    print(f"  CROSS seq={seq_i} at={received_at}: {xv}")
                    cross_reports += 1

        if next_snap is not None:
            eras_checked += 1
            ok, detail = _books_equal(yes, no, next_snap["yes"], next_snap["no"])
            if ok:
                print(
                    f"  PASS replay matches next snapshot seq={next_snap['seq']} "
                    f"({next_snap['reason']})"
                )
            else:
                print(
                    f"  FAIL replay != next snapshot seq={next_snap['seq']} "
                    f"({next_snap['reason']}): {detail}"
                )
                failures += 1
        else:
            print(
                f"  (terminal era — no following snapshot to diff; "
                f"final levels yes={len(yes)} no={len(no)}; "
                f"cross_events_in_era={total_cross_events})"
            )

    print(
        f"\nsummary: snapshot_match_eras={eras_checked} failures={failures} "
        f"cross_events={total_cross_events}"
    )
    conn.close()
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "ticker",
        nargs="?",
        help="Market ticker base, e.g. KXBTC15M-26JUL252330-30",
    )
    p.add_argument("--ticker", dest="ticker_opt", help="Same as positional ticker")
    p.add_argument("--max-cross-reports", type=int, default=10)
    args = p.parse_args()
    ticker = (args.ticker_opt or args.ticker or "").strip()
    if not ticker:
        p.error("ticker required")
    if ticker.endswith("_snapshot") or ticker.endswith("_deltas"):
        ticker = ticker.rsplit("_", 1)[0]
    return verify_cycle(ticker, max_cross_reports=args.max_cross_reports)


if __name__ == "__main__":
    raise SystemExit(main())
