#!/usr/bin/env python3
"""
Volatility Profile ETL (168-row baseline per symbol)

Output table (analytics schema):
  analytics.<symbol>_volatility_profile_<YYYYMMDD>

Columns:
  hour_of_week SMALLINT PRIMARY KEY (0..167)
  count_rows BIGINT NOT NULL
  mean_vol_1m DOUBLE PRECISION NOT NULL
  median_vol_1m DOUBLE PRECISION NOT NULL
  p90_vol_1m DOUBLE PRECISION NOT NULL
  p95_vol_1m DOUBLE PRECISION NOT NULL
  stddev_vol_1m DOUBLE PRECISION NOT NULL

Volatility definition per 1m bar:
  vol_range = (high - low) / NULLIF(open, 0)
  vol_close = ABS(close - LAG(close)) / NULLIF(LAG(close), 0)
  vol_1m = 0.5 * vol_range + 0.5 * vol_close

CLI:
  python volatility_profile.py --symbol BTC --asof 20251101
"""

import os
import sys
import argparse
from datetime import datetime

try:
    import psycopg2
except ImportError:
    psycopg2 = None


def get_db_connection():
    """Connect using env vars (defaults match local dev)."""
    host = os.getenv('DB_HOST', 'localhost')
    name = os.getenv('DB_NAME', 'rec_io_db')
    user = os.getenv('DB_USER', 'rec_io_user')
    pwd = os.getenv('DB_PASSWORD', 'rec_io_password')
    port = int(os.getenv('DB_PORT', '5432'))
    return psycopg2.connect(host=host, database=name, user=user, password=pwd, port=port)


def ensure_analytics_schema(conn):
    cur = conn.cursor()
    cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    conn.commit()
    cur.close()


def table_name(symbol: str, asof: str) -> str:
    return f"analytics.{symbol.lower()}_volatility_profile_{asof}"


def recreate_table(conn, fqtn: str):
    schema, name = fqtn.split(".")
    cur = conn.cursor()
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s)",
        (schema, name),
    )
    if cur.fetchone()[0]:
        cur.execute(f"DROP TABLE {schema}.{name}")
    cur.execute(
        f"""
        CREATE TABLE {schema}.{name} (
            hour_of_week SMALLINT PRIMARY KEY,
            count_rows BIGINT NOT NULL,
            mean_vol_1m DOUBLE PRECISION NOT NULL,
            median_vol_1m DOUBLE PRECISION NOT NULL,
            p90_vol_1m DOUBLE PRECISION NOT NULL,
            p95_vol_1m DOUBLE PRECISION NOT NULL,
            stddev_vol_1m DOUBLE PRECISION NOT NULL
        )
        """
    )
    conn.commit()
    cur.close()


