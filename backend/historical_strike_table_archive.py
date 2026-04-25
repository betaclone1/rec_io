"""
Append-only archive of live strike table rows into ``historical_data``.

Single logical table:

  ``historical_data.strike_table_master``

Partitioned monthly on ``timestamp`` (**US Eastern wall**, ``TIMESTAMP WITHOUT TIME ZONE``),
same convention as other ``historical_data`` time-series tables. Writers ensure the
current month partition exists before insert.

Rows mirror unified live strike table inserts (45-value tuple: symbol .. created_at), plus:
- ``market_ticker`` (the Kalshi market ticker from row ``ticker``)
- ``market_result`` (NULL until lifecycle outcome writes YES/NO)

Enable/disable: ``REC_STRIKE_TABLE_ARCHIVE`` (default ``1``; set ``0`` to disable).

Archive **source** (what gets written to ``historical_data.strike_table_master``):

- ``REC_STRIKE_TABLE_ARCHIVE_SOURCE=publisher`` (default): rows come only from
  ``strike_snapshot_publisher`` after each successful Redis publish — the same ladder
  payload AES/ATS consume when snapshots are fresh. The generator must **not** archive
  (avoids duplicate / divergent rows vs supervisors).

- ``generator``: legacy — archive only from ``StrikeTableGenerator`` live inserts.

- ``both``: generator **and** publisher (debug / transition; duplicates possible).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

import psycopg2

from backend.core.time_eastern import eastern_wall_naive, now_est

logger = logging.getLogger(__name__)

MASTER_TABLE = "historical_data.strike_table_master"
_ENSURED_PARTITIONS: set[str] = set()


def _strike_archive_runtime_ddl_enabled() -> bool:
    """
    Runtime DDL guard for archive writers.

    Default OFF so hot-path writers do not issue CREATE/ALTER and contend on heavy locks.
    Set REC_STRIKE_ARCHIVE_RUNTIME_DDL=1 only for controlled local/bootstrap workflows.
    """
    v = (os.getenv("REC_STRIKE_ARCHIVE_RUNTIME_DDL") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def strike_archive_enabled() -> bool:
    v = (os.getenv("REC_STRIKE_TABLE_ARCHIVE") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def strike_table_archive_source() -> str:
    """Return ``publisher``, ``generator``, or ``both``."""
    v = (os.getenv("REC_STRIKE_TABLE_ARCHIVE_SOURCE") or "publisher").strip().lower()
    if v in ("publisher", "snapshot", "redis"):
        return "publisher"
    if v in ("generator", "live", "strike_generator"):
        return "generator"
    if v == "both":
        return "both"
    return "publisher"


def strike_archive_from_generator() -> bool:
    return strike_table_archive_source() in ("generator", "both")


def strike_archive_from_publisher() -> bool:
    return strike_table_archive_source() in ("publisher", "both")


def _month_bounds_eastern_naive(ts: datetime) -> tuple[datetime, datetime]:
    """First instant of calendar month in US Eastern wall (naive) through first of next month."""
    t = eastern_wall_naive(ts)
    start = datetime(t.year, t.month, 1)
    if t.month == 12:
        end = datetime(t.year + 1, 1, 1)
    else:
        end = datetime(t.year, t.month + 1, 1)
    return start, end


def _partition_relname_for_ts(ts: datetime) -> str:
    t = eastern_wall_naive(ts)
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
            "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (timezone('America/New_York', now())),
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
    cursor.execute(
        """
        ALTER TABLE historical_data.strike_table_master
            ADD COLUMN IF NOT EXISTS snapshot_wall_second BIGINT,
            ADD COLUMN IF NOT EXISTS snapshot_generation_seq BIGINT
        """
    )


def ensure_month_partition(cursor: Any, ts: datetime) -> None:
    start, end = _month_bounds_eastern_naive(ts)
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
    """Ensure current month plus N future monthly partitions (US Eastern calendar months)."""
    ensured: list[str] = []
    wall = eastern_wall_naive(now_est())
    year, month = wall.year, wall.month
    for _ in range(max(0, int(months_ahead)) + 1):
        ts_anchor = datetime(year, month, 1)
        rel = _partition_relname_for_ts(ts_anchor)
        ensure_month_partition(cursor, ts_anchor)
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
    if not strike_archive_from_generator():
        return
    mt = str(market_ticker or "").strip()
    if not mt:
        return
    if len(row) != 45:
        raise ValueError(f"strike archive row must have 45 values, got {len(row)}")

    row_ts = row[43]
    if not isinstance(row_ts, datetime):
        raise ValueError(f"row[43] must be datetime, got {type(row_ts)}")
    row_ca = row[44]
    if not isinstance(row_ca, datetime):
        raise ValueError(f"row[44] must be datetime, got {type(row_ca)}")

    ts_wall = eastern_wall_naive(row_ts)
    ca_wall = eastern_wall_naive(row_ca)

    if _strike_archive_runtime_ddl_enabled():
        ensure_master_table(cursor)
        ensure_month_partition(cursor, ts_wall)

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
            "timestamp", created_at, snapshot_wall_second, snapshot_generation_seq, market_result
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL
        )
        """,
        (
            row[0],
            row[1],
            row[2],
            mt,
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
            ts_wall,
            ca_wall,
        ),
    )


