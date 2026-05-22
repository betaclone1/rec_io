"""
Redis switchboard: LISTEN to PostgreSQL NOTIFY, publish to Redis, fan out to WebSocket clients.

SCOPE (anti-bloat): This process does exactly: (1) LISTEN rec_io_db_changes,
(2) map (schema, table) -> stream name via stream_registry, (3) publish one JSON
to Redis rec_io:db_changes, (4) fan out to /ws/db_changes clients. Plus /health.

Also publishes ``{"type":"live_symbol_spot",...}`` after live_state symbol updates and
``live_data.price_change_*`` NOTIFY (``live_symbol_status`` NOTIFY is LP-only).
with spot rows plus latest 1h/3h/1d percent fields from ``price_change_<symbol>`` tables.

Do NOT add application HTTP APIs or auth here. See docs/REALTIME_BACKBONE.md
Section 0. The only allowed HTTP surface is /health and /ws/db_changes; pilot
endpoints (/api/redis_basic_test, /redis-basic-test, /api/strike_table_15m_latest,
/strike-table-15m-test) are temporary for testing.

Run: python -m backend.redis_switchboard
Config (env): REDIS_URL or REDIS_HOST+REDIS_PORT; SWITCHBOARD_*; PG_NOTIFY_CHANNEL;
REDIS_CHANNEL_DB_CHANGES; DB via get_system_postgresql_connection (LISTEN).
"""

import os
import sys
import json
import logging
import select
import threading
import queue
import asyncio
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from psycopg2 import sql as psql
from psycopg2.extras import RealDictCursor

# Project root (only for DB and Redis; no main.py or frontend dependency)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, HTMLResponse
import uvicorn

# Config
REDIS_URL = os.getenv("REDIS_URL")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
REDIS_CHANNEL_DB_CHANGES = os.getenv("REDIS_CHANNEL_DB_CHANGES", "rec_io:db_changes")
SWITCHBOARD_HOST = os.getenv("SWITCHBOARD_HOST", "0.0.0.0")
SWITCHBOARD_PORT = int(os.getenv("SWITCHBOARD_PORT", "3010"))
PG_NOTIFY_CHANNEL = os.getenv("PG_NOTIFY_CHANNEL", "rec_io_db_changes")

# Stream registry: (schema, table) -> stream name. Single source of truth: backend/core/stream_registry.py
from backend.core.stream_registry import resolve_stream_for_notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [redis_switchboard] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("redis_switchboard")

STREAM_LIVE_SYMBOL_STATUS = "live_symbol_status"

# NOTIFY from these tables only fans out ``live_symbol_spot`` (no separate db_change).
_PRICE_CHANGE_NOTIFY_TABLES = frozenset(
    {"price_change_btc", "price_change_eth", "price_change_sol", "price_change_xrp"}
)

# In-memory client set and message queue
clients_db_changes = set()
message_queue = queue.Queue()


def get_redis_client():
    if REDIS_URL:
        return redis.from_url(REDIS_URL, decode_responses=True)
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )


def _numeric_spot_from_row(row: dict):
    """Match strike generators: prefer one_minute_avg, else price."""
    o = row.get("one_minute_avg")
    p = row.get("price")
    for v in (o, p):
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _live_tick_spot_from_row(row: dict):
    """UI live tick: raw Coinbase ``price`` when cache-only; else legacy avg-first."""
    try:
        from backend.core.live_state_config import (
            live_state_cache_enabled,
            live_state_pg_writes_enabled,
        )

        if live_state_cache_enabled() and not live_state_pg_writes_enabled():
            p = row.get("price")
            if p is not None:
                return float(p)
    except Exception:
        pass
    return _numeric_spot_from_row(row)


_CHANGES_BY_SYMBOL_CACHE: dict = {}
_CHANGES_BY_SYMBOL_CACHE_AT: float = 0.0
_CHANGES_CACHE_TTL_SEC = float(os.getenv("LIVE_SYMBOL_CHANGES_CACHE_TTL_SEC", "30"))


def invalidate_price_changes_cache() -> None:
    global _CHANGES_BY_SYMBOL_CACHE_AT
    _CHANGES_BY_SYMBOL_CACHE_AT = 0.0


