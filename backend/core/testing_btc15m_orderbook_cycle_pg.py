"""
Compatibility shim — use ``backend.core.cycle_hot_tables``.
"""

from backend.core.cycle_hot_tables import (  # noqa: F401
    deltas_table_name,
    drain_recorder,
    enqueue_delta,
    enqueue_snapshot,
    ensure_cycle_tables,
    is_cycle_ticker,
    list_hot_cycle_tickers_in_db,
    recorder_enabled,
    shutdown_recorder_executor,
    snapshot_table_name,
)


def migrate_all_existing_cycle_tables() -> int:
    """No-op: legacy testing-schema upgrade path retired."""
    return 0
