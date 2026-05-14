#!/usr/bin/env python3
"""
Experiment: capture Kalshi orderbook updates for the current BTC 15m market.

Behavior:
- Resolves current BTC 15m market_ticker from local DB (`live_data.market_kalshi_15m`).
- Subscribes to Kalshi `orderbook_delta` websocket channel for that single ticker.
- Persists raw websocket payload fields as-is into testing schema, 4 columns total:
    type, sid, seq, msg
- Detects rollover to next 15m BTC market from local DB and switches subscription.
- Writes next market into a new table.

Run:
    python backend/api/kalshi-api/kalshi_orderbook_15m_experiment.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import websockets
import psycopg2

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.kalshi_ws_auth import kalshi_ws_connect_headers
from backend.core.time_eastern import merge_psycopg2_connect_kwargs

WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
ROLL_CHECK_SEC = 5.0


def _sanitize_ticker_for_table(market_ticker: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_]+", "_", str(market_ticker).strip())
    t = re.sub(r"_+", "_", t).strip("_").lower()
    return t or "unknown"


def _table_name_for_ticker(market_ticker: str) -> str:
    return f"orderbook_updates_{_sanitize_ticker_for_table(market_ticker)}"


def _quoted_table_ident(table_name: str) -> str:
    # Table names generated from a strict sanitizer above.
    return f'testing."{table_name}"'


def _open_local_db():
    # Use explicit DB env vars so this experiment works without tenant-context env requirements.
    return psycopg2.connect(
        **merge_psycopg2_connect_kwargs(
            {
                "host": os.getenv("DB_HOST", "localhost"),
                "port": int(os.getenv("DB_PORT", "5432")),
                "dbname": os.getenv("DB_NAME", "rec_io_db"),
                "user": os.getenv("DB_USER", "rec_io_user"),
                "password": os.getenv("DB_PASSWORD", "rec_io_password"),
            }
        )
    )


def _ensure_capture_table(table_name: str) -> None:
    conn = _open_local_db()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS testing")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_quoted_table_ident(table_name)} (
                    type TEXT,
                    sid BIGINT,
                    seq BIGINT,
                    msg JSONB
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def _insert_raw_message(table_name: str, payload: dict[str, Any]) -> None:
    conn = _open_local_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_quoted_table_ident(table_name)} (type, sid, seq, msg)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (
                    payload.get("type"),
                    payload.get("sid"),
                    payload.get("seq"),
                    json.dumps(payload.get("msg"), default=str),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def current_btc_15m_ticker() -> Optional[str]:
    """
    Read the freshest BTC 15m market ticker from local unified market table.
    """
    conn = _open_local_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT market_ticker
                FROM live_data.market_kalshi_15m
                WHERE symbol = 'BTC'
                  AND exchange = 'kalshi'
                  AND market_ticker IS NOT NULL
                  AND TRIM(market_ticker::text) <> ''
                ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row or not row[0]:
                return None
            return str(row[0]).strip()
    except Exception:
        return None
    finally:
        conn.close()


class Orderbook15mExperiment:
    def __init__(self) -> None:
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.command_id = 1
        self.current_ticker: Optional[str] = None
        self.current_table: Optional[str] = None
        self.current_sid: Optional[int] = None
        self.log = logging.getLogger("orderbook_15m_experiment")

    async def connect(self) -> None:
        headers = kalshi_ws_connect_headers()
        self.ws = await websockets.connect(
            WS_URL,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
            max_size=8_000_000,
        )
        self.log.info("connected websocket")

    async def _send(self, payload: dict[str, Any]) -> None:
        if not self.ws:
            raise RuntimeError("websocket not connected")
        await self.ws.send(json.dumps(payload))
        self.command_id += 1

    async def subscribe_ticker(self, market_ticker: str) -> None:
        if not self.ws:
            raise RuntimeError("websocket not connected")

        table_name = _table_name_for_ticker(market_ticker)
        _ensure_capture_table(table_name)

        if self.current_ticker is None:
            await self._send(
                {
                    "id": self.command_id,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_ticker": market_ticker,
                    },
                }
            )
        else:
            # Prefer in-place subscription update on the same channel connection.
            await self._send(
                {
                    "id": self.command_id,
                    "cmd": "update_subscription",
                    "params": {
                        "sids": [self.current_sid] if self.current_sid else [],
                        "market_tickers": [market_ticker],
                        "delete_markets": [self.current_ticker],
                    },
                }
            )

        self.current_ticker = market_ticker
        self.current_table = table_name
        self.log.info("subscribed ticker=%s table=testing.%s", market_ticker, table_name)

    async def _maybe_rollover(self) -> None:
        latest = current_btc_15m_ticker()
        if not latest:
            return
        if self.current_ticker is None:
            await self.subscribe_ticker(latest)
            return
        if latest != self.current_ticker:
            self.log.info("rollover detected old=%s new=%s", self.current_ticker, latest)
            await self.subscribe_ticker(latest)

    async def run(self) -> None:
        await self.connect()
        # Wait for first resolvable ticker.
        while True:
            t = current_btc_15m_ticker()
            if t:
                await self.subscribe_ticker(t)
                break
            self.log.warning("no BTC 15m ticker yet in live_data.market_kalshi_15m; retrying")
            await asyncio.sleep(2)

        last_roll_check = 0.0
        while True:
            if not self.ws:
                raise RuntimeError("websocket disconnected")
            raw = await self.ws.recv()
            now = time.time()
            if now - last_roll_check >= ROLL_CHECK_SEC:
                await self._maybe_rollover()
                last_roll_check = now

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            # Keep sid for update_subscription rollover path.
            if payload.get("type") == "subscribed":
                msg = payload.get("msg") or {}
                if isinstance(msg, dict) and msg.get("sid") is not None:
                    try:
                        self.current_sid = int(msg["sid"])
                    except Exception:
                        self.current_sid = None
                continue

            # Persist only payloads in the requested 4-column shape.
            if all(k in payload for k in ("type", "sid", "seq", "msg")) and self.current_table:
                _insert_raw_message(self.current_table, payload)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    exp = Orderbook15mExperiment()
    while True:
        try:
            asyncio.run(exp.run())
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            logging.getLogger("orderbook_15m_experiment").warning(
                "run loop error: %s (retrying in 3s)", e
            )
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())