def _fetch_changes_by_symbol() -> dict:
    """Latest 1h/3h/1d %% from ``live_data.price_change_*`` (not on hot tick path)."""
    global _CHANGES_BY_SYMBOL_CACHE, _CHANGES_BY_SYMBOL_CACHE_AT
    now = time.monotonic()
    if _CHANGES_BY_SYMBOL_CACHE and (now - _CHANGES_BY_SYMBOL_CACHE_AT) < _CHANGES_CACHE_TTL_SEC:
        return dict(_CHANGES_BY_SYMBOL_CACHE)
    changes_by_symbol: dict = {}
    try:
        from backend.core.config.database import get_system_postgresql_connection

        conn = get_system_postgresql_connection()
        if not conn:
            return dict(_CHANGES_BY_SYMBOL_CACHE)
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            for sym_key, tbl in (
                ("BTC", "price_change_btc"),
                ("ETH", "price_change_eth"),
                ("SOL", "price_change_sol"),
                ("XRP", "price_change_xrp"),
            ):
                try:
                    cur.execute(
                        psql.SQL(
                            "SELECT change1h, change3h, change1d FROM live_data.{} "
                            "ORDER BY id DESC LIMIT 1"
                        ).format(psql.Identifier(tbl))
                    )
                    prow = cur.fetchone()
                    if prow:
                        pd = dict(prow)
                        changes_by_symbol[sym_key] = {
                            "change1h": _jsonable_value(pd.get("change1h")),
                            "change3h": _jsonable_value(pd.get("change3h")),
                            "change1d": _jsonable_value(pd.get("change1d")),
                        }
                except Exception:
                    continue
            cur.close()
        finally:
            conn.close()
    except Exception as e:
        logger.debug("_fetch_changes_by_symbol: %s", e)
        return dict(_CHANGES_BY_SYMBOL_CACHE)
    _CHANGES_BY_SYMBOL_CACHE = changes_by_symbol
    _CHANGES_BY_SYMBOL_CACHE_AT = now
    return dict(changes_by_symbol)


def _momentum_by_symbol_from_rows(row_dicts: list) -> dict:
    """Trade-monitor header Mom: prefer 30s smoothed momentum (stored as percentile)."""
    out: dict = {}
    for r in row_dicts or []:
        sym = r.get("symbol")
        if sym is None:
            continue
        key = str(sym).strip().upper()
        if not key:
            continue
        raw = r.get("momentum_30s_avg")
        if raw is None:
            raw = r.get("momentum_percentile")
        if raw is None:
            raw = r.get("momentum")
        if raw is not None:
            try:
                out[key] = float(raw)
            except (TypeError, ValueError):
                continue
    return out


def _publish_to_db_changes_bus(text: str) -> None:
    """Fan out to main_app (Redis pub/sub) and switchboard WS bridge (local queue)."""
    try:
        get_redis_client().publish(REDIS_CHANNEL_DB_CHANGES, text)
    except Exception as e:
        logger.warning("Redis publish db_changes bus failed: %s", e)
    message_queue.put((REDIS_CHANNEL_DB_CHANGES, text))


def publish_live_orderbook_ws_message(payload: dict) -> None:
    """Push one ``live_orderbook`` frame to the db_changes bus (trade-monitor WS clients)."""
    if not payload:
        return
    body = dict(payload)
    body.setdefault("type", "live_orderbook")
    _publish_to_db_changes_bus(json.dumps(body))


def build_live_symbol_spot_from_cache():
    """Build live_symbol_spot from Redis live_state symbol keys only (no PG)."""
    from backend.core import live_state_cache
    from backend.core.live_state_config import live_state_cache_enabled

    if not live_state_cache_enabled():
        return None
    row_dicts = []
    spot_by_symbol: dict = {}
    for sym in ("BTC", "ETH", "SOL", "XRP"):
        cached = live_state_cache.get_symbol_data(sym)
        if not cached:
            continue
        merged = dict(cached)
        merged["symbol"] = sym
        row_dicts.append(_jsonable_row(merged))
        sp = _live_tick_spot_from_row(merged)
        if sp is not None:
            spot_by_symbol[sym] = sp
    if not row_dicts:
        return None
    now = datetime.now(timezone.utc).isoformat()
    return {
        "type": "live_symbol_spot",
        "timestamp": now,
        "spot_by_symbol": spot_by_symbol,
        "changes_by_symbol": _fetch_changes_by_symbol(),
        "momentum_by_symbol": _momentum_by_symbol_from_rows(row_dicts),
        "rows": row_dicts,
    }


