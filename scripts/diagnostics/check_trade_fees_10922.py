#!/usr/bin/env python3
"""One-off: trade 10922 - confirm closed before expiration and expected fees (taker formula)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.core.config.database import get_postgresql_connection


def estimate_kalshi_taker_fee(position: int, price: float) -> float:
    if position is None or position <= 0 or price is None or price <= 0 or price >= 1:
        return 0.0
    raw = 0.07 * position * price * (1.0 - price)
    return math.ceil(raw * 100) / 100


def main():
    conn = get_postgresql_connection()
    if not conn:
        print("No DB connection")
        sys.exit(1)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, buy_price, position, sell_price, fees, close_method, status, paper_trade, ticker, date
            FROM users.trades_0001 WHERE id = %s
        """, (10922,))
        row = cur.fetchone()
    conn.close()
    if not row:
        print("Trade 10922 not found")
        sys.exit(1)
    (id_, buy_price, position, sell_price, fees_stored, close_method, status, paper_trade, ticker, date) = row
    buy_price = float(buy_price) if buy_price is not None else None
    position = int(position) if position is not None else None
    sell_price = float(sell_price) if sell_price is not None else None
    fees_stored = float(fees_stored) if fees_stored is not None else None

    print("Trade 10922:", ticker, "date=", date, "status=", status, "paper_trade=", paper_trade)
    print("  buy_price=", buy_price, "position=", position, "sell_price=", sell_price)
    print("  close_method=", close_method)
    print("  fees (stored)=", fees_stored)
    closed_before_exp = close_method and str(close_method).lower() != "expired"
    print("  Closed before expiration?", closed_before_exp)
    if buy_price is not None and position is not None and sell_price is not None:
        open_fee = estimate_kalshi_taker_fee(position, buy_price)
        price_to_close = 1.0 - sell_price
        close_fee = estimate_kalshi_taker_fee(position, price_to_close) if 0 < price_to_close < 1 else 0.0
        total_expected = open_fee + close_fee
        print("  Expected (our calc): open_fee=", round(open_fee, 2), "close_fee=", round(close_fee, 2), "total=", round(total_expected, 2))
        if fees_stored is not None:
            print("  Match?", abs(fees_stored - total_expected) < 0.02)


if __name__ == "__main__":
    main()
