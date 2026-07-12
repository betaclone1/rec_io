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


def test_sync_subaccounts_from_kalshi_poll_updates_by_id(monkeypatch):
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
    cursor.rowcount = 1
    mtb = account_sync._sync_subaccounts_from_kalshi_poll(
        cursor,
        "users.subaccounts_0001",
        {0: 100, 1: 50000, 2: 0},
    )
    assert mtb == 50000
    # One UPDATE per Kalshi number; match key is id, not label.
    assert cursor.execute.call_count == 3
    for call, expected_id in zip(cursor.execute.call_args_list, (0, 1, 2)):
        assert call.args[1][1] == expected_id


def test_upsert_subaccount_balance_inserts_with_kalshi_id_not_max_plus_one(monkeypatch):
    monkeypatch.setattr(
        trading_mode,
        "sql_ident_qualified_table",
        _sql_ident_fqn,
    )
    cursor = MagicMock()
    cursor.rowcount = 0  # no existing row for this id
    cursor.fetchone.return_value = (1,)  # setval result
    table_ident = _sql_ident_fqn("users_0001.subaccounts_0001")
    account_sync._upsert_subaccount_balance(
        cursor,
        table_ident,
        "users_0001.subaccounts_0001",
        3,
        42,
    )
    # UPDATE by id, then INSERT with id=3 (Kalshi number), then setval.
    assert cursor.execute.call_count == 3
    insert_call = cursor.execute.call_args_list[1]
    assert insert_call.args[1] == (3, "undefined_3", 42)


def test_upsert_preserves_custom_label_on_update():
    cursor = MagicMock()
    cursor.rowcount = 1
    table_ident = _sql_ident_fqn("users_0001.subaccounts_0001")
    account_sync._upsert_subaccount_balance(
        cursor,
        table_ident,
        "users_0001.subaccounts_0001",
        2,
        99,
    )
    assert cursor.execute.call_count == 1
    args = cursor.execute.call_args.args[1]
    assert args == (99, 2)
    # No INSERT — custom label on id=2 is left alone.


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


def test_subaccount_numbers_from_table_use_id_not_label():
    class Cur:
        def execute(self, q, p=None):
            pass

        def fetchall(self):
            # Custom labels; ids are Kalshi numbers.
            return [(0,), (1,), (2,), (3,)]

    assert balance_snapshot._subaccount_numbers_from_subaccounts_table(
        Cur(), "users_0001.subaccounts_0001"
    ) == [0, 1, 2, 3]