def build_live_symbol_spot_payload():
    """
    Snapshot spot/momentum from live_state Redis plus ``price_change_*`` %% (PG, ~30s cache).

    When ``LIVE_STATE_CACHE_ENABLED=1``, symbol rows come only from Redis; missing cache → None.
    """
    from backend.core.live_state_config import live_state_cache_enabled

    if live_state_cache_enabled():
        return build_live_symbol_spot_from_cache()

    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT *
            FROM live_data.live_symbol_status
            ORDER BY symbol NULLS LAST
            """
        )
        rows = cur.fetchall()
        if not rows:
            return None
        row_dicts = [_jsonable_row(dict(r)) for r in rows]
        try:
            from backend.core.live_state_config import live_state_cache_enabled
            from backend.core import live_state_cache

            if live_state_cache_enabled():
                for sym in ("BTC", "ETH", "SOL", "XRP"):
                    cached = live_state_cache.get_symbol_data(sym)
                    if not cached:
                        continue
                    merged = dict(cached)
                    merged["symbol"] = sym
                    replaced = False
                    for i, existing in enumerate(row_dicts):
                        if str(existing.get("symbol", "")).upper() == sym:
                            row_dicts[i] = _jsonable_row({**existing, **merged})
                            replaced = True
                            break
                    if not replaced:
                        row_dicts.append(_jsonable_row(merged))
        except Exception:
            pass
        spot_by_symbol = {}
        for r in row_dicts:
            sym = r.get("symbol")
            if sym is None:
                continue
            key = str(sym).strip().upper()
            if not key:
                continue
            sp = _live_tick_spot_from_row(r)
            if sp is not None:
                spot_by_symbol[key] = sp
        changes_by_symbol = _fetch_changes_by_symbol()
        now = datetime.now(timezone.utc).isoformat()
        return {
            "type": "live_symbol_spot",
            "timestamp": now,
            "spot_by_symbol": spot_by_symbol,
            "changes_by_symbol": changes_by_symbol,
            "momentum_by_symbol": _momentum_by_symbol_from_rows(row_dicts),
            "rows": row_dicts,
        }
    except Exception as e:
        logger.warning("build_live_symbol_spot_payload: %s", e)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def pg_listen_loop():
    """Run in a thread: LISTEN to PostgreSQL, on notify build db_change message and publish to Redis."""
    try:
        import psycopg2.extensions
        from backend.core.config.database import get_system_postgresql_connection
        conn = get_system_postgresql_connection()
        if not conn:
            logger.warning("PG connection failed; DB-driven events disabled")
            return
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute(f"LISTEN {PG_NOTIFY_CHANNEL};")
        logger.info("LISTEN %s started (db=%s)", PG_NOTIFY_CHANNEL, conn.info.dbname)
        r = get_redis_client()
        while True:
            # Block until the connection has data (NOTIFY delivery)
            ready, _, _ = select.select([conn], [], [], 5.0)
            if not ready:
                conn.poll()
                continue
            conn.poll()
            while conn.notifies:
                n = conn.notifies.pop(0)
                logger.info("NOTIFY received: channel=%s payload=%s", n.channel, n.payload)
                try:
                    payload = json.loads(n.payload)
                    schema = payload.get("schema")
                    table = payload.get("table")
                    sch_l = str(schema or "").lower()
                    tbl_l = str(table or "").lower()
                    if sch_l == "live_data" and tbl_l in _PRICE_CHANGE_NOTIFY_TABLES:
                        try:
                            invalidate_price_changes_cache()
                            spot_msg = build_live_symbol_spot_payload()
                            if spot_msg:
                                r.publish(
                                    REDIS_CHANNEL_DB_CHANGES,
                                    json.dumps(spot_msg),
                                )
                                logger.info(
                                    "Published live_symbol_spot (from %s) -> Redis",
                                    tbl_l,
                                )
                        except Exception as se:
                            logger.warning(
                                "live_symbol_spot from price_change notify failed: %s",
                                se,
                            )
                        continue
                    op = payload.get("op", "UNKNOWN")
                    db_name, tenant_user_no = resolve_stream_for_notify(
                        str(schema) if schema else "",
                        str(table) if table else "",
                    )
                    if not db_name:
                        logger.debug("Ignore notify for %s.%s (no mapping)", schema, table)
                        continue
                    now = datetime.now(timezone.utc).isoformat()
                    msg = {
                        "type": "db_change",
                        "database": db_name,
                        "data": {
                            "timestamp": payload.get("timestamp"),
                            "change_data": {"schema": schema, "table": table, "op": op},
                        },
                        "timestamp": now,
                    }
                    if tenant_user_no:
                        msg["tenant_user_no"] = tenant_user_no
                    try:
                        r.publish(REDIS_CHANNEL_DB_CHANGES, json.dumps(msg))
                        logger.info("Published db_change %s -> Redis", db_name)
                    except Exception as re:
                        logger.warning("Redis publish failed: %s", re)
                    if db_name == STREAM_LIVE_SYMBOL_STATUS:
                        try:
                            spot_msg = build_live_symbol_spot_payload()
                            if spot_msg:
                                r.publish(
                                    REDIS_CHANNEL_DB_CHANGES,
                                    json.dumps(spot_msg),
                                )
                                logger.info("Published live_symbol_spot -> Redis")
                        except Exception as se:
                            logger.warning("live_symbol_spot after NOTIFY failed: %s", se)
                except Exception as e:
                    logger.warning("Error handling NOTIFY: %s", e)
    except Exception as e:
        logger.warning("PG listen thread exited: %s", e)


def _market_from_live_state_key(parts: list[str]) -> Optional[str]:
    """Parse market segment from ``rec_io:live_state:v1:{kind}:{exchange}:{market}:{symbol}``."""
    # parts: rec_io, live_state, v1, kind, exchange, market, symbol
    if len(parts) < 7:
        return None
    return str(parts[5] or "").strip().lower()


def _publish_orderbook_kalshi_db_change(market_ticker: str = "") -> None:
    """Synthetic ``orderbook_kalshi`` db_change for cache-only depth (replaces PG NOTIFY)."""
    now = datetime.now(timezone.utc).isoformat()
    change = {"schema": "live_data", "table": "orderbook_kalshi", "op": "LIVE_CACHE"}
    if market_ticker:
        change["market_ticker"] = market_ticker
    _publish_to_db_changes_bus(
        json.dumps(
            {
                "type": "db_change",
                "schema": "live_data",
                "database": "orderbook_kalshi",
                "table": "orderbook_kalshi",
                "data": {"timestamp": now, "change_data": change},
                "timestamp": now,
            }
        )
    )


def _fanout_live_strike_ladder_ws(exchange: str, market: str, symbol: str) -> None:
    """Push ``live_strike_ladder`` from Redis on every strike_ladder cache write."""
    sym = str(symbol or "").strip().upper()
    mk = str(market or "").strip().lower()
    if not sym or mk not in ("hourly", "15m"):
        return
    try:
        from backend.core.live_state_read_helpers import strike_ladder_ws_payload

        ladder_msg = strike_ladder_ws_payload(exchange, mk, sym)
        if not ladder_msg:
            return
        _publish_to_db_changes_bus(json.dumps(ladder_msg))
    except Exception as e:
        logger.debug("live_strike_ladder fanout failed: %s", e)


def _fanout_live_state_updated(payload: dict) -> None:
    """Map live_state pub/sub events to WS payloads (cache-only mode; no PG NOTIFY)."""
    kind = payload.get("kind")
    key = str(payload.get("key") or "")
    parts = key.split(":")
    if kind == "orderbook":
        mt = str(payload.get("market_ticker") or "").strip()
        if not mt:
            return
        try:
            from backend.core.trade_monitor_orderbook_watch import should_fanout_orderbook_live_ws

            mk_fanout = str(payload.get("market_interval") or "15m").strip().lower()
            if not should_fanout_orderbook_live_ws(mt, market=mk_fanout):
                return
        except Exception:
            pass
        event_seq = payload.get("book_seq")
        try:
            from backend.core.trade_monitor_live_orderbook_payload import (
                build_live_orderbook_ws_payload,
            )

            ob_msg = build_live_orderbook_ws_payload(mt)
            if not ob_msg:
                return
            _publish_to_db_changes_bus(json.dumps(ob_msg))
        except Exception as e:
            logger.debug("live_orderbook fanout failed: %s", e)
        return
    if kind == "symbol":
        spot = build_live_symbol_spot_payload()
        if spot:
            _publish_to_db_changes_bus(json.dumps(spot))
        now = datetime.now(timezone.utc).isoformat()
        _publish_to_db_changes_bus(
            json.dumps(
                {
                    "type": "db_change",
                    "database": STREAM_LIVE_SYMBOL_STATUS,
                    "data": {
                        "timestamp": now,
                        "change_data": {
                            "schema": "live_data",
                            "table": "live_symbol_status",
                            "op": "LIVE_CACHE",
                        },
                    },
                    "timestamp": now,
                }
            )
        )
        return
    mk = _market_from_live_state_key(parts)
    if not mk:
        return
    sym = str(parts[6] or "").strip().upper() if len(parts) >= 7 else ""
    if kind == "strike_ladder":
        if sym:
            _fanout_live_strike_ladder_ws("kalshi", mk, sym)
        db_name = "strike_table_15m" if mk == "15m" else "strike_table_hourly"
    elif kind == "market":
        if sym:
            _fanout_live_strike_ladder_ws("kalshi", mk, sym)
        db_name = "market_kalshi_15m" if mk == "15m" else "market_kalshi_hourly"
    else:
        return
    now = datetime.now(timezone.utc).isoformat()
    _publish_to_db_changes_bus(
        json.dumps(
            {
                "type": "db_change",
                "schema": "live_data",
                "database": db_name,
                "table": db_name,
                "data": {
                    "timestamp": now,
                    "change_data": {"schema": "live_data", "table": db_name, "op": "LIVE_STATE"},
                },
                "timestamp": now,
            }
        )
    )


def live_state_subscriber_loop():
    """Subscribe to rec_io:live_state:updated and fan out synthetic WS messages."""
    from backend.core.live_state_cache import UPDATED_CHANNEL
    from backend.core.live_state_config import live_state_cache_enabled

    if not live_state_cache_enabled():
        return
    try:
        r = get_redis_client()
        pubsub = r.pubsub()
        pubsub.subscribe(UPDATED_CHANNEL)
        logger.info("Subscribed to Redis %s (live_state fanout)", UPDATED_CHANNEL)
        for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("type") != "live_state_updated":
                continue
            _fanout_live_state_updated(payload)
    except Exception as e:
        logger.warning("live_state subscriber thread exited: %s", e)


def redis_subscriber_loop():
    """Run in a thread: subscribe to Redis channel, push (channel, message) to message_queue."""
    try:
        r = get_redis_client()
        pubsub = r.pubsub()
        pubsub.subscribe(REDIS_CHANNEL_DB_CHANGES)
        logger.info("Subscribed to Redis %s", REDIS_CHANNEL_DB_CHANGES)
        for message in pubsub.listen():
            if message["type"] == "message":
                message_queue.put((message["channel"], message["data"]))
    except Exception as e:
        logger.warning("Redis subscriber thread exited: %s", e)


app = FastAPI(title="Redis Switchboard")


def get_pg():
    from backend.core.config.database import get_system_postgresql_connection
    return get_system_postgresql_connection()


def _jsonable_value(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def _jsonable_row(row: dict):
    return {k: _jsonable_value(v) for k, v in row.items()}


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "redis_channel": REDIS_CHANNEL_DB_CHANGES,
        "clients_db_changes": len(clients_db_changes),
    })


_COLUMNS = [f"test_value_{i}" for i in range(1, 21)]
_SELECT_COLS = ", ".join(_COLUMNS)


@app.get("/api/redis_basic_test")
async def api_get_redis_basic_test():
    """Read current row(s) from testing.redis_basic_test (standalone test only). Returns all test_value_1..20."""
    conn = get_pg()
    if not conn:
        return JSONResponse({"status": "error", "message": "No DB connection"}, status_code=503)
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT id, {_SELECT_COLS} FROM testing.redis_basic_test ORDER BY id LIMIT 10")
        rows = cur.fetchall()
        conn.close()
        out = []
        for r in rows:
            row_dict = {"id": r[0]}
            for i, col in enumerate(_COLUMNS):
                v = r[1 + i]
                row_dict[col] = float(v) if v is not None else None
            out.append(row_dict)
        return JSONResponse({"status": "ok", "rows": out})
    except Exception as e:
        logger.warning("GET redis_basic_test: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/api/redis_basic_test")
async def api_post_redis_basic_test(request: Request):
    """Set test_value_1 (insert or update one row). Trigger will NOTIFY -> Redis -> WS (standalone test only)."""
    try:
        body = await request.json()
        val = body.get("test_value_1")
        if val is None:
            return JSONResponse({"status": "error", "message": "test_value_1 required"}, status_code=400)
        conn = get_pg()
        if not conn:
            return JSONResponse({"status": "error", "message": "No DB connection"}, status_code=503)
        cur = conn.cursor()
        cur.execute("SELECT id FROM testing.redis_basic_test LIMIT 1")
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE testing.redis_basic_test SET test_value_1 = %s WHERE id = %s", (float(val), row[0]))
        else:
            cur.execute("INSERT INTO testing.redis_basic_test (test_value_1) VALUES (%s)", (float(val),))
        conn.commit()
        conn.close()
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.warning("POST redis_basic_test: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


_STRIKE_TABLE_15M_LATEST_SQL = """
SELECT DISTINCT ON (exchange, symbol)
    id, "timestamp", symbol, exchange, market, current_price,
    ttc_hourly, ttc_15m, event_ticker, market_title, strike_tier, market_status,
    strike, buffer, buffer_pct, probability_hourly, probability_15m,
    yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    ticker, active_side, volume_fp, open_interest_fp,
    momentum_weighted_score, momentum_percentile, volatility, volatility_percentile,
    movement, movement_percentile, created_at
