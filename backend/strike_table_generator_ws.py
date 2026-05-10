#!/usr/bin/env python3
"""
WS strike table generator (Redis-triggered).

Refreshes unified strike tables from Kalshi WS-backed market rows: 15m or hourly.
Writes canonical health to live_data.strike_pipeline_health (exchange, market, symbol).
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

from backend.core.config.database import get_system_postgresql_connection
from backend.strike_table_generator import (
    DEFAULT_KALSHI_15M_SYMBOL_ORDER,
    KALSHI_15M_SYMBOLS,
    StrikeTableGenerator,
    fetch_kalshi_15m_symbols_ordered_from_db,
)
from backend.core.exchange_ids import normalize_exchange
from backend.core.strike_pipeline_health import (
    MARKET_15M,
    MARKET_HOURLY,
    pipeline_health_writer_dead_sec,
    strike_pipeline_health_strict_mode_enabled,
    upsert_strike_pipeline_health,
)


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
DEFAULT_STREAM_MARKET_HOURLY = "market_kalshi_hourly"
DEFAULT_STREAM_SYMBOL = "live_symbol_status"
DEFAULT_REDIS_CHANNEL = "rec_io:db_changes"
# Hourly: WS ladder rows update often; tight freshness is reasonable.
DEFAULT_PIPELINE_MAX_AGE_SEC = 30
# 15m: same Kalshi feed can go many minutes without touching MAX(updated_at) on the
# unified market table between rollovers / quiet tape; 30s false-negatives the whole pipeline.
DEFAULT_PIPELINE_MAX_AGE_15M_SEC = 900
DEFAULT_DEGRADE_CONFIRM_SEC = 30
KALSHI_HOURLY_SYMBOLS = frozenset({"BTC", "ETH", "SOL"})


def _redis_client():
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return redis.from_url(redis_url, decode_responses=True)
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD")
    return redis.Redis(host=host, port=port, password=password, decode_responses=True)


def _symbol_price_log_table(symbol: str) -> str | None:
    mapping = {
        "BTC": "live_price_log_1s_btc",
        "ETH": "live_price_log_1s_eth",
        "SOL": "live_price_log_1s_sol",
        "XRP": "live_price_log_1s_xrp",
    }
    return mapping.get(str(symbol or "").upper())


class StrikeTableGeneratorWS(StrikeTableGenerator):
    """WS-backed strike table generator (15m or hourly); Redis-triggered refresh + pipeline health rows."""

    def __init__(
        self,
        symbol: str,
        *,
        interval: str = "15m",
        data_exchange: str = "kalshi",
        strike_table_name: str | None = None,
        market_table_name: str | None = None,
        pipeline_max_age_sec: int = DEFAULT_PIPELINE_MAX_AGE_SEC,
        degrade_confirm_sec: int = DEFAULT_DEGRADE_CONFIRM_SEC,
    ):
        iv = interval.strip().lower()
        if iv not in ("15m", "hourly"):
            raise ValueError("WS generator supports interval=15m or hourly")
        if iv == "hourly" and symbol.upper() not in KALSHI_HOURLY_SYMBOLS:
            raise ValueError(f"hourly WS generator only supports {sorted(KALSHI_HOURLY_SYMBOLS)}, got {symbol}")
        super().__init__(
            symbol=symbol,
            interval=iv,
            unified_15m=(iv == "15m"),
            data_exchange=data_exchange,
        )
        self.pipeline_health_market = MARKET_15M if iv == "15m" else MARKET_HOURLY
        self.strike_table_name = strike_table_name or (
            "strike_table_15m" if iv == "15m" else "strike_table_hourly"
        )
        self.market_table_name = market_table_name or (
            "market_kalshi_15m" if iv == "15m" else "market_kalshi_hourly"
        )
        self.pipeline_max_age_sec = max(5, int(pipeline_max_age_sec))
        self.degrade_confirm_sec = max(5, int(degrade_confirm_sec))

    def _strike_table_name(self) -> str:
        return self.strike_table_name

    def _ensure_strike_pipeline_health_schema(self, cursor, conn) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS live_data.strike_pipeline_health (
                exchange VARCHAR(20) NOT NULL,
                market VARCHAR(20) NOT NULL,
                symbol VARCHAR(10) NOT NULL,
                pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
                pipeline_health_reason TEXT,
                pipeline_health_checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 900,
                ws_transport_ok_at TIMESTAMP WITH TIME ZONE,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                PRIMARY KEY (exchange, market, symbol)
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS strike_pipeline_health_checked_idx
                ON live_data.strike_pipeline_health (pipeline_health_checked_at DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS strike_pipeline_health_transport_idx
                ON live_data.strike_pipeline_health (ws_transport_ok_at DESC NULLS LAST)
            """
        )

    def setup_live_data_schema(self) -> None:
        """Ensure health table exists, then parent strike/market DDL (migrations are source of truth)."""
        conn = None
        try:
            conn = get_system_postgresql_connection()
            cursor = conn.cursor()
            cursor.execute("CREATE SCHEMA IF NOT EXISTS live_data")
            self._ensure_strike_pipeline_health_schema(cursor, conn)
            conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
        super().setup_live_data_schema()

    def _setup_unified_15m_schema(self, cursor, conn) -> None:
        self._ensure_strike_pipeline_health_schema(cursor, conn)
        super()._setup_unified_15m_schema(cursor, conn)

    def set_pipeline_health(self, *, healthy: bool, reason: str) -> None:
        conn = get_system_postgresql_connection()
        if not conn:
            return
        try:
            upsert_strike_pipeline_health(
                conn,
                exchange=self.data_exchange,
                market=self.pipeline_health_market,
                symbol=self.symbol.upper(),
                healthy=healthy,
                reason=reason,
                max_age_sec=pipeline_health_writer_dead_sec(),
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception(
                "[%s] failed setting pipeline health healthy=%s reason=%s",
                self.symbol.upper(),
                healthy,
                reason,
            )
        finally:
            conn.close()

    def market_stream_age_sec(self) -> float:
        """Age in seconds of latest WS market row for this symbol."""
        conn = get_system_postgresql_connection()
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
        conn = get_system_postgresql_connection()
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
        """
        Integrity: refresh succeeded and produced rows.

        Freshness: when ``STRIKE_PIPELINE_HEALTH_STRICT_MODE`` is on (fail-closed trading),
        require recent WS market rows and a recent ``live_symbol_status`` tick so we never
        mark the pipeline healthy on stale Kalshi ladder data. Optionally the same checks apply
        when ``STRIKE_PIPELINE_FRESHNESS_STRICT`` is set without strict mode (dashboard-only).
        """
        if not ok:
            return False, "strike_refresh_failed"
        if row_count <= 0:
            return False, "strike_row_count_zero"
        freshness_strict = strike_pipeline_health_strict_mode_enabled() or os.getenv(
            "STRIKE_PIPELINE_FRESHNESS_STRICT", ""
        ).strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if freshness_strict:
            market_age_sec = self.market_stream_age_sec()
            if market_age_sec > float(self.pipeline_max_age_sec):
                return False, f"market_stream_stale:{market_age_sec:.1f}s>{self.pipeline_max_age_sec}s"
            price_age_sec = self.price_stream_age_sec()
            if price_age_sec > float(self.pipeline_max_age_sec):
                return False, f"price_stream_stale:{price_age_sec:.1f}s>{self.pipeline_max_age_sec}s"
        return True, "ok"

    def get_current_market_data(self):
        """Read current spot/momentum from live_symbol_status and ladder from WS market table."""
        conn = get_system_postgresql_connection()
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
        """Read latest event + ladder from the configured WS market table (15m or hourly)."""
        conn = get_system_postgresql_connection()
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
            markets.append(
                {
                    "ticker": market_ticker,
                    "floor_strike": floor_strike,
                    "yes_ask_dollars": ya,
                    "no_ask_dollars": na,
                    "yes_bid_dollars": yb,
                    "no_bid_dollars": nb,
                    "last_price_dollars": lp,
                    "volume_fp": volume_fp,
                    "open_interest_fp": oi,
                    "status": "active",
                }
            )

        # strike_tier is internal and must be computed from ladder spacing.
        # 15m remains 0 by design (single-contract cadence).
        if self.interval == "hourly":
            strike_tier = int(self.detect_strike_tier_spacing(markets))
            if strike_tier <= 0:
                raise ValueError(f"invalid computed strike_tier={strike_tier} for {self.symbol.upper()}")
        else:
            strike_tier = 0

        return {
            "event_ticker": event_ticker,
            "market_status": "active",
            "event_title": self.generate_market_title(event_ticker),
            "strike_date": datetime.now(ZoneInfo("America/New_York")).isoformat(),
            "strike_tier": strike_tier,
            "markets": markets,
        }


def _coalesced_wait(
    pubsub,
    debounce_ms: int,
    stop_after_sec: float = 30.0,
    *,
    stream_db_names: tuple[str, ...] = (DEFAULT_STREAM_MARKET, DEFAULT_STREAM_SYMBOL),
) -> bool:
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
        if db_name in stream_db_names:
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
    market_kind: str = "15m",
    redis_channel: str = DEFAULT_REDIS_CHANNEL,
    debounce_ms: int = 1200,
    min_refresh_sec: float = 1.2,
    pipeline_max_age_sec: int = DEFAULT_PIPELINE_MAX_AGE_SEC,
    degrade_confirm_sec: int = DEFAULT_DEGRADE_CONFIRM_SEC,
) -> None:
    mk = (market_kind or "15m").strip().lower()
    if mk == "hourly":
        stream_db_names = (DEFAULT_STREAM_MARKET_HOURLY, DEFAULT_STREAM_SYMBOL)
        default_strike = os.getenv("STRIKE_TABLE_HOURLY_TARGET", "strike_table_hourly")
        default_market = "market_kalshi_hourly"
    elif mk == "15m":
        stream_db_names = (DEFAULT_STREAM_MARKET, DEFAULT_STREAM_SYMBOL)
        default_strike = os.getenv("STRIKE_TABLE_15M_TARGET", "strike_table_15m")
        default_market = "market_kalshi_15m"
    else:
        raise ValueError("market_kind must be 15m or hourly")

    syms = tuple(s.upper() for s in symbols)
    if not syms:
        syms = DEFAULT_KALSHI_15M_SYMBOL_ORDER if mk == "15m" else tuple(sorted(KALSHI_HOURLY_SYMBOLS))
    if mk == "hourly":
        syms = tuple(s for s in syms if s in KALSHI_HOURLY_SYMBOLS)

    generators = {
        s: StrikeTableGeneratorWS(
            s.lower(),
            interval="15m" if mk == "15m" else "hourly",
            data_exchange=data_exchange,
            strike_table_name=default_strike,
            market_table_name=default_market,
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
        if not healthy:
            logger.warning("[%s] startup prime degraded ok=%s event=%s rows=%s reason=%s", s, ok, ev, n, reason)
        elif not healthy_raw:
            logger.warning(
                "[%s] startup prime unhealthy masked %ss ok=%s event=%s rows=%s reason=%s",
                s,
                degrade_confirm_sec,
                ok,
                ev,
                n,
                reason,
            )
        else:
            logger.info("[%s] startup prime ok=%s event=%s rows=%s", s, ok, ev, n)

    logger.info(
        "Redis-triggered WS strike generator start market=%s exchange=%s symbols=%s channel=%s debounce_ms=%s",
        mk,
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
            fired = _coalesced_wait(
                pubsub,
                debounce_ms=debounce_ms,
                stop_after_sec=30.0,
                stream_db_names=stream_db_names,
            )
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
                elif not healthy_raw:
                    logger.warning(
                        "[%s] strike refresh unhealthy but masked %ss (degrade_confirm) reason=%s event=%s rows=%s",
                        s,
                        degrade_confirm_sec,
                        reason,
                        ev,
                        n,
                    )
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
        "--market",
        choices=("15m", "hourly"),
        default="15m",
        help="Which Kalshi interval / Redis db_change stream to follow.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Optional symbol list. Default: symbols_list order filtered to Kalshi 15m or hourly set.",
    )
    parser.add_argument("--redis-channel", default=DEFAULT_REDIS_CHANNEL)
    parser.add_argument("--debounce-ms", type=int, default=1200)
    parser.add_argument("--min-refresh-sec", type=float, default=1.2)
    parser.add_argument(
        "--pipeline-max-age-sec",
        type=int,
        default=None,
        help="Max age (seconds) for WS market + spot freshness checks. "
        "Default: hourly 30 (or STRIKE_PIPELINE_MARKET_MAX_AGE_HOURLY_SEC), "
        "15m 900 (or STRIKE_PIPELINE_MARKET_MAX_AGE_15M_SEC).",
    )
    parser.add_argument("--degrade-confirm-sec", type=int, default=DEFAULT_DEGRADE_CONFIRM_SEC)
    args = parser.parse_args()

    venue = normalize_exchange(args.exchange)
    if venue != "kalshi":
        raise SystemExit(f"Only kalshi supported for WS strike generator, got {venue}")

    if args.symbols:
        syms = tuple(s.strip().upper() for s in args.symbols if s.strip())
    elif args.market == "hourly":
        syms = tuple(sorted(KALSHI_HOURLY_SYMBOLS))
    else:
        syms = fetch_kalshi_15m_symbols_ordered_from_db()
    if args.market == "hourly":
        syms = tuple(s for s in syms if s in KALSHI_HOURLY_SYMBOLS)
        if not syms:
            raise SystemExit("No valid hourly symbols configured (BTC, ETH, SOL)")
    else:
        syms = tuple(s for s in syms if s in KALSHI_15M_SYMBOLS)
        if not syms:
            raise SystemExit("No valid 15m symbols configured")

    if args.pipeline_max_age_sec is not None:
        pipeline_max_age = max(5, int(args.pipeline_max_age_sec))
    elif args.market == "15m":
        pipeline_max_age = max(
            30,
            int(os.getenv("STRIKE_PIPELINE_MARKET_MAX_AGE_15M_SEC", str(DEFAULT_PIPELINE_MAX_AGE_15M_SEC))),
        )
    else:
        pipeline_max_age = max(
            5,
            int(os.getenv("STRIKE_PIPELINE_MARKET_MAX_AGE_HOURLY_SEC", str(DEFAULT_PIPELINE_MAX_AGE_SEC))),
        )

    run_redis_triggered(
        data_exchange=venue,
        symbols=syms,
        market_kind=args.market,
        redis_channel=args.redis_channel,
        debounce_ms=max(20, int(args.debounce_ms)),
        min_refresh_sec=max(0.1, float(args.min_refresh_sec)),
        pipeline_max_age_sec=pipeline_max_age,
        degrade_confirm_sec=max(5, int(args.degrade_confirm_sec)),
    )


if __name__ == "__main__":
    main()
