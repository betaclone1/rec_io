"""Exp Scalp flicker gate: live out-of-band veto; drop-step opt-in only."""

from backend.util.auto_entry_expiration_scalp_gates import (
    ask_dollars_to_cent,
    expiration_scalp_flicker_gate,
    update_expiration_scalp_entry_verification,
)


def test_ask_cent_rounds_like_lane():
    assert ask_dollars_to_cent(0.934) == "0.93"
    assert ask_dollars_to_cent(0.978) == "0.98"


def test_in_band_drop_does_not_reset_by_default():
    action, reason = expiration_scalp_flicker_gate(
        prior_ask_cent="0.95",
        snapshot_ask=0.92,
        min_ask=0.90,
        max_ask=0.99,
        live_ask=0.92,
        step_cents=0,
    )
    assert action is None
    assert reason is None


def test_first_tick_no_prior_is_ok():
    action, reason = expiration_scalp_flicker_gate(
        prior_ask_cent=None,
        snapshot_ask=0.934,
        min_ask=0.90,
        max_ask=0.99,
        live_ask=None,
        step_cents=0,
    )
    assert action is None
    assert reason is None


def test_live_outside_band_aborts():
    action, reason = expiration_scalp_flicker_gate(
        prior_ask_cent="0.93",
        snapshot_ask=0.934,
        min_ask=0.90,
        max_ask=0.99,
        live_ask=0.87,
        step_cents=0,
    )
    assert action == "abort"
    assert reason == "flicker_live_outside_band"


def test_missing_live_ask_skips_live_veto():
    action, reason = expiration_scalp_flicker_gate(
        prior_ask_cent="0.93",
        snapshot_ask=0.934,
        min_ask=0.90,
        max_ask=0.99,
        live_ask=None,
        step_cents=0,
    )
    assert action is None


def test_ten_seconds_stable_still_fires():
    state = None
    may = False
    for t in range(11):
        action, _ = expiration_scalp_flicker_gate(
            prior_ask_cent=(state or {}).get("ask_cent"),
            snapshot_ask=0.934,
            min_ask=0.90,
            max_ask=0.99,
            live_ask=0.934,
            step_cents=0,
        )
        assert action is None
        state, may, dwell = update_expiration_scalp_entry_verification(
            state,
            eligible=True,
            now_ts=float(t),
            enabled=True,
            period_seconds=10,
        )
        assert state is not None
        state["ask_cent"] = ask_dollars_to_cent(0.934)
        if t < 10:
            assert may is False
            assert dwell == float(t)
    assert may is True


def test_opt_in_drop_step_still_resets():
    action, reason = expiration_scalp_flicker_gate(
        prior_ask_cent="0.98",
        snapshot_ask=0.934,
        min_ask=0.90,
        max_ask=0.99,
        live_ask=0.934,
        step_cents=1,
    )
    assert action == "reset"
    assert reason == "flicker_ask_step"
