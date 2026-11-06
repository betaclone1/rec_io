"""Upper Tail book trigger: emit while armed and at rail (state, not rising edge)."""

from __future__ import annotations

import json

import backend.core.upper_tail_orderbook_watch as utw
import backend.core.upper_tail_rail_trigger as rt


def test_maybe_emit_while_at_rail(monkeypatch):
    published = []

    class _R:
        def publish(self, channel, body):
            published.append((channel, json.loads(body)))
            return 1

    monkeypatch.setattr(rt, "_redis", lambda: _R())
    monkeypatch.setattr(utw, "_redis", lambda: None)
    utw.set_upper_tail_orderbook_arm({"KXBTC15M-T": 0.99})

    mid = {
        "yes": {"0.50": "10"},
        "no": {"0.50": "10"},
        "ts_ms": 1,
        "redis_written_ms": 2,
    }
    assert rt.maybe_emit_rail_from_orderbook_payload("KXBTC15M-T", mid) is False
    assert published == []

    rail = {
        "yes": {"0.99": "5"},
        "no": {"0.01": "5"},
        "ts_ms": 3,
        "redis_written_ms": 4,
        "venue_ts_ms": 3,
    }
    assert rt.maybe_emit_rail_from_orderbook_payload("KXBTC15M-T", rail) is True
    assert len(published) == 1
    assert published[0][0] == rt.CHANNEL
    assert published[0][1]["side"] == "yes"
    assert published[0][1]["market_ticker"] == "KXBTC15M-T"

    # Still at rail → publish again (agent dedupes via placed)
    assert rt.maybe_emit_rail_from_orderbook_payload("KXBTC15M-T", rail) is True
    assert len(published) == 2

    utw.set_upper_tail_orderbook_arm({})


def test_maybe_emit_skips_unarmed(monkeypatch):
    published = []

    class _R:
        def publish(self, channel, body):
            published.append(1)
            return 1

    monkeypatch.setattr(rt, "_redis", lambda: _R())
    monkeypatch.setattr(utw, "_redis", lambda: None)
    utw.set_upper_tail_orderbook_arm({})
    assert (
        rt.maybe_emit_rail_from_orderbook_payload(
            "KXBTC15M-T",
            {"yes": {"0.99": "5"}, "no": {"0.01": "5"}},
        )
        is False
    )
    assert published == []
