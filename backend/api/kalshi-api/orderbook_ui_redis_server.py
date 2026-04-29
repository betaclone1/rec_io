#!/usr/bin/env python3
"""
Redis-backed orderbook UI for Kalshi 15m experiment.

Reads live book state from:
  - key: testing:orderbook_ui:current

Presentation lives in frontend/styles/orderbook-redis-ui.css (+ global.css);
behavior in frontend/js/orderbook-redis-ui.js. This module serves HTML, API,
and static /styles /js from the repo frontend/ tree (same layout as main app).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "frontend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.trading_redis_comms import redis_client_optional

REDIS_ORDERBOOK_KEY = "testing:orderbook_ui:current"

app = FastAPI(title="Orderbook Redis UI", version="1.0")

app.mount(
    "/styles",
    StaticFiles(directory=str(FRONTEND / "styles")),
    name="orderbook_styles",
)
app.mount(
    "/js",
    StaticFiles(directory=str(FRONTEND / "js")),
    name="orderbook_js",
)
app.mount(
    "/tabs",
    StaticFiles(directory=str(FRONTEND / "tabs")),
    name="orderbook_tabs",
)


def _read_orderbook_payload() -> dict:
    r = redis_client_optional()
    if r is None:
        return {"error": "redis_unavailable"}
    raw = r.get(REDIS_ORDERBOOK_KEY)
    if not raw:
        return {"error": "no_data"}
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {"error": "invalid_payload"}


@app.get("/api/orderbook")
def api_orderbook() -> JSONResponse:
    return JSONResponse(_read_orderbook_payload())


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Orderbook (Redis)</title>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans&display=swap" rel="stylesheet"/>
  <link rel="stylesheet" href="/styles/global.css"/>
  <link rel="stylesheet" href="/styles/orderbook-redis-ui.css"/>
</head>
<body class="orderbook-redis-ui">
  <div class="meta u-hidden" id="meta"></div>
  <div id="loadErr" class="load-err u-hidden"></div>
  <div class="mkt-head" id="mktHead">
    <div class="mkt-icon" aria-hidden="true">₿</div>
    <div class="mkt-text">
      <p class="mkt-title" id="mktTitle">—</p>
      <p class="mkt-window" id="mktWindow"></p>
    </div>
  </div>
  <div class="quote-row" id="quoteRow" onclick="toggleOrderbook()">
    <div class="quote-strike" id="quoteStrike">—</div>
    <div class="tabs">
      <div class="tab active tab-yes" id="tabYes" onclick="setMode(event, 'yes')">Yes —</div>
      <div class="tab tab-no" id="tabNo" onclick="setMode(event, 'no')">No —</div>
    </div>
  </div>
  <div class="panel" id="bookPanel">
    <table class="book-table panel-head">
      <colgroup><col class="side"/><col class="price"/><col class="contracts"/><col class="total"/></colgroup>
      <thead><tr><th></th><th>Price</th><th>Contracts</th><th>Total</th></tr></thead>
    </table>
    <div class="panel-scroll" id="bookScroll">
    <table class="book-table">
      <colgroup><col class="side"/><col class="price"/><col class="contracts"/><col class="total"/></colgroup>
      <tbody id="asks" class="asks"></tbody>
      <tbody>
        <tr><td colspan="4" id="midPrice" class="mid-row mid-yes"></td></tr>
      </tbody>
      <tbody id="bids" class="bids"></tbody>
    </table>
    </div>
  </div>
  <script src="/js/orderbook-redis-ui.js"></script>
</body>
</html>
"""
    return HTMLResponse(html)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8091, log_level="info")
