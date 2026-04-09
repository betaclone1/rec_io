"""
Join Kalshi backtest minute bars to ``historical_data.*_price_history`` on Eastern-naive ``timestamp``.

Ticker prefix → table: ``KXETH*`` → ``eth_price_history``, ``KXBTC*`` (incl. ``KXBTCD``, ``KXBTC15M``) → ``btc_price_history``.
Copied columns use the **same names** as ``btc_price_history`` / ``eth_price_history`` (``open``, ``high``, …).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

# Whitelisted fully-qualified tables (never format user input into SQL identifiers beyond this map).
_PRICE_HISTORY_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("KXETH", "historical_data.eth_price_history"),
    ("KXBTC", "historical_data.btc_price_history"),
)

# Column names and types — same as historical_data.btc_price_history / eth_price_history (excluding timestamp).
BACKTEST_PRICE_HISTORY_COLUMN_DEFS: tuple[tuple[str, str], ...] = (
    ("open", "NUMERIC(20, 8)"),
    ("high", "NUMERIC(20, 8)"),
    ("low", "NUMERIC(20, 8)"),
    ("close", "NUMERIC(20, 8)"),
    ("volume", "NUMERIC(20, 8)"),
    ("momentum", "NUMERIC(10, 4)"),
    ("momentum_percentile", "NUMERIC(5, 1)"),
    ("volatility", "NUMERIC(15, 6)"),
    ("volatility_percentile", "NUMERIC(5, 1)"),
    ("movement", "NUMERIC(10, 4)"),
    ("movement_percentile", "NUMERIC(5, 1)"),
)

_COL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_BACKTEST_REL_RE = re.compile(r"^backtest_1m_[a-z0-9_]+$")


def _quote_col(name: str) -> str:
    if not _COL_NAME_RE.match(name):
        raise ValueError(f"invalid SQL column name: {name!r}")
    return f'"{name}"'


def price_history_table_for_kalshi_ticker(market_ticker: str) -> str | None:
    """Return whitelisted ``historical_data.*_price_history`` name, or None if unsupported."""
    u = market_ticker.strip().upper()
    for prefix, table in _PRICE_HISTORY_BY_PREFIX:
        if u.startswith(prefix):
            return table
    return None


def normalize_price_history_ts(ts: datetime) -> datetime:
    """Naive Eastern wall time; strip microseconds for stable PK joins."""
    if ts.tzinfo is not None:
        raise ValueError("timestamp must be naive (Eastern wall time)")
    return ts.replace(microsecond=0)


def ensure_backtest_price_history_columns(conn: Any, rel: str) -> None:
    """``ALTER TABLE backtest.<rel> ADD COLUMN IF NOT EXISTS`` for each price-history field."""
    if not _BACKTEST_REL_RE.match(rel):
        raise ValueError(f"invalid backtest table rel: {rel!r}")
    parts = [
        f"ADD COLUMN IF NOT EXISTS {_quote_col(name)} {typ}"
        for name, typ in BACKTEST_PRICE_HISTORY_COLUMN_DEFS
    ]
    sql = f"ALTER TABLE backtest.{rel} " + ", ".join(parts) + ";"
    with conn.cursor() as cur:
        cur.execute(sql)


def fetch_price_history_rows_by_timestamps(
    conn: Any,
    market_ticker: str,
    timestamps: list[datetime],
) -> dict[datetime, tuple[Any, ...]]:
    """
    Load price-history rows for the given naive Eastern minute timestamps.

    Returns a map ``normalized_ts -> (open, high, low, close, volume, momentum, ...)`` (11 values).
    Missing timestamps are omitted from the map.
    """
    table = price_history_table_for_kalshi_ticker(market_ticker)
    if not table or not timestamps:
        return {}
    uniq = list({normalize_price_history_ts(t) for t in timestamps})
    if not uniq:
        return {}

    cols = (
        "open, high, low, close, volume, momentum, momentum_percentile, "
        "volatility, volatility_percentile, movement, movement_percentile"
    )
    sql = (
        f'SELECT "timestamp", {cols} FROM {table} '
        f'WHERE "timestamp" IN %s'
    )
    out: dict[datetime, tuple[Any, ...]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (tuple(uniq),))
        for row in cur.fetchall():
            ts_raw = row[0]
            rest = row[1:]
            if ts_raw is None:
                continue
            if not isinstance(ts_raw, datetime):
                continue
            key = normalize_price_history_ts(ts_raw)
            out[key] = tuple(_adapt_price_history_cell(x) for x in rest)
    return out


def _adapt_price_history_cell(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    return v


def empty_price_history_tuple() -> tuple[Any, ...]:
    return (None,) * len(BACKTEST_PRICE_HISTORY_COLUMN_DEFS)
