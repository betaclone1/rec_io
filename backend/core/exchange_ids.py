"""Execution venue identifiers (normalized slugs)."""

from __future__ import annotations

DEFAULT_EXCHANGE = "kalshi"


def normalize_exchange(value: object | None) -> str:
    if value is None:
        return DEFAULT_EXCHANGE
    s = str(value).strip().lower()
    return s if s else DEFAULT_EXCHANGE
