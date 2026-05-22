#!/usr/bin/env python3
"""
Sandbox monitor for kalshi_market_ws_master.py — reads sandbox:kalshi:* Redis only.

Run (with ws master already running):
  python scripts/sandbox/kalshi_market_feed/kalshi_market_feed_monitor.py

Env: REDIS_URL / REDIS_HOST, SANDBOX_KALSHI_REDIS_PREFIX (default sandbox:kalshi:)
Port: SANDBOX_KALSHI_MONITOR_PORT default 8791

UI: /styles/global.css, /styles/sandbox-kalshi-monitor.css, /js/orderbook-redis-ui.js
Live stream via WebSocket /ws/feed (Redis pub/sub from ws master — no poll loops).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Optional

HealthLevel = Literal["ok", "warn", "dead"]

# Staleness thresholds (seconds) — monitor flags before Redis meta TTL (~120s).
META_STALE_SEC = float(os.getenv("SANDBOX_KALSHI_HEALTH_META_STALE_SEC", "30"))
WS_MSG_STALE_SEC = float(os.getenv("SANDBOX_KALSHI_HEALTH_WS_STALE_SEC", "90"))

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "frontend"
FRONTEND_STYLES = FRONTEND / "styles"
FRONTEND_JS = FRONTEND / "js"
REDIS_PREFIX = os.getenv("SANDBOX_KALSHI_REDIS_PREFIX", "sandbox:kalshi:").strip()
MONITOR_PORT = int(os.getenv("SANDBOX_KALSHI_MONITOR_PORT", "8791"))

_ws_clients: dict[WebSocket, str] = {}


def _push_channel() -> str:
    return f"{REDIS_PREFIX}push:v1"


def _build_feed_payload(selected_ticker: str) -> dict[str, Any]:
    meta = _json_get(_rkey_meta()) or {}
    pick = _resolve_ticker(meta, selected_ticker or None)
    ob = build_live_orderbook_payload(pick) if pick else None
    return {
        "type": "feed",
        "meta": meta,
        "health": compute_feed_health(meta),
        "active_ticker": pick,
        "orderbook": ob,
    }


async def _ws_send_feed(ws: WebSocket, ticker: str) -> None:
    await ws.send_text(json.dumps(_build_feed_payload(ticker), default=str))


async def _broadcast_meta() -> None:
    meta = _json_get(_rkey_meta()) or {}
    health = compute_feed_health(meta)
    msg = json.dumps({"type": "meta", "meta": meta, "health": health}, default=str)
    dead: list[WebSocket] = []
    for ws in list(_ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.pop(ws, None)


async def _redis_pubsub_loop() -> None:
    """Block on Redis pub/sub (event-driven, not a poll interval)."""
    r = _redis()
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(_push_channel())
    while True:
        raw = await asyncio.to_thread(pubsub.get_message, timeout=None)
        if not raw or raw.get("type") != "message":
            continue
        try:
            hint = json.loads(raw["data"])
        except (TypeError, json.JSONDecodeError, KeyError):
            continue
        kind = str(hint.get("kind") or "")
        if kind == "meta":
            await _broadcast_meta()
            continue
        if kind not in ("orderbook", "ticker"):
            continue
        mt = str(hint.get("market_ticker") or "").strip()
        if not mt:
            continue
        dead: list[WebSocket] = []
        for ws, watched in list(_ws_clients.items()):
            if watched != mt:
                continue
            try:
                await _ws_send_feed(ws, watched)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_clients.pop(ws, None)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    task = asyncio.create_task(_redis_pubsub_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Kalshi market feed monitor", lifespan=_lifespan)
if FRONTEND_STYLES.is_dir():
    app.mount("/styles", StaticFiles(directory=str(FRONTEND_STYLES)), name="styles")
if FRONTEND_JS.is_dir():
    app.mount("/js", StaticFiles(directory=str(FRONTEND_JS)), name="js")


def _redis():
    import redis

    url = os.getenv("REDIS_URL", "").strip()
    if url:
        return redis.from_url(url, decode_responses=True)
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
    )


def _sanitize(mt: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_]+", "_", mt.strip()).strip("_").lower()
    return t[:50] if t else "unknown"


def _rkey_meta() -> str:
    return f"{REDIS_PREFIX}meta:v1"


def _rkey_orderbook(mt: str) -> str:
    return f"{REDIS_PREFIX}orderbook:v1:{_sanitize(mt)}"


def _rkey_ticker(mt: str) -> str:
    return f"{REDIS_PREFIX}ticker:v1:{_sanitize(mt)}"


def _json_get(key: str) -> Any:
    raw = _redis().get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _d(v: Any) -> Decimal:
    return Decimal(str(v))


def _fmt(v: Decimal, q: str = "0.0000") -> str:
    return str(v.quantize(Decimal(q)))


def _last_trade_from_ticker(tq: dict[str, Any]) -> dict[str, str]:
    lp = tq.get("last_price_dollars") or tq.get("price")
    if lp is None or str(lp).strip() == "":
        yb = tq.get("yes_bid_dollars")
        ya = tq.get("yes_ask_dollars")
        try:
            if yb is not None and ya is not None:
                lp = (Decimal(str(yb)) + Decimal(str(ya))) / 2
            elif yb is not None:
                lp = yb
            elif ya is not None:
                lp = ya
        except Exception:
            lp = None
    yes_cents = ""
    no_cents = ""
    if lp is None or str(lp).strip() == "":
        return {"yes_cents": yes_cents, "no_cents": no_cents}
    try:
        d_yes = Decimal(str(lp).strip())
        qy = (d_yes * Decimal("100")).quantize(Decimal("0.01"))
        sy = str(qy).rstrip("0").rstrip(".") if "." in str(qy) else str(qy)
        yes_cents = f"{sy}¢"
        d_no = (Decimal("1") - d_yes).quantize(Decimal("0.0001"))
        qn = (d_no * Decimal("100")).quantize(Decimal("0.01"))
        sn = str(qn).rstrip("0").rstrip(".") if "." in str(qn) else str(qn)
        no_cents = f"{sn}¢"
    except Exception:
        pass
    return {"yes_cents": yes_cents, "no_cents": no_cents}


def _book_rows_all_levels(
    levels: dict[Decimal, Decimal], *, is_ask: bool
) -> list[dict[str, str]]:
    prices = sorted(p for p, sz in levels.items() if sz > 0)
    if not prices:
        return []
    if is_ask:
        display = list(reversed(prices))
        touch = prices
    else:
        display = list(reversed(prices))
        touch = sorted(prices, reverse=True)
    cum: dict[Decimal, Decimal] = {}
    run = Decimal("0")
    for p in touch:
        run += p * levels[p]
        cum[p] = run
    return [
        {
            "price": _fmt(p),
            "size_fp": _fmt(levels[p], "0.01"),
            "total_dollars": _fmt(cum[p], "0.01"),
        }
        for p in display
    ]


def _touch_from_trade_book(book: dict[str, Any]) -> dict[str, Optional[str]]:
    """Best bid = highest bid row; best ask = lowest ask row (trade_yes / trade_no layout)."""
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    return {
        "best_bid_dollars": bids[0]["price"] if bids else None,
        "best_ask_dollars": asks[-1]["price"] if asks else None,
    }


def _price_decimal(v: Any) -> Optional[Decimal]:
    if v is None or str(v).strip() == "":
        return None
    try:
        return Decimal(str(v).strip())
    except Exception:
        return None


def _compare_prices(ticker_val: Any, ob_val: Any) -> dict[str, Any]:
    t = _price_decimal(ticker_val)
    o = _price_decimal(ob_val)
    if t is None or o is None:
        return {"match": None, "delta_cents": None}
    delta = (o - t) * Decimal("100")
    q = delta.quantize(Decimal("0.01"))
    return {"match": abs(delta) < Decimal("0.0001"), "delta_cents": str(q)}


def _complement(levels: dict[Decimal, Decimal]) -> dict[Decimal, Decimal]:
    out: dict[Decimal, Decimal] = {}
    for p, sz in levels.items():
        cp = Decimal("1") - p
        out[cp] = out.get(cp, Decimal("0")) + sz
    return out


def build_live_orderbook_payload(market_ticker: str) -> Optional[dict[str, Any]]:
    data = _json_get(_rkey_orderbook(market_ticker))
    if not data or data.get("valid") is False:
        return None
    yes: dict[Decimal, Decimal] = {}
    no: dict[Decimal, Decimal] = {}
    for p, s in (data.get("yes") or {}).items():
        try:
            yes[_d(p)] = _d(s)
        except Exception:
            pass
    for p, s in (data.get("no") or {}).items():
        try:
            no[_d(p)] = _d(s)
        except Exception:
            pass
    if not yes and not no:
        return None
    tq = _json_get(_rkey_ticker(market_ticker)) or {}
    trade_yes = {
        "asks": _book_rows_all_levels(_complement(no), is_ask=True),
        "bids": _book_rows_all_levels(yes, is_ask=False),
    }
    trade_no = {
        "asks": _book_rows_all_levels(_complement(yes), is_ask=True),
        "bids": _book_rows_all_levels(no, is_ask=False),
    }
    touch_yes = _touch_from_trade_book(trade_yes)
    touch_no = _touch_from_trade_book(trade_no)
    return {
        "type": "live_orderbook",
        "market_ticker": market_ticker,
        "book_seq": data.get("seq"),
        "last_trade": _last_trade_from_ticker(tq),
        "trade_yes": trade_yes,
        "trade_no": trade_no,
        "ticker_quote": tq,
        "ob_touch_yes": touch_yes,
        "ob_touch_no": touch_no,
        "compare_yes": {
            "yes_bid": _compare_prices(tq.get("yes_bid_dollars"), touch_yes.get("best_bid_dollars")),
            "yes_ask": _compare_prices(tq.get("yes_ask_dollars"), touch_yes.get("best_ask_dollars")),
        },
        "compare_no": {
            "no_bid": _compare_prices(tq.get("no_bid_dollars"), touch_no.get("best_bid_dollars")),
            "no_ask": _compare_prices(tq.get("no_ask_dollars"), touch_no.get("best_ask_dollars")),
        },
    }


def _wall_age_sec(h: dict[str, Any], key: str, now: float) -> Optional[float]:
    raw = h.get(key)
    if raw is None:
        return None
    try:
        ts = float(raw)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return max(0.0, now - ts)


def _stream_stale_sec(h: dict[str, Any], now: float) -> Optional[float]:
    """Recompute from wall-clock stamps written by ws master (never frozen snapshot ages)."""
    book = _wall_age_sec(h, "last_book_wall_at", now)
    if book is not None:
        return book
    return _wall_age_sec(h, "last_ticker_wall_at", now)


def _ticker_health_level(
    h: dict[str, Any],
    *,
    ws_connected: bool,
) -> tuple[HealthLevel, str]:
    """Subscription health only: socket down = dead; valid book on active sub = live."""
    if not ws_connected:
        return "dead", "ws_down"
    if not h:
        return "warn", "warming"
    if not h.get("valid"):
        return "warn", "awaiting_snapshot"
    return "ok", "live"


def compute_feed_health(meta: dict[str, Any]) -> dict[str, Any]:
    """Real-time subscription health from ws master meta (evaluated at poll time)."""
    now = time.time()
    meta_at = meta.get("meta_updated_at")
    meta_age: Optional[float] = None
    if meta_at is not None:
        try:
            meta_age = round(now - float(meta_at), 2)
        except (TypeError, ValueError):
            meta_age = None

    ws_connected = bool(meta.get("ws_connected"))
    ws_age = meta.get("ws_last_msg_age_sec")
    resync_in_progress = bool(meta.get("resync_in_progress"))
    feed_issues: list[str] = []
    if meta_age is None or meta_age > META_STALE_SEC:
        feed_issues.append("meta_stale")
    if not ws_connected:
        feed_issues.append("ws_down")
    elif ws_age is None or float(ws_age) > WS_MSG_STALE_SEC:
        feed_issues.append("ws_silent")

    ws_channel_quiet = (
        ws_connected
        and (ws_age is None or float(ws_age) > WS_MSG_STALE_SEC)
    )
    subs = sorted(str(t).strip() for t in (meta.get("orderbook_subscribed") or []) if str(t).strip())
    per = meta.get("per_ticker") or {}
    ticker_sub = set(meta.get("ticker_subscribed") or [])
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {"ok": 0, "warn": 0, "dead": 0}
    for mt in subs:
        h = per.get(mt) or {}
        level, reason = _ticker_health_level(h, ws_connected=ws_connected)
        counts[level] = counts.get(level, 0) + 1
        book_age = _wall_age_sec(h, "last_book_wall_at", now)
        ticker_age = _wall_age_sec(h, "last_ticker_wall_at", now)
        rows.append(
            {
                "market_ticker": mt,
                "level": level,
                "reason": reason,
                "valid": h.get("valid"),
                "last_seq": h.get("last_seq"),
                "resync_count": h.get("resync_count"),
                "last_book_age_sec": round(book_age, 2) if book_age is not None else None,
                "last_ticker_age_sec": round(ticker_age, 2) if ticker_age is not None else None,
                "stream_stale_sec": _stream_stale_sec(h, now),
                "ticker_sub": mt in ticker_sub,
                "ob_sub": True,
            }
        )

    ticker_warn = sum(1 for r in rows if r["level"] == "warn")
    if not subs:
        if not meta_at:
            overall: HealthLevel = "warn"
            feed_issues.append("no_meta")
        elif not ws_connected:
            overall = "dead"
        else:
            overall = "warn"
            feed_issues.append("no_subs")
    elif not ws_connected:
        overall = "dead"
    elif resync_in_progress or ticker_warn > 0:
        overall = "warn"
    else:
        overall = "ok"

    return {
        "overall": overall,
        "feed_issues": feed_issues,
        "ws_channel_quiet": ws_channel_quiet,
        "resync_in_progress": resync_in_progress,
        "meta_age_sec": meta_age,
        "ws_connected": ws_connected,
        "ws_last_msg_age_sec": ws_age,
        "ob_channel_seq": meta.get("ob_channel_seq"),
        "channel_resync_count": meta.get("channel_resync_count"),
        "counts": counts,
        "subscriptions": rows,
        "thresholds": {
            "meta_stale_sec": META_STALE_SEC,
            "ws_stale_sec": WS_MSG_STALE_SEC,
        },
    }


@app.get("/api/health")
def api_health() -> JSONResponse:
    """One-shot health (UI uses WebSocket stream)."""
    meta = _json_get(_rkey_meta()) or {}
    return JSONResponse({"meta": meta, "health": compute_feed_health(meta)})


@app.websocket("/ws/feed")
async def ws_feed(websocket: WebSocket) -> None:
    await websocket.accept()
    ticker = str(websocket.query_params.get("ticker") or "").strip()
    _ws_clients[websocket] = ticker
    try:
        await _ws_send_feed(websocket, ticker)
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("select") is not None:
                ticker = str(msg.get("select") or "").strip()
                _ws_clients[websocket] = ticker
                await _ws_send_feed(websocket, ticker)
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.pop(websocket, None)


def _resolve_ticker(meta: dict[str, Any], requested: Optional[str]) -> Optional[str]:
    subs = [str(t).strip() for t in (meta.get("orderbook_subscribed") or []) if str(t).strip()]
    if requested and str(requested).strip() in subs:
        return str(requested).strip()
    return subs[0] if subs else None


@app.get("/api/feed")
def api_feed(ticker: Optional[str] = Query(None)) -> JSONResponse:
    meta = _json_get(_rkey_meta()) or {}
    pick = _resolve_ticker(meta, ticker)
    ob = build_live_orderbook_payload(pick) if pick else None
    return JSONResponse(
        {
            "meta": meta,
            "health": compute_feed_health(meta),
            "active_ticker": pick,
            "orderbook": ob,
        }
    )


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Kalshi market feed monitor</title>
  <link rel="stylesheet" href="/styles/global.css"/>
  <link rel="stylesheet" href="/styles/sandbox-kalshi-monitor.css"/>
</head>
<body class="trade-monitor-new-page">
<div class="sandbox-wrap">
  <div class="sandbox-header-row">
    <h1 class="panel-header">Kalshi market feed monitor</h1>
    <div class="ttc-chip" id="sandboxTtcClock" aria-live="polite">--:--</div>
  </div>
  <div id="feedHealthStrip" class="feed-health-strip feed-health-dead" role="status" aria-live="assertive">
    <span id="feedHealthBadge" class="feed-health-badge">—</span>
    <span id="feedHealthSummary" class="feed-health-summary">Loading feed health…</span>
    <span id="feedHealthMeta" class="feed-health-meta"></span>
  </div>
  <p class="sandbox-meta" id="status">Loading…</p>
  <div class="sandbox-ob-picker-row">
    <label class="sandbox-ob-picker-label" for="liveObSelect">View orderbook</label>
    <select id="liveObSelect" class="sandbox-ob-select"></select>
  </div>
  <p class="sandbox-meta" id="activeTicker">—</p>
  <div class="sandbox-row">
    <div class="panel-container trade-monitor-new" style="flex:2">
      <div class="panel-header">Orderbook</div>
      <div class="tm-new-orderbook-stack">
        <div id="sandboxBookHost"></div>
      </div>
    </div>
    <div class="panel-container trade-monitor-new sandbox-side-col">
      <div class="panel-header">Market ticker (WS channel)</div>
      <div id="tickerPanel"></div>
      <div class="panel-header" style="margin-top:12px">Schedule</div>
      <p class="sandbox-meta sandbox-schedule-note" id="scheduleNote">Schedule loading…</p>
      <div id="schedule" style="max-height:60vh;overflow:auto"></div>
    </div>
  </div>
  <div class="panel-container trade-monitor-new" style="margin-top:12px">
    <div class="panel-header">Subscribed tickers (live = active sub + valid book · dead = socket down)</div>
    <div id="healthGrid"></div>
  </div>
</div>
<script src="/js/orderbook-redis-ui.js"></script>
<script>
function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;'); }

function phaseClass(p) {
  if (p === 'live') return 'phase-live';
  if (p === 'outgoing') return 'phase-outgoing';
  if (p === 'settled') return 'phase-settled';
  return 'phase-upcoming';
}

function fmtResult(r) {
  if (r.market_result) return esc(r.market_result);
  if (r.phase === 'outgoing') return '<span class="result-pending">pending</span>';
  return '—';
}

let selectedOb = sessionStorage.getItem('sandboxKalshiOb') || '';
let lastPickKey = '';

function syncObPicker(meta) {
  const subs = meta.orderbook_subscribed || [];
  const key = subs.join('|');
  const sel = document.getElementById('liveObSelect');
  if (!sel) return;
  if (key !== lastPickKey) {
    lastPickKey = key;
    if (selectedOb && subs.indexOf(selectedOb) < 0) selectedOb = subs[0] || '';
    let h = '';
    for (const mt of subs) {
      h += '<option value="' + esc(mt) + '"' + (mt === selectedOb ? ' selected' : '') + '>' + esc(mt) + '</option>';
    }
    sel.innerHTML = h || '<option value="">—</option>';
    sel.parentElement.style.display = subs.length > 1 ? '' : 'none';
  } else if (selectedOb) sel.value = selectedOb;
}
document.getElementById('liveObSelect')?.addEventListener('change', function() {
  selectedOb = this.value;
  sessionStorage.setItem('sandboxKalshiOb', selectedOb);
  if (feedWs && feedWs.readyState === WebSocket.OPEN) {
    feedWs.send(JSON.stringify({ select: selectedOb }));
  }
});

function renderSchedule(rows, meta) {
  const subs = new Set(meta.orderbook_subscribed || []);
  const m15 = (rows||[]).filter(r => r.interval === '15m');
  const sorted = m15.slice().sort((a,b) => (a.close_ts||0) - (b.close_ts||0));
  const show = sorted.filter(r => r.phase !== 'dropped');
  const onSubs = show.filter(r => subs.has(r.market_ticker));
  const upcoming = show.filter(r => r.phase === 'upcoming').slice(0, 4);
  const trimmed = onSubs.length ? onSubs : upcoming;
  const note = document.getElementById('scheduleNote');
  if (note) {
    note.textContent =
      (subs.size ? subs.size + ' live OB subs' : 'no OB subs') +
      ' · schedule shows subscribed + a few upcoming 15m';
  }
  let html = '<table class="sandbox-grid"><thead><tr><th>Phase</th><th>Sym</th><th>Int</th><th>Ticker</th><th>Result</th></tr></thead><tbody>';
  for (const r of trimmed) {
    html += '<tr><td class="'+phaseClass(r.phase)+'">'+esc(r.phase)+'</td><td>'+esc(r.symbol)+'</td><td>'+esc(r.interval)+'</td><td>'+esc(r.market_ticker)+'</td><td>'+fmtResult(r)+'</td></tr>';
  }
  document.getElementById('schedule').innerHTML = html + '</tbody></table>';
}

function fmtDelta(c) {
  if (c == null || c.delta_cents == null) return '—';
  const n = Number(c.delta_cents);
  if (!Number.isFinite(n)) return '—';
  const s = (n > 0 ? '+' : '') + n.toFixed(2) + '¢';
  return s;
}

function cmpClass(c) {
  if (!c || c.match == null) return '';
  return c.match ? 'ticker-match' : 'ticker-diff';
}

function renderTickerPanel(ob) {
  const el = document.getElementById('tickerPanel');
  if (!el) return;
  if (!ob || !ob.ticker_quote) {
    el.innerHTML = '<p class="sandbox-meta">No ticker data</p>';
    return;
  }
  const tq = ob.ticker_quote || {};
  const ty = ob.ob_touch_yes || {};
  const tn = ob.ob_touch_no || {};
  const cy = ob.compare_yes || {};
  const cn = ob.compare_no || {};
  const rows = [
    ['Last trade', esc(tq.last_price_dollars || '—'), '—', '—', ''],
    ['Yes bid', esc(tq.yes_bid_dollars || '—'), esc(ty.best_bid_dollars || '—'), fmtDelta(cy.yes_bid), cmpClass(cy.yes_bid)],
    ['Yes ask', esc(tq.yes_ask_dollars || '—'), esc(ty.best_ask_dollars || '—'), fmtDelta(cy.yes_ask), cmpClass(cy.yes_ask)],
    ['No bid', esc(tq.no_bid_dollars || '—'), esc(tn.best_bid_dollars || '—'), fmtDelta(cn.no_bid), cmpClass(cn.no_bid)],
    ['No ask', esc(tq.no_ask_dollars || '—'), esc(tn.best_ask_dollars || '—'), fmtDelta(cn.no_ask), cmpClass(cn.no_ask)],
    ['Volume', esc(tq.volume_fp || '—'), '—', '—', ''],
    ['Updated', esc(tq.updated_at || '—'), 'OB seq ' + esc(ob.book_seq), '—', ''],
  ];
  let html = '<table class="sandbox-grid ticker-compare-grid"><thead><tr>' +
    '<th>Field</th><th>Ticker WS</th><th>OB touch</th><th>Δ (OB−ticker)</th></tr></thead><tbody>';
  for (const r of rows) {
    html += '<tr class="'+r[4]+'"><td>'+r[0]+'</td><td>'+r[1]+'</td><td>'+r[2]+'</td><td>'+r[3]+'</td></tr>';
  }
  html += '</tbody></table>';
  html += '<p class="sandbox-meta ticker-compare-note">OB touch = best bid/ask from live book (yes/no trade sides). Green = match ticker; red = mismatch.</p>';
  el.innerHTML = html;
}

function healthLevelClass(level) {
  if (level === 'ok') return 'health-ok';
  if (level === 'warn') return 'health-warn';
  return 'health-dead';
}

function fmtAge(sec) {
  if (sec == null || sec === '') return '—';
  const n = Number(sec);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(1) + 's';
}

let lastStableHealth = null;
let healthDeadStreak = 0;
const HEALTH_DEAD_STREAK = 2;

function healthForDisplay(health) {
  if (!health) return health;
  if (health.overall === 'dead') {
    healthDeadStreak += 1;
    if (healthDeadStreak < HEALTH_DEAD_STREAK && lastStableHealth) {
      return lastStableHealth;
    }
  } else {
    healthDeadStreak = 0;
    lastStableHealth = health;
  }
  return health;
}

function renderFeedHealth(health) {
  const strip = document.getElementById('feedHealthStrip');
  const badge = document.getElementById('feedHealthBadge');
  const summary = document.getElementById('feedHealthSummary');
  const metaEl = document.getElementById('feedHealthMeta');
  if (!strip || !health) return;
  health = healthForDisplay(health);
  const level = health.overall || 'ok';
  strip.className = 'feed-health-strip feed-health-' + level;
  const counts = health.counts || {};
  const nOk = counts.ok || 0;
  const nWarn = counts.warn || 0;
  const nDead = counts.dead || 0;
  const total = nOk + nWarn + nDead;
  if (level === 'ok') {
    badge.textContent = 'HEALTHY';
    summary.textContent = total + ' subscriptions live · WS up';
  } else if (level === 'warn') {
    badge.textContent = 'DEGRADED';
    summary.textContent = nOk + ' live · ' + nWarn + ' warming (not subscribed yet)';
  } else {
    badge.textContent = 'WS DOWN';
    const issues = (health.feed_issues || []).join(', ');
    summary.textContent = (issues ? ('feed: ' + issues + ' · ') : '') + 'socket unavailable';
  }
  const th = health.thresholds || {};
  metaEl.textContent =
    'meta ' + fmtAge(health.meta_age_sec) +
    ' · ws msg ' + fmtAge(health.ws_last_msg_age_sec) +
    ' · ch resyncs ' + (health.channel_resync_count != null ? health.channel_resync_count : '—') +
    (health.resync_in_progress ? ' · snapshot batch' : '') +
    (health.ws_channel_quiet ? ' · channel quiet (info)' : '');
}

function renderHealth(health) {
  const rows = health && health.subscriptions ? health.subscriptions : [];
  let html = '<table class="sandbox-grid health-grid"><thead><tr>' +
    '<th>Status</th><th>Ticker</th><th>Reason</th><th>book Δ</th><th>ticker Δ</th><th>seq</th><th>resyncs</th></tr></thead><tbody>';
  for (const r of rows) {
    const lvl = r.level || 'dead';
    const dot = '<span class="health-dot ' + healthLevelClass(lvl) + '" title="'+esc(r.reason||'')+'"></span>';
    html += '<tr class="health-row-' + lvl + '">' +
      '<td>' + dot + ' ' + esc(lvl.toUpperCase()) + '</td>' +
      '<td>' + esc(r.market_ticker) + '</td>' +
      '<td>' + esc(r.reason) + '</td>' +
      '<td>' + fmtAge(r.last_book_age_sec) + '</td>' +
      '<td>' + fmtAge(r.last_ticker_age_sec) + '</td>' +
      '<td>' + esc(r.last_seq) + '</td>' +
      '<td>' + esc(r.resync_count) + '</td></tr>';
  }
  if (!rows.length) {
    html += '<tr><td colspan="7" class="sandbox-meta">No subscriptions</td></tr>';
  }
  document.getElementById('healthGrid').innerHTML = html + '</tbody></table>';
}

let ttcExpireAtMs = null;
let ttcTickerKey = '';

function formatTtcClock(totalSeconds) {
  const s = Number(totalSeconds);
  if (!Number.isFinite(s) || s < 0) return '--:--';
  const whole = Math.floor(s);
  const mm = Math.floor(whole / 60);
  const ss = whole % 60;
  return String(mm).padStart(2, '0') + ':' + String(ss).padStart(2, '0');
}

function updateTtcFromSchedule(meta, ticker) {
  const t = String(ticker || '').trim();
  const el = document.getElementById('sandboxTtcClock');
  if (!el) return;
  if (!t) {
    ttcExpireAtMs = null;
    ttcTickerKey = '';
    el.textContent = '--:--';
    return;
  }
  const rows = meta.schedule || [];
  const row = rows.find(r => r.market_ticker === t && (r.phase === 'live' || r.phase === 'outgoing'))
    || rows.find(r => r.market_ticker === t);
  const closeTs = row && row.close_ts != null ? Number(row.close_ts) : NaN;
  if (!Number.isFinite(closeTs) || closeTs <= 0) {
    ttcExpireAtMs = null;
    ttcTickerKey = t;
    el.textContent = '--:--';
    return;
  }
  ttcTickerKey = t;
  ttcExpireAtMs = closeTs * 1000;
  tickTtcClock();
}

function tickTtcClock() {
  const el = document.getElementById('sandboxTtcClock');
  if (!el) return;
  if (ttcExpireAtMs == null || !Number.isFinite(ttcExpireAtMs)) {
    el.textContent = '--:--';
    return;
  }
  const sec = Math.max(0, Math.floor((ttcExpireAtMs - Date.now()) / 1000));
  el.textContent = formatTtcClock(sec);
}

function paintOrderbook(ob, ticker) {
  const host = document.getElementById('sandboxBookHost');
  const ui = window.recOrderbookRedisUi;
  if (!host || !ui) return;
  const norm = ui.normalizeOrderbookPayload(ob);
  if (!norm) {
    if (!host.querySelector('.book-panel')) host.innerHTML = '<p class="sandbox-meta">No valid orderbook</p>';
    return;
  }
  if (host.querySelector('.book-panel') && ui.patchOrderbookInto(host, norm, ticker || norm.market_ticker)) {
    return;
  }
  ui.renderOrderbookInto(host, norm, ticker || norm.market_ticker);
}

let feedWs = null;
let activeTicker = '';

function updateStatusLine(m) {
  const status = document.getElementById('status');
  if (!status) return;
  let statusLine =
    'stream ' + (feedWs && feedWs.readyState === WebSocket.OPEN ? 'live' : 'off') +
    ' · ingest WS ' + (m.ws_connected ? 'up' : 'down') +
    ' | ch seq ' + (m.ob_channel_seq != null ? m.ob_channel_seq : '—') +
    ' | ch resyncs ' + (m.channel_resync_count != null ? m.channel_resync_count : 0) +
    ' | ob sid ' + (m.orderbook_sid != null ? m.orderbook_sid : '—');
  const lr = m.last_market_result;
  if (lr && lr.market_ticker) {
    statusLine += ' | last result ' + lr.market_ticker + ' ' + (lr.market_result || '—') +
      ' (' + (lr.source || '?') + ')';
  }
  status.textContent = statusLine;
}

function applyMeta(msg) {
  const m = msg.meta || {};
  const health = msg.health || {};
  renderFeedHealth(health);
  renderHealth(healthForDisplay(health));
  if (!selectedOb && msg.active_ticker) {
    selectedOb = msg.active_ticker;
    sessionStorage.setItem('sandboxKalshiOb', selectedOb);
  }
  syncObPicker(m);
  renderSchedule(m.schedule, m);
  activeTicker = msg.active_ticker || selectedOb || '';
  document.getElementById('activeTicker').textContent = activeTicker ? ('Live: ' + activeTicker) : 'Live: —';
  updateStatusLine(m);
  if (activeTicker !== ttcTickerKey) updateTtcFromSchedule(m, activeTicker);
  else tickTtcClock();
}

function applyFeed(msg) {
  const m = msg.meta || {};
  const subs = m.orderbook_subscribed || [];
  if (selectedOb && subs.indexOf(selectedOb) < 0) {
    selectedOb = msg.active_ticker || subs[0] || '';
    sessionStorage.setItem('sandboxKalshiOb', selectedOb);
    lastPickKey = '';
    if (feedWs && feedWs.readyState === WebSocket.OPEN) {
      feedWs.send(JSON.stringify({ select: selectedOb }));
      return;
    }
  }
  applyMeta(msg);
  paintOrderbook(msg.orderbook, activeTicker);
  renderTickerPanel(msg.orderbook);
}

function connectFeedStream() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const q = selectedOb ? '?ticker=' + encodeURIComponent(selectedOb) : '';
  feedWs = new WebSocket(proto + '//' + location.host + '/ws/feed' + q);
  feedWs.onopen = function() {
    document.getElementById('status').textContent = 'stream connected — waiting for push…';
  };
  feedWs.onmessage = function(ev) {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type === 'meta') applyMeta(msg);
    else if (msg.type === 'feed') applyFeed(msg);
  };
  feedWs.onclose = function() {
    document.getElementById('status').textContent = 'stream disconnected — reconnecting…';
    window.setTimeout(connectFeedStream, 1500);
  };
  feedWs.onerror = function() {
    document.getElementById('status').textContent = 'stream error';
  };
}

connectFeedStream();
</script>
</body>
</html>"""
    )


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=MONITOR_PORT, log_level="info")


if __name__ == "__main__":
    main()
