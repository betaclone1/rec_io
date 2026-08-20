"""Shard-aware transferable balance from Kalshi matrix rows."""

from unittest.mock import MagicMock, patch

from backend.bookkeeper.kalshi_portfolio_balance import fetch_subaccount_transferable_cents


@patch("backend.bookkeeper.kalshi_portfolio_balance.kalshi_prod_request")
def test_transferable_cents_filters_by_exchange_index(mock_req):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "subaccount_balances": [
            {"subaccount_number": 1, "exchange_index": 0, "balance": "100.5072"},
            {"subaccount_number": 1, "exchange_index": 2, "balance": "1.0000"},
        ]
    }
    mock_req.return_value = resp
    assert fetch_subaccount_transferable_cents("0001", 1, exchange_index=0) == 10050
    assert fetch_subaccount_transferable_cents("0001", 1, exchange_index=2) == 100


@patch("backend.bookkeeper.kalshi_portfolio_balance.kalshi_prod_request")
def test_transferable_cents_missing_pair_returns_zero(mock_req):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "subaccount_balances": [
            {"subaccount_number": 1, "exchange_index": 0, "balance": "10.00"},
        ]
    }
    mock_req.return_value = resp
    assert fetch_subaccount_transferable_cents("0001", 1, exchange_index=2) == 0
