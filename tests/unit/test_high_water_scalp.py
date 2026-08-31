"""High Water Scalp: identity, AES occupancy, GTC sizing, partial close, stop cancel, settings."""

from __future__ import annotations

import inspect

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.aes_btc15m_exp_scalp_cutout import is_btc15m_exp_scalp_cutout_row
from backend.core.high_water_scalp import (
    complement_limit_price,
    is_expiration_scalp_entry_strategy,
    is_high_water_scalp,
    parse_limit_close_price,
    remaining_contracts,
    two_leg_close_totals,
)
from backend.core.tenant_context import TenantContext
from backend.core.tenant_strategy_list import FALLBACK_STRATEGY_NAMES


def test_identity_and_reverse_prefix():
    assert is_high_water_scalp("High Water Scalp")
    assert is_high_water_scalp("Reverse High Water Scalp")
    assert not is_high_water_scalp("Expiration Scalp")
    assert is_expiration_scalp_entry_strategy("High Water Scalp")
    assert is_expiration_scalp_entry_strategy("Expiration Scalp")
    assert is_expiration_scalp_entry_strategy("Reverse High Water Scalp")
    assert "High Water Scalp" in FALLBACK_STRATEGY_NAMES


def test_ask_hits_price_target_one_cent():
    from backend.core.high_water_scalp import ask_hits_price_target

    assert ask_hits_price_target(0.50, 0.50) is True
    assert ask_hits_price_target(0.504, 0.50) is True
    assert ask_hits_price_target(0.51, 0.50) is False
    assert ask_hits_price_target(0.90, 0.50) is False
    assert ask_hits_price_target(None, 0.50) is False
    assert ask_hits_price_target(0.50, 0) is False


def test_hws_entry_gate_single_price_limit():
    from backend.util.auto_entry_expiration_scalp_gates import evaluate_expiration_scalp_entry

    settings = {
        "min_time": 0,
        "max_time": 900,
        "min_probability": 0,
        "max_probability": 100,
        "min_ask": 0.50,
        "max_ask": 0.99,
        "min_movement": 0,
        "max_movement": 100,
    }
    miss, reason = evaluate_expiration_scalp_entry(
        settings,
        ttc_seconds=60,
        side="yes",
        ask_dollars=0.51,
        probability=80.0,
        high_water_scalp=True,
    )
    assert miss is None
    assert reason == "ask_misses_price_target"

    hit, reason_ok = evaluate_expiration_scalp_entry(
        settings,
        ttc_seconds=60,
        side="yes",
        ask_dollars=0.50,
        probability=80.0,
        high_water_scalp=True,
    )
    assert reason_ok is None
    assert hit["buy_price"] == 0.50
    assert hit["entry_limit_price"] == 0.50

    window, _ = evaluate_expiration_scalp_entry(
        settings,
        ttc_seconds=60,
        side="yes",
        ask_dollars=0.51,
        probability=80.0,
        high_water_scalp=False,
    )
    assert window["buy_price"] == 0.51
    assert window.get("entry_limit_price") is None


def test_limit_close_price_parse_and_complement():
    assert parse_limit_close_price(0.99) == 0.99
    assert parse_limit_close_price("0.9900") == 0.99
    assert parse_limit_close_price(0) is None
    assert parse_limit_close_price(1) is None
    assert parse_limit_close_price(None) is None
    assert complement_limit_price(0.99) == 0.01
    assert remaining_contracts(2500, 0) == 2500.0
    assert remaining_contracts(2500, 400) == 2100.0
    assert remaining_contracts(100, 100) == 0.0


def test_hws_not_on_btc15m_exp_scalp_cutout():
    assert not is_btc15m_exp_scalp_cutout_row(
        {"symbol": "BTC", "market": "15m", "strategy": "High Water Scalp"}
    )
    assert is_btc15m_exp_scalp_cutout_row(
        {"symbol": "BTC", "market": "15m", "strategy": "Expiration Scalp"}
    )


