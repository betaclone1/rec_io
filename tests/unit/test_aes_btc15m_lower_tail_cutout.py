"""Lower Tail membership + limit resolution."""

from __future__ import annotations

from backend.core.aes_btc15m_lower_tail_cutout import (
    STRATEGY_NAME,
    filter_lower_tail_rows_only,
    filter_out_lower_tail_rows,
    is_lower_tail_row,
    is_lower_tail_symbol,
    lower_tail_symbols,
    resolve_monitor_limit_dollars,
    row_matches_lower_tail_fields,
)
from backend.core.lower_tail_kalshi import v2_price_for_limit_side

_TRACKED_15M = (
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "DOGE",
    "GOLD",
    "SILVER",
    "WTI",
)


def test_membership_exact(monkeypatch):
    monkeypatch.setattr(
        "backend.core.live_data_level.market_feed_symbols",
        lambda: _TRACKED_15M,
    )
    assert is_lower_tail_row(
        {"symbol": "BTC", "market": "15m", "strategy": "Lower Tail"}
    )
    assert row_matches_lower_tail_fields(
        symbol="btc", market="15M", strategy="Lower Tail"
    )
    assert STRATEGY_NAME == "Lower Tail"


def test_membership_multi_symbol(monkeypatch):
    monkeypatch.setattr(
        "backend.core.live_data_level.market_feed_symbols",
        lambda: _TRACKED_15M,
    )
    for sym in _TRACKED_15M:
        assert is_lower_tail_symbol(sym)
        assert is_lower_tail_row(
            {"symbol": sym, "market": "15m", "strategy": "Lower Tail"}
        )
    assert lower_tail_symbols() == frozenset(_TRACKED_15M)
    assert is_lower_tail_symbol("SOL")
    assert is_lower_tail_symbol("XRP")


def test_membership_rejects_near_misses(monkeypatch):
    monkeypatch.setattr(
        "backend.core.live_data_level.market_feed_symbols",
        lambda: _TRACKED_15M,
    )
    assert not is_lower_tail_row(
        {"symbol": "BTC", "market": "hourly", "strategy": "Lower Tail"}
    )
    assert not is_lower_tail_row(
        {"symbol": "BTC", "market": "15m", "strategy": "High Water Scalp"}
    )
    # Tracked but not in SERIES_15M — not Lower Tail.
    monkeypatch.setattr(
        "backend.core.live_data_level.market_feed_symbols",
        lambda: ("BTC", "FAKE"),
    )
    assert not is_lower_tail_symbol("FAKE")


def test_filters_partition(monkeypatch):
    monkeypatch.setattr(
        "backend.core.live_data_level.market_feed_symbols",
        lambda: _TRACKED_15M,
    )
    rows = [
        {"monitor_id": "1", "symbol": "BTC", "market": "15m", "strategy": "Lower Tail"},
        {"monitor_id": "2", "symbol": "BTC", "market": "15m", "strategy": "Rising Devil"},
        {"monitor_id": "3", "symbol": "BTC", "market": "15m", "strategy": "Expiration Scalp"},
        {"monitor_id": "4", "symbol": "ETH", "market": "15m", "strategy": "Lower Tail"},
        {"monitor_id": "5", "symbol": "GOLD", "market": "15m", "strategy": "Lower Tail"},
        {"monitor_id": "6", "symbol": "SOL", "market": "15m", "strategy": "Lower Tail"},
    ]
    only = filter_lower_tail_rows_only(rows)
    rest = filter_out_lower_tail_rows(rows)
    assert [r["monitor_id"] for r in only] == ["1", "4", "5", "6"]
    assert [r["monitor_id"] for r in rest] == ["2", "3"]


def test_resolve_limit_requires_agreement():
    assert resolve_monitor_limit_dollars({"min_ask": 0.01, "max_ask": 0.01}) == 0.01
    assert resolve_monitor_limit_dollars({"min_ask": 0.01, "max_ask": 0.02}) is None
    assert resolve_monitor_limit_dollars({"min_ask": 0.05, "max_ask": None}) == 0.05


def test_v2_price_bid_ask_same_limit():
    assert v2_price_for_limit_side(side="bid", limit_dollars=0.01) == "0.0100"
    assert v2_price_for_limit_side(side="ask", limit_dollars=0.01) == "0.9900"


def test_cancel_order_requires_market_ticker_and_routes(monkeypatch):
    from backend.core import lower_tail_kalshi as mek

    assert mek.cancel_order("oid1", subaccount=3) is False

    captured: dict = {}

    class _Resp:
        status_code = 200
        text = '{"reduced_by":"1.00"}'

    def _fake_delete(url, headers=None, timeout=None):
        captured["url"] = url
        return _Resp()

    class _Sess:
        def delete(self, url, headers=None, timeout=None):
            return _fake_delete(url, headers=headers, timeout=timeout)

    monkeypatch.setattr(mek, "_auth_headers", lambda method, path: {})
    monkeypatch.setattr(mek, "_http_session", lambda: _Sess())
    assert (
        mek.cancel_order(
            "oid1", subaccount=3, market_ticker="KXBTC15M-26OCT182200-00"
        )
        is True
    )
    assert "market_ticker=KXBTC15M-26OCT182200-00" in captured["url"]
    assert "subaccount=3" in captured["url"]
    assert "exchange_index=-1" in captured["url"]


