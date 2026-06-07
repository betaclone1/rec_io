"""Read helpers: live_state envelopes → API / WS payload shapes."""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.core import live_state_cache
from backend.core.exchange_ids import normalize_exchange


def symbol_metrics_from_cache(symbol: str) -> Optional[Dict[str, Any]]:
    data = live_state_cache.get_symbol_data(symbol)
    if not data:
        return None
    return {
        "price": data.get("price"),
        "momentum": data.get("momentum"),
        "delta_1m": data.get("delta_1m"),
        "delta_2m": data.get("delta_2m"),
        "delta_3m": data.get("delta_3m"),
        "delta_4m": data.get("delta_4m"),
        "delta_15m": data.get("delta_15m"),
        "delta_30m": data.get("delta_30m"),
        "momentum_percentile": data.get("momentum_percentile"),
        "momentum_5s_avg": data.get("momentum_5s_avg"),
        "momentum_10s_avg": data.get("momentum_10s_avg"),
        "momentum_30s_avg": data.get("momentum_30s_avg"),
        "momentum_1m_avg": data.get("momentum_1m_avg"),
        "momentum_acceleration": data.get("momentum_acceleration"),
        "move_1m": data.get("move_1m"),
        "move_2m": data.get("move_2m"),
        "move_3m": data.get("move_3m"),
        "move_4m": data.get("move_4m"),
        "move_15m": data.get("move_15m"),
        "move_30m": data.get("move_30m"),
        "volatility": data.get("volatility"),
        "volatility_percentile": data.get("volatility_percentile"),
    }


def strike_ladder_from_cache(
    exchange: str,
    market: str,
    symbol: str,
) -> Optional[Dict[str, Any]]:
    ex = normalize_exchange(exchange)
    mk = (market or "hourly").strip().lower()
    sym = (symbol or "").strip().upper()
    env = live_state_cache.get_strike_ladder(ex, mk, sym)
    if not env:
        return None
    data = env.get("data")
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if isinstance(meta, dict) and meta.get("strikes") is not None:
        return dict(meta)
    rows = data.get("rows")
    if isinstance(rows, list) and rows:
        out: Dict[str, Any] = {
            "symbol": sym,
            "market": mk,
            "strikes": rows,
        }
        if isinstance(meta, dict):
            for k, v in meta.items():
                if k != "strikes":
                    out.setdefault(k, v)
        return out
    return None


def strike_ladder_ws_payload(
    exchange: str,
    market: str,
    symbol: str,
) -> Optional[Dict[str, Any]]:
    ladder = strike_ladder_from_cache(exchange, market, symbol)
    if not ladder:
        return None
    out = dict(ladder)
    out.setdefault("type", "live_strike_ladder")
    out.setdefault("symbol", (symbol or "").strip().upper())
    out.setdefault("market", (market or "15m").strip().lower())
    return out
