"""Kalshi API money field normalization (dollars vs integer cents)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional


def dollars_to_cents(value: Any) -> Optional[int]:
    """
    Convert Kalshi dollar-denominated fields (e.g. subaccount ``balance`` strings
    like ``"1533.9800"``) to integer cents for ``account_balance`` / subaccounts tables.
    """
    if value is None:
        return None
    try:
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            return int(round(float(s) * 100))
        if isinstance(value, (int, float, Decimal)):
            return int(round(float(value) * 100))
        return None
    except (TypeError, ValueError):
        return None


def normalize_kalshi_subaccount_balance_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize one ``subaccount_balances`` entry from GET /portfolio/subaccounts/balances.

    - ``balance`` becomes integer cents (matches GET /portfolio/balance).
    - Original API value preserved as ``balance_dollars`` when it was a dollar string/number.
    """
    out = dict(row)
    raw = row.get("balance")
    if raw is None:
        return out
    if isinstance(raw, str) or isinstance(raw, (float, Decimal)):
        out["balance_dollars"] = str(raw).strip() if isinstance(raw, str) else str(raw)
        cents = dollars_to_cents(raw)
        if cents is not None:
            out["balance"] = cents
        return out
    if isinstance(raw, int):
        # Already integer cents (e.g. re-normalized or future API shape).
        return out
    cents = dollars_to_cents(raw)
    if cents is not None:
        out["balance_dollars"] = str(raw)
        out["balance"] = cents
    return out


def normalize_kalshi_subaccount_balances_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize full GET /portfolio/subaccounts/balances JSON payload."""
    if not data:
        return data
    rows: List[Dict[str, Any]] = data.get("subaccount_balances") or []
    return {
        **data,
        "subaccount_balances": [
            normalize_kalshi_subaccount_balance_row(dict(r)) for r in rows
        ],
    }
