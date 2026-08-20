"""Automatic MTB rake → CASH (Kalshi #1 → #0 on live)."""

from unittest.mock import MagicMock, patch

from backend.balance_snapshot import (
    AUTOMATIC_MTB_RAKE_TO_SUBACCOUNT,
    apply_balance_snapshot,
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
    # base 50000, home-shard balance 56000 → 12% pnl; target 11%, transfer_amt 0.10 → 5000 cents
    # row: balance, base, target, transfer_amt, auto, e0, e1, e2, e3
    cur = _MtbCursor((56000, 50000, 0.11, 0.10, True, 56000, 0, 0, 0))
    amt = compute_automatic_mtb_rake_amount_cents(cur, "users_0001.subaccounts_0001")
    assert amt == 5000


def test_compute_automatic_mtb_rake_none_when_disabled():
    cur = _MtbCursor((56000, 50000, 0.11, 0.10, False, 56000, 0, 0, 0))
    assert compute_automatic_mtb_rake_amount_cents(cur, "users_0001.subaccounts_0001") is None


def test_compute_automatic_mtb_rake_none_when_below_target():
    cur = _MtbCursor((54000, 50000, 0.11, 0.10, True, 54000, 0, 0, 0))
    assert compute_automatic_mtb_rake_amount_cents(cur, "users_0001.subaccounts_0001") is None


def test_compute_automatic_mtb_rake_uses_home_shard_cash_not_sum():
    # Sum balance would meet target, but home shard 0 cash does not.
    cur = _MtbCursor((56000, 50000, 0.11, 0.10, True, 100, 0, 55900, 0))
    assert compute_automatic_mtb_rake_amount_cents(
        cur, "users_0001.subaccounts_0001", home_exchange_index=0
    ) is None
    # Home shard 2 has the large cash → rake fires, capped to home cash if needed
    amt = compute_automatic_mtb_rake_amount_cents(
        cur, "users_0001.subaccounts_0001", home_exchange_index=2
    )
    assert amt == 5000


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
    args, kwargs = mock_xfer.call_args
    assert args[0] == "0001"
    assert args[1] == 1
    assert args[2] == 0
    assert args[3] == 2500
    assert kwargs.get("exchange_index") == 0
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


@patch("backend.balance_snapshot.get_drawdown_trading_controls", return_value=(False, 50))
@patch("backend.balance_snapshot.get_mtb_snapshot_from_subaccounts", return_value=(51000, 50500))
def test_force_bankroll_to_mtb_base_sets_bankroll_current_to_new_base(_snap, _dd):
    """After rake, sticky high-water bankroll must reset to the new MTB base_value."""

    class Cur:
        def __init__(self):
            self.calls = []
            # prev portfolio, prev bankroll_current (sticky high-water)
            self._fetch = [(56000, 56000)]

        def execute(self, q, p=None):
            self.calls.append((str(q), p))

        def fetchone(self):
            if self._fetch:
                return self._fetch.pop(0)
            return None

    cur = Cur()
    inserted, stepped = apply_balance_snapshot(
        cur,
        balance_amount=51000,
        portfolio_value_raw=0,
        positions_value=0,
        total_exposure=0,
        portfolio_value=51000,
        account_balance_table="users_0001.account_balance_0001",
        subaccounts_table="users_0001.subaccounts_0001",
        current_timestamp="2026-07-12T12:00:00",
        throttle=False,
        record_internal_transfers=False,
        live_mtb_balance_cents=51000,
        force_bankroll_to_mtb_base=True,
        notify_frontend=False,
        notify_monitors=False,
    )
    assert inserted is True
    assert stepped is False
    insert_calls = [c for c in cur.calls if "INSERT INTO" in c[0]]
    assert insert_calls
    # INSERT args: balance, exposure, positions, portfolio, bankroll_current, ...
    assert insert_calls[0][1][4] == 50500


@patch("backend.balance_snapshot.get_drawdown_trading_controls", return_value=(False, 50))
@patch(
    "backend.balance_snapshot.subaccounts_update",
    return_value=(51000, True),
)
@patch("backend.balance_snapshot.get_mtb_snapshot_from_subaccounts", return_value=(51000, 50500))
def test_paper_transfer_triggered_sets_bankroll_to_new_base(_snap, _su, _dd):
    class Cur:
        def __init__(self):
            self.calls = []
            self._fetch = [(56000, 56000)]

        def execute(self, q, p=None):
            self.calls.append((str(q), p))

        def fetchone(self):
            if self._fetch:
                return self._fetch.pop(0)
            return None

    cur = Cur()
    inserted, _ = apply_balance_snapshot(
        cur,
        balance_amount=51000,
        portfolio_value_raw=0,
        positions_value=0,
        total_exposure=0,
        portfolio_value=51000,
        account_balance_table="users_0001.account_balance_paper_0001",
        subaccounts_table="users_0001.subaccounts_paper_0001",
        current_timestamp="2026-07-12T12:00:00",
        throttle=False,
        record_internal_transfers=True,
        notify_frontend=False,
        notify_monitors=False,
    )
    assert inserted is True
    insert_calls = [c for c in cur.calls if "INSERT INTO" in c[0]]
    assert insert_calls[0][1][4] == 50500


@patch("backend.balance_snapshot.get_drawdown_trading_controls", return_value=(False, 50))
@patch("backend.balance_snapshot.get_mtb_snapshot_from_subaccounts", return_value=(757037, 750000))
def test_force_bankroll_current_cents_mirrors_without_sticky(_snap, _dd):
    """Hero aggregate must accept a lower sab #1 bankroll_current (no re-sticky)."""

    class Cur:
        def __init__(self):
            self.calls = []
            self._fetch = [(1520382, 815694)]

        def execute(self, q, p=None):
            self.calls.append((str(q), p))

        def fetchone(self):
            if self._fetch:
                return self._fetch.pop(0)
            return None

    cur = Cur()
    inserted, _ = apply_balance_snapshot(
        cur,
        balance_amount=100000,
        portfolio_value_raw=0,
        positions_value=0,
        total_exposure=0,
        portfolio_value=1520382,
        account_balance_table="users_0001.account_balance_0001",
        subaccounts_table="users_0001.subaccounts_0001",
        current_timestamp="2026-07-12T12:00:00",
        throttle=False,
        record_internal_transfers=False,
        live_mtb_balance_cents=757037,
        force_bankroll_current_cents=757037,
        notify_frontend=False,
        notify_monitors=False,
    )
    assert inserted is True
    insert_calls = [c for c in cur.calls if "INSERT INTO" in c[0]]
    assert insert_calls[0][1][4] == 757037
