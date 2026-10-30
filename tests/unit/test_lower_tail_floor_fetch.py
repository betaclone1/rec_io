"""Lower Tail floor_strike refresh from Kalshi GET /markets (lean symbols)."""

from __future__ import annotations

from unittest.mock import patch

from backend.lower_tail_agent import DualRestState, _book_fill_to_tm, _maybe_fetch_floor


def _st(**kwargs) -> DualRestState:
    base = dict(
        monitor_id="10082",
        ticker="KXGOLD15M-26OCT292015-15",
        event_ticker="KXGOLD15M-26OCT292015",
        limit_px=0.01,
        contracts=1,
        subaccount=14,
        paper=True,
        floor_strike=None,
        symbol="GOLD",
    )
    base.update(kwargs)
    return DualRestState(**base)


def test_maybe_fetch_floor_sets_strike_from_market_payload():
    st = _st()
    with patch(
        "backend.lower_tail_agent.fetch_market_payload",
        return_value={"floor_strike": 4008.01},
    ) as fetch:
        _maybe_fetch_floor(st)
    assert st.floor_strike == 4008.01
    fetch.assert_called_once()


def test_maybe_fetch_floor_cooldown_skips_repeat_get():
    import time

    st = _st(floor_fetch_mono=time.monotonic())
    with patch(
        "backend.lower_tail_agent.fetch_market_payload",
        return_value={"floor_strike": 1.0},
    ) as fetch:
        _maybe_fetch_floor(st)
    assert st.floor_strike is None
    fetch.assert_not_called()


def test_book_fill_fetches_floor_when_ladder_misses():
    st = _st(paper=True)
    with patch(
        "backend.lower_tail_agent._resolve_floor_strike", return_value=None
    ), patch(
        "backend.lower_tail_agent.fetch_market_payload",
        return_value={"floor_strike": 51.939},
    ), patch("backend.lower_tail_agent.requests.post") as post:
        post.return_value.status_code = 201
        post.return_value.content = b'{"id": 99}'
        post.return_value.json.return_value = {"id": 99}
        tid = _book_fill_to_tm(st, side="yes", fill_qty=1.0)
    assert tid == 99
    assert st.floor_strike == 51.939
    payload = post.call_args.kwargs["json"]
    assert payload["strike"] == 51.939
    assert payload["symbol"] == "GOLD"