FROM live_data.strike_table_15m
ORDER BY exchange, symbol, "timestamp" DESC NULLS LAST
"""


@app.get("/api/strike_table_15m_latest")
async def api_get_strike_table_15m_latest():
    """Latest row per (exchange, symbol) on live_data.strike_table_15m (test UI only)."""
    conn = get_pg()
    if not conn:
        return JSONResponse({"status": "error", "message": "No DB connection"}, status_code=503)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(_STRIKE_TABLE_15M_LATEST_SQL)
        rows = cur.fetchall()
        conn.close()
        out = [_jsonable_row(dict(r)) for r in rows]
        return JSONResponse({"status": "ok", "rows": out, "count": len(out)})
    except Exception as e:
        logger.warning("GET strike_table_15m_latest: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


STRIKE_TABLE_15M_TEST_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>strike_table_15m (live)</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 1.5rem; max-width: 1400px; }
    h1 { font-size: 1.2rem; }
    .meta { color: #555; font-size: 0.85rem; margin: 0.5rem 0 1rem; }
    button { padding: 0.35rem 0.75rem; margin-right: 0.5rem; cursor: pointer; }
    table { border-collapse: collapse; width: 100%; font-size: 0.8rem; }
    th, td { border: 1px solid #ccc; padding: 0.35rem 0.5rem; text-align: left; vertical-align: top; }
    th { background: #f0f0f0; position: sticky; top: 0; }
    .wrap { overflow-x: auto; max-height: 80vh; overflow-y: auto; }
    .err { color: #a00; }
  </style>
</head>
<body>
  <h1>live_data.strike_table_15m — latest row per symbol</h1>
  <p class="meta">Updates via WebSocket when NOTIFY fires on the table (same path as redis_basic_test pilot).
    Requires migration <code>20260326_2000_strike_table_15m_db_notify</code> and stream registry entry.</p>
  <div>
    <button type="button" onclick="fetchRows()">Refresh now</button>
    <span class="meta">WebSocket: <span id="ws">connecting…</span> · Last push: <span id="ts">—</span></span>
  </div>
  <p id="msg" class="err"></p>
  <div class="wrap" id="holder"></div>
  <script>
    const port = window.location.port || (window.location.protocol === 'https:' ? 443 : 80);
    const wsUrl = (window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.hostname + ':' + port + '/ws/db_changes';
    function render(rows) {
      const holder = document.getElementById('holder');
      document.getElementById('msg').textContent = '';
      if (!rows || !rows.length) {
        holder.textContent = '(no rows in live_data.strike_table_15m)';
        return;
      }
      const keys = Object.keys(rows[0]);
      let html = '<table><thead><tr>';
      keys.forEach(function(k) { html += '<th>' + k + '</th>'; });
      html += '</tr></thead><tbody>';
      rows.forEach(function(r) {
        html += '<tr>';
        keys.forEach(function(k) {
          const v = r[k];
          html += '<td>' + (v !== null && v !== undefined ? String(v) : '—') + '</td>';
        });
        html += '</tr>';
      });
      html += '</tbody></table>';
      holder.innerHTML = html;
    }
    function fetchRows() {
      fetch('/api/strike_table_15m_latest').then(function(r) { return r.json(); }).then(function(d) {
        if (d.status === 'ok') render(d.rows);
        else document.getElementById('msg').textContent = d.message || JSON.stringify(d);
      }).catch(function(e) { document.getElementById('msg').textContent = 'fetch error: ' + e.message; });
    }
    const ws = new WebSocket(wsUrl);
    ws.onopen = function() { document.getElementById('ws').textContent = 'connected'; };
    ws.onclose = function() { document.getElementById('ws').textContent = 'closed'; };
    ws.onmessage = function(ev) {
      try {
        const d = JSON.parse(ev.data);
        if (d.type === 'db_change' && d.database === 'strike_table_15m') {
          document.getElementById('ts').textContent = new Date().toLocaleTimeString();
          fetchRows();
        }
      } catch (e) {}
    };
    fetchRows();
  </script>
</body>
</html>
"""


