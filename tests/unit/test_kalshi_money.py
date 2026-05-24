from backend.core.kalshi_money import (
    dollars_to_cents,
    normalize_kalshi_subaccount_balance_row,
    normalize_kalshi_subaccount_balances_response,
)


def test_dollars_to_cents_subaccount_style():
    assert dollars_to_cents("1533.9800") == 153398
    assert dollars_to_cents("0.0000") == 0


def test_dollars_to_cents_none_and_empty():
    assert dollars_to_cents(None) is None
    assert dollars_to_cents("") is None


def test_normalize_subaccount_balance_row():
    row = {"subaccount_number": 0, "balance": "1533.9800", "updated_ts": 1}
    out = normalize_kalshi_subaccount_balance_row(row)
    assert out["balance"] == 153398
    assert out["balance_dollars"] == "1533.9800"
    assert out["subaccount_number"] == 0


def test_normalize_subaccount_balances_response():
    payload = {
        "subaccount_balances": [
            {"balance": "1533.9800", "subaccount_number": 0},
            {"balance": "0.0000", "subaccount_number": 1},
        ]
    }
    out = normalize_kalshi_subaccount_balances_response(payload)
    assert out["subaccount_balances"][0]["balance"] == 153398
    assert out["subaccount_balances"][1]["balance"] == 0


def test_normalize_preserves_integer_cents():
    row = {"subaccount_number": 0, "balance": 153398}
    out = normalize_kalshi_subaccount_balance_row(row)
    assert out["balance"] == 153398
    assert "balance_dollars" not in out
