"""Kalshi subaccount transfers and name ↔ number mapping (live).

Addressing: ``(exchange_index, subaccount_number)``.

- Same shard → ``POST /portfolio/subaccounts/transfer`` with ``exchange_index``.
- Cross shard → single ``POST /portfolio/intra_exchange_instance_transfer`` with
  ``source_subaccount`` / ``destination_subaccount`` (no app-orchestrated hops).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from backend.bookkeeper.kalshi_portfolio_balance import kalshi_prod_request

logger = logging.getLogger(__name__)

# users.subaccounts_* display name → Kalshi subaccount_number
KALSHI_SUBACCOUNT_NAME_TO_NUMBER: dict[str, int] = {
    "CASH": 0,
    "Master Trading Bankroll": 1,
    "undefined_2": 2,
    "Reserve": 2,
    # Legacy labels (pre-migration rows / transfer history display)
    "PRIMARY": 0,
    "Cash Transfer": 2,
    "Cash Reserve": 2,
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


def mtb_home_exchange_index() -> int:
    """Shard where MTB (#1) and automatic rake (#1→#0) run. Default 0; set to 2 at crypto cutover."""
    try:
        return max(0, int(os.environ.get("REC_MTB_HOME_EXCHANGE_INDEX", "0")))
    except (TypeError, ValueError):
        return 0


def cents_to_centicents(amount_cents: int) -> int:
    """Kalshi IAT ``amount`` is centicents ($1 = 10000)."""
    return int(amount_cents) * 100


def apply_subaccount_transfer(
    user_no: str,
    from_subaccount: int,
    to_subaccount: int,
    amount_cents: int,
    client_transfer_id: str,
    *,
    exchange_index: int,
) -> None:
    """
    POST /portfolio/subaccounts/transfer (within one exchange shard).

    Raises on API or credential failure.
    """
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    body = {
        "client_transfer_id": str(client_transfer_id),
        "from_subaccount": int(from_subaccount),
        "to_subaccount": int(to_subaccount),
        "amount_cents": int(amount_cents),
        "exchange_index": int(exchange_index),
    }
    resp = kalshi_prod_request(
        user_no,
        "POST",
        "/portfolio/subaccounts/transfer",
        json_body=body,
    )
    resp.raise_for_status()


def apply_intra_exchange_instance_transfer(
    user_no: str,
    *,
    source_exchange_shard: int,
    destination_exchange_shard: int,
    source_subaccount: int,
    destination_subaccount: int,
    amount_cents: int,
) -> str:
    """
    POST /portfolio/intra_exchange_instance_transfer (cross-shard, single call).

    Amount is converted to centicents. Returns Kalshi ``transfer_id``.
    Processed asynchronously — callers should wait for dest matrix credit.
    """
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    if int(source_exchange_shard) == int(destination_exchange_shard):
        raise ValueError(
            "IAT requires different exchange shards; use apply_subaccount_transfer for same shard"
        )
    body = {
        "source": "event_contract",
        "destination": "event_contract",
        "amount": cents_to_centicents(amount_cents),
        "source_exchange_shard": int(source_exchange_shard),
        "destination_exchange_shard": int(destination_exchange_shard),
        "source_subaccount": int(source_subaccount),
        "destination_subaccount": int(destination_subaccount),
    }
    resp = kalshi_prod_request(
        user_no,
        "POST",
        "/portfolio/intra_exchange_instance_transfer",
        json_body=body,
    )
    resp.raise_for_status()
    data = resp.json() if resp.content else {}
    transfer_id = (data or {}).get("transfer_id")
    if not transfer_id:
        raise RuntimeError(f"IAT response missing transfer_id: {data!r}")
    return str(transfer_id)


def _matrix_pair_cents(matrix: dict[int, dict] | None, exchange_index: int, subaccount: int) -> int:
    if not matrix:
        return 0
    entry = matrix.get(int(subaccount))
    if not entry:
        return 0
    ex_map = entry.get("exchange_balances_cents") or {}
    return int(ex_map.get(int(exchange_index), 0))


def wait_for_kalshi_address_credit(
    user_no: str,
    *,
    exchange_index: int,
    subaccount: int,
    min_cents: int,
    baseline_cents: int | None = None,
    timeout_sec: float | None = None,
    poll_interval_sec: float | None = None,
) -> int:
    """
    Poll balance matrix until ``(exchange_index, subaccount)`` cash is at least ``min_cents``,
    or (if ``baseline_cents`` set) has increased by at least ``min_cents - baseline`` wait target.

    When ``baseline_cents`` is provided, success requires
    ``current >= baseline_cents + expected_delta`` where expected_delta is derived from
    ``min_cents`` as the absolute floor after credit when baseline is omitted; with baseline,
    ``min_cents`` is treated as the **delta** to observe.

    Returns final cents on that address. Raises ``TimeoutError`` if not credited in time.
    """
    from backend.bookkeeper.kalshi_portfolio_balance import fetch_subaccount_balances_matrix

    try:
        timeout = float(
            timeout_sec
            if timeout_sec is not None
            else os.environ.get("REC_IAT_CREDIT_TIMEOUT_SEC", "30")
        )
    except (TypeError, ValueError):
        timeout = 30.0
    try:
        interval = float(
            poll_interval_sec
            if poll_interval_sec is not None
            else os.environ.get("REC_IAT_CREDIT_POLL_SEC", "1.0")
        )
    except (TypeError, ValueError):
        interval = 1.0
    interval = max(0.2, interval)
    deadline = time.monotonic() + max(1.0, timeout)

    target: int
    if baseline_cents is None:
        target = int(min_cents)
    else:
        target = int(baseline_cents) + int(min_cents)

    last = 0
    while True:
        matrix = fetch_subaccount_balances_matrix(user_no)
        last = _matrix_pair_cents(matrix, exchange_index, subaccount)
        if last >= target:
            return last
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Kalshi address ({exchange_index},{subaccount}) credit not observed "
                f"(have={last} need>={target}) within {timeout}s"
            )
        time.sleep(interval)