def test_place_post_only_gtc_sends_count_as_string(monkeypatch):
    """Kalshi rejects numeric count; must match trade_executor count_fp strings."""
    from backend.core import lower_tail_kalshi as mek

    captured: dict = {}

    class _Resp:
        status_code = 201
        text = '{"order":{"order_id":"oid1"}}'

        def json(self):
            return {"order": {"order_id": "oid1"}}

    class _Sess:
        def post(self, url, headers=None, json=None, data=None, timeout=None):
            captured["json"] = json
            captured["data"] = data
            return _Resp()

    monkeypatch.setattr(mek, "_auth_headers", lambda method, path: {"Accept": "application/json"})
    monkeypatch.setattr(mek, "_http_session_for_lane", lambda lane: _Sess())
    out = mek.place_post_only_gtc(
        ticker="KXBTC15M-TEST",
        side="bid",
        limit_dollars=0.01,
        count=1,
        subaccount=3,
    )
    assert out.api_json and out.api_json["order"]["order_id"] == "oid1"
    assert captured["json"] is None
    assert captured["data"] is not None
    body = __import__("json").loads(captured["data"])
    assert body["count"] == "1.00"
    assert isinstance(body["count"], str)
    assert body["price"] == "0.0100"
    assert body["post_only"] is True
    assert out.t_send <= out.t_ack

    # Prefetched body bytes path (hot path after open_time).
    pre = mek.encode_place_body(
        mek.build_place_body(
            ticker="KXBTC15M-TEST",
            side="ask",
            price="0.9900",
            count=2500,
            subaccount=3,
            client_order_id="pre-oid",
        )
    )
    captured.clear()
    out2 = mek.place_post_only_gtc(
        ticker="KXBTC15M-TEST",
        side="ask",
        limit_dollars=0.01,
        count=2500,
        subaccount=3,
        prebuilt_price="0.9900",
        prebuilt_body_bytes=pre,
    )
    assert out2.api_json is not None
    body2 = __import__("json").loads(captured["data"])
    assert body2["client_order_id"] == "pre-oid"
    assert body2["count"] == "2500.00"
    assert body2["side"] == "ask"


def test_select_oldest_me_dual_rests_cancels_newer():
    from backend.core.lower_tail_kalshi import select_oldest_me_dual_rests

    ticker = "KXBTC15M-TEST"
    orders = [
        {
            "order_id": "bid_new",
            "ticker": ticker,
            "book_side": "bid",
            "yes_price_dollars": "0.0100",
            "created_time": "2026-10-19T17:17:31Z",
        },
        {
            "order_id": "bid_old",
            "ticker": ticker,
            "book_side": "bid",
            "yes_price_dollars": "0.0100",
            "created_time": "2026-10-19T17:15:00Z",
        },
        {
            "order_id": "ask_old",
            "ticker": ticker,
            "book_side": "ask",
            "no_price_dollars": "0.0100",
            "yes_price_dollars": "0.9900",
            "created_time": "2026-10-19T17:15:00Z",
        },
        {
            "order_id": "ask_new",
            "ticker": ticker,
            "book_side": "ask",
            "no_price_dollars": "0.0100",
            "yes_price_dollars": "0.9900",
            "created_time": "2026-10-19T17:17:31Z",
        },
    ]
    keep_bid, keep_ask, cancel_ids = select_oldest_me_dual_rests(
        orders, market_ticker=ticker, limit_dollars=0.01
    )
    assert keep_bid["order_id"] == "bid_old"
    assert keep_ask["order_id"] == "ask_old"
    assert set(cancel_ids) == {"bid_new", "ask_new"}


def test_lower_tail_auto_trade_status():
    from backend.lower_tail_agent import determine_lower_tail_auto_trade_status

    assert (
        determine_lower_tail_auto_trade_status(
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
        determine_lower_tail_auto_trade_status(
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
        determine_lower_tail_auto_trade_status(
            auto_trade=True,
            limit_px=0.01,
            contracts=2500,
        )
        == "ACTIVE"
    )
    # open_time placement: TTC is not a gate — still ACTIVE when configured
    assert (
        determine_lower_tail_auto_trade_status(
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
        determine_lower_tail_auto_trade_status(
            auto_trade=True,
            limit_px=0.01,
            contracts=2500,
            ttc=50,
            min_time=100,
            max_time=900,
        )
        == "ACTIVE"
    )
