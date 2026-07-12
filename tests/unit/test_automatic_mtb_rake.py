"""Automatic MTB rake → CASH (Kalshi #1 → #0 on live)."""

from unittest.mock import MagicMock, patch

from backend.balance_snapshot import (
    AUTOMATIC_MTB_RAKE_TO_SUBACCOUNT,
    compute_automatic_mtb_rake_amount_cents,
    maybe_execute_live_automatic_mtb_rake,
)


class _MtbCursor:
    def __init__(self, row):
        self._row = row
        self.executed = []

    def execute(self, q, p=None):
        self.executed.append((str(q), p))

    def fetchone(self):
        return self._row


def test_compute_automatic_mtb_rake_amount_when_target_met():
    # base 50000, balance 56000 → 12% pnl; target 11%, transfer_amt 0.10 → 5000 cents
    cur = _MtbCursor((56000, 50000, 0.11, 0.10, True))
    amt = compute_automatic_mtb_rake_amount_cents(cur, "users_0001.subaccounts_0001")
    assert amt == 5000


def test_compute_automatic_mtb_rake_none_when_disabled():
    cur = _MtbCursor((56000, 50000, 0.11, 0.10, False))
    assert compute_automatic_mtb_rake_amount_cents(cur, "users_0001.subaccounts_0001") is None


def test_compute_automatic_mtb_rake_none_when_below_target():
    cur = _MtbCursor((54000, 50000, 0.11, 0.10, True))
    assert compute_automatic_mtb_rake_amount_cents(cur, "users_0001.subaccounts_0001") is None


@patch("backend.balance_snapshot.apply_automatic_mtb_rake_post_transfer_db")
@patch("backend.bookkeeper.kalshi_subaccount_transfer.apply_subaccount_transfer")
@patch("backend.balance_snapshot.refresh_mtb_realized_pnl_from_balance")
@patch("backend.balance_snapshot.compute_automatic_mtb_rake_amount_cents", return_value=2500)
@patch("backend.balance_snapshot.get_mtb_snapshot_from_subaccounts", return_value=(10000, 5000))
@patch("backend.balance_snapshot._live_automatic_mtb_rake_host_allowed", return_value=True)
def test_maybe_execute_live_automatic_mtb_rake_calls_kalshi_1_to_0(
    _host_ok,
    _snap,
    _compute,
    _refresh,
    mock_xfer,
    mock_post_db,
):
    cur = MagicMock()
    assert maybe_execute_live_automatic_mtb_rake(cur, "0001", subaccounts_table="users_0001.subaccounts_0001")
    mock_xfer.assert_called_once()
    args = mock_xfer.call_args[0]
    assert args[0] == "0001"
    assert args[1] == 1
    assert args[2] == 0
    assert args[3] == 2500
    mock_post_db.assert_called_once()
    assert mock_post_db.call_args[0][2] == 2500  # transfer_amount
    assert mock_post_db.call_args[0][3] == 7500  # new_mtb_balance
    assert mock_post_db.call_args[1].get("to_subaccount", AUTOMATIC_MTB_RAKE_TO_SUBACCOUNT) == "CASH"


@patch("backend.bookkeeper.kalshi_subaccount_transfer.apply_subaccount_transfer")
@patch("backend.balance_snapshot._live_automatic_mtb_rake_host_allowed", return_value=False)
def test_maybe_execute_live_automatic_mtb_rake_blocked_off_production(mock_host, mock_xfer):
    cur = MagicMock()
    assert not maybe_execute_live_automatic_mtb_rake(
        cur, "0001", subaccounts_table="users_0001.subaccounts_0001"
    )
    mock_xfer.assert_not_called()