def transfer_kalshi_address(
    user_no: str,
    *,
    from_exchange: int,
    from_subaccount: int,
    to_exchange: int,
    to_subaccount: int,
    amount_cents: int,
    client_transfer_id: str,
    wait_for_iat_credit: bool = True,
) -> dict[str, Any]:
    """
    Move ``amount_cents`` from ``(from_exchange, from_subaccount)`` to
    ``(to_exchange, to_subaccount)`` in one Kalshi API call (within-shard or IAT).

    Returns ``{"mode": "within_shard"|"iat", "transfer_id": str|None, ...}``.
    """
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    if (
        int(from_exchange) == int(to_exchange)
        and int(from_subaccount) == int(to_subaccount)
    ):
        raise ValueError("from and to addresses must differ")

    from_ex = int(from_exchange)
    to_ex = int(to_exchange)
    from_sub = int(from_subaccount)
    to_sub = int(to_subaccount)

    if from_ex == to_ex:
        apply_subaccount_transfer(
            user_no,
            from_sub,
            to_sub,
            int(amount_cents),
            str(client_transfer_id),
            exchange_index=from_ex,
        )
        return {
            "mode": "within_shard",
            "transfer_id": None,
            "from_exchange": from_ex,
            "from_subaccount": from_sub,
            "to_exchange": to_ex,
            "to_subaccount": to_sub,
            "amount_cents": int(amount_cents),
        }

    from backend.bookkeeper.kalshi_portfolio_balance import fetch_subaccount_balances_matrix

    baseline = _matrix_pair_cents(
        fetch_subaccount_balances_matrix(user_no),
        to_ex,
        to_sub,
    )
    transfer_id = apply_intra_exchange_instance_transfer(
        user_no,
        source_exchange_shard=from_ex,
        destination_exchange_shard=to_ex,
        source_subaccount=from_sub,
        destination_subaccount=to_sub,
        amount_cents=int(amount_cents),
    )
    if wait_for_iat_credit:
        wait_for_kalshi_address_credit(
            user_no,
            exchange_index=to_ex,
            subaccount=to_sub,
            min_cents=int(amount_cents),
            baseline_cents=baseline,
        )
    logger.info(
        "IAT %s: (%s,%s)->(%s,%s) amount_cents=%s",
        transfer_id,
        from_ex,
        from_sub,
        to_ex,
        to_sub,
        amount_cents,
    )
    return {
        "mode": "iat",
        "transfer_id": transfer_id,
        "from_exchange": from_ex,
        "from_subaccount": from_sub,
        "to_exchange": to_ex,
        "to_subaccount": to_sub,
        "amount_cents": int(amount_cents),
    }
