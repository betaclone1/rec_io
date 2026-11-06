"""Upper Tail trigger and entry window."""

from __future__ import annotations

from backend.core.upper_tail import (
    STRATEGY_NAME,
    floor_strike_from_market,
    is_upper_tail_row,
    upper_tail_side_from_bbo,
    upper_tail_side_from_orderbook,
    upper_tail_side_from_print,
    ttc_in_entry_window,
)


def test_membership(monkeypatch):
    monkeypatch.setattr(
        "backend.core.live_data_level.market_feed_symbols",
        lambda: ("ETH", "SOL", "XRP"),
    )
    assert is_upper_tail_row(
        {"symbol": "ETH", "market": "15m", "strategy": "Upper Tail"}
    )
    assert is_upper_tail_row(
        {"symbol": "SOL", "market": "15m", "strategy": "Upper Tail"}
    )
    assert is_upper_tail_row(
        {"symbol": "XRP", "market": "15m", "strategy": "Upper Tail"}
    )
    assert not is_upper_tail_row(
        {"symbol": "DOGE", "market": "15m", "strategy": "Upper Tail"}
    )
    assert not is_upper_tail_row(
        {"symbol": "ETH", "market": "15m", "strategy": "Lower Tail"}
    )
    assert STRATEGY_NAME == "Upper Tail"


def test_floor_strike_from_market_requires_api_field():
    assert floor_strike_from_market({"floor_strike": 4118.65}) == 4118.65
    assert floor_strike_from_market({"ticker": "KXETH15M-X"}) is None
    assert floor_strike_from_market(None) is None


def test_side_from_print_high_end():
    assert (
        upper_tail_side_from_print(yes_price=0.99, no_price=0.01, limit_px=0.99)
        == "yes"
    )
    assert (
        upper_tail_side_from_print(yes_price=0.01, no_price=0.995, limit_px=0.99)
        == "no"
    )
    assert (
        upper_tail_side_from_print(yes_price=0.50, no_price=0.50, limit_px=0.99)
        is None
    )
    assert (
        upper_tail_side_from_print(yes_price=0.99, no_price=0.99, limit_px=0.99)
        is None
    )


def test_trigger_mode_tape_vs_orderbook(monkeypatch):
    from unittest.mock import MagicMock

    from backend.core import upper_tail as ut

    monkeypatch.setattr(ut, "_trigger_by_symbol", {})
    monkeypatch.setattr(ut, "_trigger_loaded_mono", 0.0)

    monkeypatch.setattr(
        "backend.core.live_data_level.level_of",
        lambda s: {
            "BTC": "full",
            "SOL": "full",
            "GOLD": "market",
            "SILVER": "full",
        }.get(s, "none"),
    )

    def _cat(conn, sym):
        if sym in ("GOLD", "SILVER"):
            return "commodity", "ok"
        return "crypto", "ok"

    monkeypatch.setattr(
        "backend.core.strike_pipeline_health.get_symbol_category_conn",
        _cat,
    )
    monkeypatch.setattr(
        "backend.core.config.database.get_system_postgresql_connection",
        lambda: MagicMock(),
    )

    assert ut.upper_tail_trigger_mode("BTC") == ut.TRIGGER_ORDERBOOK
    assert ut.upper_tail_trigger_mode("SOL") == ut.TRIGGER_ORDERBOOK
    assert ut.upper_tail_trigger_mode("GOLD") == ut.TRIGGER_TAPE
    # Commodity still on tape even if mistakenly left at full.
    assert ut.upper_tail_trigger_mode("SILVER") == ut.TRIGGER_TAPE


