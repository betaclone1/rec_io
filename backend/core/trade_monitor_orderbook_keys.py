"""Redis and Postgres identifiers for trade-monitor orderbook depth."""

from __future__ import annotations

import re

_OB_REDIS_PREFIX = "trade_monitor:orderbook_levels:v1:"
_OB_WS_REDIS_PREFIX = "trade_monitor:orderbook_ws:v1:"
_PG_TABLE_PREFIX = "orderbook_kalshi_"


def _sanitize_ticker_for_table(market_ticker: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_]+", "_", str(market_ticker or "").strip())
    t = re.sub(r"_+", "_", t).strip("_").lower()
    return t or "unknown"


def trade_monitor_orderbook_redis_key(market_ticker: str) -> str:
    mt = str(market_ticker or "").strip()
    return f"{_OB_REDIS_PREFIX}{mt}"


def trade_monitor_orderbook_ws_redis_key(market_ticker: str) -> str:
    """Pre-serialized ``live_orderbook`` JSON for switchboard fanout (optional)."""
    mt = str(market_ticker or "").strip()
    return f"{_OB_WS_REDIS_PREFIX}{mt}"


def physical_table_name(market_ticker: str) -> str:
    return f"{_PG_TABLE_PREFIX}{_sanitize_ticker_for_table(market_ticker)}"


def quoted_table(market_ticker: str) -> str:
    name = physical_table_name(market_ticker)
    return f'live_data."{name}"'
