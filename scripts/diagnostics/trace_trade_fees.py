#!/usr/bin/env python3
"""
Trace how total fees for a single live trade were determined from opening and closing orders.

We only ever pay taker fees; maker_fees_dollars should be 0. Prints the trade row and the
corresponding rows from ``users.orders_<slot>`` for open and close (taker_fees_dollars, maker_fees_dollars,
and the sum used for each leg).

Usage (from project root):
  PYTHONPATH=$(pwd) python3 scripts/diagnostics/trace_trade_fees.py <trade_id>
Example:
  PYTHONPATH=$(pwd) python3 scripts/diagnostics/trace_trade_fees.py 10988

Read-only: SELECT only.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_legacy_sql import legacy_users_orders, legacy_users_trades
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no


def _parse_dollars(value):
    """Match trade_manager: fixed-point dollar value to float."""
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(description="Trace fee breakdown for one trade (read-only).")
    add_user_no_argument(parser)
    parser.add_argument("trade_id", type=int, help="Trades table id")
    args = parser.parse_args()
    trade_id = args.trade_id
    user_no = resolve_user_no(args)
    trades_t = legacy_users_trades(user_no)
    orders_t = legacy_users_orders(user_no)

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("Failed to connect to database.")
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, order_id_open, order_id_close, fees, buy_price, position, sell_price,
                       close_method, status, ticker, paper_trade
                FROM {trades_t}
                WHERE id = %s
            """,
                (trade_id,),
            )
            row = cur.fetchone()
        if not row:
            print(f"Trade {trade_id} not found.")
            return

        (id_, order_id_open, order_id_close, fees, buy_price, position, sell_price,
         close_method, status, ticker, paper_trade) = row

        print(f"=== Trade {id_} === ")
        print(f"  ticker={ticker} status={status} paper_trade={paper_trade}")
        print(f"  buy_price={buy_price} position={position} sell_price={sell_price}")
        print(f"  close_method={close_method}")
        print(f"  order_id_open={order_id_open}")
        print(f"  order_id_close={order_id_close}")
        print(f"  fees (stored total)={fees}")
        print()

        open_fees_usd = None
        close_fees_usd = None

        if order_id_open:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT order_id, side, fill_count_fp, remaining_count_fp, status,
                           taker_fees_dollars, maker_fees_dollars,
                           taker_fill_cost_dollars, maker_fill_cost_dollars
                    FROM {orders_t}
                    WHERE order_id = %s
                """,
                    (order_id_open,),
                )
                orow = cur.fetchone()
            if orow:
                (oid, side, fill_count_fp, rem_fp, order_status,
                 taker_fees_dollars, maker_fees_dollars,
                 taker_fill_cost_dollars, maker_fill_cost_dollars) = orow
                taker_usd = _parse_dollars(taker_fees_dollars)
                maker_usd = _parse_dollars(maker_fees_dollars)
                open_fees_usd = (taker_usd or 0.0) + (maker_usd or 0.0)
                print(f"=== Opening order ({orders_t}) ===")
                print(f"  order_id={oid} side={side} status={order_status}")
                print(f"  fill_count_fp={fill_count_fp} remaining_count_fp={rem_fp}")
                print(f"  taker_fees_dollars={taker_fees_dollars} -> {taker_usd}")
                print(f"  maker_fees_dollars={maker_fees_dollars} -> {maker_usd}")
                print(f"  open leg fees = {open_fees_usd} (taker only; we never pay maker)")
                print(f"  taker_fill_cost_dollars={taker_fill_cost_dollars} maker_fill_cost_dollars={maker_fill_cost_dollars}")
            else:
                print(f"=== Opening order: not found in {orders_t} ===")
            print()

        if order_id_close:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT order_id, side, fill_count_fp, remaining_count_fp, status,
                           taker_fees_dollars, maker_fees_dollars,
                           taker_fill_cost_dollars, maker_fill_cost_dollars
                    FROM {orders_t}
                    WHERE order_id = %s
                """,
                    (order_id_close,),
                )
                crow = cur.fetchone()
            if crow:
                (oid, side, fill_count_fp, rem_fp, order_status,
                 taker_fees_dollars, maker_fees_dollars,
                 taker_fill_cost_dollars, maker_fill_cost_dollars) = crow
                taker_usd = _parse_dollars(taker_fees_dollars)
                maker_usd = _parse_dollars(maker_fees_dollars)
                close_fees_usd = (taker_usd or 0.0) + (maker_usd or 0.0)
                print(f"=== Closing order ({orders_t}) ===")
                print(f"  order_id={oid} side={side} status={order_status}")
                print(f"  fill_count_fp={fill_count_fp} remaining_count_fp={rem_fp}")
                print(f"  taker_fees_dollars={taker_fees_dollars} -> {taker_usd}")
                print(f"  maker_fees_dollars={maker_fees_dollars} -> {maker_usd}")
                print(f"  close leg fees = {close_fees_usd} (taker only; we never pay maker)")
                print(f"  taker_fill_cost_dollars={taker_fill_cost_dollars} maker_fill_cost_dollars={maker_fill_cost_dollars}")
            else:
                print(f"=== Closing order: not found in {orders_t} ===")
            print()

        # Reconstructed total
        if open_fees_usd is not None or close_fees_usd is not None:
            reconstructed = (open_fees_usd or 0.0) + (close_fees_usd or 0.0)
            print("=== Fee summary ===")
            print(f"  open leg:  {open_fees_usd}")
            print(f"  close leg: {close_fees_usd}")
            print(f"  reconstructed total (open + close) = {reconstructed}")
            print(f"  stored {trades_t}.fees = {fees}")
            if fees is not None and abs(reconstructed - float(fees)) > 0.001:
                print(f"  (mismatch: diff = {float(fees) - reconstructed})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
