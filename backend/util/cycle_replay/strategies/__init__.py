from __future__ import annotations

from backend.util.cycle_replay.strategies.expiration_scalp import ExpirationScalpAdapter

STRATEGY_ADAPTERS = {
    "Expiration Scalp": ExpirationScalpAdapter,
    "expiration_scalp": ExpirationScalpAdapter,
    "expiration-scalp": ExpirationScalpAdapter,
}


def get_strategy_adapter(name: str):
    key = (name or "").strip()
    cls = STRATEGY_ADAPTERS.get(key) or STRATEGY_ADAPTERS.get(key.lower())
    if cls is None:
        known = sorted({k for k in STRATEGY_ADAPTERS if " " in k or k[0].isupper()})
        raise ValueError(f"Unknown strategy {name!r}; known: {known}")
    return cls()