def test_aes_routes_hws_to_expiration_scalp_entry():
    aes_src = (
        Path(__file__).resolve().parents[2] / "backend" / "auto_entry_supervisor.py"
    ).read_text()
    assert "is_expiration_scalp_entry_strategy" in aes_src
    assert "determine_auto_entry_status_expiration_scalp" in aes_src
    assert "check_auto_entry_conditions_expiration_scalp" in aes_src
    assert "ask_misses_price_target" in aes_src
    assert "entry_limit_price" in aes_src
    tm_src = (
        Path(__file__).resolve().parents[2] / "backend" / "trade_manager.py"
    ).read_text()
    enrich = tm_src[
        tm_src.index("def _enrich_open_trade_execution_from_monitor") : tm_src.index(
            "def _live_partial_row_if_residual"
        )
    ]
    assert 'data["order_type"] = "limit"' in enrich
    assert 'data["time_in_force"] = "immediate_or_cancel"' in enrich


def test_aes_occupancy_includes_partial():
    aes_src = (
        Path(__file__).resolve().parents[2] / "backend" / "auto_entry_supervisor.py"
    ).read_text()
    assert "WHERE status IN ('open', 'pending', 'partial', 'closing')" in aes_src
    assert aes_src.count("WHERE status IN ('open', 'pending', 'partial', 'closing')") >= 3


def test_tm_places_gtc_at_complement_for_fill_count(monkeypatch):
    import backend.trade_manager as tm

    sent = {}
    row = (
        "High Water Scalp",
        2500.0,
        0.0,
        0.99,
        "KXBTC-TICK",
        "yes",
        False,
        None,
        "open",
        "mon_0001_1",
        1,
    )

    class Cur:
        def execute(self, *a, **k):
            return None

        def fetchone(self):
            return row

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            return None

    monkeypatch.setattr(tm, "get_postgresql_connection", lambda: Conn())
    monkeypatch.setattr(tm, "send_trigger_to_executor", lambda payload: sent.update(payload))
    monkeypatch.setattr(tm, "log_event", lambda *a, **k: None)

    tm._maybe_place_high_water_resting_close(42, "ticket-hws")
    assert sent["intent"] == "resting_close"
    assert sent["buy_price"] == 0.01
    assert sent["count"] == 2500.0
    assert sent["time_in_force"] == "good_till_canceled"


