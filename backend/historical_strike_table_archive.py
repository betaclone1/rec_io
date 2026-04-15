"""
Append-only archive of live strike table rows into ``historical_data``.

Single logical table:

  ``historical_data.strike_table_master``

Partitioned monthly by ``timestamp`` (UTC instant / ``TIMESTAMPTZ``). Writers ensure the
current month partition exists before insert.

Rows mirror unified live strike table inserts (45-value tuple: symbol .. created_at), plus:
- ``market_ticker`` (the Kalshi market ticker from row ``ticker``)
- ``market_result`` (NULL until lifecycle outcome writes YES/NO)

Enable/disable: ``REC_STRIKE_TABLE_ARCHIVE`` (default ``1``; set ``0`` to disable).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Sequence

logger = logging.getLogger(__name__)

MASTER_TABLE = "historical_data.strike_table_master"
_ENSURED_PARTITIONS: set[str] = set()


def strike_archive_enabled() -> bool:
    v = (os.getenv("REC_STRIKE_TABLE_ARCHIVE") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _month_bounds_utc(ts: datetime) -> tuple[datetime, datetime]:
    t = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
    t = t.astimezone(timezone.utc)
    start = datetime(t.year, t.month, 1, tzinfo=timezone.utc)
    if t.month == 12:
        end = datetime(t.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(t.year, t.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _partition_relname_for_ts(ts: datetime) -> str:
    t = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
    t = t.astimezone(timezone.utc)
    return f"strike_table_master_{t.year:04d}{t.month:02d}"


def ensure_master_table(cursor: Any) -> None:
    cursor.execute("CREATE SCHEMA IF NOT EXISTS historical_data")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS historical_data.strike_table_master (
            id BIGINT GENERATED ALWAYS AS IDENTITY,
            symbol VARCHAR(10) NOT NULL,
            exchange VARCHAR(20) NOT NULL,
            market TEXT DEFAULT '15m',
            market_ticker VARCHAR(64) NOT NULL,
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
            "timestamp" TIMESTAMP WITH TIME ZONE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            market_result TEXT,
            PRIMARY KEY (id, "timestamp")
        ) PARTITION BY RANGE ("timestamp")
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS strike_table_master_market_ts_idx
            ON historical_data.strike_table_master (market_ticker, "timestamp" DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS strike_table_master_symbol_market_ts_idx
            ON historical_data.strike_table_master (symbol, market, "timestamp" DESC)
        """
    )


def ensure_month_partition(cursor: Any, ts: datetime) -> None:
    start, end = _month_bounds_utc(ts)
    rel = _partition_relname_for_ts(ts)
    if rel in _ENSURED_PARTITIONS:
        return
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS historical_data.{rel}
        PARTITION OF historical_data.strike_table_master
        FOR VALUES FROM (%s) TO (%s)
        """,
        (start, end),
    )
    cursor.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {rel}_market_ts_idx
            ON historical_data.{rel} (market_ticker, "timestamp" DESC)
        """
    )
    cursor.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {rel}_symbol_market_ts_idx
            ON historical_data.{rel} (symbol, market, "timestamp" DESC)
        """
    )
    _ENSURED_PARTITIONS.add(rel)


def ensure_partitions_months_ahead(cursor: Any, months_ahead: int = 2) -> list[str]:
    """Ensure current month plus N future monthly partitions."""
    ensured: list[str] = []
    now_utc = datetime.now(timezone.utc)
    year = now_utc.year
    month = now_utc.month
    for _ in range(max(0, int(months_ahead)) + 1):
        ts = datetime(year, month, 1, tzinfo=timezone.utc)
        rel = _partition_relname_for_ts(ts)
        ensure_month_partition(cursor, ts)
        ensured.append(rel)
        month += 1
        if month == 13:
            month = 1
            year += 1
    return ensured


def append_strike_archive_row_from_live_tuple(
    cursor: Any,
    market_ticker: str,
    row: Sequence[Any],
) -> None:
    """
    Insert one archived row into ``historical_data.strike_table_master``.

    ``row`` must be the 45-value unified tuple used for live strike inserts.
    """
    if not strike_archive_enabled():
        return
    mt = str(market_ticker or "").strip()
    if not mt:
        return
    if len(row) != 45:
        raise ValueError(f"strike archive row must have 45 values, got {len(row)}")

    row_ts = row[43]
    if not isinstance(row_ts, datetime):
        raise ValueError(f"row[43] must be datetime, got {type(row_ts)}")

    ensure_master_table(cursor)
    ensure_month_partition(cursor, row_ts)

    cursor.execute(
        """
        INSERT INTO historical_data.strike_table_master (
            symbol, exchange, market, market_ticker, current_price, ttc_hourly, ttc_15m, event_ticker, market_title,
            strike_tier, market_status, strike, buffer, buffer_pct, probability_hourly, probability_15m,
            yes_prob_hourly, no_prob_hourly, yes_prob_15m, no_prob_15m,
            yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
            yes_price_spread, no_price_spread, yes_diff, no_diff, volume_fp, open_interest_fp, ticker, active_side,
            momentum_weighted_score, momentum_percentile, volatility, volatility_percentile, movement, movement_percentile,
            yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m, yes_ask_range_15m, no_ask_range_15m,
            "timestamp", created_at, market_result
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL
        )
        """,
        (
            row[0],   # symbol
            row[1],   # exchange
            row[2],   # market
            mt,       # market_ticker
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            row[8],
            row[9],
            row[10],
            row[11],
            row[12],
            row[13],
            row[14],
            row[15],
            row[16],
            row[17],
            row[18],
            row[19],
            row[20],
            row[21],
            row[22],
            row[23],
            row[24],
            row[25],
            row[26],
            row[27],
            row[28],
            row[29],
            row[30],
            row[31],
            row[32],
            row[33],
            row[34],
            row[35],
            row[36],
            row[37],
            row[38],
            row[39],
            row[40],
            row[41],
            row[42],
            row[43],  # timestamp
            row[44],  # created_at
        ),
    )


def backfill_strike_archive_market_result(market_ticker: str, market_result: str) -> None:
    """Set ``market_result`` on all archived rows for one market ticker."""
    if not strike_archive_enabled():
        return
    mt = str(market_ticker or "").strip()
    res = str(market_result or "").strip().lower()
    if not mt or res not in ("yes", "no"):
        return

    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            ensure_master_table(cur)
            cur.execute(
                """
                UPDATE historical_data.strike_table_master
                   SET market_result = %s
                 WHERE market_ticker = %s
                """,
                (res, mt),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("strike archive market_result backfill failed ticker=%s", mt)
    finally:
        try:
            conn.close()
        except Exception:
            pass
