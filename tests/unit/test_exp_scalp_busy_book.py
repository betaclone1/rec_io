"""Busy-book verify pause: 1¢ reversal resets; one-way grind does not."""

from backend.util.auto_entry_expiration_scalp_gates import (
    ask_dollars_to_cent,
    expiration_scalp_busy_book_gate,
    update_expiration_scalp_entry_verification,
)


def test_first_print_sets_no_dir():
    reason, new_dir = expiration_scalp_busy_book_gate(
        prior_ask_cent=None, prior_dir=None, ask=0.95
    )
    assert reason is None
    assert new_dir is None


def test_one_way_up_does_not_reset():
    dir_ = None
    cent = None
    for ask in (0.90, 0.92, 0.93, 0.94, 0.95, 0.97):
        reason, dir_ = expiration_scalp_busy_book_gate(
            prior_ask_cent=cent, prior_dir=dir_, ask=ask
        )
        assert reason is None
        cent = ask_dollars_to_cent(ask)
    assert dir_ == 1


def test_one_way_down_does_not_reset():
    reason, dir_ = expiration_scalp_busy_book_gate(
        prior_ask_cent="0.95", prior_dir=None, ask=0.92
    )
    assert reason is None
    assert dir_ == -1
    reason, dir_ = expiration_scalp_busy_book_gate(
        prior_ask_cent="0.92", prior_dir=dir_, ask=0.91
    )
    assert reason is None
    assert dir_ == -1


def test_down_then_up_resets():
    reason, dir_ = expiration_scalp_busy_book_gate(
        prior_ask_cent="0.95", prior_dir=None, ask=0.92
    )
    assert reason is None
    reason, dir_ = expiration_scalp_busy_book_gate(
        prior_ask_cent="0.92", prior_dir=dir_, ask=0.93
    )
    assert reason == "busy_book_reversal"
    assert dir_ == 1


def test_up_then_down_resets():
    reason, dir_ = expiration_scalp_busy_book_gate(
        prior_ask_cent="0.93", prior_dir=None, ask=0.96
    )
    assert reason is None
    reason, dir_ = expiration_scalp_busy_book_gate(
        prior_ask_cent="0.96", prior_dir=dir_, ask=0.95
    )
    assert reason == "busy_book_reversal"
    assert dir_ == -1


def test_flat_does_not_reset_or_change_dir():
    reason, dir_ = expiration_scalp_busy_book_gate(
        prior_ask_cent="0.93", prior_dir=1, ask=0.934
    )
    assert reason is None
    assert dir_ == 1


def test_climb_still_completes_verify():
    state = None
    dir_ = None
    asks = [0.90, 0.91, 0.92, 0.93, 0.94, 0.95, 0.96]
    may = False
    for t, ask in enumerate(asks):
        reason, dir_ = expiration_scalp_busy_book_gate(
            prior_ask_cent=(state or {}).get("ask_cent"),
            prior_dir=dir_,
            ask=ask,
        )
        assert reason is None
        state, may, dwell = update_expiration_scalp_entry_verification(
            state,
            eligible=True,
            now_ts=float(t),
            enabled=True,
            period_seconds=6,
        )
        assert state is not None
        state["ask_cent"] = ask_dollars_to_cent(ask)
        state["last_dir"] = dir_
    assert may is True
    assert dwell == 6.0