@app.get("/strike-table-15m-test", response_class=HTMLResponse)
async def strike_table_15m_test_page():
    """Pilot UI: live_data.strike_table_15m via REST + /ws/db_changes."""
    return HTMLResponse(STRIKE_TABLE_15M_TEST_HTML)


REDIS_BASIC_TEST_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Redis switchboard test</title>
  <style>
    body { font-family: sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.25rem; }
    h2 { font-size: 1rem; margin-top: 1.5rem; color: #333; }
    .how-to { background: #f5f5f5; padding: 0.75rem 1rem; border-radius: 6px; font-family: monospace; font-size: 0.85rem; margin: 0.5rem 0; overflow-x: auto; }
    .values-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 0.5rem; margin: 1rem 0; }
    .cell { padding: 0.5rem; text-align: center; background: #eee; border-radius: 4px; font-family: monospace; font-weight: bold; font-size: 1.1rem; }
    .cell-label { font-size: 0.7rem; font-weight: normal; color: #666; }
    .meta { color: #666; font-size: 0.85rem; margin-top: 1rem; }
    button { padding: 0.4rem 0.8rem; margin-right: 0.5rem; cursor: pointer; }
    .status { margin: 0.5rem 0; }
  </style>
</head>
<body>
  <h1>Redis switchboard test</h1>
  <p>testing.redis_basic_test — first row, columns test_value_1 … test_value_20</p>
  <h2>How to test</h2>
  <p>Run the randomizer in a terminal (from project root). Values below update in real time via DB trigger → NOTIFY → Redis → WebSocket.</p>
  <div class="how-to">PYTHONPATH=$(pwd) ./venv/bin/python scripts/redis_basic_test_randomizer.py</div>
  <p>Or edit the row in TablePlus and commit; this page should update without refresh.</p>
  <h2>Values (live)</h2>
  <div class="status">
    <button type="button" onclick="fetchVal()">Refresh now</button>
    <span class="meta">WebSocket: <span id="ws">connecting…</span> · Last update: <span id="ts">—</span></span>
  </div>
  <div class="values-grid" id="values"></div>
  <div class="meta" id="row-info"></div>
  <script>
    const port = window.location.port || (window.location.protocol === 'https:' ? 443 : 80);
    const wsUrl = (window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.hostname + ':' + port + '/ws/db_changes';
    const cols = Array.from({ length: 20 }, (_, i) => 'test_value_' + (i + 1));
    function fetchVal() {
      fetch('/api/redis_basic_test').then(r => r.json()).then(d => {
        const el = document.getElementById('values');
        el.innerHTML = '';
        if (d.status === 'ok' && d.rows && d.rows.length > 0) {
          const row = d.rows[0];
          document.getElementById('row-info').textContent = 'Row id: ' + row.id;
          cols.forEach((c, i) => {
            const cell = document.createElement('div');
            cell.className = 'cell';
            const v = row[c];
            cell.innerHTML = '<span class="cell-label">' + (i + 1) + '</span><br>' + (v != null ? v : '—');
            cell.id = 'v_' + c;
            el.appendChild(cell);
          });
        } else {
          el.textContent = '(no rows — run the randomizer once to create a row)';
        }
      }).catch(e => { document.getElementById('values').textContent = 'Error: ' + e.message; });
    }
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => { document.getElementById('ws').textContent = 'connected'; };
    ws.onclose = () => { document.getElementById('ws').textContent = 'closed'; };
    ws.onmessage = function(ev) {
      const d = JSON.parse(ev.data);
      if (d.type === 'db_change' && d.database === 'redis_basic_test') {
        document.getElementById('ts').textContent = new Date().toLocaleTimeString();
        fetchVal();
      }
    };
    fetchVal();
  </script>
</body>
</html>
"""


@app.get("/redis-basic-test", response_class=HTMLResponse)
async def redis_basic_test_page():
    """Standalone test UI: shows testing.redis_basic_test and subscribes to db_changes."""
    return HTMLResponse(REDIS_BASIC_TEST_HTML)


@app.websocket("/ws/db_changes")
async def websocket_db_changes(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_running_loop()
    try:
        spot_payload = await loop.run_in_executor(None, build_live_symbol_spot_payload)
        if spot_payload:
            await websocket.send_text(json.dumps(spot_payload))
    except Exception as e:
        logger.debug("WS initial live_symbol_spot snapshot failed: %s", e)
    clients_db_changes.add(websocket)
    logger.info("WS client connected (db_changes); total=%d", len(clients_db_changes))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients_db_changes.discard(websocket)
        logger.info("WS client disconnected; total=%d", len(clients_db_changes))


async def bridge_loop():
    """Read from message_queue (via executor) and broadcast to clients_db_changes."""
    loop = asyncio.get_event_loop()
    while True:
        try:
            channel, message = await loop.run_in_executor(None, message_queue.get)
            if channel != REDIS_CHANNEL_DB_CHANGES:
                continue
            text = message if isinstance(message, str) else json.dumps(message)
            to_remove = set()
            for ws in clients_db_changes:
                try:
                    await ws.send_text(text)
                except Exception:
                    to_remove.add(ws)
            clients_db_changes.difference_update(to_remove)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Bridge loop: %s", e)


@app.on_event("startup")
async def startup():
    # Start PG LISTEN thread (for testing.redis_basic_test)
    t_pg = threading.Thread(target=pg_listen_loop, daemon=True)
    t_pg.start()
    # Start Redis subscriber thread
    t_redis = threading.Thread(target=redis_subscriber_loop, daemon=True)
    t_redis.start()
    t_live_state = threading.Thread(target=live_state_subscriber_loop, daemon=True)
    t_live_state.start()
    # Start bridge task
    asyncio.create_task(bridge_loop())
    logger.info("Switchboard listening on %s:%s", SWITCHBOARD_HOST, SWITCHBOARD_PORT)


def main():
    uvicorn.run(
        app,
        host=SWITCHBOARD_HOST,
        port=SWITCHBOARD_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
