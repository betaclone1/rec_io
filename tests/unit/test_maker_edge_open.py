"""Maker Edge open_time targeting."""

from __future__ import annotations

import time

from backend.core.maker_edge_open import (
    select_next_open_target,
    wait_until_open_ts,
)


def _iso(ts: float) -> str:
    # Preserve fractional seconds so grace-window tests are meaningful.
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(int(ts))) + (
        f".{int((ts % 1) * 1_000_000):06d}Z"
    )


def _m(ticker: str, open_ts: float, close_ts: float, *, floor: float | None = 100.0):
    return {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "open_time": _iso(open_ts),
        "close_time": _iso(close_ts),
        "floor_strike": floor,
    }


def test_select_next_open_prefers_soonest_future():
    now = 1_700_000_000.0
    markets = [
        _m("KXBTC15M-A-00", now - 900, now - 10),  # closed
        _m("KXBTC15M-B-15", now + 60, now + 960),
        _m("KXBTC15M-C-30", now + 960, now + 1860),
    ]
    tgt = select_next_open_target(markets, now=now, late_grace_sec=0.25)
    assert tgt is not None
    assert tgt.market_ticker == "KXBTC15M-B-15"
    assert abs(tgt.open_ts - (now + 60)) < 1.0


def test_select_allows_just_opened_within_grace():
    now = 1_700_000_000.0
    markets = [
        _m("KXBTC15M-B-15", now - 0.1, now + 899.9),
    ]
    tgt = select_next_open_target(markets, now=now, late_grace_sec=0.25)
    assert tgt is not None
    assert tgt.market_ticker == "KXBTC15M-B-15"


def test_select_skips_opened_past_grace():
    now = 1_700_000_000.0
    markets = [
        _m("KXBTC15M-B-15", now - 5.0, now + 895.0),
        _m("KXBTC15M-C-30", now + 100, now + 1000),
    ]
    tgt = select_next_open_target(markets, now=now, late_grace_sec=0.25)
    assert tgt is not None
    assert tgt.market_ticker == "KXBTC15M-C-30"


def test_wait_until_open_ts_spin():
    open_ts = time.time() + 0.08
    assert wait_until_open_ts(open_ts, late_grace_sec=0.5, spin_before_sec=0.05) is True
    assert time.time() >= open_ts


def test_min_ttc_cancel_gate():
    from backend.maker_edge_agent import should_cancel_unfilled_at_min_ttc

    assert should_cancel_unfilled_at_min_ttc(min_time=0, ttc=50) is False
    assert should_cancel_unfilled_at_min_ttc(min_time=100, ttc=None) is False
    assert should_cancel_unfilled_at_min_ttc(min_time=100, ttc=101) is False
    assert should_cancel_unfilled_at_min_ttc(min_time=100, ttc=100) is True
    assert should_cancel_unfilled_at_min_ttc(min_time=100, ttc=0) is True


def test_check_fills_cancels_both_at_min_ttc():
    from unittest.mock import patch

    import backend.maker_edge_agent as me

    st = me.DualRestState(
        monitor_id="99027",
        ticker="KXBTC15M-26OCT181300-00",
        event_ticker="KXBTC15M-26OCT181300",
        limit_px=0.01,
        contracts=2500,
        subaccount=1,
        paper=False,
        floor_strike=100000.0,
        min_time=120,
        bid_order_id="bid1",
        ask_order_id="ask1",
    )
    canceled: list[str] = []

    def _cancel(oid, *, subaccount):
        canceled.append(oid)
        return True

    with (
        patch.object(me, "_order_fill_qty", return_value=0.0),
        patch.object(me, "cancel_order", side_effect=_cancel),
    ):
        me._check_fills(st, ttc=120)

    assert st.done is True
    assert set(canceled) == {"bid1", "ask1"}


def test_check_fills_min_zero_does_not_cancel():
    from unittest.mock import patch

    import backend.maker_edge_agent as me

    st = me.DualRestState(
        monitor_id="99027",
        ticker="KXBTC15M-26OCT181300-00",
        event_ticker="KXBTC15M-26OCT181300",
        limit_px=0.01,
        contracts=2500,
        subaccount=1,
        paper=False,
        floor_strike=100000.0,
        min_time=0,
        bid_order_id="bid1",
        ask_order_id="ask1",
    )
    with (
        patch.object(me, "_order_fill_qty", return_value=0.0),
        patch.object(me, "cancel_order") as cancel,
    ):
        me._check_fills(st, ttc=0)

    assert st.done is False
    cancel.assert_not_called()
