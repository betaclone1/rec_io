"""Subaccount label → Kalshi number resolution (display labels may be renamed)."""

from unittest.mock import MagicMock

from psycopg2 import sql as psql

from backend.web.routers.subaccount_routes import _subaccount_kalshi_number_for_label


def _ident():
    return psql.SQL("{}.{}").format(
        psql.Identifier("users_0001"),
        psql.Identifier("subaccounts_0001"),
    )


def test_cash_aliases_map_to_zero_without_db():
    cursor = MagicMock()
    assert _subaccount_kalshi_number_for_label(cursor, _ident(), "CASH") == 0
    assert _subaccount_kalshi_number_for_label(cursor, _ident(), "PRIMARY") == 0
    cursor.execute.assert_not_called()


def test_custom_label_resolves_via_row_id():
    cursor = MagicMock()
    cursor.fetchone.return_value = (2,)
    assert _subaccount_kalshi_number_for_label(cursor, _ident(), "Reserve") == 2
    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[1] == ("Reserve",)


def test_missing_label_returns_none():
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    assert _subaccount_kalshi_number_for_label(cursor, _ident(), "No Such") is None
