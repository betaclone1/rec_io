"""Kalshi subaccount transfers and name ↔ number mapping (live)."""

from __future__ import annotations

from backend.bookkeeper.kalshi_portfolio_balance import kalshi_prod_request

# users.subaccounts_* display name → Kalshi subaccount_number
KALSHI_SUBACCOUNT_NAME_TO_NUMBER: dict[str, int] = {
    "CASH": 0,
    "Master Trading Bankroll": 1,
    "undefined_2": 2,
    # Legacy labels (pre-migration rows / transfer history display)
    "PRIMARY": 0,
    "Cash Transfer": 2,
}

KALSHI_SUBACCOUNT_NUMBER_TO_NAME: dict[int, str] = {
    0: "CASH",
    1: "Master Trading Bankroll",
    2: "undefined_2",
}


def subaccount_name_to_number(name: str) -> int:
    """Map DB subaccount label to Kalshi subaccount_number."""
    if name in KALSHI_SUBACCOUNT_NAME_TO_NUMBER:
        return KALSHI_SUBACCOUNT_NAME_TO_NUMBER[name]
    if name.startswith("undefined_"):
        return int(name.split("_", 1)[1])
    raise ValueError(f"Unknown subaccount name for Kalshi mapping: {name!r}")


def kalshi_subaccount_row_name(subaccount_number: int) -> str:
    return KALSHI_SUBACCOUNT_NUMBER_TO_NAME.get(
        int(subaccount_number),
        f"undefined_{int(subaccount_number)}",
    )


def apply_subaccount_transfer(
    user_no: str,
    from_subaccount: int,
    to_subaccount: int,
    amount_cents: int,
    client_transfer_id: str,
) -> None:
    """
    POST /portfolio/subaccounts/transfer.

    Raises on API or credential failure.
    """
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    body = {
        "client_transfer_id": str(client_transfer_id),
        "from_subaccount": int(from_subaccount),
        "to_subaccount": int(to_subaccount),
        "amount_cents": int(amount_cents),
    }
    resp = kalshi_prod_request(
        user_no,
        "POST",
        "/portfolio/subaccounts/transfer",
        json_body=body,
    )
    resp.raise_for_status()
