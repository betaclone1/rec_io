"""Lower Tail stamps fill-time ladder prob/diff after sibling cancel."""

from __future__ import annotations

from unittest.mock import patch

import backend.lower_tail_agent as me


def test_paper_ask_prefers_orderbook_touch():
    with (
        patch(
            "backend.core.orderbook_strike_prices.resolve_orderbook_touch_dollars",
            return_value=({"yes_ask_dollars": "0.0100", "no_ask_dollars": "0.9900"}, "ok"),
        ),
        patch.object(me, "_ladder_row_for_ticker") as ladder_row,
    ):
        assert me._ladder_side_ask("KXBTC15M-x", "yes") == 0.01
        ladder_row.assert_not_called()


def test_ladder_prob_diff_at_fill_side_aware():
    row = {
        "ticker": "KXBTC15M-26OCT181200-00",
        "yes_prob_15m": 2.5,
        "no_prob_15m": 97.5,
        "yes_diff": 1.4,
        "no_diff": -0.2,
        "probability": 50.0,
    }
    with patch.object(me, "_ladder_row_for_ticker", return_value=row):
        py, dy = me.ladder_prob_diff_at_fill("KXBTC15M-26OCT181200-00", "yes")
        pn, dn = me.ladder_prob_diff_at_fill("KXBTC15M-26OCT181200-00", "no")
    assert py == 2.5 and dy == 1.4
    assert pn == 97.5 and dn == -0.2


def test_ladder_prob_diff_at_fill_missing_row_is_null():
    with patch.object(me, "_ladder_row_for_ticker", return_value=None):
        assert me.ladder_prob_diff_at_fill("KXBTC15M-x", "yes") == (None, None)


def test_on_first_fill_cancels_before_snapshot_and_books_prob():
    st = me.DualRestState(
        monitor_id="99027",
        ticker="KXBTC15M-26OCT181200-00",
        event_ticker="KXBTC15M-26OCT181200",
        limit_px=0.01,
        contracts=2500,
        subaccount=1,
        paper=False,
        floor_strike=100000.0,
        bid_order_id="bid1",
        ask_order_id="ask1",
    )
    order: list[str] = []

    def _cancel(*_a, **_k):
        order.append("cancel")

    def _snap(*_a, **_k):
        order.append("snap")
        return 3.0, 1.5

    def _book(*_a, **_k):
        order.append("book")
        return 99

    with (
        patch.object(me, "_cancel_order_routed", side_effect=lambda *a, **k: (order.append("cancel") or True)),
        patch.object(me, "ladder_prob_diff_at_fill", side_effect=_snap),
        patch.object(me, "_book_fill_to_tm", side_effect=_book),
    ):
        me._on_first_fill(st, side="yes", fill_qty=2500.0)

    assert order == ["cancel", "snap", "book"]
    assert st.fill_prob == 3.0
    assert st.fill_diff == 1.5
    assert st.trade_id == 99
    assert st.done is True


def test_book_fill_payload_includes_fill_snapshot():
    st = me.DualRestState(
        monitor_id="99027",
        ticker="KXBTC15M-26OCT181200-00",
        event_ticker="KXBTC15M-26OCT181200",
        limit_px=0.01,
        contracts=2500,
        subaccount=1,
        paper=True,
        floor_strike=100000.0,
        bid_order_id="paper_bid",
        ask_order_id="paper_ask",
        fill_prob=4.25,
        fill_diff=-1.0,
    )
    captured: dict = {}

    class _Resp:
        status_code = 200
        content = b'{"id": 7}'

        def json(self):
            return {"id": 7}

    def _post(url, json=None, timeout=None):
        captured.update(json or {})
        return _Resp()

    with (
        patch.object(me, "get_port", return_value=9000),
        patch.object(me, "_user_no", return_value="0001"),
        patch.object(me.requests, "post", side_effect=_post),
    ):
        tid = me._book_fill_to_tm(st, side="yes", fill_qty=2500.0)

    assert tid == 7
    assert captured["prob"] == 4.25
    assert captured["diff"] == -1.0
    assert captured["intent"] == "lower_tail_fill"
    assert captured["initial_count"] == 2500.0


def test_on_first_fill_live_keeps_fill_sync_open():
    st = me.DualRestState(
        monitor_id="10064",
        ticker="KXBTC15M-x",
        event_ticker="KXBTC15M-x",
        limit_px=0.01,
        contracts=25,
        subaccount=3,
        paper=False,
        floor_strike=100000.0,
        bid_order_id="bid1",
        ask_order_id="ask1",
    )
    with (
        patch.object(me, "_cancel_order_routed", return_value=True),
        patch.object(me, "ladder_prob_diff_at_fill", return_value=(None, None)),
        patch.object(me, "_book_fill_to_tm", return_value=42),
    ):
        me._on_first_fill(st, side="yes", fill_qty=10.0)
    assert st.done is True
    assert st.fill_sync_done is False
    assert st.fill_qty == 10.0
    assert st.trade_id == 42


def test_sync_live_fill_totals_raises_tm_position():
    st = me.DualRestState(
        monitor_id="10064",
        ticker="KXBTC15M-x",
        event_ticker="KXBTC15M-x",
        limit_px=0.01,
        contracts=25,
        subaccount=3,
        paper=False,
        floor_strike=100000.0,
        bid_order_id="bid1",
        ask_order_id="ask1",
        filled_side="yes",
        fill_qty=10.0,
        trade_id=42,
        done=True,
        fill_sync_done=False,
    )
    books: list[float] = []

    def _book(_st, *, side, fill_qty):
        books.append(fill_qty)
        return 42

    with (
        patch.object(me, "_order_fill_qty", return_value=25.0),
        patch.object(me, "_order_remaining_qty", return_value=0.0),
        patch.object(me, "_book_fill_to_tm", side_effect=_book),
    ):
        me._sync_live_fill_totals(st)
    assert books == [25.0]
    assert st.fill_qty == 25.0
    assert st.fill_sync_done is True
