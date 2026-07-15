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


def test_fetch_total_portfolio_cents_tolerates_one_cent_rounding(monkeypatch) -> None:
    # Two Kalshi partitions of the same money can round differently by ~1 cent;
    # this must NOT abort the reconcile.
    def fake_request(user_no, method, path, *, params=None, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "balance_breakdown": [
                {"balance": "1503.7600", "exchange_index": 0},
                {"balance": "5720.8000", "exchange_index": 1},
                {"balance": "6881.5700", "exchange_index": 2},
            ],
            "portfolio_value": 0,
            "balance": 150376,
        }
        return resp

    monkeypatch.setattr(kpb, "kalshi_prod_request", fake_request)
    # subaccount sum is 1 cent higher than the breakdown sum
    monkeypatch.setattr(
        kpb,
        "fetch_subaccount_balances_cents_map",
        lambda user_no: {0: 150376, 1: 572080, 2: 688158, 3: 0},
    )

    total, detail = kpb.fetch_total_portfolio_cents("0001")
    assert detail["balance_cents"] == 1410613
    assert detail["subaccount_sum_cents"] == 1410614
    assert detail["subaccount_cross_check_drift_cents"] == 1
    assert total == 1410613


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
