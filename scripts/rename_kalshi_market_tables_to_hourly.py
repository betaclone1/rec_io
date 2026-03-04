#!/usr/bin/env python3
import os

import psycopg2


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        database=os.getenv("POSTGRES_DB", "rec_io_db"),
        user=os.getenv("POSTGRES_USER", "rec_io_user"),
        password=os.getenv("POSTGRES_PASSWORD", "rec_io_password"),
    )


def rename_table(cursor, old_name: str, new_name: str):
    cursor.execute(
        """
        SELECT to_regclass(%s)
        """,
        (old_name,),
    )
    exists = cursor.fetchone()[0]
    if not exists:
        print(f"Table {old_name} does not exist, skipping")
        return

    cursor.execute(f'ALTER TABLE {old_name} RENAME TO "{new_name.split(".")[-1]}"')
    print(f"Renamed {old_name} -> {new_name}")


def main():
    mapping = {
        "live_data.market_kalshi_btc": "live_data.market_kalshi_hourly_btc",
        "live_data.market_kalshi_eth": "live_data.market_kalshi_hourly_eth",
        "live_data.market_kalshi_ndx": "live_data.market_kalshi_hourly_ndx",
        "live_data.market_kalshi_spx": "live_data.market_kalshi_hourly_spx",
    }

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                for old, new in mapping.items():
                    rename_table(cursor, old, new)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

