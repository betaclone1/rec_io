"""Windowed tick-buffer reads: results must not depend on how much history is held.

Regression guard for the creeping CFB hot-path lag: every read walks back only as
far as its own window, and old ticks are trimmed instead of accumulating.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.core import symbol_tick_buffer as stb

_EST = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _clean_buffer():
    stb._ticks.clear()
    stb._momentum.clear()
    yield
    stb._ticks.clear()
    stb._momentum.clear()


def _seed(sym: str, seconds: int, *, price_of=lambda secs_ago: 100.0 + secs_ago) -> None:
    """Append ``seconds`` ticks at 1 Hz ending now, priced by age so that window
    answers are comparable across different history depths."""
    now = datetime.now(_EST).timestamp()
    q = stb._ticks[sym]
    for secs_ago in range(seconds - 1, -1, -1):
        q.append((now - secs_ago, float(price_of(secs_ago))))


def test_retention_trims_beyond_window():
    sym = "BTC"
    now = datetime.now(_EST)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S")
    stb._ticks[sym].append((now.timestamp() - 5 * 3600, 1.0))
    stb.append_tick(sym, ts, 2.0)
    epochs = [e for e, _ in stb._ticks[sym]]
    assert len(epochs) == 1, "tick older than retention should be dropped"


def test_retention_keeps_volatility_lookback():
    sym = "ETH"
    now = datetime.now(_EST)
    stb._ticks[sym].append((now.timestamp() - 119 * 60, 1.0))
    stb.append_tick(sym, now.strftime("%Y-%m-%dT%H:%M:%S"), 2.0)
    assert len(stb._ticks[sym]) == 2, "120m volatility lookback must survive trim"


def test_window_results_independent_of_history_depth():
    """A 30m window must read the same with 1h vs 3h of buffered history."""
    _seed("BTC", 3600)
    short = (
        stb.avg_price_last_minute("BTC", 0.0),
        stb.price_at_offset_minutes("BTC", 30),
        stb.high_low_open_window("BTC", 30),
        len(stb.minute_candles("BTC", 60)),
    )

    stb._ticks.clear()
    _seed("BTC", 3 * 3600)
    deep = (
        stb.avg_price_last_minute("BTC", 0.0),
        stb.price_at_offset_minutes("BTC", 30),
        stb.high_low_open_window("BTC", 30),
        len(stb.minute_candles("BTC", 60)),
    )
    # Prices are a function of age, so 3x the history must not move any answer.
    assert short == deep


def test_price_at_offset_picks_nearest_tick():
    _seed("SOL", 600)
    assert stb.price_at_offset_minutes("SOL", 5) == pytest.approx(400.0, abs=1.0)
    assert stb.price_at_offset_minutes("SOL", 0) == pytest.approx(100.0, abs=1.0)


def test_high_low_open_window_open_is_oldest_in_window():
    _seed("XRP", 300)
    high, low, open_price = stb.high_low_open_window("XRP", 1)
    assert low == 100.0, "newest tick is the cheapest in this series"
    assert high == pytest.approx(159.0, abs=2.0)
    assert open_price == high, "open must be the oldest tick in the window"


def test_minute_candles_ohlc_and_order():
    _seed("DOGE", 180)
    candles = stb.minute_candles("DOGE", 5)
    assert 3 <= len(candles) <= 4
    for c in candles:
        assert c["low"] <= c["open"] <= c["high"]
        assert c["low"] <= c["close"] <= c["high"]
        assert c["open"] >= c["close"], "prices decline toward now in this series"
    opens = [c["open"] for c in candles]
    assert opens == sorted(opens, reverse=True), "candles must be oldest first"


def test_empty_buffer_is_safe():
    assert stb.price_at_offset_minutes("BTC", 5) is None
    assert stb.high_low_open_window("BTC", 5) == (None, None, None)
    assert stb.minute_candles("BTC", 60) == []
    assert stb.avg_price_last_minute("BTC", 7.5) == 7.5