def test_side_from_orderbook_rail():
    # Mid book — do not fire.
    assert (
        upper_tail_side_from_orderbook(yes_ask=0.51, no_ask=0.50, limit_px=0.99)
        is None
    )
    # YES ask rail.
    assert (
        upper_tail_side_from_orderbook(yes_ask=0.99, no_ask=0.01, limit_px=0.99)
        == "yes"
    )
    # YES bid rail (ask still short of limit) — still fire.
    assert (
        upper_tail_side_from_orderbook(
            yes_ask=0.98, no_ask=0.02, yes_bid=0.99, no_bid=0.01, limit_px=0.99
        )
        == "yes"
    )
    # NO rail.
    assert (
        upper_tail_side_from_orderbook(yes_ask=0.01, no_ask=0.99, limit_px=0.99)
        == "no"
    )
    # Ask still climbing (0.98), bids also below — not yet.
    assert (
        upper_tail_side_from_orderbook(
            yes_ask=0.98, no_ask=0.02, yes_bid=0.97, no_bid=0.01, limit_px=0.99
        )
        is None
    )
    # Ask-only alias still works.
    assert (
        upper_tail_side_from_bbo(yes_ask=0.99, no_ask=0.01, limit_px=0.99) == "yes"
    )


def test_book_stamps_ladder_prob_diff_when_present():
    from unittest.mock import patch

    import backend.upper_tail_agent as te

    cy = te._Cycle(
        monitor_id="99029",
        symbol="ETH",
        ticker="KXETH15M-26OCT202230-30",
        event_ticker="KXETH15M-26OCT202230",
        limit_px=0.99,
        contracts=10,
        subaccount=1,
        paper=True,
        floor_strike=2445.0,
        close_ts=0.0,
        min_time=0,
        max_time=900,
        bankroll_cents=None,
    )
    captured = {}

    class _Resp:
        status_code = 200
        content = b'{"id": 1}'

        def json(self):
            return {"id": 1}

    def _post(url, json=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    with (
        patch.object(te, "_fill_prob_diff", return_value=(77.0, -1.2)),
        patch.object(te.requests, "post", side_effect=_post),
        patch.object(te, "get_port", return_value=8001),
    ):
        assert te._book(cy, side="no", fill_qty=10.0) == 1
    assert captured["payload"]["prob"] == 77.0
    assert captured["payload"]["diff"] == -1.2
    assert captured["payload"]["symbol"] == "ETH"


def test_book_omits_prob_diff_when_ladder_missing():
    from unittest.mock import patch

    import backend.upper_tail_agent as te

    cy = te._Cycle(
        monitor_id="99030",
        symbol="GOLD",
        ticker="KXGOLD15M-26OCT202230-30",
        event_ticker="KXGOLD15M-26OCT202230",
        limit_px=0.99,
        contracts=10,
        subaccount=1,
        paper=True,
        floor_strike=4119.0,
        close_ts=0.0,
        min_time=0,
        max_time=900,
        bankroll_cents=None,
    )
    captured = {}

    class _Resp:
        status_code = 200
        content = b'{"id": 2}'

        def json(self):
            return {"id": 2}

    def _post(url, json=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    with (
        patch.object(te, "_fill_prob_diff", return_value=(None, None)),
        patch.object(te.requests, "post", side_effect=_post),
        patch.object(te, "get_port", return_value=8001),
    ):
        te._book(cy, side="yes", fill_qty=10.0)
    assert "prob" not in captured["payload"]
    assert "diff" not in captured["payload"]


def test_entry_window():
    assert ttc_in_entry_window(ttc=120, min_time=60, max_time=180) is True
    assert ttc_in_entry_window(ttc=30, min_time=60, max_time=180) is False
    assert ttc_in_entry_window(ttc=None, min_time=0, max_time=900) is False


def test_event_ts_to_unix_ms_seconds_and_iso():
    import backend.upper_tail_agent as te

    assert te._event_ts_to_unix_ms(1_700_000_000) == 1_700_000_000_000.0
    assert te._event_ts_to_unix_ms(1_700_000_000_000) == 1_700_000_000_000.0
    iso_ms = te._event_ts_to_unix_ms("2023-11-14T22:13:20+00:00")
    assert iso_ms is not None
    assert abs(iso_ms - 1_700_000_000_000.0) < 1000.0


def test_qualifying_orderbook_returns_trigger_hit(monkeypatch):
    import time

    import backend.upper_tail_agent as te
    from backend.core.orderbook_strike_prices import OrderbookTouchMeta
    from backend.core.upper_tail import TRIGGER_ORDERBOOK

    cy = te._Cycle(
        monitor_id="10073",
        symbol="BTC",
        ticker="KXBTC15M-X",
        event_ticker="KXBTC15M-X",
        limit_px=0.99,
        contracts=1,
        subaccount=6,
        paper=False,
        floor_strike=1.0,
        close_ts=time.time() + 600,
        min_time=0,
        max_time=900,
        bankroll_cents=None,
    )

    def _resolve(_ticker, max_age_sec=None):
        touch = {
            "yes_bid_dollars": "0.9900",
            "yes_ask_dollars": "0.9910",
            "no_bid_dollars": "0.0090",
            "no_ask_dollars": "0.0100",
        }
        meta = OrderbookTouchMeta(
            age_sec=0.012,
            ts_ms=1_700_000_000_100.0,
            redis_written_ms=1_700_000_000_120.0,
            venue_ts_ms=1_700_000_000_100.0,
        )
        return touch, "ok", meta

    monkeypatch.setattr(te, "resolve_orderbook_touch_with_meta", _resolve)
    monkeypatch.setattr(te.time, "time", lambda: 1_700_000_000_112.0 / 1000.0)
    hit = te._qualifying_side_from_orderbook(cy)
    assert hit is not None
    assert hit.side == "yes"
    assert hit.mode == TRIGGER_ORDERBOOK
    assert hit.source_age_ms is not None
    assert abs(hit.source_age_ms - 12.0) < 0.1
    assert hit.source_ts_ms == 1_700_000_000_100.0


def test_qualifying_tape_returns_trigger_hit(monkeypatch):
    import time

    import backend.upper_tail_agent as te
    from backend.core.upper_tail import TRIGGER_TAPE

    cy = te._Cycle(
        monitor_id="10080",
        symbol="GOLD",
        ticker="KXGOLD15M-X",
        event_ticker="KXGOLD15M-X",
        limit_px=0.99,
        contracts=1,
        subaccount=1,
        paper=False,
        floor_strike=1.0,
        close_ts=time.time() + 600,
        min_time=0,
        max_time=900,
        bankroll_cents=None,
    )
    t_print = time.time() - 0.05
    monkeypatch.setattr(
        te,
        "load_public_trade_prints",
        lambda _t: [
            {
                "yes_price_dollars": "0.99",
                "no_price_dollars": "0.01",
                "ts": t_print,
            }
        ],
    )
    hit = te._qualifying_side_from_tape(cy)
    assert hit is not None
    assert hit.side == "yes"
    assert hit.mode == TRIGGER_TAPE
    assert hit.source_age_ms is not None
    assert hit.source_age_ms >= 40.0


def test_place_live_logs_detect_to_ack(monkeypatch):
    import time

    import backend.upper_tail_agent as te
    from backend.core.lower_tail_kalshi import PlaceResult
    from backend.core.upper_tail import TRIGGER_ORDERBOOK

    cy = te._Cycle(
        monitor_id="10073",
        symbol="BTC",
        ticker="KXBTC15M-X",
        event_ticker="KXBTC15M-X",
        limit_px=0.99,
        contracts=1,
        subaccount=6,
        paper=False,
        floor_strike=1.0,
        close_ts=time.time() + 600,
        min_time=0,
        max_time=900,
        bankroll_cents=None,
    )
    t0 = time.time()
    hit = te._TriggerHit(
        side="yes",
        mode=TRIGGER_ORDERBOOK,
        t_detect=t0,
        source_age_ms=8.0,
        source_ts_ms=t0 * 1000.0,
    )
    logged = []

    def _capture(msg):
        logged.append(msg)

    monkeypatch.setattr(te, "_log", _capture)
    monkeypatch.setattr(te, "v2_price_for_limit_side", lambda **kwargs: "0.9900")
    monkeypatch.setattr(
        te,
        "place_limit_gtc",
        lambda **kwargs: PlaceResult(
            api_json={
                "order_id": "oid-1",
                "fill_count": "1.00",
                "ts_ms": int((t0 + 0.03) * 1000),
            },
            t_send=t0 + 0.002,
            t_ack=t0 + 0.028,
        ),
    )
    assert te._place_live(cy, hit, path="hot") is True
    gtc = next(m for m in logged if m.startswith("GTC "))
    assert "detect_to_send_ms=" in gtc
    assert "detect_to_ack_ms=" in gtc
    assert "rtt_ms=" in gtc
    assert "source_age_ms=8.0" in gtc
    assert "mode=orderbook" in gtc
    assert "path=hot" in gtc  # path label is caller-supplied
    assert cy.order_id == "oid-1"


def _make_cycle(**kwargs):
    import time

    import backend.upper_tail_agent as te
    from backend.core.upper_tail import TRIGGER_ORDERBOOK

    base = dict(
        monitor_id="10073",
        symbol="BTC",
        ticker="KXBTC15M-STREAM",
        event_ticker="KXBTC15M-STREAM",
        limit_px=0.99,
        contracts=1,
        subaccount=6,
        paper=True,
        floor_strike=1.0,
        close_ts=time.time() + 600,
        min_time=0,
        max_time=900,
        bankroll_cents=None,
        trigger_mode=TRIGGER_ORDERBOOK,
    )
    base.update(kwargs)
    return te._Cycle(**base)


def _rail_payload(ticker: str, *, yes: dict, no: dict, limit_px: float = 0.99) -> dict:
    from backend.core.orderbook_strike_prices import touch_dollars_from_orderbook_snapshot

    touch = touch_dollars_from_orderbook_snapshot(
        {"valid": True, "yes": yes, "no": no}
    )
    return {
        "type": "upper_tail_rail_trigger",
        "market_ticker": ticker,
        "side": "yes",
        "limit_px": limit_px,
        "touch": touch or {},
        "ts_ms": 1_700_000_000_100,
        "venue_ts_ms": 1_700_000_000_100,
        "redis_written_ms": 1_700_000_000_110,
        "emitted_ms": 1_700_000_000_120,
    }


def test_rail_trigger_noop_below_rail(monkeypatch):
    import backend.upper_tail_agent as te

    cy = _make_cycle()
    te._cycles.clear()
    te._cycles[cy.monitor_id] = cy
    with te._arm_lock:
        te._armed_by_ticker = {cy.ticker: [cy.monitor_id]}
    fired = []
    monkeypatch.setattr(te, "_try_fire_cycle", lambda *a, **k: fired.append(1) or True)
    # Payload claims trigger but touch is mid-book — agent re-checks limit.
    te._on_rail_trigger(
        _rail_payload(cy.ticker, yes={"0.50": "10"}, no={"0.50": "10"})
    )
    assert fired == []
    assert cy.placed is False


def test_book_trigger_fires_once_on_rail(monkeypatch):
    import backend.upper_tail_agent as te

    cy = _make_cycle()
    te._cycles.clear()
    te._cycles[cy.monitor_id] = cy
    with te._arm_lock:
        te._armed_by_ticker = {cy.ticker: [cy.monitor_id]}

    booked = []

    def _book(c, *, side, fill_qty):
        booked.append((side, fill_qty))
        return 42

    monkeypatch.setattr(te, "_book", _book)
    payload = _rail_payload(cy.ticker, yes={"0.99": "5"}, no={"0.01": "5"})
    te._on_rail_trigger(payload)
    te._on_rail_trigger(payload)  # second publish must not double-fire
    assert cy.placed is True
    assert cy.side == "yes"
    assert len(booked) == 1


def test_book_trigger_ignores_unarmed_ticker(monkeypatch):
    import backend.upper_tail_agent as te

    cy = _make_cycle()
    te._cycles.clear()
    te._cycles[cy.monitor_id] = cy
    with te._arm_lock:
        te._armed_by_ticker = {}
    fired = []
    monkeypatch.setattr(te, "_try_fire_cycle", lambda *a, **k: fired.append(1) or True)
    te._on_rail_trigger(
        _rail_payload(cy.ticker, yes={"0.99": "5"}, no={"0.01": "5"})
    )
    assert fired == []


def test_rebuild_armed_registers_book_arm_and_evaluates_new(monkeypatch):
    import time

    import backend.upper_tail_agent as te
    from backend.core.upper_tail import TRIGGER_ORDERBOOK, TRIGGER_TAPE

    armed = {}
    evaluated = []

    def _set(arms):
        armed["arms"] = dict(arms)

    monkeypatch.setattr(te, "set_upper_tail_orderbook_arm", _set)
    monkeypatch.setattr(
        te, "_evaluate_book_from_redis", lambda mt: evaluated.append(mt)
    )
    te._cycles.clear()
    te._prev_armed_tickers = set()
    btc = _make_cycle(monitor_id="1", ticker="KXBTC15M-A", trigger_mode=TRIGGER_ORDERBOOK)
    gold = _make_cycle(
        monitor_id="2",
        symbol="GOLD",
        ticker="KXGOLD15M-A",
        trigger_mode=TRIGGER_TAPE,
    )
    te._cycles[btc.monitor_id] = btc
    te._cycles[gold.monitor_id] = gold
    te._rebuild_armed_index(time.time())
    assert "KXBTC15M-A" in armed["arms"]
    assert armed["arms"]["KXBTC15M-A"] == 0.99
    assert "KXGOLD15M-A" not in armed["arms"]
    assert evaluated == ["KXBTC15M-A"]
    with te._arm_lock:
        assert btc.monitor_id in te._armed_by_ticker.get("KXBTC15M-A", [])
        assert "KXGOLD15M-A" not in te._armed_by_ticker
    # Second rebuild: same arm → no re-evaluate
    evaluated.clear()
    te._rebuild_armed_index(time.time())
    assert evaluated == []


def test_upper_tail_arm_does_not_wake_tradeflow(monkeypatch):
    from backend.core import orderbook_hot_publish_registry as reg
    from backend.core import upper_tail_orderbook_watch as utw

    monkeypatch.setattr(reg, "immediate_orderbook_flush_enabled", lambda: True)
    monkeypatch.setattr(reg, "hot_crypto_15m_enabled", lambda: False)
    monkeypatch.setattr(reg, "_parse_allowlist_env", lambda: set())
    monkeypatch.setattr(
        "backend.core.trade_monitor_orderbook_watch.get_trade_monitor_orderbook_watch",
        lambda: None,
    )
    utw.set_upper_tail_orderbook_arm({"KXBTC15M-HOT": 0.99})
    monkeypatch.setattr(utw, "_redis", lambda: None)
    with reg._lock:
        reg._last_refresh_mono = 0.0
    # Flush is universal; UT arm must not wake AES/tradeflow.
    assert reg.should_immediate_flush_orderbook("KXETH15M-COLD") is True
    assert reg.should_wake_tradeflow_on_orderbook("KXBTC15M-HOT") is False
    assert reg.should_wake_tradeflow_on_orderbook("KXETH15M-COLD") is False
    utw.set_upper_tail_orderbook_arm({})


def test_crypto_15m_tradeflow_wake_not_flush_gate(monkeypatch):
    from backend.core import orderbook_hot_publish_registry as reg

    monkeypatch.setattr(reg, "immediate_orderbook_flush_enabled", lambda: True)
    monkeypatch.setattr(reg, "hot_crypto_15m_enabled", lambda: True)
    monkeypatch.setattr(reg, "_parse_allowlist_env", lambda: set())
    monkeypatch.setattr(
        "backend.core.trade_monitor_orderbook_watch.get_trade_monitor_orderbook_watch",
        lambda: None,
    )

    def _clock(sym, _now):
        return {
            "BTC": "KXBTC15M-CUR",
            "ETH": "KXETH15M-CUR",
        }.get(str(sym).upper())

    monkeypatch.setattr(
        "backend.core.market_watchdog.venues.kalshi.schedule.clock_current_15m_ticker",
        _clock,
    )
    assert reg.should_immediate_flush_orderbook("KXGOLD15M-ANY") is True
    assert reg.should_wake_tradeflow_on_orderbook("KXBTC15M-CUR") is True
    assert reg.should_wake_tradeflow_on_orderbook("KXETH15M-CUR") is True
    # Next-cycle crypto book: flush ok, no tradeflow wake until clock rolls.
    assert reg.should_wake_tradeflow_on_orderbook("KXBTC15M-NEXT") is False
    assert reg.should_wake_tradeflow_on_orderbook("KXGOLD15M-ANY") is False