def test_partial_close_updates_remaining_without_finalize(monkeypatch):
    import backend.trade_manager as tm

    captured = []

    class Cur:
        def execute(self, q, params=None):
            captured.append((q, params))

        def fetchone(self):
            return (0.90, 2500.0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(tm, "get_postgresql_connection", lambda: Conn())
    monkeypatch.setattr(tm, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(tm, "notify_frontend_trade_change", lambda *a, **k: None)
    monkeypatch.setattr(tm, "notify_strike_table_trade_change", lambda *a, **k: None)

    tm._apply_high_water_partial_close(
        7,
        "ticket-hws",
        fill_val=400.0,
        remaining_val=2100.0,
        order_rec={
            "taker_fill_cost_dollars": "4.00",
            "taker_fees_dollars": "0",
            "maker_fees_dollars": "0",
        },
    )
    sql = " ".join(q for q, _ in captured).lower()
    assert "close_filled_count" in sql
    assert "set status" not in sql
    assert "'closed'" not in sql


def test_two_leg_close_totals_gtc_then_expiry():
    win = two_leg_close_totals(
        buy_price=0.90,
        position=2500,
        filled_qty=400,
        filled_sell=0.99,
        remainder_sell=1.0,
        total_fees=5.0,
    )
    assert win is not None
    assert win["remainder_qty"] == 2100.0
    assert win["sell_value"] == 2496.0
    assert win["pnl"] == 241.0
    assert win["blended_sell"] == pytest.approx(2496.0 / 2500.0)

    lose = two_leg_close_totals(
        buy_price=0.90,
        position=2500,
        filled_qty=400,
        filled_sell=0.99,
        remainder_sell=0.0,
        total_fees=5.0,
    )
    assert lose is not None
    assert lose["sell_value"] == 396.0
    assert lose["pnl"] == -1859.0


def test_two_leg_close_totals_stop_flatten_remaining():
    out = two_leg_close_totals(
        buy_price=0.90,
        position=100,
        filled_qty=40,
        filled_sell=0.99,
        remainder_sell=0.20,
        total_fees=1.5,
    )
    assert out is not None
    assert out["sell_value"] == pytest.approx(40 * 0.99 + 60 * 0.20)
    assert out["blended_sell"] == pytest.approx((40 * 0.99 + 60 * 0.20) / 100)
    assert out["pnl"] == round(out["sell_value"] - 90.0 - 1.5, 6)


def test_confirm_close_matches_open_partial_and_fills_wake():
    import backend.trade_manager as tm

    close_src = inspect.getsource(tm.confirm_close_trade_for_order_id)
    wake_src = inspect.getsource(tm.apply_positions_updated_payload)
    confirm_src = inspect.getsource(tm.confirm_close_trade)
    assert "open" in close_src and "partial" in close_src
    assert "fills" in wake_src
    assert "wake_confirm_close_for_order" in wake_src
    assert "two_leg_close_totals" in confirm_src
    assert "_hws_sum_kalshi_close_fees" in confirm_src
    assert "close_fill_val + 0.02 < pos_all" not in confirm_src


def test_ats_hws_stop_cancels_then_flattens_without_entry_dwell():
    ats_src = (
        Path(__file__).resolve().parents[2] / "backend" / "active_trade_supervisor.py"
    ).read_text()
    hws_start = ats_src.index("def check_auto_stop_conditions_high_water_scalp")
    hws_end = ats_src.index("def check_auto_stop_conditions_expiration_scalp")
    hws_src = ats_src[hws_start:hws_end]
    assert "get_stop_verification_period_enabled" in hws_src
    assert "get_stop_verification_period_seconds" in hws_src
    assert "get_verification_period_enabled()" not in hws_src
    assert "get_verification_period_seconds()" not in hws_src
    assert "floor_stop_verify_allows_fire" in hws_src
    assert "if is_high_water_scalp(get_trade_strategy()):" in ats_src
    assert "_hws_cancel_resting_and_apply_remaining(trade)" in ats_src
    assert "check_auto_stop_conditions_high_water_scalp" in ats_src
    assert "evaluate_paper_resting_gtc" in ats_src
    assert "paper_hws_resting_fill" in ats_src
    assert "paper_touch" not in ats_src
    enq_start = ats_src.index("def _hws_enqueue_paper_resting_fill")
    enq_end = ats_src.index("def check_auto_stop_conditions_high_water_scalp")
    assert '"close_fee": 0.0' in ats_src[enq_start:enq_end]
    hws_start = ats_src.index("def check_auto_stop_conditions_high_water_scalp")
    hws_end = ats_src.index("def check_auto_stop_conditions_expiration_scalp")
    hws_src = ats_src[hws_start:hws_end]
    assert 'trigger_reason="limit_close"' not in hws_src
    assert "probability_auto_stop" not in hws_src
    assert "get_min_ttc_seconds" not in hws_src
    assert "check_probability_divergence=False" in hws_src


def test_hws_floor_stop_verify_allows_fire():
    from backend.core.high_water_scalp import floor_is_past, floor_stop_verify_allows_fire

    assert floor_is_past(0.11, 0.90) is True
    assert floor_is_past(0.09, 0.90) is False
    assert floor_is_past(None, 0.90) is False
    assert floor_is_past(0.50, 0) is False

    may, until = floor_stop_verify_allows_fire(False, True, 1, 100.0, 101.0)
    assert may is False and until is None

    may, until = floor_stop_verify_allows_fire(True, False, 1, 100.0, None)
    assert may is True and until is None

    may, until = floor_stop_verify_allows_fire(True, True, 0, 100.0, None)
    assert may is True and until is None

    may, until = floor_stop_verify_allows_fire(True, True, 1, 100.0, None)
    assert may is False and until == 101.0

    may, until = floor_stop_verify_allows_fire(True, True, 1, 100.5, 101.0)
    assert may is False and until == 101.0

    may, until = floor_stop_verify_allows_fire(True, True, 1, 101.0, 101.0)
    assert may is True and until is None


def test_hws_modal_full_cycle_time_window_hides_stop_extras():
    js = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "js"
        / "unified_auto_trade_settings.js"
    ).read_text()
    assert "function uatTimeWindowMaxSeconds" in js
    assert "return uatMonitorMarketIs15m(market) ? 900 : 3600;" in js
    assert "const showHtcStopExtras = !isExpirationScalp;" in js
    assert "function uatApplyRangeMinMaxValue" in js
    assert "const showStopVerify = showHtcStopExtras || !!isHighWaterScalp;" in js
    assert "payload.current_probability = parseInt(document.getElementById('autoStopProbabilitySlider')" in js
    save_idx = js.index("payload.min_ask = parseFloat(parseFloat(dashboardExpirationScalpMinAsk)")
    save_hws = js[save_idx : js.index("} else {\n          // HOURLY HTC", save_idx)]
    assert "limit_close_price" in save_hws
    assert "entry_verification_period_enabled" in save_hws
    assert "entry_verification_period_seconds" in save_hws
    assert "stop_verification_period_enabled" in save_hws
    assert "stop_verification_period_seconds" in save_hws
    assert "current_probability" not in save_hws
    assert "min_ttc_seconds" not in save_hws
    assert "payload.min_ask = pt" in save_hws
    assert "payload.max_ask = pt" in save_hws
    assert "Active-Side Price Target" in (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "tabs"
        / "partials"
        / "unified_auto_trade_modal.html"
    ).read_text()
    assert "highWaterScalpPriceTargetSlider" in js
    assert "payload.time_in_force = 'immediate_or_cancel'" in js
    html = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "tabs"
        / "partials"
        / "unified_auto_trade_modal.html"
    ).read_text()
    ask_start = html.index('id="expirationScalpAskWindowSection"')
    ask_end = html.index('id="expirationScalpFillGatesSection"')
    assert "highWaterScalpLimitCloseSection" not in html[ask_start:ask_end]
    assert 'id="highWaterScalpLimitCloseSection"' in html
    assert 'id="htcAutoStopVerificationControls"' in html
    assert 'id="verificationPeriodSlider" min="1" max="60"' in html
    mobile = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "mobile"
        / "dashboard_mobile.html"
    ).read_text()
    assert "const showStopVerify = showHtcStopExtras || !!isHighWaterScalp;" in mobile
    assert 'id="m_htcAutoStopVerificationControls"' in mobile
    assert "stop_verification_period_enabled" in mobile