def populate_profile(conn, fqtn: str, symbol: str):
    price = f"historical_data.{symbol.lower()}_price_history"
    schema, name = fqtn.split(".")
    cur = conn.cursor()
    cur.execute(
        f"""
        WITH base AS (
            SELECT 
                timestamp,
                (high::double precision - low::double precision) / NULLIF(open::double precision, 0) AS vol_range,
                ABS(close::double precision - LAG(close::double precision) OVER (ORDER BY timestamp))
                    / NULLIF(LAG(close::double precision) OVER (ORDER BY timestamp), 0) AS vol_close,
                (EXTRACT(DOW FROM timestamp)::int * 24 + EXTRACT(HOUR FROM timestamp)::int)::smallint AS hour_of_week
            FROM {price}
            WHERE open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL
        ), vols AS (
            SELECT hour_of_week, 0.5 * vol_range + 0.5 * vol_close AS vol_1m
            FROM base
            WHERE vol_range IS NOT NULL AND vol_close IS NOT NULL
        ), g AS (
            SELECT 
                AVG(vol_1m) AS g_mean,
                percentile_disc(0.5) WITHIN GROUP (ORDER BY vol_1m) AS g_median,
                percentile_disc(0.9) WITHIN GROUP (ORDER BY vol_1m) AS g_p90,
                percentile_disc(0.95) WITHIN GROUP (ORDER BY vol_1m) AS g_p95,
                stddev_pop(vol_1m) AS g_std
            FROM vols
        ), agg AS (
            SELECT 
                hour_of_week,
                COUNT(*)::bigint AS count_rows,
                AVG(vol_1m)::double precision AS mean_vol_1m,
                percentile_disc(0.5) WITHIN GROUP (ORDER BY vol_1m) AS median_vol_1m,
                percentile_disc(0.9) WITHIN GROUP (ORDER BY vol_1m) AS p90_vol_1m,
                percentile_disc(0.95) WITHIN GROUP (ORDER BY vol_1m) AS p95_vol_1m,
                stddev_pop(vol_1m) AS stddev_vol_1m
            FROM vols
            GROUP BY hour_of_week
        ), hours AS (
            SELECT generate_series(0,167)::smallint AS hour_of_week
        )
        INSERT INTO {schema}.{name} (hour_of_week, count_rows, mean_vol_1m, median_vol_1m, p90_vol_1m, p95_vol_1m, stddev_vol_1m)
        SELECT 
            h.hour_of_week,
            COALESCE(a.count_rows, 0) AS count_rows,
            COALESCE(a.mean_vol_1m, g.g_mean) AS mean_vol_1m,
            COALESCE(a.median_vol_1m, g.g_median) AS median_vol_1m,
            COALESCE(a.p90_vol_1m, g.g_p90) AS p90_vol_1m,
            COALESCE(a.p95_vol_1m, g.g_p95) AS p95_vol_1m,
            COALESCE(a.stddev_vol_1m, g.g_std) AS stddev_vol_1m
        FROM hours h
        LEFT JOIN agg a ON a.hour_of_week = h.hour_of_week
        CROSS JOIN g
        ORDER BY h.hour_of_week
        """
    )
    conn.commit()
    cur.close()


def print_summary(conn, fqtn: str):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {fqtn}")
    n = cur.fetchone()[0]
    print(f"Total rows: {n} (expected 168)")

    cur.execute(f"SELECT MIN(median_vol_1m), MAX(median_vol_1m) FROM {fqtn}")
    lo, hi = cur.fetchone()
    print(f"Median_vol_1m range: {lo:.6g} .. {hi:.6g}")

    cur.execute(
        f"""
        SELECT hour_of_week, mean_vol_1m
        FROM {fqtn}
        ORDER BY mean_vol_1m DESC
        LIMIT 5
        """
    )
    print("Top 5 hour_of_week by mean_vol_1m:")
    for how, mv in cur.fetchall():
        print(f"  {how}: {mv:.6g}")

    cur.execute(
        f"""
        SELECT 
            SUM((count_rows IS NULL)::int + (mean_vol_1m IS NULL)::int + (median_vol_1m IS NULL)::int +
                (p90_vol_1m IS NULL)::int + (p95_vol_1m IS NULL)::int + (stddev_vol_1m IS NULL)::int)
        FROM {fqtn}
        """
    )
    nulls = cur.fetchone()[0] or 0
    print(f"Null count across columns: {int(nulls)}")
    cur.close()


def main():
    parser = argparse.ArgumentParser(description="Generate 168-row volatility profile in analytics schema")
    parser.add_argument("--symbol", required=True, help="Symbol like BTC")
    parser.add_argument("--asof", required=False, help="As-of date YYYYMMDD (UTC)")
    args = parser.parse_args()

    if psycopg2 is None:
        print("❌ psycopg2 is not installed")
        sys.exit(1)

    symbol = args.symbol.upper()
    asof = args.asof or datetime.utcnow().strftime("%Y%m%d")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET TIME ZONE 'UTC'")
        conn.commit()
        cur.close()
    except Exception:
        pass

    ensure_analytics_schema(conn)
    fqtn = table_name(symbol, asof)
    print(f"📊 Building volatility_profile for {symbol} as of {asof} -> {fqtn}")
    recreate_table(conn, fqtn)
    populate_profile(conn, fqtn, symbol)
    print_summary(conn, fqtn)
    print("✅ Completed")
    conn.close()


if __name__ == "__main__":
    main()


