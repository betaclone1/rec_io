"""
Lower Tail open-time targeting: Kalshi ``open_time`` is the place trigger.

No TTC / ladder gates. Market identity comes from Kalshi ``/markets`` only
(no clock-invented tickers). Discovers across all tracked Lower Tail 15m series
(``lower_tail_symbols()`` ∩ Kalshi ``SERIES_15M_BY_SYMBOL``).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

from backend.core.aes_btc15m_lower_tail_cutout import lower_tail_symbols
from backend.core.kalshi_event_market_fetch import kalshi_trade_api_base
from backend.core.market_watchdog.venues.kalshi.schedule import SERIES_15M_BY_SYMBOL

log = logging.getLogger("lower_tail_open")

SERIES_BTC_15M = "KXBTC15M"
# If we overshoot open_time by more than this, skip the cycle (do not late-place).
LATE_PLACE_GRACE_SEC = float(__import__("os").getenv("LOWER_TAIL_LATE_PLACE_GRACE_SEC", "0.25"))
# Busy-spin window immediately before open for tighter wake.
SPIN_BEFORE_OPEN_SEC = float(__import__("os").getenv("LOWER_TAIL_SPIN_BEFORE_OPEN_SEC", "0.05"))
_HEADERS = {"Accept": "application/json", "User-Agent": "rec_io_lower_tail/1.0"}


@dataclass(frozen=True)
class OpenTarget:
    market_ticker: str
    event_ticker: str
    open_ts: float
    close_ts: float
    floor_strike: Optional[float]
    symbol: str = ""
    series_ticker: str = ""


def series_15m_for_symbol(symbol: str) -> Optional[str]:
    sym = str(symbol or "").strip().upper()
    return SERIES_15M_BY_SYMBOL.get(sym)


def symbol_from_series_ticker(series: str) -> Optional[str]:
    s = str(series or "").strip().upper()
    for sym, ser in SERIES_15M_BY_SYMBOL.items():
        if ser == s:
            return sym
    return None


def symbol_from_market_ticker(ticker: str) -> Optional[str]:
    """Map ``KXBTC15M-…`` / ``KXETH15M-…`` → underlying symbol."""
    head = str(ticker or "").strip().upper().split("-", 1)[0]
    return symbol_from_series_ticker(head)


def lower_tail_series_tickers(
    symbols: Optional[Iterable[str]] = None,
) -> List[str]:
    allowed = lower_tail_symbols()
    want = (
        {str(s).strip().upper() for s in symbols}
        if symbols is not None
        else set(allowed)
    )
    out: list[str] = []
    for sym in sorted(want):
        if sym not in allowed:
            continue
        ser = series_15m_for_symbol(sym)
        if ser:
            out.append(ser)
    return out


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
    series = mt.split("-", 1)[0].upper()
    symbol = symbol_from_series_ticker(series) or ""
    return OpenTarget(
        market_ticker=mt,
        event_ticker=et or mt,
        open_ts=float(open_ts),
        close_ts=float(close_ts),
        floor_strike=_floor_from_market(m),
        symbol=symbol,
        series_ticker=series,
    )


def select_next_open_target(
    markets: List[dict[str, Any]],
    *,
    now: Optional[float] = None,
    late_grace_sec: float = LATE_PLACE_GRACE_SEC,
    exclude_events: Optional[Iterable[str]] = None,
) -> Optional[OpenTarget]:
    """Earliest market whose open_time is still in the future (or within open grace)."""
    t = time.time() if now is None else float(now)
    skip = {str(e) for e in (exclude_events or ())}
    candidates: list[OpenTarget] = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        tgt = market_dict_to_open_target(m)
        if tgt is None:
            continue
        if tgt.event_ticker in skip:
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


def select_targets_co_opening(
    markets: List[dict[str, Any]],
    *,
    primary: OpenTarget,
    now: Optional[float] = None,
    late_grace_sec: float = LATE_PLACE_GRACE_SEC,
    open_ts_epsilon_sec: float = 1.0,
) -> List[OpenTarget]:
    """All placeable targets that share (approx) the same open as ``primary``.

    Used so BTC/ETH/commodity cycles that open together each get rests in one fire.
    """
    t = time.time() if now is None else float(now)
    out: list[OpenTarget] = []
    seen: set[str] = set()
    for m in markets:
        if not isinstance(m, dict):
            continue
        tgt = market_dict_to_open_target(m)
        if tgt is None:
            continue
        if tgt.close_ts <= t:
            continue
        if abs(tgt.open_ts - primary.open_ts) > open_ts_epsilon_sec:
            continue
        if tgt.open_ts > t + late_grace_sec and tgt.open_ts > primary.open_ts + open_ts_epsilon_sec:
            continue
        if t > tgt.open_ts + late_grace_sec and tgt.event_ticker != primary.event_ticker:
            # Past grace and not the primary we waited for.
            if abs(tgt.open_ts - primary.open_ts) > 1e-6:
                continue
        if tgt.event_ticker in seen:
            continue
        seen.add(tgt.event_ticker)
        out.append(tgt)
    if primary.event_ticker not in seen:
        out.append(primary)
        seen.add(primary.event_ticker)
    out.sort(key=lambda x: (x.open_ts, x.market_ticker))
    return out


def select_live_targets_by_symbol(
    markets: List[dict[str, Any]],
    *,
    now: Optional[float] = None,
) -> Dict[str, OpenTarget]:
    """Currently open market per symbol (past open_time, before close)."""
    t = time.time() if now is None else float(now)
    best: Dict[str, OpenTarget] = {}
    for m in markets:
        if not isinstance(m, dict):
            continue
        tgt = market_dict_to_open_target(m)
        if tgt is None or not tgt.symbol:
            continue
        if not (tgt.open_ts <= t < tgt.close_ts):
            continue
        cur = best.get(tgt.symbol)
        if cur is None or tgt.open_ts > cur.open_ts:
            best[tgt.symbol] = tgt
    return best


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


# series_ticker → (monotonic_ts, markets)
_markets_cache: Dict[str, tuple[float, list[dict[str, Any]]]] = {}
_MARKETS_CACHE_SEC = float(__import__("os").getenv("LOWER_TAIL_MARKETS_CACHE_SEC", "30"))


def fetch_series_15m_markets(
    series_ticker: str,
    *,
    timeout_sec: float = 8.0,
    force: bool = False,
) -> List[dict[str, Any]]:
    """Public series poll around now → prediscover horizon (no auth). Cached per series."""
    global _markets_cache
    series = str(series_ticker or "").strip().upper()
    if not series:
        return []
    now_m = time.monotonic()
    cached = _markets_cache.get(series)
    if (
        not force
        and cached
        and (now_m - cached[0]) < _MARKETS_CACHE_SEC
        and cached[1]
    ):
        return list(cached[1])

    now = datetime.now(timezone.utc)
    min_close = int((now - timedelta(hours=1)).timestamp())
    max_close = int((now + timedelta(hours=4, minutes=45)).timestamp())
    out: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    base = kalshi_trade_api_base()
    while True:
        params: dict[str, Any] = {
            "series_ticker": series,
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
            log.warning("%s markets fetch failed: %s", series, e)
            # Keep stale cache on 429 / transient errors.
            if cached and cached[1]:
                return list(cached[1])
            break
        if not isinstance(data, dict):
            break
        out.extend(m for m in (data.get("markets") or []) if isinstance(m, dict))
        cursor = data.get("cursor")
        if not cursor:
            break
    if out:
        _markets_cache[series] = (now_m, out)
    return list(out)


def fetch_lower_tail_markets(
    *,
    symbols: Optional[Sequence[str]] = None,
    force: bool = False,
) -> List[dict[str, Any]]:
    """Union of public markets for all configured Lower Tail 15m series."""
    out: list[dict[str, Any]] = []
    for series in lower_tail_series_tickers(symbols):
        out.extend(fetch_series_15m_markets(series, force=force))
    return out


def fetch_kxbtc15m_markets(
    *, timeout_sec: float = 8.0, force: bool = False
) -> List[dict[str, Any]]:
    """Back-compat: BTC 15m series only."""
    return fetch_series_15m_markets(
        SERIES_BTC_15M, timeout_sec=timeout_sec, force=force
    )


def fetch_next_open_target(*, now: Optional[float] = None) -> Optional[OpenTarget]:
    markets = fetch_lower_tail_markets()
    return select_next_open_target(markets, now=now)


def fetch_live_market(*, now: Optional[float] = None) -> Optional[OpenTarget]:
    markets = fetch_lower_tail_markets()
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