def test_settings_store_limit_close_price_round_trip_and_reject():
    from backend.core.auto_entry_settings_store import apply_auto_entry_settings

    ctx = TenantContext.from_schema("users_0001")

    class Cur:
        def __init__(self):
            self.last = ""
            self.updated = None

        def execute(self, q, params=None):
            self.last = q
            if "UPDATE" in q and params:
                self.updated = params

        def fetchone(self):
            if "information_schema" in self.last:
                return (1,)
            if "SELECT id FROM" in self.last.replace("\n", " "):
                return (1,)
            # apply() SELECT after update: 30 base cols then optional flip
            row = [None] * 36
            row[1] = 0.25
            row[16] = 22
            row[23] = 0.0
            row[24] = "fill_or_kill"
            row[25] = "market"
            row[26] = False
            row[27] = 0.99
            row[28] = False
            row[29] = 1
            return tuple(row)

    bad = apply_auto_entry_settings(
        Cur(), "1", {"limit_close_price": 1.5}, tenant_context=ctx
    )
    assert bad["status"] == "error"

    zero = apply_auto_entry_settings(
        Cur(), "1", {"limit_close_price": 0}, tenant_context=ctx
    )
    assert zero["status"] == "error"

    ok_cur = Cur()
    with patch(
        "backend.core.time_based_loss_prevention.sync_simulated_trade_after_monitor_settings_save"
    ):
        ok = apply_auto_entry_settings(
            ok_cur, "1", {"limit_close_price": 0.99}, tenant_context=ctx
        )
    assert ok["status"] == "ok"
    assert ok["limit_close_price"] == 0.99
    assert ok_cur.updated is not None
    assert 0.99 in ok_cur.updated


def test_settings_store_stop_verification_round_trip_and_reject():
    from backend.core.auto_entry_settings_store import apply_auto_entry_settings

    ctx = TenantContext.from_schema("users_0001")

    class Cur:
        def __init__(self):
            self.last = ""
            self.updated = None

        def execute(self, q, params=None):
            self.last = q
            if "UPDATE" in q and params:
                self.updated = params

        def fetchone(self):
            if "information_schema" in self.last:
                return (1,)
            if "SELECT id FROM" in self.last.replace("\n", " "):
                return (1,)
            row = [None] * 36
            row[1] = 0.25
            row[16] = 22
            row[23] = 0.0
            row[24] = "fill_or_kill"
            row[25] = "market"
            row[26] = False
            row[27] = 0.99
            row[28] = True
            row[29] = 1
            return tuple(row)

    bad = apply_auto_entry_settings(
        Cur(), "1", {"stop_verification_period_seconds": 61}, tenant_context=ctx
    )
    assert bad["status"] == "error"

    ok_cur = Cur()
    with patch(
        "backend.core.time_based_loss_prevention.sync_simulated_trade_after_monitor_settings_save"
    ):
        ok = apply_auto_entry_settings(
            ok_cur,
            "1",
            {
                "stop_verification_period_enabled": True,
                "stop_verification_period_seconds": 1,
            },
            tenant_context=ctx,
        )
    assert ok["status"] == "ok"
    assert ok["stop_verification_period_enabled"] is True
    assert ok["stop_verification_period_seconds"] == 1
    assert ok_cur.updated is not None
    assert True in ok_cur.updated
    assert 1 in ok_cur.updated


