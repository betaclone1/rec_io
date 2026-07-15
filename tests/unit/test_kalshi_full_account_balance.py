"""Full-account Kalshi total for bookkeeper: balance_breakdown + subaccount confirm."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import backend.bookkeeper.kalshi_portfolio_balance as kpb


def test_sum_balance_breakdown_cents() -> None:
    data = {
        "balance": 150376,
        "balance_dollars": "1503.7600",
        "balance_breakdown": [{"balance": "15392.6093", "exchange_index": 0}],
        "portfolio_value": 0,
    }
    assert kpb.sum_balance_breakdown_cents(data) == 1539261


def test_sum_balance_breakdown_rejects_missing() -> None:
    with pytest.raises(ValueError, match="balance_breakdown"):
        kpb.sum_balance_breakdown_cents({"balance": 150376, "balance_dollars": "1503.7600"})


def test_fetch_total_portfolio_cents_uses_breakdown_and_confirms(monkeypatch) -> None:
    def fake_request(user_no, method, path, *, params=None, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if path == "/portfolio/balance":
            resp.json.return_value = {
                "balance": 150376,
                "balance_dollars": "1503.7600",
                "balance_breakdown": [{"balance": "15392.6093", "exchange_index": 0}],
                "portfolio_value": 0,
            }
        else:
            raise AssertionError(f"unexpected path {path}")
        return resp

    monkeypatch.setattr(kpb, "kalshi_prod_request", fake_request)
    monkeypatch.setattr(
        kpb,
        "fetch_subaccount_balances_cents_map",
        lambda user_no: {0: 150376, 1: 700727, 2: 688158, 3: 0},
    )

    total, detail = kpb.fetch_total_portfolio_cents("0001")
    assert total == 1539261
    assert detail["balance_cents"] == 1539261
    assert detail["portfolio_value_cents"] == 0
    assert detail["subaccount_sum_cents"] == 1539261
    assert detail["legacy_top_level_balance_cents"] == 150376


def test_fetch_total_portfolio_cents_mismatch_raises(monkeypatch) -> None:
    def fake_request(user_no, method, path, *, params=None, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "balance_breakdown": [{"balance": "100.00", "exchange_index": 0}],
            "portfolio_value": 0,
            "balance": 50,
        }
        return resp

    monkeypatch.setattr(kpb, "kalshi_prod_request", fake_request)
    monkeypatch.setattr(
        kpb,
        "fetch_subaccount_balances_cents_map",
        lambda user_no: {0: 5000, 1: 6000},
    )

    with pytest.raises(RuntimeError, match="mismatch"):
        kpb.fetch_total_portfolio_cents("0001")


def test_fetch_total_portfolio_cents_subaccounts_required(monkeypatch) -> None:
    def fake_request(user_no, method, path, *, params=None, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "balance_breakdown": [{"balance": "10.00"}],
            "portfolio_value": 0,
            "balance": 1000,
        }
        return resp

    monkeypatch.setattr(kpb, "kalshi_prod_request", fake_request)
    monkeypatch.setattr(kpb, "fetch_subaccount_balances_cents_map", lambda user_no: None)

    with pytest.raises(RuntimeError, match="subaccount"):
        kpb.fetch_total_portfolio_cents("0001")
