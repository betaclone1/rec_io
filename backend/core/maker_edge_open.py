"""
Maker Edge open-time targeting: Kalshi ``open_time`` is the place trigger.

No TTC / ladder gates. Market identity comes from Kalshi ``/markets`` only
(no clock-invented tickers).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from backend.core.kalshi_event_market_fetch import kalshi_trade_api_base

log = logging.getLogger("maker_edge_open")

SERIES_BTC_15M = "KXBTC15M"
# If we overshoot open_time by more than this, skip the cycle (do not late-place).
LATE_PLACE_GRACE_SEC = float(__import__("os").getenv("MAKER_EDGE_LATE_PLACE_GRACE_SEC", "0.25"))
# Busy-spin window immediately before open for tighter wake.
SPIN_BEFORE_OPEN_SEC = float(__import__("os").getenv("MAKER_EDGE_SPIN_BEFORE_OPEN_SEC", "0.05"))
_HEADERS = {"Accept": "application/json", "User-Agent": "rec_io_maker_edge/1.0"}


@dataclass(frozen=True)
class OpenTarget:
    market_ticker: str
    event_ticker: str
    open_ts: float
    close_ts: float
    floor_strike: Optional[float]


def parse_kalshi_iso_ts(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _floor_from_market(m: dict[str, Any]) -> Optional[float]:
    for key in ("floor_strike", "strike"):
        raw = m.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def market_dict_to_open_target(m: dict[str, Any]) -> Optional[OpenTarget]:
    mt = str(m.get("ticker") or "").strip()
    if not mt:
        return None
    open_ts = parse_kalshi_iso_ts(m.get("open_time"))
    close_ts = parse_kalshi_iso_ts(m.get("close_time"))
    if open_ts is None or close_ts is None:
        return None
    et = str(m.get("event_ticker") or "").strip()
    if not et and "-" in mt:
        # KXBTC15M-26OCT181200-00 → event without trailing strike token
        parts = mt.rsplit("-", 1)
        et = parts[0] if len(parts) == 2 else mt
    return OpenTarget(
        market_ticker=mt,
        event_ticker=et or mt,
        open_ts=float(open_ts),
        close_ts=float(close_ts),
        floor_strike=_floor_from_market(m),
    )


def select_next_open_target(
    markets: List[dict[str, Any]],
    *,
    now: Optional[float] = None,
    late_grace_sec: float = LATE_PLACE_GRACE_SEC,
) -> Optional[OpenTarget]:
    """Earliest market whose open_time is still in the future (or within open grace)."""
    t = time.time() if now is None else float(now)
    candidates: list[OpenTarget] = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        tgt = market_dict_to_open_target(m)
        if tgt is None:
            continue
        if tgt.close_ts <= t:
            continue
        # Still placeable at open: open in the future, or opened within grace.
        if tgt.open_ts > t + late_grace_sec:
            candidates.append(tgt)
        elif t <= tgt.open_ts + late_grace_sec:
            candidates.append(tgt)
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x.open_ts, x.market_ticker))
    return candidates[0]


def select_live_market(
    markets: List[dict[str, Any]],
    *,
    now: Optional[float] = None,
) -> Optional[OpenTarget]:
    """Currently open market (past open_time, before close). Used for restart recovery."""
    t = time.time() if now is None else float(now)
    live: list[OpenTarget] = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        tgt = market_dict_to_open_target(m)
        if tgt is None:
            continue
        if tgt.open_ts <= t < tgt.close_ts:
            live.append(tgt)
    if not live:
        return None
    # Prefer the most recently opened live window.
    live.sort(key=lambda x: (x.open_ts, x.market_ticker), reverse=True)
    return live[0]


_markets_cache: list[dict[str, Any]] = []
_markets_cache_mono: float = 0.0
_MARKETS_CACHE_SEC = float(__import__("os").getenv("MAKER_EDGE_MARKETS_CACHE_SEC", "30"))


def fetch_kxbtc15m_markets(
    *, timeout_sec: float = 8.0, force: bool = False
) -> List[dict[str, Any]]:
    """Public series poll around now → prediscover horizon (no auth). Cached to avoid 429."""
    global _markets_cache, _markets_cache_mono
    now_m = time.monotonic()
    if (
        not force
        and _markets_cache
        and (now_m - _markets_cache_mono) < _MARKETS_CACHE_SEC
    ):
        return list(_markets_cache)

    now = datetime.now(timezone.utc)
    min_close = int((now - timedelta(hours=1)).timestamp())
    max_close = int((now + timedelta(hours=4, minutes=45)).timestamp())
    out: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    base = kalshi_trade_api_base()
    while True:
        params: dict[str, Any] = {
            "series_ticker": SERIES_BTC_15M,
            "min_close_ts": min_close,
            "max_close_ts": max_close,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(
                f"{base}/markets",
                headers=_HEADERS,
                params=params,
                timeout=timeout_sec,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("KXBTC15M markets fetch failed: %s", e)
            # Keep stale cache on 429 / transient errors.
            if _markets_cache:
                return list(_markets_cache)
            break
        if not isinstance(data, dict):
            break
        out.extend(m for m in (data.get("markets") or []) if isinstance(m, dict))
        cursor = data.get("cursor")
        if not cursor:
            break
    if out:
        _markets_cache = out
        _markets_cache_mono = now_m
    return list(out)


def fetch_next_open_target(*, now: Optional[float] = None) -> Optional[OpenTarget]:
    markets = fetch_kxbtc15m_markets()
    return select_next_open_target(markets, now=now)


def fetch_live_market(*, now: Optional[float] = None) -> Optional[OpenTarget]:
    markets = fetch_kxbtc15m_markets()
    return select_live_market(markets, now=now)


def wait_until_open_ts(
    open_ts: float,
    *,
    late_grace_sec: float = LATE_PLACE_GRACE_SEC,
    spin_before_sec: float = SPIN_BEFORE_OPEN_SEC,
) -> bool:
    """
    Block until ``open_ts``. Returns True if still within late grace after wake.
    Uses coarse sleep then a short busy-spin for tighter open alignment.
    """
    while True:
        now = time.time()
        remaining = open_ts - now
        if remaining <= 0:
            return now <= open_ts + late_grace_sec
        if remaining > spin_before_sec:
            # Cap sleep chunks so a late cancel / process stop is responsive.
            time.sleep(min(remaining - spin_before_sec, 0.5))
        else:
            while time.time() < open_ts:
                pass
            return time.time() <= open_ts + late_grace_sec
