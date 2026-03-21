"""Reusable SQL predicates for backtests (defaults match backend / read_api conventions)."""

from __future__ import annotations


def exclude_test_filter_sql(alias: str = "t") -> str:
    """Trades flagged for testing (`test_filter = TRUE`) are excluded from backtests by default."""
    a = alias
    return f"({a}.test_filter IS NULL OR {a}.test_filter = FALSE)"
