from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.core.trade_history_detail import (
    KalshiDetailError,
    fetch_kalshi_market,
    fetch_kalshi_trade_context,
    following_event_ticker,
    load_trade_detail_fills,
    load_trade_detail_orders,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: Dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


def queued_get(
    responses: List[FakeResponse],
    calls: List[str],
):
    def _get(url: str, **_kwargs: Any) -> FakeResponse:
        calls.append(url)
        return responses.pop(0)

    return _get


class FakeFillsCursor:
    def __init__(self, rows: List[tuple]):
        self.rows = rows
        self.executed: List[tuple] = []

    def execute(self, query: str, params: tuple) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> List[tuple]:
        return self.rows


def test_trade_detail_fills_match_open_and_close_orders() -> None:
    cursor = FakeFillsCursor(
        [
            (
                "fill-open",
                "order-open",
                "2026-07-30T17:20:56.401533Z",
                2,
                "buy",
                "yes",
                "0.7800",
                "0.2200",
                "bid",
            ),
            (
                "fill-close",
                "order-close",
                "2026-07-30T17:22:10.698619Z",
                1,
                "buy",
                "no",
                "0.7000",
                "0.3000",
                "bid",
            ),
        ]
    )

    fills = load_trade_detail_fills(
        cursor,
        slot="0001",
        order_id_open="order-open",
        order_id_close="order-close",
    )

    assert "FROM users.fills_0001" in cursor.executed[0][0]
    assert cursor.executed[0][1] == (["order-open", "order-close"],)
    assert fills == [
        {
            "fill_id": "fill-open",
            "order_id": "order-open",
            "phase": "open",
            "created_time": "2026-07-30T17:20:56.401533Z",
            "count": "2",
            "action": "buy",
            "outcome_side": "yes",
            "price": "0.7800",
            "orderbook_side": "bid",
        },
        {
            "fill_id": "fill-close",
            "order_id": "order-close",
            "phase": "close",
            "created_time": "2026-07-30T17:22:10.698619Z",
            "count": "1",
            "action": "buy",
            "outcome_side": "no",
            "price": "0.3000",
            "orderbook_side": "bid",
        },
    ]


def test_trade_detail_fills_skip_query_without_order_ids() -> None:
    cursor = FakeFillsCursor([])

    assert (
        load_trade_detail_fills(
            cursor,
            slot="0001",
            order_id_open=None,
            order_id_close="",
        )
        == []
    )
    assert cursor.executed == []


def test_trade_detail_orders_match_open_and_close_orders() -> None:
    cursor = FakeFillsCursor(
        [
            (
                "order-open",
                "2026-07-30T17:20:56.401533Z",
                "executed",
                "yes",
                "bid",
                "0.7800",
                2,
                2,
                "0.120000",
                1,
            ),
            (
                "order-close",
                "2026-07-30T17:22:10.698619Z",
                "executed",
                "no",
                "ask",
                "0.3000",
                2,
                1,
                "0.060000",
                2,
            ),
        ]
    )

    orders = load_trade_detail_orders(
        cursor,
        slot="0001",
        order_id_open="order-open",
        order_id_close="order-close",
    )

    query, params = cursor.executed[0]
    assert "FROM users.orders_0001" in query
    assert "taker_fees_dollars" in query
    assert "maker_fees_dollars" in query
    assert params == (["order-open", "order-close"],)
    assert orders == [
        {
            "order_id": "order-open",
            "phase": "open",
            "created_time": "2026-07-30T17:20:56.401533Z",
            "status": "executed",
            "outcome_side": "yes",
            "orderbook_side": "bid",
            "price": "0.7800",
            "initial_count": "2",
            "fill_count": "2",
            "total_fees": "0.120000",
            "subaccount": 1,
        },
        {
            "order_id": "order-close",
            "phase": "close",
            "created_time": "2026-07-30T17:22:10.698619Z",
            "status": "executed",
            "outcome_side": "no",
            "orderbook_side": "ask",
            "price": "0.3000",
            "initial_count": "2",
            "fill_count": "1",
            "total_fees": "0.060000",
            "subaccount": 2,
        },
    ]


def test_trade_detail_orders_skip_query_without_order_ids() -> None:
    cursor = FakeFillsCursor([])

    assert (
        load_trade_detail_orders(
            cursor,
            slot="0001",
            order_id_open=None,
            order_id_close="",
        )
        == []
    )
    assert cursor.executed == []


def test_market_uses_current_endpoint_when_present() -> None:
    calls: List[str] = []
    get = queued_get(
        [FakeResponse(200, {"market": {"ticker": "KXBTC15M-X-00"}})],
        calls,
    )

    market, source = fetch_kalshi_market("KXBTC15M-X-00", http_get=get)

    assert market["ticker"] == "KXBTC15M-X-00"
    assert source == "current"
    assert len(calls) == 1
    assert calls[0].endswith("/markets/KXBTC15M-X-00")


def test_market_uses_historical_endpoint_after_current_404() -> None:
    calls: List[str] = []
    get = queued_get(
        [
            FakeResponse(404, {"error": {"code": "not_found"}}),
            FakeResponse(
                200,
                {
                    "market": {
                        "ticker": "KXBTC15M-X-00",
                        "floor_strike": 69563.47,
                    }
                },
            ),
        ],
        calls,
    )

    market, source = fetch_kalshi_market("KXBTC15M-X-00", http_get=get)

    assert source == "historical"
    assert market["floor_strike"] == 69563.47
    assert calls[1].endswith("/historical/markets/KXBTC15M-X-00")


def test_market_does_not_try_historical_after_current_server_error() -> None:
    calls: List[str] = []
    get = queued_get(
        [FakeResponse(500, {"error": {"code": "internal"}})],
        calls,
    )

    with pytest.raises(KalshiDetailError) as exc_info:
        fetch_kalshi_market("KXBTC15M-X-00", http_get=get)

    assert exc_info.value.status_code == 500
    assert len(calls) == 1


def test_trade_context_returns_market_and_live_data_without_files() -> None:
    calls: List[str] = []
    get = queued_get(
        [
            FakeResponse(
                200,
                {
                    "market": {
                        "ticker": "KXBTC15M-26MAR120000-00",
                        "floor_strike": 69563.47,
                        "open_time": "2026-03-12T03:45:00Z",
                        "close_time": "2026-03-12T04:00:00Z",
                    }
                },
            ),
            FakeResponse(
                200,
                {
                    "live_data": {
                        "type": "crypto",
                        "details": {
                            "event_ticker": "KXBTC15M-26MAR120000",
                            "timeseries": [{"t": 1, "v": 2}],
                        },
                    }
                },
            ),
            FakeResponse(
                200,
                {
                    "live_data": {
                        "type": "crypto",
                        "details": {
                            "event_ticker": "KXBTC15M-26MAR120015",
                            "timeseries": [{"t": 3, "v": 4}],
                        },
                    }
                },
            ),
        ],
        calls,
    )

    detail = fetch_kalshi_trade_context(
        "KXBTC15M-26MAR120000-00",
        http_get=get,
    )

    assert detail["event_ticker"] == "KXBTC15M-26MAR120000"
    assert detail["market_source"] == "current"
    assert detail["market"]["floor_strike"] == 69563.47
    assert detail["live_data"]["details"]["timeseries"] == [{"t": 1, "v": 2}]
    assert detail["following_event_ticker"] == "KXBTC15M-26MAR120015"
    assert detail["following_live_data"]["details"]["timeseries"] == [{"t": 3, "v": 4}]
    assert detail["market_error"] is None
    assert detail["live_data_error"] is None
    assert detail["following_live_data_error"] is None
    assert calls[2].endswith("/live_data/events/KXBTC15M-26MAR120015")


@pytest.mark.parametrize(
    ("event_ticker", "open_time", "close_time", "expected"),
    [
        (
            "KXBTC15M-26MAR120000",
            "2026-03-12T03:45:00Z",
            "2026-03-12T04:00:00Z",
            "KXBTC15M-26MAR120015",
        ),
        (
            "KXETHD-26JUL2923",
            "2026-07-30T02:00:00Z",
            "2026-07-30T03:00:00Z",
            "KXETHD-26JUL3000",
        ),
    ],
)
def test_following_event_ticker_uses_authoritative_cycle_duration(
    event_ticker: str,
    open_time: str,
    close_time: str,
    expected: str,
) -> None:
    following, following_close = following_event_ticker(
        event_ticker,
        {"open_time": open_time, "close_time": close_time},
    )

    assert following == expected
    assert following_close.isoformat() == (
        "2026-03-12T04:15:00+00:00"
        if "15M" in event_ticker
        else "2026-07-30T04:00:00+00:00"
    )
