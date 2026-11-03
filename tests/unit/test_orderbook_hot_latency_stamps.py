"""Venue stamps + inline hot hints for orderbook latency path."""

from __future__ import annotations

from backend.core.orderbook_hot_subscriber import (
    snapshot_from_orderbook_hint,
)
from backend.core.market_watchdog.venues.kalshi import ws_ingest as wi


def test_stamp_book_prefers_venue_ts_ms():
    b: dict = {}
    msg = {"ts_ms": 1_700_000_000_100, "clock": 42}
    envelope = {"sending_ts_ms": 1_700_000_000_105}
    wi._stamp_book_from_venue(b, msg, envelope, t_ws_recv_ms=1_700_000_000_110)
    assert b["venue_ts_ms"] == 1_700_000_000_100
    assert b["sending_ts_ms"] == 1_700_000_000_105
    assert b["ts_ms"] == 1_700_000_000_100
    assert b["t_ws_recv_ms"] == 1_700_000_000_110
    assert b["t_apply_ms"] is not None
    assert b["clock"] == 42


def test_stamp_book_falls_back_to_local_apply():
    b: dict = {}
    wi._stamp_book_from_venue(b, {}, {}, t_ws_recv_ms=1_700_000_000_200)
    assert b["venue_ts_ms"] is None
    assert b["ts_ms"] == b["t_apply_ms"]
    assert b["t_ws_recv_ms"] == 1_700_000_000_200


def test_snapshot_from_inline_hint():
    snap = snapshot_from_orderbook_hint(
        {
            "kind": "orderbook",
            "market_ticker": "KXBTC15M-X",
            "book_seq": 9,
            "ts_ms": 100,
            "venue_ts_ms": 100,
            "sending_ts_ms": 104,
            "redis_written_ms": 108,
            "t_apply_ms": 106,
            "yes": {"0.99": "1"},
            "no": {"0.01": "2"},
            "valid": True,
        },
        received_ms=110,
    )
    assert snap is not None
    assert snap.from_hint is True
    assert snap.seq == 9
    assert snap.venue_ts_ms == 100
    assert snap.yes == {"0.99": "1"}
    assert snap.age_ms == 10
    assert snap.venue_to_send_ms == 4
    assert snap.apply_to_hot_ms == 2


def test_snapshot_from_hint_requires_levels():
    assert (
        snapshot_from_orderbook_hint(
            {
                "kind": "orderbook",
                "market_ticker": "KXBTC15M-X",
                "ts_ms": 1,
            }
        )
        is None
    )
