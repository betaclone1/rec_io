"""Subaccount balance polling orchestrator."""

from unittest.mock import MagicMock

from backend.balance_snapshot import (
    aggregate_account_balance_from_subaccounts,
    apply_balance_snapshot,
)


def test_aggregate_account_balance_from_subaccounts_sums_and_copies_mtb():
    class Cur:
        def __init__(self):
            self._latest = {
                "users_0001.subaccount_balance_0001_0": (
                    10000, 0, 0, 10000, 0, 10000, None, None
                ),
                "users_0001.subaccount_balance_0001_1": (
                    5000, 2000, 2000, 7000, 2000, 55000, 55000, 50000
                ),
            }
            self._hero_prev = [(200000, 55000)]
            self._mtb_sub = [(55000, 50000)]
            self.calls = []

        def execute(self, q, p=None):
            self.calls.append((str(q), p))

        def fetchone(self):
            if self._hero_prev:
                return self._hero_prev.pop(0)
            if self._mtb_sub:
                return self._mtb_sub.pop(0)
            return None

    cur = Cur()

    def fake_latest(cursor, table_fqn):
        row = cur._latest.get(table_fqn)
        if not row:
            return None
        keys = (
            "balance",
            "exposure",
            "positions",
            "portfolio",
            "portfolio_value",
            "bankroll_current",
            "master_trading_bankroll",
            "mtb_base_value",
        )
        return {k: row[i] for i, k in enumerate(keys)}

    import backend.balance_snapshot as bs

    orig = bs._latest_subaccount_balance_row
    bs._latest_subaccount_balance_row = fake_latest
    try:
        inserted, _ = aggregate_account_balance_from_subaccounts(
            cur,
            user_no="0001",
            account_balance_table="users_0001.account_balance_0001",
            subaccount_numbers=[0, 1],
            current_timestamp="2026-05-23T12:00:00",
            throttle=False,
        )
    finally:
        bs._latest_subaccount_balance_row = orig

    assert inserted is True
    insert_calls = [c for c in cur.calls if c[0] and "INSERT INTO" in c[0]]
    assert insert_calls
    vals = insert_calls[-1][1]
    assert vals[0] == 15000  # balance sum
    assert vals[3] == 17000  # portfolio sum
    assert vals[4] == 55000  # bankroll from MTB subaccount 1


def test_parse_user_number_subaccount_balance_table():
    from backend.core.system_settings_store import parse_user_number_from_account_balance_table

    assert parse_user_number_from_account_balance_table("users_0001.subaccount_balance_0001_3") == "0001"
    assert parse_user_number_from_account_balance_table("users_0001.subaccount_balance_0001_0") == "0001"
    assert parse_user_number_from_account_balance_table("users_0001.account_balance_0001") == "0001"


def test_apply_balance_snapshot_subaccount_table_slot_match():
    """subaccount_balance FQN must not be parsed as user slot 0/3."""
    class Cur:
        def __init__(self):
            self.calls = []
            self._fetch = [None, (50000, 50000), (50000, 40000)]

        def execute(self, q, p=None):
            self.calls.append((str(q), p))

        def fetchone(self):
            if self._fetch:
                return self._fetch.pop(0)
            return None

    cur = Cur()
    inserted, _ = apply_balance_snapshot(
        cur,
        balance_amount=1000,
        portfolio_value_raw=0,
        positions_value=0,
        total_exposure=0,
        portfolio_value=1000,
        account_balance_table="users_0001.subaccount_balance_0001_0",
        subaccounts_table="users_0001.subaccounts_0001",
        current_timestamp="2026-05-23T12:00:00",
        throttle=False,
        record_internal_transfers=False,
        notify_frontend=False,
        notify_monitors=False,
    )
    assert inserted is True
    insert_calls = [c for c in cur.calls if "INSERT INTO" in c[0]]
    assert insert_calls


def test_fetch_portfolio_balance_detail_subaccount_query(monkeypatch):
    captured = {}

    def fake_request(user_no, method, path, *, params=None, **kwargs):
        captured["path"] = path
        captured["params"] = params
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"balance": 100, "portfolio_value": 50}
        return resp

    import backend.bookkeeper.kalshi_portfolio_balance as kpb

    monkeypatch.setattr(kpb, "kalshi_prod_request", fake_request)
    detail = kpb.fetch_portfolio_balance_detail("0001", subaccount=2)
    assert captured["path"] == "/portfolio/balance"
    assert captured["params"] == {"subaccount": 2}
    assert detail == {
        "balance_cents": 100,
        "portfolio_value_cents": 50,
        "total_portfolio_cents": 150,
    }