def test_paper_resting_fill_increment_first_touch_and_increase():
    from backend.core.high_water_scalp import paper_resting_fill_increment

    assert paper_resting_fill_increment(0, 0) == 0.0
    assert paper_resting_fill_increment(100, 0) == 100.0
    assert paper_resting_fill_increment(100, 100) == 0.0
    assert paper_resting_fill_increment(150, 100) == 50.0
    assert paper_resting_fill_increment(80, 100) == 0.0
    assert paper_resting_fill_increment(50, 0) == 50.0


def test_paper_resting_gtc_walk_at_and_through_limit():
    from backend.core.high_water_scalp import simulate_paper_resting_gtc

    # Own YES @ 0.99 close: GTC buys NO at 0.01, lifting YES bids >= 0.99.
    yes = {"0.99": "80", "0.995": "20", "0.98": "500"}
    no = {}
    first = simulate_paper_resting_gtc(yes, no, "yes", 0.99, 2500.0, 0.0)
    assert first["ok"] is True
    assert first["reason"] == "fill"
    assert first["fill_qty"] == 100.0
    assert first["available"] == 100.0
    # VWAP of NO buys: 80 @ 0.01 + 20 @ 0.005 = 0.009; owned sell = 0.991
    assert abs(first["opp_vwap"] - 0.009) < 1e-6
    assert abs(first["owned_sell_vwap"] - 0.991) < 1e-6
    assert first["close_fee"] == 0.0

    same = simulate_paper_resting_gtc(yes, no, "yes", 0.99, 2400.0, 100.0)
    assert same["fill_qty"] == 0.0
    assert same["reason"] == "no_new_size"

    grown = {"0.99": "130", "0.995": "20", "0.98": "500"}
    inc = simulate_paper_resting_gtc(grown, no, "yes", 0.99, 2400.0, 100.0)
    assert inc["fill_qty"] == 50.0
    assert inc["available"] == 150.0


def test_paper_resting_gtc_no_fill_when_book_empty():
    from backend.core.high_water_scalp import simulate_paper_resting_gtc

    empty = simulate_paper_resting_gtc({}, {}, "yes", 0.99, 100.0, 0.0)
    assert empty["fill_qty"] == 0.0
    assert empty["reset_last"] is True
    assert empty["owned_sell_vwap"] is None

    deep = simulate_paper_resting_gtc({"0.50": "1000"}, {}, "yes", 0.99, 100.0, 0.0)
    assert deep["fill_qty"] == 0.0
    assert deep["reason"] == "not_marketable"
    assert deep["owned_sell_vwap"] is None


def test_paper_resting_gtc_skips_stale_or_missing_book():
    from backend.core.high_water_scalp_paper import evaluate_paper_resting_gtc

    miss = evaluate_paper_resting_gtc("TICK-1", "yes", 0.99, 100.0, 0.0)
    # Default: no redis snap in unit tests.
    assert miss["fill_qty"] == 0.0
    assert miss["owned_sell_vwap"] is None
    assert miss["available"] is None
    assert miss["reason"] in (
        "orderbook_miss",
        "orderbook_invalid",
        "orderbook_no_timestamp",
        "orderbook_empty",
        "missing_ticker",
    )

    with patch(
        "backend.core.high_water_scalp_paper.load_fresh_orderbook_levels",
        return_value=(None, None, "orderbook_stale:40.0s>30.0s"),
    ):
        stale = evaluate_paper_resting_gtc("TICK-1", "yes", 0.99, 100.0, 0.0)
    assert stale["fill_qty"] == 0.0
    assert stale["owned_sell_vwap"] is None
    assert stale["reason"].startswith("orderbook_stale")


