from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from backend.core.btc15m_cycle_candles import (
    build_cycle_candle_from_payloads,
    settlement_end_utc_from_ticker,
    timeseries_prices,
)


def test_settlement_end_utc_from_ticker() -> None:
    ts = settlement_end_utc_from_ticker("KXBTC15M-26AUG020000-00")
    assert ts.tzinfo is not None
    # Midnight Eastern on Aug 2 2026 is 04:00 UTC (EDT)
    assert ts == datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc)
    from backend.core.btc15m_cycle_candles import settlement_end_utc_iso_from_ticker

    assert settlement_end_utc_iso_from_ticker("KXBTC15M-26AUG020000-00") == (
        "2026-08-02T04:00:00.000Z"
    )


def test_build_cycle_candle_ignores_preopen_extremes() -> None:
    # Cycle 04:00–04:15 UTC. Pre-open spike/dip must not affect high/low.
    open_ms = int(datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc).timestamp() * 1000)
    mid_ms = int(datetime(2026, 8, 2, 4, 7, 30, tzinfo=timezone.utc).timestamp() * 1000)
    close_ms = int(datetime(2026, 8, 2, 4, 15, tzinfo=timezone.utc).timestamp() * 1000)
    pre_ms = open_ms - 30 * 60 * 1000

    market = {
        "floor_strike": "100000",
        "open_time": "2026-08-02T04:00:00Z",
        "close_time": "2026-08-02T04:15:00Z",
        "result": "yes",
    }
    live_data = {
        "details": {
            "timeseries": [
                {"t": pre_ms, "v": "99000"},   # pre-open low — ignore
                {"t": pre_ms + 1000, "v": "101000"},  # pre-open high — ignore
                {"t": open_ms, "v": "99900"},
                {"t": mid_ms, "v": "100500"},
                {"t": close_ms, "v": "100200"},
            ]
        }
    }
    row = build_cycle_candle_from_payloads(
        ticker="KXBTC15M-26AUG020015-15",
        contract="BTC 12:15am",
        market=market,
        live_data=live_data,
    )
    assert row["floor_strike"] == Decimal("100000")
    assert row["high_price"] == Decimal("100500")
    assert row["low_price"] == Decimal("99900")
    assert row["close"] == Decimal("100200")
    assert row["total_range_pct"] == Decimal("0.6")
    assert row["final_diff_pct"] == Decimal("0.2")
    assert row["market_result"] == "yes"
    assert row["price_points"] == 3


def test_market_result_null_when_unset() -> None:
    from backend.core.btc15m_cycle_candles import market_result_from_market

    assert market_result_from_market({}) is None
    assert market_result_from_market({"result": ""}) is None
    assert market_result_from_market({"market_result": "no"}) == "no"


def test_timeseries_prices_skips_junk() -> None:
    assert timeseries_prices({"details": {"timeseries": [{"v": "1"}, {"v": None}, {"x": 1}]}}) == [
        Decimal("1")
    ]
