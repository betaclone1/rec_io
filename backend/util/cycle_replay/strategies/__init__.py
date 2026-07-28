from __future__ import annotations

from backend.util.cycle_replay.strategies.expiration_scalp import ExpirationScalpAdapter
from backend.util.cycle_replay.strategies.htc_15m import Htc15mAdapter

STRATEGY_ADAPTERS = {
    "Expiration Scalp": ExpirationScalpAdapter,
    "expiration_scalp": ExpirationScalpAdapter,
    "expiration-scalp": ExpirationScalpAdapter,
    "15m HTC": Htc15mAdapter,
    "15m_htc": Htc15mAdapter,
    "Hourly HTC": Htc15mAdapter,
    "hourly_htc": Htc15mAdapter,
}


def get_strategy_adapter(name: str):
    key = (name or "").strip()
    cls = STRATEGY_ADAPTERS.get(key) or STRATEGY_ADAPTERS.get(key.lower())
    if cls is None:
        known = sorted({k for k in STRATEGY_ADAPTERS if " " in k or k[0].isupper()})
        raise ValueError(f"Unknown strategy {name!r}; known: {known}")
    return cls()
