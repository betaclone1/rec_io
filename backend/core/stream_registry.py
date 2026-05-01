"""
Stream registry: (schema, table) -> stream name for the real-time backbone.

SCOPE (anti-bloat): This module contains ONLY the mapping. No business logic, no
imports of other app code, no per-stream behavior. To add a watched set of values:
(1) Add a trigger on the table (public.rec_io_db_notify() or statement-level for
high volume), (2) Add one entry here: (schema, table) -> stream_name, (3) Optionally
document in docs/REALTIME_BACKBONE.md. If you need more than a mapping, add a
separate module and document the rule in REALTIME_BACKBONE.md Section 0.

Keys (schema, table) must be lowercase for consistent lookup.
"""

import re
from typing import Dict, Optional, Tuple

_TENANT_SCHEMA_RE = re.compile(r"^users_(\d{4})$", re.IGNORECASE)

# (schema, table) -> stream name. Stream name is the value of "database" in db_change payloads.
TABLE_TO_STREAM: Dict[Tuple[str, str], str] = {
    ("system", "master_users"): "master_users",
    ("testing", "redis_basic_test"): "redis_basic_test",
    # Account / bankroll / portfolio top-level values (dashboard, account_manager, etc.)
    ("users", "account_balance_0001"): "account_balance",
    ("users", "account_balance_paper_0001"): "account_balance_paper",
    ("users", "transfers_paper_0001"): "transfers_paper",
    # Trade log (GET /trades via read_api / main proxy, trade_history UIs); NOTIFY → stream "trades"
    ("users", "trades_0001"): "trades",
    # Per-tenant monitor rows (lifecycle, counts); NOTIFY → stream "monitor_list" (Admin Tools refetch, etc.)
    ("users", "monitor_list_0001"): "monitor_list",
    # Live price feed snapshot table (used by the standalone live UI)
    ("live_data", "live_symbol_status"): "live_symbol_status",
    # 15m market ladder/quotes consumed by strike_table_generator_ws
    ("live_data", "market_kalshi_15m"): "market_kalshi_15m",
    # Unified hourly market ladder (BTC+ETH) for strike_table_generator_ws hourly
    ("live_data", "market_kalshi_hourly"): "market_kalshi_hourly",
    # Unified 15m strike row(s) per symbol (strike_table_generator / strike_table_generator_ws)
    ("live_data", "strike_table_15m"): "strike_table_15m",
    # Unified hourly strike rows
    ("live_data", "strike_table_hourly"): "strike_table_hourly",
}


def get_table_to_stream() -> Dict[Tuple[str, str], str]:
    """Return the full (schema, table) -> stream_name mapping. Used by the switchboard."""
    return dict(TABLE_TO_STREAM)


def resolve_stream_for_notify(
    schema: str, table: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    Map NOTIFY payload (schema, table) to (stream_name, tenant_user_no).

    ``tenant_user_no`` is set when schema is ``users_NNNN`` and the table suffix matches
    that user (e.g. users_0001.trades_0001). Shared streams (live_data, testing) return
    ``tenant_user_no=None``.
    """
    s = (schema or "").lower()
    t = (table or "").lower()
    key = (s, t)
    if key in TABLE_TO_STREAM:
        return TABLE_TO_STREAM[key], None
    if s == "live_data" and t.startswith("orderbook_kalshi_"):
        return "orderbook_kalshi", None
    m = _TENANT_SCHEMA_RE.match(s)
    if not m:
        return None, None
    user_no = m.group(1)
    if not t.endswith(f"_{user_no}"):
        return None, None
    legacy_key = ("users", t)
    if legacy_key in TABLE_TO_STREAM:
        return TABLE_TO_STREAM[legacy_key], user_no
    # Same logical stream as legacy users.<base>_0001 (e.g. account_balance_paper_0002 → paper stream).
    suffix = f"_{user_no}"
    base_table = t[: -len(suffix)] if len(t) > len(suffix) else ""
    if base_table:
        canonical_key = ("users", f"{base_table}_0001")
        if canonical_key in TABLE_TO_STREAM:
            return TABLE_TO_STREAM[canonical_key], user_no
    return None, None
