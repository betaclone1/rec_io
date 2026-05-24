"""Live Kalshi subaccount → users.subaccounts_* sync helpers."""

from unittest.mock import MagicMock

from psycopg2 import sql as psql

import backend.balance_snapshot as balance_snapshot
import backend.kalshi_account_sync_ws as account_sync
import backend.trading_mode as trading_mode


def _sql_ident_fqn(fqn: str):
    sch, tbl = fqn.split(".", 1)
    return psql.SQL("{}.{}").format(psql.Identifier(sch), psql.Identifier(tbl))


def test_fetch_kalshi_subaccount_balances_cents(monkeypatch):
    monkeypatch.setattr(
        account_sync,
        "_kas_process_user_no",
        lambda: "0001",
    )

    def _fake_fetch(user_no):
        assert user_no == "0001"
        return {0: 1050, 1: 525}

    import backend.bookkeeper.kalshi_portfolio_balance as kpb

    monkeypatch.setattr(kpb, "fetch_subaccount_balances_cents_map", _fake_fetch)
    assert account_sync._fetch_kalshi_subaccount_balances_cents() == {0: 1050, 1: 525}


def test_sync_subaccounts_from_kalshi_poll_updates_rows(monkeypatch):
    monkeypatch.setattr(
        balance_snapshot,
        "refresh_mtb_realized_pnl_from_balance",
        lambda cursor, table: 50000,
    )
    monkeypatch.setattr(
        trading_mode,
        "sql_ident_qualified_table",
        _sql_ident_fqn,
    )
    cursor = MagicMock()
    mtb = account_sync._sync_subaccounts_from_kalshi_poll(
        cursor,
        "users.subaccounts_0001",
        {0: 100, 1: 50000, 2: 0},
    )
    assert mtb == 50000
    assert cursor.execute.call_count == 3


def test_refresh_mtb_realized_pnl_from_balance():
    class Cur:
        def __init__(self):
            self.calls = []
            self._fetch = [(52000, 50000)]

        def execute(self, q, p=None):
            self.calls.append((str(q), p))

        def fetchone(self):
            if self._fetch:
                return self._fetch.pop(0)
            return None

    cur = Cur()
    out = balance_snapshot.refresh_mtb_realized_pnl_from_balance(cur, "users.subaccounts_0001")
    assert out == 52000
    assert cur.calls[-1][1] == (2000, 0.04)
