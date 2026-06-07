"""
CFB experiment metrics: reuse symbol_price_watchdog row builder without modifying it.

- Spot + deltas/movement/volatility: build_symbol_tick_row (read-only import).
- one_minute_avg: Kalshi avg_60s_data when present.
- Mom rolling averages: CFB-local time windows (sparse ~1 tick/min feed).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from backend.core.cfbenchmarks_feed_cache import symbol_for_index

logger = logging.getLogger("cfbenchmarks_price_watchdog")

_EST = ZoneInfo("America/New_York")
_TRACKED_SYMBOLS = frozenset({"BTC", "ETH", "SOL", "XRP"})
_profiles_loaded = False
_MAX_CFB_MOMENTUM = 120

_cfb_lock = threading.Lock()
# Per-symbol (epoch, raw momentum) — isolated from Coinbase symbol_tick_buffer.
_cfb_momentum: Dict[str, Deque[Tuple[float, float]]] = defaultdict(
    lambda: deque(maxlen=_MAX_CFB_MOMENTUM)
)

_MOM_WINDOWS_SEC = (
    ("momentum_5s_avg", 5),
    ("momentum_10s_avg", 10),
    ("momentum_30s_avg", 30),
    ("momentum_1m_avg", 60),
)

# Top-level envelope keys copied from tick_row for UI / consumers
_METRIC_SHORTCUTS = (
    "delta_1m",
    "delta_2m",
    "delta_3m",
    "delta_4m",
    "delta_15m",
    "delta_30m",
    "momentum",
    "momentum_percentile",
    "momentum_5s_avg",
    "momentum_10s_avg",
    "momentum_30s_avg",
    "momentum_1m_avg",
    "momentum_acceleration",
    "one_minute_avg",
    "volatility",
    "volatility_percentile",
    "move_1m",
    "move_2m",
    "move_3m",
    "move_4m",
    "move_15m",
    "move_30m",
    "movement",
    "movement_percentile",
)


def wall_timestamp_est() -> str:
    now = datetime.now(_EST)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}"


def _epoch_from_ts(ts: str) -> float:
    s = (ts or "").strip()
    if not s:
        return datetime.now(_EST).timestamp()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        if "." in s and "+" not in s and s.count("-") <= 2:
            dt = datetime.strptime(s[:26], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=_EST)
        elif "+" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_EST)
        else:
            dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_EST)
        return dt.timestamp()
    except Exception:
        return datetime.now(_EST).timestamp()


def symbols_for_index_ids(index_ids: List[str]) -> List[str]:
    out: List[str] = []
    for iid in index_ids:
        sym = symbol_for_index(iid)
        if sym in _TRACKED_SYMBOLS and sym not in out:
            out.append(sym)
    return out


def preload_analytics_profiles(symbols: List[str]) -> None:
    global _profiles_loaded
    if _profiles_loaded:
        return
    from backend.symbol_price_watchdog import (
        load_movement_profile,
        load_momentum_profile,
        load_volatility_profile,
    )

    for sym in symbols:
        if sym not in _TRACKED_SYMBOLS:
            continue
        load_momentum_profile(sym)
        load_volatility_profile(sym)
        load_movement_profile(sym)
        logger.info("loaded analytics profiles for %s", sym)
    _profiles_loaded = True


def _tick_timestamp_est(envelope: Dict[str, Any]) -> str:
    """Prefer Kalshi index source time for buffer/delta alignment with the CFB print."""
    ms = envelope.get("source_ts_ms")
    if ms is not None:
        try:
            dt = datetime.fromtimestamp(int(ms) / 1000.0, tz=_EST)
            return (
                dt.strftime("%Y-%m-%dT%H:%M:%S")
                + f".{dt.microsecond // 1000:03d}"
            )
        except (TypeError, ValueError, OSError):
            pass
    return str(envelope.get("published_at") or wall_timestamp_est())


def _one_minute_avg_from_cfb(envelope: Dict[str, Any]) -> Optional[float]:
    """Kalshi cfbenchmarks_value avg_60s_data (authoritative 1m index average)."""
    avg60 = envelope.get("avg_60s_data")
    if not isinstance(avg60, dict):
        return None
    raw = avg60.get("value")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _cfb_record_momentum(symbol: str, momentum: Optional[float], epoch: float) -> None:
    if momentum is None:
        return
    sym = symbol.upper()
    with _cfb_lock:
        _cfb_momentum[sym].append((epoch, float(momentum)))


def _cfb_momentum_in_window(symbol: str, seconds: float) -> List[float]:
    if seconds <= 0:
        return []
    cutoff = datetime.now(_EST).timestamp() - seconds
    sym = symbol.upper()
    with _cfb_lock:
        return [m for epoch, m in _cfb_momentum.get(sym, ()) if epoch >= cutoff]


def _cfb_momentum_avg_percentile(symbol: str, window_seconds: int) -> Optional[float]:
    from backend.symbol_price_watchdog import calculate_momentum_percentile

    vals = _cfb_momentum_in_window(symbol, float(window_seconds))
    if not vals:
        return None
    avg = sum(vals) / len(vals)
    pct = calculate_momentum_percentile(symbol, avg)
    return pct if pct is not None else avg


def _cfb_momentum_acceleration(
    momentum_10s_avg: Optional[float],
    momentum_1m_avg: Optional[float],
) -> Optional[float]:
    """mom_10s − mom_1m on percentile scale (same formula as trade-monitor helpers)."""
    if momentum_10s_avg is None or momentum_1m_avg is None:
        return None
    try:
        return round(float(momentum_10s_avg) - float(momentum_1m_avg), 2)
    except (TypeError, ValueError):
        return None


def _apply_cfb_momentum_windows(symbol: str, tick_row: Dict[str, Any]) -> None:
    """Time-based mom averages (Coinbase semantics at ~1 Hz; correct for sparse CFB)."""
    mom: Dict[str, Optional[float]] = {}
    for key, sec in _MOM_WINDOWS_SEC:
        mom[key] = _cfb_momentum_avg_percentile(symbol, sec)
        tick_row[key] = mom[key]

    tick_row["momentum_acceleration"] = _cfb_momentum_acceleration(
        mom.get("momentum_10s_avg"),
        mom.get("momentum_1m_avg"),
    )


def replay_cfb_momentum_from_price_rows(
    symbol: str,
    rows: List[Tuple[str, float]],
) -> None:
    """Replay CFB momentum deque after ring PG hydration (chronological price rows)."""
    sym = symbol.strip().upper()
    if sym not in _TRACKED_SYMBOLS or not rows:
        return
    from backend.symbol_price_watchdog import build_symbol_tick_row

    for ts, px in rows:
        try:
            tick_row, _table = build_symbol_tick_row(
                sym, ts, px, ws_received_mono=0.0
            )
            raw = tick_row.get("momentum")
            _cfb_record_momentum(sym, raw, _epoch_from_ts(ts))
        except Exception as e:
            logger.debug("ring momentum replay %s %s: %s", sym, ts, e)


def attach_legacy_metrics(
    envelope: Dict[str, Any],
    *,
    ingest_mono: float,
) -> Dict[str, Any]:
    """
    Build tick row via symbol_price_watchdog (unchanged), then CFB-only overrides.

    Uses this process's symbol_tick_buffer for price/deltas. Publishing to live_state /
    experiment Redis is handled by cfbenchmarks_publish.publish_envelope_outputs.
    """
    symbol = str(envelope.get("symbol") or "").strip().upper()
    price = envelope.get("price")
    if symbol not in _TRACKED_SYMBOLS or price is None:
        return envelope

    ts = _tick_timestamp_est(envelope)
    epoch = _epoch_from_ts(ts)
    px = float(price)
    one_min_avg = _one_minute_avg_from_cfb(envelope)

    try:
        from backend.core.symbol_tick_buffer import append_tick
        from backend.symbol_price_watchdog import build_symbol_tick_row

        append_tick(symbol, ts, px)
        tick_row, _table = build_symbol_tick_row(
            symbol, ts, px, ws_received_mono=ingest_mono
        )

        if one_min_avg is not None:
            tick_row["one_minute_avg"] = one_min_avg

        raw_momentum = tick_row.get("momentum")
        _cfb_record_momentum(symbol, raw_momentum, epoch)
        _apply_cfb_momentum_windows(symbol, tick_row)

        envelope["metrics"] = tick_row
        for key in _METRIC_SHORTCUTS:
            if key in tick_row:
                envelope[key] = tick_row[key]
        if one_min_avg is not None:
            envelope["one_minute_avg_source"] = "cfb_avg_60s"
    except Exception as e:
        logger.warning("legacy metrics failed %s: %s", symbol, e)
        envelope["metrics_error"] = str(e)

    return envelope
