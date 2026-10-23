#!/usr/bin/env python3
"""
Recompute paper Taker Edge open/close fees and PnL (same Kalshi taker schedule as
Expiration / HTC). Maker Edge paper stays $0 and is not touched.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/db/backfill_paper_taker_edge_fees.py --user-no 0001 --dry-run
  PYTHONPATH=. .venv/bin/python scripts/db/backfill_paper_taker_edge_fees.py --user-no 0001 --apply
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _taker_fee(position: float, price: float) -> float:
    if position <= 0 or price is None or price <= 0 or price >= 1:
        return 0.0
    raw = 0.07 * float(position) * float(price) * (1.0 - float(price))
    return math.ceil(raw * 100) / 100


def _expected_fees(buy_price, position, sell_price, close_method, status) -> float:
    open_fee = _taker_fee(float(position or 0), float(buy_price or 0))
    st = str(status or "").strip().lower()
    cm = str(close_method or "").strip().lower()
    if st in ("open", "partial", "pending"):
        return open_fee
    if cm == "expired" or sell_price is None:
        return open_fee
    try:
        sell = float(sell_price)
    except (TypeError, ValueError):
        return open_fee
    # Settlement prices are not a taker close leg.
    if sell <= 0.0 or sell >= 1.0:
        return open_fee
    price_to_close = 1.0 - sell
    close_fee = _taker_fee(float(position or 0), price_to_close)
    return round(open_fee + close_fee, 2)


def main() -> int:
    from backend.core.config.database import get_postgresql_connection
    from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no

    p = argparse.ArgumentParser(description=__doc__)
    add_user_no_argument(p)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()
    user_no = resolve_user_no(args)
    schema = f"users_{user_no}"
    table = f"{schema}.trades_{user_no}"

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("DB unavailable", file=sys.stderr)
        return 1
    updated = 0
    scanned = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, buy_price, position, sell_price, fees, pnl, close_method, status,
                       bankroll, mtb_base_value, win_loss
                FROM {table}
                WHERE paper_trade IS TRUE
                  AND trade_strategy = 'Taker Edge'
                ORDER BY id
                """
            )
            rows = cur.fetchall() or []
            for row in rows:
                (
                    trade_id,
                    buy_price,
                    position,
                    sell_price,
                    fees,
                    pnl,
                    close_method,
                    status,
                    bankroll,
                    mtb_base,
                    win_loss,
                ) = row
                scanned += 1
                try:
                    buy = float(buy_price)
                    pos = float(position)
                except (TypeError, ValueError):
                    continue
                new_fees = _expected_fees(buy, pos, sell_price, close_method, status)
                old_fees = float(fees) if fees is not None else None
                st = str(status or "").strip().lower()
                new_pnl = None
                new_win = None
                new_ret = None
                new_ret_base = None
                new_roi = None
                if st in ("closed", "expired") and sell_price is not None:
                    try:
                        sell = float(sell_price)
                    except (TypeError, ValueError):
                        sell = None
                    if sell is not None:
                        new_pnl = round(sell * pos - buy * pos - new_fees, 6)
                        new_win = "W" if new_pnl > 0 else "L" if new_pnl < 0 else "D"
                        try:
                            br = float(bankroll) if bankroll is not None else 0.0
                        except (TypeError, ValueError):
                            br = 0.0
                        try:
                            mtb = float(mtb_base) if mtb_base is not None else 0.0
                        except (TypeError, ValueError):
                            mtb = 0.0
                        if br > 0:
                            new_ret = round((new_pnl / (br / 100.0)) * 100, 5)
                        if mtb > 0:
                            new_ret_base = round((new_pnl / (mtb / 100.0)) * 100, 5)
                        buy_value = buy * pos
                        if buy_value > 0:
                            new_roi = round((new_pnl / buy_value) * 100.0, 5)

                fees_changed = old_fees is None or abs(old_fees - new_fees) > 1e-9
                pnl_changed = False
                if new_pnl is not None:
                    try:
                        old_pnl = float(pnl) if pnl is not None else None
                    except (TypeError, ValueError):
                        old_pnl = None
                    pnl_changed = old_pnl is None or abs(old_pnl - new_pnl) > 1e-9
                if not fees_changed and not pnl_changed:
                    continue
                updated += 1
                print(
                    f"id={trade_id} status={status} close={close_method} "
                    f"fees {old_fees} -> {new_fees} pnl {pnl} -> {new_pnl}"
                )
                if args.apply:
                    if new_pnl is not None:
                        cur.execute(
                            f"""
                            UPDATE {table}
                            SET fees = %s,
                                pnl = %s,
                                win_loss = %s,
                                ret_pct = %s,
                                ret_pct_base = %s,
                                roi_pct = %s,
                                updated_at = NOW()
                            WHERE id = %s
                            """,
                            (
                                new_fees,
                                new_pnl,
                                new_win,
                                new_ret,
                                new_ret_base,
                                new_roi,
                                trade_id,
                            ),
                        )
                    else:
                        cur.execute(
                            f"""
                            UPDATE {table}
                            SET fees = %s, updated_at = NOW()
                            WHERE id = %s
                            """,
                            (new_fees, trade_id),
                        )
            if args.apply:
                conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: scanned={scanned} would_update_or_updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
