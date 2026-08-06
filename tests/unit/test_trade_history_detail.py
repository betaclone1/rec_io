from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.core.trade_history_detail import (
    KalshiDetailError,
    candle_package_tickers,
    fetch_kalshi_market,
    fetch_kalshi_trade_context,
    fetch_spot_candles_for_market,
    following_event_ticker,
    load_trade_detail_fills,
    load_trade_detail_orders,
    market_ticker_from_event_ticker,
    market_tickers_covering_window,
    ohlc_1m_from_price_rows,
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


def test_trade_detail_fills_use_order_ids_open_array() -> None:
    cursor = FakeFillsCursor(
        [
            (
                "fill-a",
                "open-a",
                "2026-07-30T17:20:56.401533Z",
                1,
                "buy",
                "yes",
                "0.5000",
                "0.5000",
                "bid",
            ),
            (
                "fill-b",
                "open-b",
                "2026-07-30T17:21:10.000000Z",
                2,
                "buy",
                "yes",
                "0.5100",
                "0.4900",
                "bid",
            ),
        ]
    )

    fills = load_trade_detail_fills(
        cursor,
        slot="0001",
        trade={
            "order_id_open": "open-b",
            "order_id_close": None,
            "order_ids_open": ["open-a", "open-b"],
            "order_ids_close": [],
        },
    )

    assert cursor.executed[0][1] == (["open-a", "open-b"],)
    assert [row["order_id"] for row in fills] == ["open-a", "open-b"]
    assert all(row["phase"] == "open" for row in fills)


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


def test_market_ticker_from_event_ticker_15m() -> None:
    assert (
        market_ticker_from_event_ticker("KXBTC15M-26AUG041045")
        == "KXBTC15M-26AUG041045-45"
    )
    assert market_ticker_from_event_ticker("KXETHD-26JUL2923") is None


def test_market_tickers_covering_window_includes_boundary_packages() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    start = datetime(2026, 8, 4, 9, 30, tzinfo=et)
    end = datetime(2026, 8, 4, 10, 45, tzinfo=et)
    tickers = market_tickers_covering_window("KXBTC15M", start, end)
    assert tickers == [
        "KXBTC15M-26AUG040930-30",
        "KXBTC15M-26AUG040945-45",
        "KXBTC15M-26AUG041000-00",
        "KXBTC15M-26AUG041015-15",
        "KXBTC15M-26AUG041030-30",
        "KXBTC15M-26AUG041045-45",
    ]


def test_candle_package_tickers_uses_timeseries_span() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    live = {
        "details": {
            "timeseries": [
                {
                    "t": int(
                        datetime(2026, 8, 4, 13, 41, tzinfo=ZoneInfo("UTC")).timestamp()
                        * 1000
                    ),
                    "v": 1,
                },
                {
                    "t": int(
                        datetime(2026, 8, 4, 14, 30, tzinfo=ZoneInfo("UTC")).timestamp()
                        * 1000
                    ),
                    "v": 2,
                },
            ]
        }
    }
    following = {
        "details": {
            "timeseries": [
                {
                    "t": int(
                        datetime(2026, 8, 4, 14, 45, tzinfo=ZoneInfo("UTC")).timestamp()
                        * 1000
                    ),
                    "v": 3,
                },
            ]
        }
    }

    tickers = candle_package_tickers(
        "KXBTC15M-26AUG041030-30",
        following_event_ticker_value="KXBTC15M-26AUG041045",
        live_data=live,
        following_live_data=following,
    )
    assert "KXBTC15M-26AUG041000-00" in tickers
    assert "KXBTC15M-26AUG041015-15" in tickers
    assert "KXBTC15M-26AUG041030-30" in tickers
    assert "KXBTC15M-26AUG041045-45" in tickers


def test_ohlc_1m_from_price_rows_buckets_by_utc_minute() -> None:
    candles = ohlc_1m_from_price_rows(
        [
            {"timestamp": "2026-08-04T14:15:05.000Z", "price": "100"},
            {"timestamp": "2026-08-04T14:15:40.000Z", "price": "110"},
            {"timestamp": "2026-08-04T14:15:55.000Z", "price": "105"},
            {"timestamp": "2026-08-04T14:16:01.000Z", "price": "106"},
        ]
    )
    assert len(candles) == 2
    assert candles[0]["open"] == 100.0
    assert candles[0]["high"] == 110.0
    assert candles[0]["low"] == 100.0
    assert candles[0]["close"] == 105.0
    assert candles[1]["open"] == 106.0
    assert candles[1]["close"] == 106.0


def test_fetch_spot_candles_for_market_uses_local_package(monkeypatch, tmp_path) -> None:
    pkg_path = tmp_path / "KXBTC15M-26JUL271030-30.tar.xz"

    class FakePkg:
        price_rows = [
            {"timestamp": "2026-07-27T14:15:05.000Z", "price": "65000"},
            {"timestamp": "2026-07-27T14:15:59.000Z", "price": "65100"},
        ]

    import backend.core.cycle_gdrive_download as cgd
    import backend.core.cycle_package as cp

    monkeypatch.setattr(
        cgd,
        "ensure_cycle_packages_local",
        lambda tickers: {t: pkg_path for t in tickers},
    )
    monkeypatch.setattr(cp, "load_cycle_package", lambda _p: FakePkg())

    out = fetch_spot_candles_for_market("KXBTC15M-26JUL271030-30")
    assert out["error"] is None
    assert len(out["candles"]) == 1
    assert out["candles"][0]["open"] == 65000.0
    assert out["candles"][0]["close"] == 65100.0
    assert out["source"] == str(pkg_path)


def test_fetch_spot_candles_missing_package(monkeypatch) -> None:
    import backend.core.cycle_gdrive_download as cgd

    monkeypatch.setattr(
        cgd,
        "ensure_cycle_packages_local",
        lambda tickers: {t: None for t in tickers},
    )
    out = fetch_spot_candles_for_market("KXBTC15M-26AUG041030-30")
    assert out["candles"] == []
    assert out["error"]
    assert "not found" in out["error"]

