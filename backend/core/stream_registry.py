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

from typing import Dict, Tuple

# (schema, table) -> stream name. Stream name is the value of "database" in db_change payloads.
TABLE_TO_STREAM: Dict[Tuple[str, str], str] = {
    ("testing", "redis_basic_test"): "redis_basic_test",
    # Account / bankroll / portfolio top-level values (dashboard, account_manager, etc.)
    ("users", "account_balance_0001"): "account_balance",
    # Live price feed snapshot table (used by the standalone live UI)
    ("live_data", "live_symbol_status"): "live_symbol_status",
    # 15m market ladder/quotes consumed by strike_table_generator_ws
    ("live_data", "market_kalshi_15m"): "market_kalshi_15m",
    # Unified 15m strike row(s) per symbol (strike_table_generator / strike_table_generator_ws)
    ("live_data", "strike_table_15m"): "strike_table_15m",
}


def get_table_to_stream() -> Dict[Tuple[str, str], str]:
    """Return the full (schema, table) -> stream_name mapping. Used by the switchboard."""
    return dict(TABLE_TO_STREAM)
