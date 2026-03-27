#!/usr/bin/env python3
"""
WS strike table generator.

Phase 1 target: 15m WS market rows -> live_data.strike_table_ws_15m.
Architecture remains interval-aware so hourly can be wired later without redesign.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import redis

from backend.core.config.database import get_postgresql_connection
from backend.strike_table_generator import (
    DEFAULT_KALSHI_15M_SYMBOL_ORDER,
    KALSHI_15M_SYMBOLS,
    StrikeTableGenerator,
    fetch_kalshi_15m_symbols_ordered_from_db,
)
from backend.core.exchange_ids import normalize_exchange


def _est_formatter():
    class ESTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            if datefmt:
                return dt.strftime(datefmt)
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)

    return ESTFormatter(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def _configure_logging():
    log = logging.getLogger("strike_table_generator_ws")
    if log.handlers:
        return log
    h = logging.StreamHandler()
    h.setFormatter(_est_formatter())
    log.addHandler(h)
    log.setLevel(logging.INFO)
    return log


logger = _configure_logging()

DEFAULT_STREAM_MARKET = "market_kalshi_15m"
DEFAULT_STREAM_SYMBOL = "live_symbol_status"
DEFAULT_REDIS_CHANNEL = "rec_io:db_changes"
DEFAULT_PIPELINE_MAX_AGE_SEC = 30
DEFAULT_DEGRADE_CONFIRM_SEC = 30
HEALTH_TABLE_15M = "strike_pipeline_health_15m"


def _redis_client():
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return redis.from_url(redis_url, decode_responses=True)
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD")
    return redis.Redis(host=host, port=port, password=password, decode_responses=True)


def _dollars_to_cents(dollars_val):
    if dollars_val is None:
        return None
    s = str(dollars_val).strip()
    if not s:
        return None
    try:
        return float(s) * 100.0
    except Exception:
        return None


def _symbol_price_log_table(symbol: str) -> str | None:
    mapping = {
        "BTC": "live_price_log_1s_btc",
        "ETH": "live_price_log_1s_eth",
        "SOL": "live_price_log_1s_sol",
        "XRP": "live_price_log_1s_xrp",
    }
    return mapping.get(str(symbol or "").upper())


class StrikeTableGeneratorWS(StrikeTableGenerator):
    """WS-backed strike table generator for 15m; keeps interval-aware extension points."""

    def __init__(
        self,
        symbol: str,
        *,
        interval: str = "15m",
        data_exchange: str = "kalshi",
        strike_table_name: str = "strike_table_15m",
        market_table_name: str = "market_kalshi_15m",
        pipeline_max_age_sec: int = DEFAULT_PIPELINE_MAX_AGE_SEC,
        degrade_confirm_sec: int = DEFAULT_DEGRADE_CONFIRM_SEC,
    ):
        if interval.lower() != "15m":
            raise ValueError("phase 1 supports only interval=15m for WS generator")
        super().__init__(
            symbol=symbol,
            interval=interval,
            unified_15m=True,
            data_exchange=data_exchange,
        )
        self.strike_table_name = strike_table_name
        self.market_table_name = market_table_name
        self.pipeline_max_age_sec = max(5, int(pipeline_max_age_sec))
        self.degrade_confirm_sec = max(5, int(degrade_confirm_sec))

    def _strike_table_name(self) -> str:
        return self.strike_table_name

    def _setup_unified_15m_schema(self, cursor, conn) -> None:
        table_name = self._strike_table_name()
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS live_data.{HEALTH_TABLE_15M} (
                exchange VARCHAR(20) NOT NULL,
                symbol VARCHAR(10) NOT NULL,
                pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
                pipeline_health_reason TEXT,
                pipeline_health_checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 30,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                PRIMARY KEY (exchange, symbol)
            )
            """
        )
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {HEALTH_TABLE_15M}_checked_idx
                ON live_data.{HEALTH_TABLE_15M} (pipeline_health_checked_at DESC)
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS live_data.{table_name} (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                symbol VARCHAR(10) NOT NULL,
                exchange VARCHAR(20) NOT NULL,
                market TEXT DEFAULT '15m',
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
                yes_ask DECIMAL(5,2),
                no_ask DECIMAL(5,2),
                yes_ask_dollars TEXT,
                no_ask_dollars TEXT,
                yes_bid_dollars TEXT,
                no_bid_dollars TEXT,
                yes_price_spread NUMERIC(6,4),
                no_price_spread NUMERIC(6,4),
                yes_diff DECIMAL(5,2),
                no_diff DECIMAL(5,2),
                volume INTEGER,
                ticker VARCHAR(50),
                active_side VARCHAR(10),
                momentum_weighted_score DECIMAL(5,3),
                momentum_percentile DECIMAL(5,1),
                volatility NUMERIC(10,6),
                volatility_percentile NUMERIC(5,1),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
                pipeline_health_reason TEXT,
                pipeline_health_checked_at TIMESTAMP WITH TIME ZONE,
                pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 30,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {table_name}_exchange_symbol_idx
                ON live_data.{table_name} (exchange, symbol)
            """
        )
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_lookup
                ON live_data.{table_name} (timestamp, symbol, current_price)
            """
        )
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {table_name}_exchange_symbol_timestamp_idx
                ON live_data.{table_name} (exchange, symbol, timestamp DESC)
            """
        )
        conn.commit()

    def set_pipeline_health(self, *, healthy: bool, reason: str) -> None:
        conn = get_postgresql_connection()
        if not conn:
            return
        try:
            cur = conn.cursor()
            # Write to dedicated health table (source of truth for UI/trade gate).
            cur.execute(
                f"""
                INSERT INTO live_data.{HEALTH_TABLE_15M}
                    (exchange, symbol, pipeline_healthy, pipeline_health_reason,
                     pipeline_health_checked_at, pipeline_health_max_age_sec, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), %s, NOW())
                ON CONFLICT (exchange, symbol) DO UPDATE SET
                    pipeline_healthy = EXCLUDED.pipeline_healthy,
                    pipeline_health_reason = EXCLUDED.pipeline_health_reason,
                    pipeline_health_checked_at = EXCLUDED.pipeline_health_checked_at,
                    pipeline_health_max_age_sec = EXCLUDED.pipeline_health_max_age_sec,
                    updated_at = NOW()
                """,
                (
                    self.data_exchange,
                    self.symbol.upper(),
                    bool(healthy),
                    reason,
                    self.pipeline_max_age_sec,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception(
                "[%s] failed setting pipeline health healthy=%s reason=%s",
                self.symbol.upper(),
                healthy,
                reason,
            )
            conn.close()
            return

        try:
            cur = conn.cursor()
            # Backfill legacy health columns on latest strike row when present.
            # This is best-effort and must never block canonical health updates.
            cur.execute(
                f"""
                UPDATE live_data.{self.strike_table_name}
                SET pipeline_healthy = %s,
                    pipeline_health_reason = %s,
                    pipeline_health_checked_at = NOW(),
                    pipeline_health_max_age_sec = %s
                WHERE exchange = %s
                  AND symbol = %s
                  AND timestamp = (
                    SELECT MAX(timestamp) FROM live_data.{self.strike_table_name}
                    WHERE exchange = %s AND symbol = %s
                  )
                """,
                (
                    bool(healthy),
                    reason,
                    self.pipeline_max_age_sec,
                    self.data_exchange,
                    self.symbol.upper(),
                    self.data_exchange,
                    self.symbol.upper(),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.debug("[%s] legacy health-column backfill skipped", self.symbol.upper(), exc_info=True)
        finally:
            conn.close()

    def market_stream_age_sec(self) -> float:
        """Age in seconds of latest WS market row for this symbol."""
        conn = get_postgresql_connection()
        if not conn:
            return float("inf")
        try:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT EXTRACT(EPOCH FROM (NOW() - MAX(updated_at)))
                FROM live_data.{self.market_table_name}
                WHERE exchange = %s AND symbol = %s
                """,
                (self.data_exchange, self.symbol.upper()),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return float("inf")
            return float(row[0])
        except Exception:
            logger.exception("[%s] failed reading market stream age", self.symbol.upper())
            return float("inf")
        finally:
            conn.close()

    def price_stream_age_sec(self) -> float:
        """Age in seconds of latest live symbol status tick for this symbol."""
        conn = get_postgresql_connection()
        if not conn:
            return float("inf")
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT EXTRACT(
                    EPOCH FROM (
                        NOW() - (
                            NULLIF("timestamp", '')::timestamp
                            AT TIME ZONE 'America/New_York'
                        )
                    )
                )
                FROM live_data.live_symbol_status
                WHERE symbol = %s
                """,
                (self.symbol.upper(),),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return float("inf")
            return float(row[0])
        except Exception:
            logger.exception("[%s] failed reading price stream age", self.symbol.upper())
            return float("inf")
        finally:
            conn.close()

    def evaluate_pipeline_health(self, ok: bool, row_count: int) -> tuple[bool, str]:
        """Determine health from WS market + live price freshness (feed-level truth)."""
        market_age_sec = self.market_stream_age_sec()
        if market_age_sec > float(self.pipeline_max_age_sec):
            return False, f"market_stream_stale:{market_age_sec:.1f}s>{self.pipeline_max_age_sec}s"
        price_age_sec = self.price_stream_age_sec()
        if price_age_sec > float(self.pipeline_max_age_sec):
            return False, f"price_stream_stale:{price_age_sec:.1f}s>{self.pipeline_max_age_sec}s"
        return True, "ok"

    def get_current_market_data(self):
        """Read current spot/momentum from live_symbol_status and ladder from WS market table."""
        conn = get_postgresql_connection()
        if not conn:
            raise ValueError("database unavailable")
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    COALESCE(one_minute_avg, price),
                    momentum,
                    momentum_percentile,
                    volatility,
                    volatility_percentile,
                    movement,
                    movement_percentile
                FROM live_data.live_symbol_status
                WHERE symbol = %s
                LIMIT 1
                """,
                (self.symbol.upper(),),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"no live_symbol_status for {self.symbol.upper()}")
            current_price = float(row[0]) if row[0] is not None else None
            if current_price is None:
                raise ValueError(f"no current price in live_symbol_status for {self.symbol.upper()}")
            momentum_score = float(row[1]) if row[1] is not None else 0.0
            momentum_percentile = float(row[2]) if row[2] is not None else 0.0
            volatility = float(row[3]) if row[3] is not None else None
            volatility_percentile = float(row[4]) if row[4] is not None else None
            movement = float(row[5]) if row[5] is not None else None
            movement_percentile = float(row[6]) if row[6] is not None else None
        finally:
            conn.close()

        market_data = self.get_kalshi_market_snapshot()
        return {
            "current_price": current_price,
            "momentum_score": momentum_score,
            "momentum_percentile": momentum_percentile,
            "volatility": volatility,
            "volatility_percentile": volatility_percentile,
            "movement": movement,
            "movement_percentile": movement_percentile,
            "market_data": market_data,
        }

    def get_kalshi_market_snapshot(self):
        """Read latest event + ladder from live_data.market_kalshi_15m."""
        conn = get_postgresql_connection()
        if not conn:
            raise ValueError("database unavailable")
        try:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT event_ticker
                FROM live_data.{self.market_table_name}
                WHERE exchange = %s AND symbol = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (self.data_exchange, self.symbol.upper()),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(
                    f"No event_ticker in {self.market_table_name} exchange={self.data_exchange} symbol={self.symbol.upper()}"
                )
            event_ticker = row[0]
            cur.execute(
                f"""
                SELECT
                    market_ticker, strike,
                    yes_ask_dollars, no_ask_dollars,
                    yes_bid_dollars, no_bid_dollars,
                    last_price_dollars, volume_fp, open_interest_fp
                FROM live_data.{self.market_table_name}
                WHERE exchange = %s AND symbol = %s AND event_ticker = %s
                ORDER BY market_ticker
                """,
                (self.data_exchange, self.symbol.upper(), event_ticker),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            raise ValueError(f"No rows in {self.market_table_name} for event {event_ticker}")

        markets = []
        for r in rows:
            market_ticker, strike_txt, ya, na, yb, nb, lp, volume_fp, oi = r
            floor_strike = None
            if strike_txt:
                try:
                    floor_strike = float(str(strike_txt).replace("$", "").replace(",", ""))
                except ValueError:
                    floor_strike = None
            # Keep fields compatible with base class strike-table generation.
            markets.append(
                {
                    "ticker": market_ticker,
                    "floor_strike": floor_strike,
                    "yes_ask": _dollars_to_cents(ya),
                    "no_ask": _dollars_to_cents(na),
                    "yes_bid": _dollars_to_cents(yb),
                    "no_bid": _dollars_to_cents(nb),
                    "last_price": _dollars_to_cents(lp),
                    "yes_ask_dollars": ya,
                    "no_ask_dollars": na,
                    "yes_bid_dollars": yb,
                    "no_bid_dollars": nb,
                    "last_price_dollars": lp,
                    "volume": float(volume_fp) if volume_fp is not None else None,
                    "open_interest": float(oi) if oi is not None else None,
                    "status": "active",
                }
            )

        return {
            "event_ticker": event_ticker,
            "market_status": "active",
            "event_title": self.generate_market_title(event_ticker),
            "strike_date": datetime.now(ZoneInfo("America/New_York")).isoformat(),
            "strike_tier": 0,
            "markets": markets,
        }


def _coalesced_wait(pubsub, debounce_ms: int, stop_after_sec: float = 30.0) -> bool:
    """Wait for at least one message, then debounce briefly to coalesce bursts."""
    deadline = time.time() + stop_after_sec
    got_one = False
    while time.time() < deadline:
        msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if not msg or msg.get("type") != "message":
            continue
        raw = msg.get("data")
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if payload.get("type") != "db_change":
            continue
        db_name = payload.get("database")
        if db_name in (DEFAULT_STREAM_MARKET, DEFAULT_STREAM_SYMBOL):
            got_one = True
            break
    if not got_one:
        return False

    end = time.time() + (debounce_ms / 1000.0)
    while time.time() < end:
        _ = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
    return True


def run_redis_triggered(
    *,
    data_exchange: str,
    symbols: tuple[str, ...],
    redis_channel: str = DEFAULT_REDIS_CHANNEL,
    debounce_ms: int = 1200,
    min_refresh_sec: float = 1.2,
    pipeline_max_age_sec: int = DEFAULT_PIPELINE_MAX_AGE_SEC,
    degrade_confirm_sec: int = DEFAULT_DEGRADE_CONFIRM_SEC,
) -> None:
    syms = tuple(s.upper() for s in symbols)
    if not syms:
        syms = DEFAULT_KALSHI_15M_SYMBOL_ORDER
    generators = {
        s: StrikeTableGeneratorWS(
            s.lower(),
            interval="15m",
            data_exchange=data_exchange,
            strike_table_name=os.getenv("STRIKE_TABLE_15M_TARGET", "strike_table_15m"),
            market_table_name="market_kalshi_15m",
            pipeline_max_age_sec=pipeline_max_age_sec,
            degrade_confirm_sec=degrade_confirm_sec,
        )
        for s in syms
    }
    raw_unhealthy_since: dict[str, float | None] = {s: None for s in syms}
    # Ensure schema once.
    next(iter(generators.values())).setup_live_data_schema()

    # Prime immediately at startup.
    for s in syms:
        now = time.time()
        ok, ev, n = generators[s].generate_strike_table()
        healthy_raw, reason_raw = generators[s].evaluate_pipeline_health(ok, n)
        if healthy_raw:
            raw_unhealthy_since[s] = None
            healthy, reason = True, "ok"
        else:
            if raw_unhealthy_since[s] is None:
                raw_unhealthy_since[s] = now
            elapsed = now - float(raw_unhealthy_since[s] or now)
            if elapsed < float(degrade_confirm_sec):
                healthy = True
                reason = f"transient_unhealthy:{reason_raw}:{elapsed:.1f}s<{degrade_confirm_sec}s"
            else:
                healthy = False
                reason = reason_raw
        generators[s].set_pipeline_health(healthy=healthy, reason=reason)
        logger.info("[%s] startup prime ok=%s event=%s rows=%s", s, ok, ev, n)

    logger.info(
        "Redis-triggered WS strike generator start exchange=%s symbols=%s channel=%s debounce_ms=%s",
        data_exchange,
        ",".join(syms),
        redis_channel,
        debounce_ms,
    )

    r = _redis_client()
    pubsub = r.pubsub()
    pubsub.subscribe(redis_channel)
    logger.info("Subscribed Redis channel %s", redis_channel)
    last_refresh_at = 0.0

    while True:
        try:
            fired = _coalesced_wait(pubsub, debounce_ms=debounce_ms, stop_after_sec=30.0)
            if not fired:
                continue
            now = time.time()
            if now - last_refresh_at < min_refresh_sec:
                continue
            last_refresh_at = now
            for s in syms:
                ok, ev, n = generators[s].generate_strike_table()
                healthy_raw, reason_raw = generators[s].evaluate_pipeline_health(ok, n)
                if healthy_raw:
                    raw_unhealthy_since[s] = None
                    healthy, reason = True, "ok"
                else:
                    if raw_unhealthy_since[s] is None:
                        raw_unhealthy_since[s] = now
                    elapsed = now - float(raw_unhealthy_since[s] or now)
                    if elapsed < float(degrade_confirm_sec):
                        healthy = True
                        reason = f"transient_unhealthy:{reason_raw}:{elapsed:.1f}s<{degrade_confirm_sec}s"
                    else:
                        healthy = False
                        reason = reason_raw
                generators[s].set_pipeline_health(healthy=healthy, reason=reason)
                if not healthy:
                    logger.warning("[%s] strike refresh degraded reason=%s event=%s rows=%s", s, reason, ev, n)
                else:
                    logger.info("[%s] strike refresh ok event=%s rows=%s", s, ev, n)
        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception as e:
            logger.error("redis loop error: %s", e, exc_info=True)
            time.sleep(2.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="WS-backed strike table generator (Redis-triggered).")
    parser.add_argument("--exchange", default="kalshi")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Optional symbol list. Default: symbols_list order filtered to Kalshi 15m set.",
    )
    parser.add_argument("--redis-channel", default=DEFAULT_REDIS_CHANNEL)
    parser.add_argument("--debounce-ms", type=int, default=1200)
    parser.add_argument("--min-refresh-sec", type=float, default=1.2)
    parser.add_argument("--pipeline-max-age-sec", type=int, default=DEFAULT_PIPELINE_MAX_AGE_SEC)
    parser.add_argument("--degrade-confirm-sec", type=int, default=DEFAULT_DEGRADE_CONFIRM_SEC)
    args = parser.parse_args()

    venue = normalize_exchange(args.exchange)
    if venue != "kalshi":
        raise SystemExit(f"Only kalshi supported for WS strike generator, got {venue}")

    if args.symbols:
        syms = tuple(s.strip().upper() for s in args.symbols if s.strip())
    else:
        syms = fetch_kalshi_15m_symbols_ordered_from_db()
    syms = tuple(s for s in syms if s in KALSHI_15M_SYMBOLS)
    if not syms:
        raise SystemExit("No valid 15m symbols configured")

    run_redis_triggered(
        data_exchange=venue,
        symbols=syms,
        redis_channel=args.redis_channel,
        debounce_ms=max(20, int(args.debounce_ms)),
        min_refresh_sec=max(0.1, float(args.min_refresh_sec)),
        pipeline_max_age_sec=max(5, int(args.pipeline_max_age_sec)),
        degrade_confirm_sec=max(5, int(args.degrade_confirm_sec)),
    )


if __name__ == "__main__":
    main()
