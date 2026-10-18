"""Maker Edge membership + limit resolution."""

from __future__ import annotations

from backend.core.aes_btc15m_maker_edge_cutout import (
    STRATEGY_NAME,
    filter_maker_edge_rows_only,
    filter_out_maker_edge_rows,
    is_maker_edge_row,
    resolve_monitor_limit_dollars,
    row_matches_maker_edge_fields,
)
from backend.core.maker_edge_kalshi import v2_price_for_limit_side


def test_membership_exact():
    assert is_maker_edge_row(
        {"symbol": "BTC", "market": "15m", "strategy": "Maker Edge"}
    )
    assert row_matches_maker_edge_fields(
        symbol="btc", market="15M", strategy="Maker Edge"
    )
    assert STRATEGY_NAME == "Maker Edge"


def test_membership_rejects_near_misses():
    assert not is_maker_edge_row(
        {"symbol": "ETH", "market": "15m", "strategy": "Maker Edge"}
    )
    assert not is_maker_edge_row(
        {"symbol": "BTC", "market": "hourly", "strategy": "Maker Edge"}
    )
    assert not is_maker_edge_row(
        {"symbol": "BTC", "market": "15m", "strategy": "High Water Scalp"}
    )


def test_filters_partition():
    rows = [
        {"monitor_id": "1", "symbol": "BTC", "market": "15m", "strategy": "Maker Edge"},
        {"monitor_id": "2", "symbol": "BTC", "market": "15m", "strategy": "Rising Devil"},
        {"monitor_id": "3", "symbol": "BTC", "market": "15m", "strategy": "Expiration Scalp"},
    ]
    only = filter_maker_edge_rows_only(rows)
    rest = filter_out_maker_edge_rows(rows)
    assert [r["monitor_id"] for r in only] == ["1"]
    assert [r["monitor_id"] for r in rest] == ["2", "3"]


def test_resolve_limit_requires_agreement():
    assert resolve_monitor_limit_dollars({"min_ask": 0.01, "max_ask": 0.01}) == 0.01
    assert resolve_monitor_limit_dollars({"min_ask": 0.01, "max_ask": 0.02}) is None
    assert resolve_monitor_limit_dollars({"min_ask": 0.05, "max_ask": None}) == 0.05


def test_v2_price_bid_ask_same_limit():
    assert v2_price_for_limit_side(side="bid", limit_dollars=0.01) == "0.0100"
    assert v2_price_for_limit_side(side="ask", limit_dollars=0.01) == "0.9900"


def test_maker_edge_auto_trade_status():
    from backend.maker_edge_agent import determine_maker_edge_auto_trade_status

    assert (
        determine_maker_edge_auto_trade_status(
            auto_trade=False,
            limit_px=0.01,
            contracts=2500,
            ttc=500,
            min_time=0,
            max_time=900,
        )
        == "DISABLED"
    )
    assert (
        determine_maker_edge_auto_trade_status(
            auto_trade=True,
            limit_px=None,
            contracts=2500,
            ttc=500,
            min_time=0,
            max_time=900,
        )
        == "DISABLED"
    )
    assert (
        determine_maker_edge_auto_trade_status(
            auto_trade=True,
            limit_px=0.01,
            contracts=2500,
        )
        == "ACTIVE"
    )
    # open_time placement: TTC is not a gate — still ACTIVE when configured
    assert (
        determine_maker_edge_auto_trade_status(
            auto_trade=True,
            limit_px=0.01,
            contracts=2500,
            ttc=None,
            min_time=0,
            max_time=900,
        )
        == "ACTIVE"
    )
    assert (
        determine_maker_edge_auto_trade_status(
            auto_trade=True,
            limit_px=0.01,
            contracts=2500,
            ttc=50,
            min_time=100,
            max_time=900,
        )
        == "ACTIVE"
    )