def test_paper_hws_partial_fill_does_not_finalize(monkeypatch):
    import backend.trade_manager as tm

    captured = []
    row = (
        "High Water Scalp",
        "open",
        True,
        0.90,
        2500.0,
        0.0,
        None,
        1.50,
        10000.0,
        10000.0,
        "BTC",
    )

    class Cur:
        def execute(self, q, params=None):
            captured.append((q, params))

        def fetchone(self):
            return row

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(tm, "get_postgresql_connection", lambda: Conn())
    monkeypatch.setattr(tm, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(tm, "notify_frontend_trade_change", lambda *a, **k: None)
    monkeypatch.setattr(tm, "notify_strike_table_trade_change", lambda *a, **k: None)

    out = tm.apply_paper_high_water_resting_fill(
        {
            "id": 7,
            "ticket_id": "ticket-hws",
            "count": 400,
            "sell_price": 0.99,
            "close_fee": 0.10,
        }
    )
    assert out["closed"] is False
    sql = " ".join(q for q, _ in captured).lower()
    assert "close_filled_count" in sql
    assert "status = 'closing'" not in sql
    assert "status = 'closed'" not in sql
    # Payload close_fee is ignored; paper GTC is $0 maker. Open fee 1.50 stays.
    assert any(params is not None and 1.5 in params for _, params in captured)
    assert not any(params is not None and 1.6 in params for _, params in captured)


def test_paper_hws_full_remaining_finalizes(monkeypatch):
    import backend.trade_manager as tm

    captured = []
    row = (
        "High Water Scalp",
        "partial",
        True,
        0.90,
        100.0,
        0.0,
        None,
        0.50,
        10000.0,
        10000.0,
        "BTC",
    )
    finalized = {}

    class Cur:
        def execute(self, q, params=None):
            captured.append((q, params))

        def fetchone(self):
            return row

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(tm, "get_postgresql_connection", lambda: Conn())
    monkeypatch.setattr(tm, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(tm, "log", lambda *a, **k: None)
    monkeypatch.setattr(tm, "notify_frontend_trade_change", lambda *a, **k: None)
    monkeypatch.setattr(tm, "notify_strike_table_trade_change", lambda *a, **k: None)
    monkeypatch.setattr(tm, "notify_active_trade_supervisor_direct", lambda *a, **k: None)
    monkeypatch.setattr(tm, "_symbol_close_for_early_close", lambda *a, **k: None)
    monkeypatch.setattr(tm, "get_high_low_prices_from_active_trades", lambda *a, **k: (None, None))
    monkeypatch.setattr(tm, "_paper_ledger_on_close", lambda *a, **k: None)

    def _finalize(*a, **k):
        finalized["closed"] = True

    monkeypatch.setattr(tm, "update_trade_status_with_ret_pct", _finalize)

    out = tm.apply_paper_high_water_resting_fill(
        {
            "id": 9,
            "ticket_id": "ticket-hws",
            "count": 100,
            "sell_price": 0.99,
            "close_fee": 0.05,
            "close_method": "limit_close",
        }
    )
    assert out["closed"] is True
    assert finalized.get("closed") is True
    sql = " ".join(q for q, _ in captured).lower()
    assert "status = 'closing'" in sql
    assert any(
        params is not None and "limit_close" in str(params)
        for _, params in captured
    )
    # Open fee 0.50 unchanged (no taker close fee on paper GTC).
    assert any(params is not None and 0.5 in params for _, params in captured)
    assert not any(params is not None and 0.55 in params for _, params in captured)


def test_create_monitor_insert_placeholders_match_columns():
    mm_src = (
        Path(__file__).resolve().parents[2] / "backend" / "monitor_manager.py"
    ).read_text()
    start = mm_src.index("@app.route('/api/monitor/create'")
    fn = mm_src[start : mm_src.index("@app.route('/health'")]
    insert = fn[fn.index("INSERT INTO") : fn.index("RETURNING id")]
    n_ph = insert.split("VALUES", 1)[1].count("%s")
    col_block = insert.split("VALUES", 1)[0]
    inner = col_block[col_block.index("(") : col_block.rindex(")")]
    n_cols = inner.count(",") + 1
    assert "limit_close_price" in inner
    assert "NOW()" in insert.split("VALUES", 1)[1]
    assert n_ph == n_cols - 1


def test_tm_add_trade_routes_paper_hws_intent():
    tm_src = (
        Path(__file__).resolve().parents[2] / "backend" / "trade_manager.py"
    ).read_text()
    assert 'intent == "paper_hws_resting_fill"' in tm_src
    assert "apply_paper_high_water_resting_fill" in tm_src
    assert 'row[1] in ("open", "partial")' in tm_src
