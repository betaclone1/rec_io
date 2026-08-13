"""CASH→MTB manual funding transfer helpers."""

from unittest.mock import MagicMock, patch

import pytest

import backend.balance_snapshot as bs


def test_is_cash_to_mtb_funding_transfer():
    assert bs.is_cash_to_mtb_funding_transfer("CASH", "Master Trading Bankroll") is True
    assert bs.is_cash_to_mtb_funding_transfer("PRIMARY", "Master Trading Bankroll") is True
    assert bs.is_cash_to_mtb_funding_transfer("Master Trading Bankroll", "CASH") is False
    assert bs.is_cash_to_mtb_funding_transfer("CASH", "undefined_2") is False


def test_bump_mtb_base_value_for_cash_funding_raises_without_mtb():
    class Cur:
        def execute(self, q, p=None):
            pass

        def fetchone(self):
            return None

    cur = Cur()
    with patch.object(bs, "get_mtb_snapshot_from_subaccounts", return_value=(None, None)):
        with pytest.raises(ValueError, match="not found"):
            bs.bump_mtb_base_value_for_cash_funding(cur, "users_0001.subaccounts_0001", 5000)


def test_bump_mtb_base_value_for_cash_funding_increments_base():
    class Cur:
        def __init__(self):
            self.calls = []

        def execute(self, q, p=None):
            self.calls.append((str(q), p))

    cur = Cur()
    with patch.object(bs, "get_mtb_snapshot_from_subaccounts", return_value=(50_000, 40_000)):
        new_base = bs.bump_mtb_base_value_for_cash_funding(
            cur, "users_0001.subaccounts_0001", 10_000
        )
    assert new_base == 50_000
    assert cur.calls
    _sql, params = cur.calls[-1]
    assert params[0] == 50_000  # new base_value
    assert params[1] == 0  # realized_pnl: 50000 - 50000
    assert params[2] == 0.0  # realized_pnl_pct


def test_poll_live_account_balances_skips_rake_when_requested(monkeypatch):
    calls = {"rake": 0, "write": 0}

    def fake_rake(cursor, user_no, *, subaccounts_table):
        calls["rake"] += 1
        return False

    def fake_write(*args, **kwargs):
        calls["write"] += 1
        return True, False

    monkeypatch.setattr(
        "backend.kalshi_account_sync_ws._sync_subaccounts_from_kalshi_poll",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(bs, "refresh_mtb_realized_pnl_from_balance", lambda *a, **k: 100)
    monkeypatch.setattr(bs, "maybe_execute_live_automatic_mtb_rake", fake_rake)
    monkeypatch.setattr(bs, "_write_polled_subaccount_balances", fake_write)
    monkeypatch.setattr(bs, "_subaccount_numbers_from_subaccounts_table", lambda *a, **k: [0, 1])
    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_subaccount_balances_matrix",
        lambda user_no: {
            0: {"balance_cents": 100, "exchange_balances_cents": {0: 100}},
            1: {"balance_cents": 200, "exchange_balances_cents": {0: 200}},
        },
    )
    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_portfolio_balance_detail",
        lambda user_no, subaccount=0: {
            "balance_cents": 100,
            "portfolio_value_cents": 0,
            "total_portfolio_cents": 100,
        },
    )

    class Cur:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    bs.poll_live_account_balances(
        Cur(),
        "0001",
        throttle=False,
        skip_automatic_mtb_rake=True,
    )
    assert calls["rake"] == 0
    assert calls["write"] == 1


def test_poll_live_account_balances_runs_rake_by_default(monkeypatch):
    calls = {"rake": 0}

    def fake_rake(cursor, user_no, *, subaccounts_table):
        calls["rake"] += 1
        return False

    monkeypatch.setattr(
        "backend.kalshi_account_sync_ws._sync_subaccounts_from_kalshi_poll",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(bs, "refresh_mtb_realized_pnl_from_balance", lambda *a, **k: 100)
    monkeypatch.setattr(bs, "maybe_execute_live_automatic_mtb_rake", fake_rake)
    monkeypatch.setattr(bs, "_write_polled_subaccount_balances", lambda *a, **k: (True, False))
    monkeypatch.setattr(bs, "_subaccount_numbers_from_subaccounts_table", lambda *a, **k: [0, 1])
    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_subaccount_balances_matrix",
        lambda user_no: {
            0: {"balance_cents": 100, "exchange_balances_cents": {0: 100}},
            1: {"balance_cents": 200, "exchange_balances_cents": {0: 200}},
        },
    )
    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_portfolio_balance_detail",
        lambda user_no, subaccount=0: {
            "balance_cents": 100,
            "portfolio_value_cents": 0,
            "total_portfolio_cents": 100,
        },
    )

    class Cur:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    bs.poll_live_account_balances(Cur(), "0001", throttle=False)
    assert calls["rake"] == 1
