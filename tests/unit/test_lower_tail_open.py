"""Lower Tail open_time targeting."""

from __future__ import annotations

import time

from backend.core.lower_tail_open import (
    lower_tail_series_tickers,
    select_next_open_target,
    select_targets_co_opening,
    symbol_from_market_ticker,
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


def test_symbol_from_market_ticker_multi():
    assert symbol_from_market_ticker("KXBTC15M-26OCT181200-00") == "BTC"
    assert symbol_from_market_ticker("KXETH15M-26OCT181200-00") == "ETH"
    assert symbol_from_market_ticker("KXGOLD15M-26OCT181200-00") == "GOLD"
    assert symbol_from_market_ticker("KXSILVER15M-26OCT181200-00") == "SILVER"
    assert symbol_from_market_ticker("KXWTI15M-26OCT181200-00") == "WTI"


def test_lower_tail_series_tickers(monkeypatch):
    tracked = ("BTC", "ETH", "SOL", "XRP", "DOGE", "GOLD", "SILVER", "WTI")
    monkeypatch.setattr(
        "backend.core.live_data_level.market_feed_symbols",
        lambda: tracked,
    )
    assert lower_tail_series_tickers() == [
        "KXBTC15M",
        "KXDOGE15M",
        "KXETH15M",
        "KXGOLD15M",
        "KXSILVER15M",
        "KXSOL15M",
        "KXWTI15M",
        "KXXRP15M",
    ]


def test_select_targets_co_opening_multi_symbol():
    now = 1_700_000_000.0
    open_ts = now + 30
    markets = [
        _m("KXBTC15M-B-15", open_ts, open_ts + 900),
        _m("KXETH15M-B-15", open_ts, open_ts + 900),
        _m("KXGOLD15M-B-15", open_ts, open_ts + 900),
        _m("KXBTC15M-C-30", open_ts + 900, open_ts + 1800),
    ]
    primary = select_next_open_target(markets, now=now, late_grace_sec=0.25)
    assert primary is not None
    co = select_targets_co_opening(markets, primary=primary, now=now)
    tickers = {t.market_ticker for t in co}
    assert "KXBTC15M-B-15" in tickers
    assert "KXETH15M-B-15" in tickers
    assert "KXGOLD15M-B-15" in tickers
    assert "KXBTC15M-C-30" not in tickers


def test_select_next_skips_exclude_events():
    now = 1_700_000_000.0
    markets = [
        _m("KXBTC15M-B-15", now + 60, now + 960),
        _m("KXETH15M-B-15", now + 60, now + 960),
    ]
    primary = select_next_open_target(markets, now=now, late_grace_sec=0.25)
    assert primary is not None
    nxt = select_next_open_target(
        markets,
        now=now,
        late_grace_sec=0.25,
        exclude_events={primary.event_ticker},
    )
    assert nxt is not None
    assert nxt.event_ticker != primary.event_ticker


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


def test_paper_fill_side_from_public_print_exact_cent():
    from backend.lower_tail_agent import paper_fill_side_from_print

    # Exact L only — sub-cent / cheaper than L is not a dual-rest fill.
    assert (
        paper_fill_side_from_print(yes_price=0.001, no_price=0.999, limit_px=0.01)
        is None
    )
    assert (
        paper_fill_side_from_print(yes_price=0.01, no_price=0.99, limit_px=0.01)
        == "yes"
    )
    assert (
        paper_fill_side_from_print(yes_price=0.99, no_price=0.01, limit_px=0.01)
        == "no"
    )
    assert (
        paper_fill_side_from_print(yes_price=0.17, no_price=0.83, limit_px=0.01)
        is None
    )
    assert (
        paper_fill_side_from_print(yes_price=0.01, no_price=0.01, limit_px=0.01)
        is None
    )


def test_check_fills_paper_uses_tape_not_ask_touch():
    from unittest.mock import patch

    import backend.lower_tail_agent as me

    st = me.DualRestState(
        monitor_id="99027",
        ticker="KXBTC15M-26OCT181300-00",
        event_ticker="KXBTC15M-26OCT181300",
        limit_px=0.01,
        contracts=2500,
        subaccount=1,
        paper=True,
        floor_strike=100000.0,
        min_time=0,
        bid_order_id="paper_bid",
        ask_order_id="paper_ask",
        symbol="BTC",
    )
    with (
        patch.object(me, "paper_fill_side_from_tape", return_value="no") as tape,
        patch.object(me, "_ladder_side_ask") as ask,
        patch.object(me, "_on_first_fill") as on_fill,
    ):
        me._check_fills(st, ttc=500)

    tape.assert_called_once_with(st.ticker, st.limit_px)
    ask.assert_not_called()
    on_fill.assert_called_once_with(st, side="no", fill_qty=2500.0)


def test_min_ttc_cancel_gate():
    from backend.lower_tail_agent import should_cancel_unfilled_at_min_ttc

    assert should_cancel_unfilled_at_min_ttc(min_time=0, ttc=50) is False
    assert should_cancel_unfilled_at_min_ttc(min_time=100, ttc=None) is False
    assert should_cancel_unfilled_at_min_ttc(min_time=100, ttc=101) is False
    assert should_cancel_unfilled_at_min_ttc(min_time=100, ttc=100) is True
    assert should_cancel_unfilled_at_min_ttc(min_time=100, ttc=0) is True


def test_check_fills_cancels_both_at_min_ttc():
    from unittest.mock import patch

    import backend.lower_tail_agent as me

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

    def _cancel(oid, *, subaccount, market_ticker=None, exchange_index=-1):
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

    import backend.lower_tail_agent as me

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
