"""Unit tests for strict orderbook strike pricing."""

from __future__ import annotations

import time
from unittest.mock import patch

from backend.core import orderbook_strike_prices as obp


def test_resolve_orderbook_touch_dollars_ok():
    now_ms = int(time.time() * 1000)
    snap = {
        "valid": True,
        "redis_written_ms": now_ms,
        "ts_ms": now_ms - 5,
        "yes": {"0.46": "100", "0.45": "50"},
        "no": {"0.52": "80", "0.51": "40"},
    }
    with patch.object(obp, "load_orderbook_snapshot_from_redis", return_value=snap):
        touch, reason = obp.resolve_orderbook_touch_dollars("TICKER-1", max_age_sec=30.0)
        touch2, reason2, meta = obp.resolve_orderbook_touch_with_meta(
            "TICKER-1", max_age_sec=30.0
        )
    assert reason == "ok"
    assert touch is not None
    assert touch["yes_ask_dollars"] == "0.4800"
    assert touch["no_ask_dollars"] == "0.5400"
    assert reason2 == "ok"
    assert touch2 == touch
    assert meta.redis_written_ms == float(now_ms)
    assert meta.ts_ms == float(now_ms - 5)
    assert meta.age_sec is not None
    assert meta.age_sec < 1.0


def test_resolve_orderbook_touch_with_meta_venue_stamps():
    now_ms = int(time.time() * 1000)
    snap = {
        "valid": True,
        "redis_written_ms": now_ms,
        "ts_ms": now_ms - 20,
        "venue_ts_ms": now_ms - 20,
        "sending_ts_ms": now_ms - 15,
        "t_ws_recv_ms": now_ms - 10,
        "t_apply_ms": now_ms - 8,
        "yes": {"0.46": "100"},
        "no": {"0.52": "80"},
    }
    with patch.object(obp, "load_orderbook_snapshot_from_redis", return_value=snap):
        touch, reason, meta = obp.resolve_orderbook_touch_with_meta(
            "TICKER-V", max_age_sec=30.0
        )
    assert reason == "ok"
    assert touch is not None
    assert meta.venue_ts_ms == float(now_ms - 20)
    assert meta.sending_ts_ms == float(now_ms - 15)
    assert meta.t_apply_ms == float(now_ms - 8)


def test_resolve_orderbook_touch_dollars_stale():
    old_ms = int(time.time() * 1000) - 60_000
    snap = {
        "valid": True,
        "redis_written_ms": old_ms,
        "yes": {"0.46": "100"},
        "no": {"0.52": "80"},
    }
    with patch.object(obp, "load_orderbook_snapshot_from_redis", return_value=snap):
        touch, reason = obp.resolve_orderbook_touch_dollars("TICKER-1", max_age_sec=30.0)
    assert touch is None
    assert reason.startswith("orderbook_stale:")


def test_resolve_orderbook_touch_dollars_one_sided_yes_book():
    snap = {
        "valid": True,
        "redis_written_ms": int(time.time() * 1000),
        "yes": {"0.99": "100", "0.98": "50"},
        "no": {},
    }
    with patch.object(obp, "load_orderbook_snapshot_from_redis", return_value=snap):
        touch, reason = obp.resolve_orderbook_touch_dollars("TICKER-OTM", max_age_sec=30.0)
    assert reason == "ok"
    assert touch is not None
    assert touch["yes_ask_dollars"] == "1.0000"
    assert touch["no_ask_dollars"] == "0.0100"


def test_apply_orderbook_touch_overrides_no_ticker_fallback():
    with patch.object(
        obp,
        "resolve_orderbook_touch_dollars",
        return_value=(None, "orderbook_miss"),
    ):
        out = obp.apply_orderbook_touch_overrides("TICKER-1", "0.97", "0.98", "0.96", "0.97")
    assert out == (None, None, None, None)
