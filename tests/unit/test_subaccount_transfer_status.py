"""Subaccount transfer row semantics."""

from __future__ import annotations

from psycopg2 import sql

from backend.web.routers.subaccount_routes import _insert_manual_transfer_row


class _Cursor:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, query, params=None) -> None:
        self.calls.append((query, params))


def test_manual_internal_transfer_rows_are_marked_applied() -> None:
    cur = _Cursor()

    _insert_manual_transfer_row(
        cur,
        xfer_ident=sql.Identifier("users_0001", "transfers_0001"),
        transfer_timestamp_est="2026-07-15 13:45:00",
        from_name="CASH",
        to_name="Master Trading Bankroll",
        amount_cents=12345,
    )

    assert len(cur.calls) == 1
    _query, params = cur.calls[0]
    assert params == (
        "2026-07-15 13:45:00",
        "internal",
        "CASH",
        "Master Trading Bankroll",
        12345,
        "manual",
        "applied",
    )
