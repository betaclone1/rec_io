"""Taker Edge trigger and entry window."""

from __future__ import annotations

from backend.core.taker_edge import (
    STRATEGY_NAME,
    floor_strike_from_market,
    is_taker_edge_row,
    taker_edge_side_from_print,
    ttc_in_entry_window,
)


def test_membership():
    assert is_taker_edge_row(
        {"symbol": "ETH", "market": "15m", "strategy": "Taker Edge"}
    )
    assert not is_taker_edge_row(
        {"symbol": "ETH", "market": "15m", "strategy": "Maker Edge"}
    )
    assert STRATEGY_NAME == "Taker Edge"


def test_floor_strike_from_market_requires_api_field():
    assert floor_strike_from_market({"floor_strike": 4118.65}) == 4118.65
    assert floor_strike_from_market({"ticker": "KXETH15M-X"}) is None
    assert floor_strike_from_market(None) is None


def test_side_from_print_high_end():
    assert (
        taker_edge_side_from_print(yes_price=0.99, no_price=0.01, limit_px=0.99)
        == "yes"
    )
    assert (
        taker_edge_side_from_print(yes_price=0.01, no_price=0.995, limit_px=0.99)
        == "no"
    )
    assert (
        taker_edge_side_from_print(yes_price=0.50, no_price=0.50, limit_px=0.99)
        is None
    )
    assert (
        taker_edge_side_from_print(yes_price=0.99, no_price=0.99, limit_px=0.99)
        is None
    )


def test_book_stamps_ladder_prob_diff_when_present():
    from unittest.mock import patch

    import backend.taker_edge_agent as te

    cy = te._Cycle(
        monitor_id="99029",
        symbol="ETH",
        ticker="KXETH15M-26OCT202230-30",
        event_ticker="KXETH15M-26OCT202230",
        limit_px=0.99,
        contracts=10,
        subaccount=1,
        paper=True,
        floor_strike=2445.0,
        close_ts=0.0,
        min_time=0,
        max_time=900,
        bankroll_cents=None,
    )
    captured = {}

    class _Resp:
        status_code = 200
        content = b'{"id": 1}'

        def json(self):
            return {"id": 1}

    def _post(url, json=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    with (
        patch.object(te, "_fill_prob_diff", return_value=(77.0, -1.2)),
        patch.object(te.requests, "post", side_effect=_post),
        patch.object(te, "get_port", return_value=8001),
    ):
        assert te._book(cy, side="no", fill_qty=10.0) == 1
    assert captured["payload"]["prob"] == 77.0
    assert captured["payload"]["diff"] == -1.2
    assert captured["payload"]["symbol"] == "ETH"


def test_book_omits_prob_diff_when_ladder_missing():
    from unittest.mock import patch

    import backend.taker_edge_agent as te

    cy = te._Cycle(
        monitor_id="99030",
        symbol="GOLD",
        ticker="KXGOLD15M-26OCT202230-30",
        event_ticker="KXGOLD15M-26OCT202230",
        limit_px=0.99,
        contracts=10,
        subaccount=1,
        paper=True,
        floor_strike=4119.0,
        close_ts=0.0,
        min_time=0,
        max_time=900,
        bankroll_cents=None,
    )
    captured = {}

    class _Resp:
        status_code = 200
        content = b'{"id": 2}'

        def json(self):
            return {"id": 2}

    def _post(url, json=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    with (
        patch.object(te, "_fill_prob_diff", return_value=(None, None)),
        patch.object(te.requests, "post", side_effect=_post),
        patch.object(te, "get_port", return_value=8001),
    ):
        te._book(cy, side="yes", fill_qty=10.0)
    assert "prob" not in captured["payload"]
    assert "diff" not in captured["payload"]


def test_entry_window():
    assert ttc_in_entry_window(ttc=120, min_time=60, max_time=180) is True
    assert ttc_in_entry_window(ttc=30, min_time=60, max_time=180) is False
    assert ttc_in_entry_window(ttc=None, min_time=0, max_time=900) is False
