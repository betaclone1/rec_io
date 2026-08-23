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
    note_pipeline_health_for_system_event,
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
# Strike regen wake: market PG NOTIFY + live_state pub/sub (not live_symbol_status ticks).
DEFAULT_REDIS_CHANNEL = "rec_io:db_changes"
# Hourly: WS ladder rows update often; tight freshness is reasonable.
DEFAULT_PIPELINE_MAX_AGE_SEC = 30
# 15m: same Kalshi feed can go many minutes without touching MAX(updated_at) on the
# unified market table between rollovers / quiet tape; 30s false-negatives the whole pipeline.
DEFAULT_PIPELINE_MAX_AGE_15M_SEC = 900
DEFAULT_DEGRADE_CONFIRM_SEC = 30
# Per-symbol floor between full strike regens (pub/sub can fire many times per second).
# Env override: STRIKE_REGEN_MIN_INTERVAL_SEC (default 0.5; was 0.25).
STRIKE_REGEN_MIN_INTERVAL_SEC = float(os.getenv("STRIKE_REGEN_MIN_INTERVAL_SEC", "0.5"))
# Longer backoff when cache/OB is dead — skip useless full regen loops (no substitute data).
STRIKE_REGEN_DEAD_SYMBOL_BACKOFF_SEC = float(
    os.getenv("STRIKE_REGEN_DEAD_SYMBOL_BACKOFF_SEC", "5")
)
STRIKE_REGEN_DEAD_OB_STALE_SEC = float(os.getenv("STRIKE_REGEN_DEAD_OB_STALE_SEC", "30"))
KALSHI_HOURLY_SYMBOLS = frozenset({"BTC", "ETH", "SOL", "DOGE"})
_last_regen_mono: dict[str, float] = {}
_last_dead_regen_skip_mono: dict[str, float] = {}


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
        "DOGE": "live_price_log_1s_doge",
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
        # System Event Log for prolonged confirmed outages (independent of DB upsert).
        note_pipeline_health_for_system_event(
            exchange=self.data_exchange,
            market=self.pipeline_health_market,
            symbol=self.symbol.upper(),
            healthy=healthy,
            reason=reason,
        )
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
        """Age in seconds of latest WS market snapshot in live_state."""
        from backend.core.live_state_config import live_state_cache_enabled
        from backend.core import live_state_cache

        if not live_state_cache_enabled():
            return float("inf")
        env = live_state_cache.get_market(
            self.data_exchange, self.pipeline_health_market, self.symbol
        )
        return live_state_cache.cache_age_sec(env)

    def price_stream_age_sec(self) -> float:
        """Age in seconds of latest symbol tick in live_state."""
        from backend.core.live_state_config import live_state_cache_enabled
        from backend.core import live_state_cache

        if not live_state_cache_enabled():
            return float("inf")
        env = live_state_cache.get_symbol(self.symbol)
        return live_state_cache.cache_age_sec(env)

    def evaluate_pipeline_health(self, ok: bool, row_count: int) -> tuple[bool, str]:
        """
        Integrity: refresh succeeded and produced rows.

        Freshness: when ``STRIKE_PIPELINE_HEALTH_STRICT_MODE`` is on (fail-closed trading),
        require recent WS market rows and a recent live_state symbol tick so we never
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
        """Read spot/momentum and Kalshi ladder from live_state Redis (no PostgreSQL substitute)."""
        from backend.core.live_state_config import live_state_cache_enabled
        from backend.core import live_state_cache

        if not live_state_cache_enabled():
            raise RuntimeError(
                "live_state Redis cache is disabled; strike_table_generator_ws requires the hot path"
            )
        sym_data = live_state_cache.get_symbol_data(self.symbol)
        mkt_data = live_state_cache.get_market_data(
            self.data_exchange, self.pipeline_health_market, self.symbol
        )
        if not sym_data:
            raise ValueError(
                f"live_state symbol cache miss for {self.symbol.upper()}"
            )
        if not mkt_data or not mkt_data.get("markets"):
            raise ValueError(
                f"live_state market cache miss for {self.data_exchange}/"
                f"{self.pipeline_health_market}/{self.symbol.upper()}"
            )
        market_data = self._market_data_from_cache_snapshot(mkt_data)
        price = sym_data.get("price") or sym_data.get("one_minute_avg")
        if price is None:
            raise ValueError(f"live_state symbol cache has no price for {self.symbol.upper()}")
        return {
            "current_price": float(price),
            "momentum_score": float(sym_data.get("momentum") or 0.0),
            "momentum_percentile": float(sym_data.get("momentum_percentile") or 0.0),
            "volatility": sym_data.get("volatility"),
            "volatility_percentile": sym_data.get("volatility_percentile"),
            "movement": sym_data.get("movement"),
            "movement_percentile": sym_data.get("movement_percentile"),
            "market_data": market_data,
        }

    def _market_data_result(
        self,
        current_price,
        momentum_score,
        momentum_percentile,
        volatility,
        volatility_percentile,
        movement,
        movement_percentile,
        market_data,
    ):
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

    def _market_data_from_cache_snapshot(self, mkt_data: dict):
        """Build market_data dict from live_state market cache payload."""
        event_ticker = mkt_data.get("event_ticker")
        markets = []
        for m in mkt_data.get("markets") or []:
            floor_strike = m.get("floor_strike")
            if floor_strike is None and m.get("strike") is not None:
                try:
                    floor_strike = float(
                        str(m.get("strike")).replace("$", "").replace(",", "").strip()
                    )
                except (TypeError, ValueError):
                    floor_strike = None
            markets.append(
                {
                    "ticker": m.get("ticker"),
                    "strike": m.get("strike"),
                    "floor_strike": floor_strike,
                    "yes_ask_dollars": m.get("yes_ask_dollars"),
                    "no_ask_dollars": m.get("no_ask_dollars"),
                    "yes_bid_dollars": m.get("yes_bid_dollars"),
                    "no_bid_dollars": m.get("no_bid_dollars"),
                    "last_price_dollars": m.get("last_price_dollars"),
                    "volume_fp": m.get("volume_fp"),
                    "open_interest_fp": m.get("open_interest_fp"),
                    "status": "active",
                }
            )
        strike_tier = 0
        if self.interval == "hourly" and markets:
            strike_tier = int(self.detect_strike_tier_spacing(markets))
        return {
            "event_ticker": event_ticker,
            "market_status": "active",
            "event_title": self.generate_market_title(event_ticker or ""),
            "strike_date": datetime.now(ZoneInfo("America/New_York")).isoformat(),
            "strike_tier": strike_tier,
            "markets": markets,
        }

    def get_kalshi_market_snapshot(self):
        """Read latest event + ladder from live_state market cache only."""
        from backend.core.live_state_config import live_state_cache_enabled
        from backend.core import live_state_cache

        if not live_state_cache_enabled():
            raise RuntimeError(
                "live_state Redis cache is disabled; strike_table_generator_ws requires the hot path"
            )
        mkt_data = live_state_cache.get_market_data(
            self.data_exchange, self.pipeline_health_market, self.symbol
        )
        if not mkt_data or not mkt_data.get("markets"):
            raise ValueError(
                f"live_state market cache miss for {self.data_exchange}/"
                f"{self.pipeline_health_market}/{self.symbol.upper()}"
            )
        return self._market_data_from_cache_snapshot(mkt_data)


def _symbols_from_live_state_event(
    payload: dict,
    *,
    data_exchange: str,
    market_kind: str,
) -> set[str]:
    """Symbols needing strike regen from ``live_state_updated`` (symbol or market writes)."""
    kind = str(payload.get("kind") or "").strip()
    key = str(payload.get("key") or "")
    parts = key.split(":")
    ex = data_exchange.strip().lower()
    mk = market_kind.strip().lower()
    if kind == "symbol" and len(parts) >= 5:
        sym = str(parts[-1]).strip().upper()
        return {sym} if sym else set()
    if kind == "market" and len(parts) >= 7:
        if str(parts[4]).strip().lower() != ex:
            return set()
        if str(parts[5]).strip().lower() != mk:
            return set()
        sym = str(parts[6]).strip().upper()
        return {sym} if sym else set()
    return set()


def _symbols_from_pubsub_message(
    raw: str,
    *,
    data_exchange: str,
    market_kind: str,
    stream_db_names: tuple[str, ...],
    subscribed_symbols: frozenset[str],
) -> set[str]:
    try:
        payload = json.loads(raw)
    except Exception:
        return set()
    if payload.get("type") == "live_state_updated":
        if payload.get("kind") == "orderbook":
            mt = str(payload.get("market_ticker") or "").strip()
            if not mt:
                return set()
            from backend.core.orderbook_hot_publish_registry import symbol_market_from_orderbook_ticker

            sym, mkt = symbol_market_from_orderbook_ticker(mt)
            if not sym or not mkt:
                return set()
            if str(mkt).strip().lower() != str(market_kind or "").strip().lower():
                return set()
            sym_u = sym.strip().upper()
            return {sym_u} if sym_u in subscribed_symbols else set()
        return _symbols_from_live_state_event(
            payload, data_exchange=data_exchange, market_kind=market_kind
        ) & subscribed_symbols
    if payload.get("type") == "db_change":
        db_name = payload.get("database")
        if db_name in stream_db_names:
            return set(subscribed_symbols)
    return set()


def _collect_symbols_to_regenerate(
    pubsub,
    *,
    data_exchange: str,
    market_kind: str,
    stream_db_names: tuple[str, ...],
    subscribed_symbols: frozenset[str],
    block_timeout_sec: float = 1.0,
) -> set[str]:
    """
    Block until at least one regen signal, then drain the pubsub buffer (no wall-clock debounce).
    Bursts coalesce to one regen per symbol per drain cycle.
    """
    symbols: set[str] = set()
    msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=block_timeout_sec)
    if msg and msg.get("type") == "message":
        raw = msg.get("data")
        if raw:
            symbols |= _symbols_from_pubsub_message(
                raw,
                data_exchange=data_exchange,
                market_kind=market_kind,
                stream_db_names=stream_db_names,
                subscribed_symbols=subscribed_symbols,
            )
    while True:
        msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.0)
        if not msg:
            break
        if msg.get("type") != "message":
            continue
        raw = msg.get("data")
        if not raw:
            continue
        symbols |= _symbols_from_pubsub_message(
            raw,
            data_exchange=data_exchange,
            market_kind=market_kind,
            stream_db_names=stream_db_names,
            subscribed_symbols=subscribed_symbols,
        )
    return symbols


def _strike_regen_precheck_skip(gen: StrikeTableGeneratorWS) -> str | None:
    """
    Cheap skip when regen cannot produce a ladder (missing cache / stale market stream).

    Does not write substitute strike data — caller backs off and retries later.
    """
    try:
        from backend.core.live_state_config import live_state_cache_enabled
        from backend.core import live_state_cache

        if not live_state_cache_enabled():
            return None
        mkt_data = live_state_cache.get_market_data(
            gen.data_exchange, gen.pipeline_health_market, gen.symbol
        )
        if not mkt_data or not mkt_data.get("markets"):
            return "market_cache_miss"
        markets = mkt_data.get("markets") or []
        if len(markets) == 1:
            m0 = markets[0]
            if m0.get("floor_strike") is None and m0.get("strike") is None:
                return "missing_floor_strike"
        age = gen.market_stream_age_sec()
        if age > STRIKE_REGEN_DEAD_OB_STALE_SEC:
            return f"market_stream_stale:{age:.1f}s"
    except Exception:
        return None
    return None


def _strike_regen_dead_backoff_reason(*, ok: bool, row_count: int, health_reason: str) -> str | None:
    """Post-refresh reasons to apply dead-symbol backoff (no useful ladder published)."""
    if ok and row_count > 0:
        return None
    reason = (health_reason or "").strip().lower()
    if not ok and row_count <= 0:
        if "missing_floor" in reason or reason == "strike_refresh_failed":
            return health_reason or "strike_refresh_failed"
        return "strike_refresh_failed"
    if "orderbook" in reason or "stale" in reason:
        return health_reason
    return None


def _refresh_symbol(
    generators: dict,
    sym: str,
    *,
    raw_unhealthy_since: dict,
    degrade_confirm_sec: int,
) -> None:
    gen = generators.get(sym)
    if not gen:
        return
    now_mono = time.monotonic()
    dead_last = _last_dead_regen_skip_mono.get(sym)
    if dead_last is not None and (
        now_mono - dead_last
    ) < STRIKE_REGEN_DEAD_SYMBOL_BACKOFF_SEC:
        return
    skip = _strike_regen_precheck_skip(gen)
    if skip:
        _last_dead_regen_skip_mono[sym] = now_mono
        logger.debug(
            "[%s] strike regen skipped (%s); backoff %.1fs",
            sym,
            skip,
            STRIKE_REGEN_DEAD_SYMBOL_BACKOFF_SEC,
        )
        return
    last = _last_regen_mono.get(sym)
    if last is not None and (now_mono - last) < STRIKE_REGEN_MIN_INTERVAL_SEC:
        return
    _last_regen_mono[sym] = now_mono
    now = time.time()
    ok, ev, n = gen.generate_strike_table()
    healthy_raw, reason_raw = gen.evaluate_pipeline_health(ok, n)
    if healthy_raw:
        raw_unhealthy_since[sym] = None
        _last_dead_regen_skip_mono.pop(sym, None)
        healthy, reason = True, "ok"
    else:
        dead_reason = _strike_regen_dead_backoff_reason(
            ok=ok, row_count=n, health_reason=reason_raw
        )
        if dead_reason:
            _last_dead_regen_skip_mono[sym] = now_mono
        if raw_unhealthy_since[sym] is None:
            raw_unhealthy_since[sym] = now
        elapsed = now - float(raw_unhealthy_since[sym] or now)
        if elapsed < float(degrade_confirm_sec):
            healthy = True
            reason = f"transient_unhealthy:{reason_raw}:{elapsed:.1f}s<{degrade_confirm_sec}s"
        else:
            healthy = False
            reason = reason_raw
    gen.set_pipeline_health(healthy=healthy, reason=reason)
    if not healthy:
        logger.warning("[%s] strike refresh degraded reason=%s event=%s rows=%s", sym, reason, ev, n)
    elif not healthy_raw:
        logger.debug(
            "[%s] strike refresh unhealthy masked %ss reason=%s event=%s rows=%s",
            sym,
            degrade_confirm_sec,
            reason,
            ev,
            n,
        )


def run_redis_triggered(
    *,
    data_exchange: str,
    symbols: tuple[str, ...],
    market_kind: str = "15m",
    redis_channel: str = DEFAULT_REDIS_CHANNEL,
    pipeline_max_age_sec: int = DEFAULT_PIPELINE_MAX_AGE_SEC,
    degrade_confirm_sec: int = DEFAULT_DEGRADE_CONFIRM_SEC,
) -> None:
    mk = (market_kind or "15m").strip().lower()
    # Market ingest is live_state only — no PG market_kalshi_* writer (see docs/KALSHI_MARKET_INGEST.md).
    stream_db_names: tuple[str, ...] = ()
    if mk == "hourly":
        default_strike = os.getenv("STRIKE_TABLE_HOURLY_TARGET", "strike_table_hourly")
        default_market = "market_kalshi_hourly"
    elif mk == "15m":
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

    subscribed = frozenset(syms)

    try:
        from backend.core.probability_lookup_cache import preload_symbols

        preload_symbols(syms)
    except Exception as e:
        logger.warning("probability_lookup_cache preload skipped: %s", e)

    for s in syms:
        _last_regen_mono.pop(s, None)
        _last_dead_regen_skip_mono.pop(s, None)
        _refresh_symbol(
            generators,
            s,
            raw_unhealthy_since=raw_unhealthy_since,
            degrade_confirm_sec=degrade_confirm_sec,
        )
        logger.info("[%s] startup prime complete", s)

    logger.info(
        "Event-driven WS strike generator market=%s exchange=%s symbols=%s channels=%s,%s",
        mk,
        data_exchange,
        ",".join(syms),
        redis_channel,
        "rec_io:live_state:updated",
    )

    from backend.core.live_state_cache import UPDATED_CHANNEL

    r = _redis_client()
    pubsub = r.pubsub()
    pubsub.subscribe(redis_channel, UPDATED_CHANNEL)
    logger.info("Subscribed Redis channels %s, %s", redis_channel, UPDATED_CHANNEL)

    while True:
        try:
            to_regen = _collect_symbols_to_regenerate(
                pubsub,
                data_exchange=data_exchange,
                market_kind=mk,
                stream_db_names=stream_db_names,
                subscribed_symbols=subscribed,
            )
            if not to_regen:
                continue
            for s in sorted(to_regen):
                _refresh_symbol(
                    generators,
                    s,
                    raw_unhealthy_since=raw_unhealthy_since,
                    degrade_confirm_sec=degrade_confirm_sec,
                )
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
    else:
        env_syms = (
            os.getenv("STRIKE_TABLE_SYMBOLS", "").strip()
            or os.getenv("MARKET_WATCHDOG_SYMBOLS", "").strip()
        )
        if env_syms:
            syms = tuple(s.strip().upper() for s in env_syms.split(",") if s.strip())
        elif args.market == "hourly":
            syms = tuple(sorted(KALSHI_HOURLY_SYMBOLS))
        else:
            syms = fetch_kalshi_15m_symbols_ordered_from_db()
    if args.market == "hourly":
        syms = tuple(s for s in syms if s in KALSHI_HOURLY_SYMBOLS)
        if not syms:
            raise SystemExit("No valid hourly symbols configured (BTC, ETH, SOL, DOGE)")
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
        pipeline_max_age_sec=pipeline_max_age,
        degrade_confirm_sec=max(5, int(args.degrade_confirm_sec)),
    )


if __name__ == "__main__":
    main()
