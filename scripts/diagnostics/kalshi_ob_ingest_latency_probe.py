#!/usr/bin/env python3
"""A/B probe: Kalshi orderbook WS delivery vs our market_watchdog ingest lag.

Chief question
--------------
When ``source_age_ms`` / sending→handler is hundreds–thousands of ms, is that:

  A) Kalshi/network (message already old when it first hits an idle WS client), or
  B) Our ingest (idle client is fresh; watchdog stamps the same seq late)?

Method
------
1. Open a **minimal** second Kalshi WS (orderbook_delta only, ``update_interval_ms=0``)
   for the target ticker(s). Stamp ``t_raw_recv_ms`` at the first line after
   ``async for raw in ws`` — before JSON parse / any other work.
2. In parallel, listen to ``rec_io:live_state:updated`` for watchdog orderbook
   publishes and/or poll Redis books; capture watchdog ``t_ws_recv_ms``,
   ``t_apply_ms``, ``redis_written_ms`` keyed by ``(market_ticker, seq)``.
3. Match probe samples to watchdog samples on ``(ticker, seq)``.
4. Also measure probe event-loop overruns (10ms sleep) as a sanity check that
   the probe itself is not stalled.

Verdict (matched samples)
-------------------------
- High probe ``sending→raw`` and low ``watchdog_extra`` → upstream (Kalshi/net).
- Low probe ``sending→raw`` and high ``watchdog_extra`` → our watchdog path.
- Both high → both.

Usage (prod, read-only vs trading — second WS subscribe only)::

  PYTHONPATH=$(pwd) venv/bin/python \\
    scripts/diagnostics/kalshi_ob_ingest_latency_probe.py --seconds 60

  PYTHONPATH=$(pwd) venv/bin/python \\
    scripts/diagnostics/kalshi_ob_ingest_latency_probe.py \\
      --tickers KXBTC15M-26NOV022230-30 --seconds 45 --json-out /tmp/ob_lag.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Set, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import websockets

from backend.core.live_state_cache import UPDATED_CHANNEL, redis_client_optional
from backend.core.market_watchdog.venues.kalshi.auth import (
    load_kalshi_credentials_from_disk,
)
from backend.core.market_watchdog.venues.kalshi.ws_ingest import (
    WS_URL,
    _ws_headers,
)
from backend.core.trade_monitor_live_orderbook_payload import (
    trade_monitor_orderbook_redis_key,
)
from backend.core.upper_tail_orderbook_watch import get_upper_tail_orderbook_watch

# Kalshi orderbook ``seq`` is monotonic *per websocket subscription*, so a
# second probe socket cannot join watchdog on seq. Join on venue send time.
Key = Tuple[str, int]  # (market_ticker, sending_ts_ms)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _opt_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pct(xs: Sequence[float], p: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    idx = min(len(s) - 1, max(0, int(round((len(s) - 1) * p))))
    return float(s[idx])


def _summary(xs: Sequence[float]) -> Dict[str, Any]:
    if not xs:
        return {"n": 0}
    s = [float(x) for x in xs]
    return {
        "n": len(s),
        "min": round(min(s), 1),
        "p50": round(_pct(s, 0.50) or 0.0, 1),
        "p90": round(_pct(s, 0.90) or 0.0, 1),
        "p99": round(_pct(s, 0.99) or 0.0, 1),
        "max": round(max(s), 1),
        "mean": round(statistics.fmean(s), 1),
    }


@dataclass
class ProbeSample:
    market_ticker: str
    seq: Optional[int]
    dtype: str
    venue_ts_ms: Optional[int]
    sending_ts_ms: int
    t_raw_recv_ms: int
    t_after_json_ms: int


@dataclass
class WatchSample:
    market_ticker: str
    seq: Optional[int]
    venue_ts_ms: Optional[int]
    sending_ts_ms: int
    t_ws_recv_ms: Optional[int]
    t_apply_ms: Optional[int]
    redis_written_ms: Optional[int]
    source: str  # pubsub | redis_poll
    t_observe_ms: int


@dataclass
class MatchRow:
    market_ticker: str
    sending_ts_ms: int
    seq_probe: Optional[int]
    seq_watch: Optional[int]
    sending_to_probe_raw_ms: Optional[float]
    sending_to_watch_ws_ms: Optional[float]
    sending_to_redis_ms: Optional[float]
    venue_to_probe_raw_ms: Optional[float]
    watchdog_extra_ms: Optional[float]  # watch_ws - probe_raw (same sending clock)
    apply_to_redis_ms: Optional[float]
    probe_json_ms: float


@dataclass
class ProbeState:
    tickers: Set[str]
    probe_by_key: Dict[Key, ProbeSample] = field(default_factory=dict)
    watch_by_key: Dict[Key, WatchSample] = field(default_factory=dict)
    loop_overruns_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=20000))
    probe_n: int = 0
    watch_n: int = 0
    stop_at: float = 0.0


def _resolve_tickers(raw: str) -> List[str]:
    raw = (raw or "auto").strip()
    if raw and raw.lower() != "auto":
        return [t.strip() for t in raw.split(",") if t.strip()]
    watched = sorted(get_upper_tail_orderbook_watch() or [])
    if watched:
        return watched
    raise SystemExit(
        "No tickers: pass --tickers or ensure upper_tail orderbook watch is armed"
    )


def _ingest_watch_payload(state: ProbeState, payload: dict[str, Any], source: str) -> None:
    if str(payload.get("kind") or "") != "orderbook":
        return
    mt = str(payload.get("market_ticker") or "").strip()
    if not mt or mt not in state.tickers:
        return
    sending = _opt_int(payload.get("sending_ts_ms"))
    if sending is None:
        return
    key = (mt, sending)
    if key in state.watch_by_key:
        return
    state.watch_by_key[key] = WatchSample(
        market_ticker=mt,
        seq=_opt_int(payload.get("book_seq", payload.get("seq"))),
        venue_ts_ms=_opt_int(payload.get("venue_ts_ms")),
        sending_ts_ms=sending,
        t_ws_recv_ms=_opt_int(payload.get("t_ws_recv_ms")),
        t_apply_ms=_opt_int(payload.get("t_apply_ms")),
        redis_written_ms=_opt_int(payload.get("redis_written_ms")),
        source=source,
        t_observe_ms=_now_ms(),
    )
    state.watch_n += 1


async def _loop_lag_task(state: ProbeState) -> None:
    interval = 0.01
    while time.time() < state.stop_at:
        t0 = time.perf_counter()
        await asyncio.sleep(interval)
        over = (time.perf_counter() - t0 - interval) * 1000.0
        state.loop_overruns_ms.append(max(0.0, over))


async def _pubsub_watch_task(state: ProbeState) -> None:
    r = redis_client_optional()
    if not r:
        print("WARN: redis unavailable; pubsub watch disabled", flush=True)
        return
    ps = r.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(UPDATED_CHANNEL)
    try:
        while time.time() < state.stop_at:
            msg = await asyncio.to_thread(ps.get_message, True, 0.05)
            if not msg or msg.get("type") != "message":
                continue
            data = msg.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            try:
                payload = json.loads(data)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                _ingest_watch_payload(state, payload, "pubsub")
    finally:
        try:
            ps.close()
        except Exception:
            pass


async def _redis_poll_task(state: ProbeState) -> None:
    r = redis_client_optional()
    if not r:
        return
    last: Dict[str, Optional[int]] = {mt: None for mt in state.tickers}
    while time.time() < state.stop_at:
        for mt in list(state.tickers):
            try:
                raw = r.get(trade_monitor_orderbook_redis_key(mt))
            except Exception:
                continue
            if not raw:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            seq = _opt_int(data.get("seq"))
            if seq is None or seq == last.get(mt):
                continue
            last[mt] = seq
            _ingest_watch_payload(
                state,
                {
                    "kind": "orderbook",
                    "market_ticker": mt,
                    "book_seq": seq,
                    "venue_ts_ms": data.get("venue_ts_ms"),
                    "sending_ts_ms": data.get("sending_ts_ms"),
                    "t_ws_recv_ms": data.get("t_ws_recv_ms"),
                    "t_apply_ms": data.get("t_apply_ms"),
                    "redis_written_ms": data.get("redis_written_ms"),
                },
                "redis_poll",
            )
        await asyncio.sleep(0.005)


async def _minimal_ws_task(state: ProbeState) -> None:
    headers = await asyncio.to_thread(_ws_headers)
    tickers = sorted(state.tickers)
    async with websockets.connect(
        WS_URL,
        additional_headers=headers,
        ping_interval=30,
        ping_timeout=120,
        max_queue=1024,
    ) as ws:
        await ws.send(
            json.dumps(
                {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": tickers,
                        "update_interval_ms": 0,
                    },
                }
            )
        )
        print(
            "probe WS subscribed orderbook_delta update_interval_ms=0 tickers=%s"
            % tickers,
            flush=True,
        )
        async for raw in ws:
            t_raw = _now_ms()
            if time.time() >= state.stop_at:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t_json = _now_ms()
            dtype = str(data.get("type") or "")
            if dtype not in ("orderbook_snapshot", "orderbook_delta"):
                continue
            msg = data.get("msg") or {}
            mt = str(msg.get("market_ticker") or "").strip()
            if not mt or mt not in state.tickers:
                continue
            sending = _opt_int(data.get("sending_ts_ms"))
            if sending is None:
                continue
            key = (mt, sending)
            if key in state.probe_by_key:
                continue
            state.probe_by_key[key] = ProbeSample(
                market_ticker=mt,
                seq=_opt_int(data.get("seq")),
                dtype=dtype,
                venue_ts_ms=_opt_int(msg.get("ts_ms")),
                sending_ts_ms=sending,
                t_raw_recv_ms=t_raw,
                t_after_json_ms=t_json,
            )
            state.probe_n += 1


def _build_matches(state: ProbeState) -> List[MatchRow]:
    rows: List[MatchRow] = []
    for key, probe in state.probe_by_key.items():
        watch = state.watch_by_key.get(key)
        if not watch:
            continue
        snd = probe.sending_ts_ms
        venue = probe.venue_ts_ms
        if venue is None:
            venue = watch.venue_ts_ms
        send_to_probe = float(probe.t_raw_recv_ms - snd)
        send_to_watch = (
            float(watch.t_ws_recv_ms - snd) if watch.t_ws_recv_ms is not None else None
        )
        send_to_redis = (
            float(watch.redis_written_ms - snd)
            if watch.redis_written_ms is not None
            else None
        )
        venue_to_probe = (
            float(probe.t_raw_recv_ms - venue) if venue is not None else None
        )
        extra = None
        if send_to_watch is not None:
            extra = send_to_watch - send_to_probe
        apply_to_redis = None
        if watch.t_apply_ms is not None and watch.redis_written_ms is not None:
            apply_to_redis = float(watch.redis_written_ms - watch.t_apply_ms)
        rows.append(
            MatchRow(
                market_ticker=probe.market_ticker,
                sending_ts_ms=snd,
                seq_probe=probe.seq,
                seq_watch=watch.seq,
                sending_to_probe_raw_ms=send_to_probe,
                sending_to_watch_ws_ms=send_to_watch,
                sending_to_redis_ms=send_to_redis,
                venue_to_probe_raw_ms=venue_to_probe,
                watchdog_extra_ms=extra,
                apply_to_redis_ms=apply_to_redis,
                probe_json_ms=float(probe.t_after_json_ms - probe.t_raw_recv_ms),
            )
        )
    return rows


def _verdict(matches: List[MatchRow], loop_summary: Dict[str, Any]) -> Dict[str, Any]:
    probe_lags = [
        m.sending_to_probe_raw_ms
        for m in matches
        if m.sending_to_probe_raw_ms is not None
    ]
    extras = [
        m.watchdog_extra_ms for m in matches if m.watchdog_extra_ms is not None
    ]
    p50_probe = _pct(probe_lags, 0.50) if probe_lags else None
    p50_extra = _pct(extras, 0.50) if extras else None
    # Thresholds: <75ms = "fresh enough"; >=250ms = material lag.
    fresh = 75.0
    material = 250.0
    if p50_probe is None or p50_extra is None:
        label = "inconclusive_insufficient_matches"
        detail = "Need matched (ticker, seq) samples from probe WS and watchdog publish."
    elif p50_probe >= material and p50_extra < fresh:
        label = "upstream_kalshi_or_network"
        detail = (
            "Idle probe already sees material sending→recv lag; watchdog adds little."
        )
    elif p50_probe < fresh and p50_extra >= material:
        label = "our_watchdog_ingest"
        detail = (
            "Idle probe is fresh; watchdog handler/redis path is late on the same seq."
        )
    elif p50_probe >= material and p50_extra >= material:
        label = "both_upstream_and_our_ingest"
        detail = "Upstream delivery is slow and watchdog adds more delay on top."
    elif p50_probe < fresh and p50_extra < fresh:
        label = "path_healthy_in_window"
        detail = "In this window both probe and watchdog look fresh vs sending_ts."
    else:
        label = "mixed_borderline"
        detail = "Lags sit between fresh and material thresholds; extend --seconds."
    loop_p99 = loop_summary.get("p99")
    if isinstance(loop_p99, (int, float)) and loop_p99 >= 50:
        detail += " Probe event-loop p99 overrun is elevated; re-run on a quiet host."
    return {
        "label": label,
        "detail": detail,
        "p50_sending_to_probe_ms": None if p50_probe is None else round(p50_probe, 1),
        "p50_watchdog_extra_ms": None if p50_extra is None else round(p50_extra, 1),
        "thresholds_ms": {"fresh_lt": fresh, "material_gte": material},
    }


async def _run(seconds: float, tickers: List[str]) -> Dict[str, Any]:
    state = ProbeState(tickers=set(tickers), stop_at=time.time() + seconds)
    print(
        "starting probe seconds=%s tickers=%s" % (seconds, tickers),
        flush=True,
    )
    tasks = [
        asyncio.create_task(_loop_lag_task(state)),
        asyncio.create_task(_pubsub_watch_task(state)),
        asyncio.create_task(_redis_poll_task(state)),
        asyncio.create_task(_minimal_ws_task(state)),
    ]
    await asyncio.sleep(seconds)
    state.stop_at = time.time()  # signal exit
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    matches = _build_matches(state)
    by_sym: Dict[str, List[MatchRow]] = defaultdict(list)
    for m in matches:
        by_sym[m.market_ticker.split("-")[0]].append(m)

    loop_summary = _summary(list(state.loop_overruns_ms))
    out: Dict[str, Any] = {
        "seconds": seconds,
        "tickers": tickers,
        "probe_messages": state.probe_n,
        "watch_messages": state.watch_n,
        "matched": len(matches),
        "probe_sending_to_raw_ms": _summary(
            [
                float(p.t_raw_recv_ms - p.sending_ts_ms)
                for p in state.probe_by_key.values()
                if p.sending_ts_ms is not None
            ]
        ),
        "matched_sending_to_probe_raw_ms": _summary(
            [
                m.sending_to_probe_raw_ms
                for m in matches
                if m.sending_to_probe_raw_ms is not None
            ]
        ),
        "matched_sending_to_watch_ws_ms": _summary(
            [
                m.sending_to_watch_ws_ms
                for m in matches
                if m.sending_to_watch_ws_ms is not None
            ]
        ),
        "matched_watchdog_extra_ms": _summary(
            [m.watchdog_extra_ms for m in matches if m.watchdog_extra_ms is not None]
        ),
        "matched_apply_to_redis_ms": _summary(
            [m.apply_to_redis_ms for m in matches if m.apply_to_redis_ms is not None]
        ),
        "probe_event_loop_overrun_ms": loop_summary,
        "by_symbol": {
            sym: {
                "n": len(rows),
                "sending_to_probe_raw_ms": _summary(
                    [
                        m.sending_to_probe_raw_ms
                        for m in rows
                        if m.sending_to_probe_raw_ms is not None
                    ]
                ),
                "watchdog_extra_ms": _summary(
                    [
                        m.watchdog_extra_ms
                        for m in rows
                        if m.watchdog_extra_ms is not None
                    ]
                ),
            }
            for sym, rows in sorted(by_sym.items())
        },
        "verdict": _verdict(matches, loop_summary),
        "worst_watchdog_extra": [
            asdict(m)
            for m in sorted(
                (m for m in matches if m.watchdog_extra_ms is not None),
                key=lambda m: m.watchdog_extra_ms or 0.0,
                reverse=True,
            )[:8]
        ],
        "worst_probe_sending_lag": [
            asdict(m)
            for m in sorted(
                (m for m in matches if m.sending_to_probe_raw_ms is not None),
                key=lambda m: m.sending_to_probe_raw_ms or 0.0,
                reverse=True,
            )[:8]
        ],
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--tickers",
        default="auto",
        help="Comma tickers, or 'auto' = current upper_tail orderbook watch",
    )
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--json-out", default="", help="Optional path for full JSON report")
    args = ap.parse_args()
    load_kalshi_credentials_from_disk()
    tickers = _resolve_tickers(args.tickers)
    report = asyncio.run(_run(float(args.seconds), tickers))
    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.json_out:
        path = Path(args.json_out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print("wrote", path, flush=True)
    v = report.get("verdict") or {}
    print(
        "\nVERDICT: %s | probe_p50=%s ms | watchdog_extra_p50=%s ms\n%s"
        % (
            v.get("label"),
            v.get("p50_sending_to_probe_ms"),
            v.get("p50_watchdog_extra_ms"),
            v.get("detail"),
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
