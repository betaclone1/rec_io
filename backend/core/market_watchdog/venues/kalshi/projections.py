"""Production Redis projections from in-memory ingest (replaces sandbox:kalshi:* writes)."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import backend.core.live_state_cache as live_state_cache
from backend.core.exchange_ids import DEFAULT_EXCHANGE
from backend.core.kalshi_market_normalize import (
    KALSHI_WS_TICKER_DOLLAR_PLACES,
    normalize_kalshi_dollar_text,
)
from backend.core.market_watchdog.config import IngestConfig
from backend.core.market_watchdog.venues.kalshi.schedule import (
    clock_current_15m_ticker,
    hourly_event_ticker_for_clock,
    series_15m,
    series_hourly,
)
from backend.core.trade_monitor_orderbook_keys import trade_monitor_orderbook_redis_key

log = logging.getLogger("market_watchdog.kalshi.projections")

_OB_TTL = 7200


def _numeric_strike_from_ticker(mt: str) -> Optional[float]:
    m = re.search(r"-T([\d.]+)$", mt.strip())
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _strike_display(mt: str, floor_strike: Optional[float]) -> Optional[str]:
    if floor_strike is not None:
        return f"${floor_strike:,.2f}"
    return None


def _complement_dollar(val: Any) -> Optional[str]:
    if val is None:
        return None
    try:
        return f"{max(0.0, min(1.0, 1.0 - float(val))):.4f}"
    except (TypeError, ValueError):
        return None


def _normalize_dollar_field(val: Any) -> Optional[str]:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        s = str(val).strip()
        return s or None
    if f > 1.0001:
        f = f / 100.0
    return f"{max(0.0, min(1.0, f)):.4f}"


def _last_price_dollars_from_ticker_msg(msg: dict[str, Any]) -> Optional[str]:
    raw = msg.get("last_price_dollars") or msg.get("price_dollars") or msg.get("price")
    if raw is None or str(raw).strip() == "":
        return None
    return normalize_kalshi_dollar_text(raw, KALSHI_WS_TICKER_DOLLAR_PLACES)


def ticker_quote_body(
    mt: str, msg: dict[str, Any], *, rest_meta: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    yes_ask = _normalize_dollar_field(msg.get("yes_ask_dollars") or msg.get("yes_ask"))
    no_ask = _normalize_dollar_field(msg.get("no_ask_dollars") or msg.get("no_ask"))
    yes_bid = _normalize_dollar_field(msg.get("yes_bid_dollars") or msg.get("yes_bid"))
    no_bid = _normalize_dollar_field(msg.get("no_bid_dollars") or msg.get("no_bid"))
    if yes_ask is not None and no_ask is None:
        no_ask = _complement_dollar(yes_ask)
    if no_ask is not None and yes_ask is None:
        yes_ask = _complement_dollar(no_ask)
    if yes_bid is not None and no_bid is None:
        no_bid = _complement_dollar(yes_bid)
    if no_bid is not None and yes_bid is None:
        yes_bid = _complement_dollar(no_bid)
    body: dict[str, Any] = {
        "ticker": mt,
        "yes_ask_dollars": yes_ask,
        "no_ask_dollars": no_ask,
        "yes_bid_dollars": yes_bid,
        "no_bid_dollars": no_bid,
        "last_price_dollars": _last_price_dollars_from_ticker_msg(msg),
        "volume_fp": msg.get("volume_fp") or msg.get("volume"),
        "open_interest_fp": msg.get("open_interest_fp") or msg.get("open_interest"),
    }
    meta = rest_meta or {}
    fs = meta.get("floor_strike")
    if fs is not None:
        try:
            fs = float(fs)
        except (TypeError, ValueError):
            fs = None
    if fs is None:
        fs = _numeric_strike_from_ticker(mt)
    strike = _strike_display(mt, fs)
    if strike:
        body["strike"] = strike
        body["floor_strike"] = fs
    return body


def _live_market_tickers(master: Any, cfg: IngestConfig, symbol: str, now: float) -> set[str]:
    sym_u = symbol.upper()
    if cfg.is_15m:
        return {clock_current_15m_ticker(sym_u, now)}
    out: set[str] = set()
    for ent in master.schedule_by_symbol.get(sym_u, {}).get("hourly", []):
        if getattr(ent, "market_result", None) or ent.market_ticker in master.settled_tickers:
            continue
        cut = ent.close_ts - cfg.orderbook_cutover_sec
        if ent.open_ts <= now < cut:
            out.add(ent.market_ticker)
    return out


def build_market_snapshot(
    master: Any,
    cfg: IngestConfig,
    symbol: str,
    ticker_tickers: list[str],
    now: float,
) -> Optional[dict[str, Any]]:
    sym_u = symbol.upper()
    markets_out: list[dict[str, Any]] = []
    if cfg.is_15m:
        mt = clock_current_15m_ticker(sym_u, now)
        if mt in master.ticker_subscribed:
            markets_out.append(
                ticker_quote_body(
                    mt,
                    master.ticker_pending.get(mt) or {},
                    rest_meta=master.ticker_rest_meta.get(mt),
                )
            )
    else:
        for mt in sorted(set(ticker_tickers)):
            hourly = series_hourly(sym_u)
            if not hourly or not mt.startswith(hourly + "-"):
                continue
            msg = master.ticker_pending.get(mt) or {}
            if not msg and mt not in master.ticker_subscribed:
                continue
            markets_out.append(
                ticker_quote_body(mt, msg, rest_meta=master.ticker_rest_meta.get(mt))
            )
    if not markets_out:
        return None
    mt_list = [str(m.get("ticker") or "") for m in markets_out if m.get("ticker")]
    if cfg.is_15m:
        event_ticker = clock_current_15m_ticker(sym_u, now)
    else:
        event_ticker = hourly_event_ticker_for_clock(sym_u, now) or ""
        if not event_ticker:
            for mt in mt_list:
                if mt.startswith((series_hourly(sym_u) or "") + "-"):
                    parts = mt.split("-")
                    if len(parts) >= 2:
                        event_ticker = "-".join(parts[:2])
                        break
    return {"event_ticker": event_ticker, "markets": markets_out}


def orderbook_redis_payload(master: Any, mt: str) -> Optional[dict[str, Any]]:
    b = master.books.get(mt)
    if not b or not b.get("valid"):
        return None
    return {
        "v": 1,
        "market_ticker": mt,
        "yes": dict(b["yes"]),
        "no": dict(b["no"]),
        "seq": b.get("last_seq"),
        "ts_ms": b.get("ts_ms"),
        "valid": True,
    }


def delete_orderbook_redis(mt: str) -> None:
    r = live_state_cache.redis_client_optional()
    if not r:
        return
    try:
        r.delete(trade_monitor_orderbook_redis_key(mt))
    except Exception:
        pass


def publish_orderbook_hint(
    market_ticker: str,
    *,
    market_interval: str,
    book_seq: Any = None,
) -> None:
    r = live_state_cache.redis_client_optional()
    if not r:
        return
    try:
        key = trade_monitor_orderbook_redis_key(market_ticker)
        msg = json.dumps(
            {
                "type": "live_state_updated",
                "kind": "orderbook",
                "key": key,
                "market_ticker": market_ticker,
                "market_interval": market_interval,
                "book_seq": book_seq,
            }
        )
        r.publish(live_state_cache.UPDATED_CHANNEL, msg)
    except Exception as e:
        log.debug("orderbook hint publish failed: %s", e)


def flush_dirty_sync(
    master: Any,
    cfg: IngestConfig,
    ob_tickers: list[str],
    ticker_tickers: list[str],
) -> None:
    """Trade-monitor orderbook keys + live_state market ladder (no sandbox:kalshi:*)."""
    r = live_state_cache.redis_client_optional()
    if not r:
        return
    try:
        pipe = r.pipeline()
        published_ob: list[tuple[str, Any]] = []
        for mt in ob_tickers:
            payload = orderbook_redis_payload(master, mt)
            if not payload:
                continue
            pipe.set(
                trade_monitor_orderbook_redis_key(mt),
                json.dumps(payload, default=str),
                ex=_OB_TTL,
            )
            published_ob.append((mt, payload.get("seq")))

        now_f = time.time()
        now_ts = datetime.now(timezone.utc).isoformat()
        for sym in master.symbols:
            live_mt = _live_market_tickers(master, cfg, sym, now_f)
            sym_tickers = [
                mt
                for mt in master.ticker_subscribed
                if mt in live_mt
                and (
                    (cfg.is_15m and mt.startswith(series_15m(sym) + "-"))
                    or (
                        cfg.is_hourly
                        and series_hourly(sym)
                        and mt.startswith(series_hourly(sym) + "-")
                    )
                )
            ]
            snap = build_market_snapshot(master, cfg, sym, sym_tickers, now_f)
            if snap:
                live_state_cache.set_market(
                    DEFAULT_EXCHANGE,
                    cfg.market_interval,
                    sym,
                    snap,
                    source_event_at=now_ts,
                )

        if published_ob:
            pipe.execute()
        for mt, seq in published_ob:
            publish_orderbook_hint(mt, market_interval=cfg.market_interval, book_seq=seq)
    except Exception:
        log.debug("flush_dirty_sync failed", exc_info=True)