def _opt_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def append_strike_archive_for_published_ladder(
    *,
    exchange: str,
    market: str,
    wall_second: int,
    generation_seq: int,
    ladder: Dict[str, Any],
) -> None:
    """
    Archive every strike row in ``ladder`` (same dict as Redis ``data`` / DB ladder fetch)
    after a successful snapshot publish. Uses one Eastern-wall ``timestamp`` for the batch
    (derived from ``wall_second``) so backtests can align with AES/ATS wall-second snapshots.

    Columns not present in the ladder JSON (bids, momentum block, 15m min/max) are NULL.
    """
    if not strike_archive_enabled():
        return
    if not strike_archive_from_publisher():
        return
    if not isinstance(ladder, dict):
        return
    mkt = (market or "hourly").strip().lower()
    if mkt not in ("hourly", "15m"):
        mkt = "hourly"
    ex = str(exchange or "").strip().lower()
    sym_u = str(ladder.get("symbol") or "").strip().upper()
    if not sym_u:
        return

    ts_src = datetime.fromtimestamp(int(wall_second), tz=timezone.utc)
    ts_wall = eastern_wall_naive(ts_src)

    ttc = ladder.get("ttc")
    ttc_i = _opt_int(ttc)
    ttc_hourly = ttc_i if mkt == "hourly" else None
    ttc_15m = ttc_i if mkt == "15m" else None

    cp = _opt_float(ladder.get("current_price"))
    ev = ladder.get("event_ticker")
    title = ladder.get("market_title")
    tier = _opt_int(ladder.get("strike_tier"))
    mstat = ladder.get("market_status")

    batch: list[tuple[Any, ...]] = []
    for sd in ladder.get("strikes") or []:
        if not isinstance(sd, dict):
            continue
        mt = str(sd.get("ticker") or "").strip()
        if not mt:
            continue
        batch.append(
            (
                sym_u,
                ex,
                mkt,
                mt,
                cp,
                ttc_hourly,
                ttc_15m,
                ev,
                title,
                tier,
                mstat,
                _opt_float(sd.get("strike")),
                _opt_float(sd.get("buffer")),
                _opt_float(sd.get("buffer_pct")),
                _opt_float(sd.get("probability_hourly")),
                _opt_float(sd.get("probability_15m")),
                _opt_float(sd.get("yes_prob_hourly")),
                _opt_float(sd.get("no_prob_hourly")),
                _opt_float(sd.get("yes_prob_15m")),
                _opt_float(sd.get("no_prob_15m")),
                sd.get("yes_ask_dollars"),
                sd.get("no_ask_dollars"),
                None,
                None,
                _opt_float(sd.get("yes_price_spread")),
                _opt_float(sd.get("no_price_spread")),
                _opt_float(sd.get("yes_diff")),
                _opt_float(sd.get("no_diff")),
                sd.get("volume_fp"),
                sd.get("open_interest_fp"),
                sd.get("ticker"),
                sd.get("active_side"),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                _opt_float(sd.get("yes_ask_range_15m")),
                _opt_float(sd.get("no_ask_range_15m")),
                ts_wall,
                ts_wall,
                int(wall_second),
                int(generation_seq),
                None,
            )
        )

    if not batch:
        return

    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if not conn:
        logger.warning("strike archive publisher batch: no system DB connection")
        return
    try:
        with conn.cursor() as cur:
            if _strike_archive_runtime_ddl_enabled():
                ensure_master_table(cur)
                ensure_month_partition(cur, ts_wall)
            cur.executemany(
                """
                INSERT INTO historical_data.strike_table_master (
                    symbol, exchange, market, market_ticker, current_price, ttc_hourly, ttc_15m, event_ticker, market_title,
                    strike_tier, market_status, strike, buffer, buffer_pct, probability_hourly, probability_15m,
                    yes_prob_hourly, no_prob_hourly, yes_prob_15m, no_prob_15m,
                    yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
                    yes_price_spread, no_price_spread, yes_diff, no_diff, volume_fp, open_interest_fp, ticker, active_side,
                    momentum_weighted_score, momentum_percentile, volatility, volatility_percentile, movement, movement_percentile,
                    yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m, yes_ask_range_15m, no_ask_range_15m,
                    "timestamp", created_at, snapshot_wall_second, snapshot_generation_seq, market_result
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                batch,
            )
        conn.commit()
    except psycopg2.errors.UndefinedTable:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(
            "strike archive publisher insert failed: %s is missing and runtime DDL is disabled "
            "(set REC_STRIKE_ARCHIVE_RUNTIME_DDL=1 temporarily or apply archive schema/migrations)",
            MASTER_TABLE,
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception(
            "strike archive publisher batch failed sym=%s market=%s wall=%s",
            sym_u,
            mkt,
            wall_second,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


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
            cur.execute(
                """
                UPDATE historical_data.strike_table_master
                   SET market_result = %s
                 WHERE market_ticker = %s
                """,
                (res, mt),
            )
        conn.commit()
    except psycopg2.errors.UndefinedTable:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(
            "strike archive market_result backfill skipped: %s is missing and runtime DDL is disabled",
            MASTER_TABLE,
        )
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
