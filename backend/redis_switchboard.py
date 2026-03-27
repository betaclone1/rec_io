"""
Redis switchboard: LISTEN to PostgreSQL NOTIFY, publish to Redis, fan out to WebSocket clients.

SCOPE (anti-bloat): This process does exactly: (1) LISTEN rec_io_db_changes,
(2) map (schema, table) -> stream name via stream_registry, (3) publish one JSON
to Redis rec_io:db_changes, (4) fan out to /ws/db_changes clients. Plus /health.
Do NOT add application HTTP APIs, auth, or per-stream logic here. New capabilities
= new streams (registry + trigger) or new services. See docs/REALTIME_BACKBONE.md
Section 0. The only allowed HTTP surface is /health and /ws/db_changes; pilot
endpoints (/api/redis_basic_test, /redis-basic-test, /api/strike_table_15m_latest,
/strike-table-15m-test) are temporary for testing.

Run: python -m backend.redis_switchboard
Config (env): REDIS_URL or REDIS_HOST+REDIS_PORT; SWITCHBOARD_*; PG_NOTIFY_CHANNEL;
REDIS_CHANNEL_DB_CHANGES; DB via get_postgresql_connection (LISTEN).
"""

import os
import sys
import json
import logging
import select
import threading
import queue
import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

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
from backend.core.stream_registry import get_table_to_stream
TABLE_TO_DATABASE = get_table_to_stream()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [redis_switchboard] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("redis_switchboard")

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


def pg_listen_loop():
    """Run in a thread: LISTEN to PostgreSQL, on notify build db_change message and publish to Redis."""
    try:
        import psycopg2.extensions
        from backend.core.config.database import get_postgresql_connection
        conn = get_postgresql_connection()
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
                    op = payload.get("op", "UNKNOWN")
                    key = (str(schema).lower(), str(table).lower()) if schema and table else None
                    db_name = TABLE_TO_DATABASE.get(key) if key else None
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
                    try:
                        r.publish(REDIS_CHANNEL_DB_CHANGES, json.dumps(msg))
                        logger.info("Published db_change %s -> Redis", db_name)
                    except Exception as re:
                        logger.warning("Redis publish failed: %s", re)
                except Exception as e:
                    logger.warning("Error handling NOTIFY: %s", e)
    except Exception as e:
        logger.warning("PG listen thread exited: %s", e)


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
    from backend.core.config.database import get_postgresql_connection
    return get_postgresql_connection()


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
    ROUND((yes_ask_dollars::numeric * 100)::numeric, 2) AS yes_ask,
    ROUND((no_ask_dollars::numeric * 100)::numeric, 2) AS no_ask,
    yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    ticker, active_side, volume, open_interest,
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
