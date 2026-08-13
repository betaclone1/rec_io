"""Kalshi subaccount balance matrix (exchange_index × subaccount)."""

from backend.bookkeeper import kalshi_portfolio_balance as kpb


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_subaccount_balances_matrix_sums_shards(monkeypatch):
    payload = {
        "subaccount_balances": [
            {"subaccount_number": 0, "exchange_index": 0, "balance": "10.00"},
            {"subaccount_number": 1, "exchange_index": 0, "balance": "100.00"},
            {"subaccount_number": 1, "exchange_index": 1, "balance": "1.00"},
            {"subaccount_number": 0, "exchange_index": 1, "balance": "2.00"},
        ]
    }
    monkeypatch.setattr(
        kpb,
        "kalshi_prod_request",
        lambda *a, **k: _Resp(payload),
    )
    matrix = kpb.fetch_subaccount_balances_matrix("0001")
    assert matrix[0]["balance_cents"] == 1200
    assert matrix[0]["exchange_balances_cents"] == {0: 1000, 1: 200}
    assert matrix[1]["balance_cents"] == 10100
    assert matrix[1]["exchange_balances_cents"] == {0: 10000, 1: 100}


def test_fetch_subaccount_balances_cents_map_sums(monkeypatch):
    monkeypatch.setattr(
        kpb,
        "fetch_subaccount_balances_matrix",
        lambda user_no: {
            0: {"balance_cents": 1200, "exchange_balances_cents": {0: 1000, 1: 200}},
            1: {"balance_cents": 10100, "exchange_balances_cents": {0: 10000, 1: 100}},
        },
    )
    assert kpb.fetch_subaccount_balances_cents_map("0001") == {0: 1200, 1: 10100}
