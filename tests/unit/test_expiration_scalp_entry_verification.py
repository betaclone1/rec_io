"""Unit tests for Expiration Scalp entry verification dwell."""

from backend.util.auto_entry_expiration_scalp_gates import (
    update_expiration_scalp_entry_verification,
)


def test_disabled_passes_through_eligible():
    state, may, dwell = update_expiration_scalp_entry_verification(
        None, eligible=True, now_ts=100.0, enabled=False, period_seconds=3
    )
    assert state is None
    assert may is True
    assert dwell == 0.0


def test_disabled_blocks_ineligible():
    state, may, dwell = update_expiration_scalp_entry_verification(
        {"started_at": 90.0}, eligible=False, now_ts=100.0, enabled=False, period_seconds=3
    )
    assert state is None
    assert may is False


def test_enabled_zero_seconds_fires_immediately():
    state, may, dwell = update_expiration_scalp_entry_verification(
        None, eligible=True, now_ts=50.0, enabled=True, period_seconds=0
    )
    assert may is True
    assert state == {"started_at": 50.0}
    assert dwell == 0.0


def test_enabled_requires_contiguous_dwell():
    state, may, dwell = update_expiration_scalp_entry_verification(
        None, eligible=True, now_ts=10.0, enabled=True, period_seconds=3
    )
    assert may is False
    assert dwell == 0.0
    assert state == {"started_at": 10.0}

    state, may, dwell = update_expiration_scalp_entry_verification(
        state, eligible=True, now_ts=12.0, enabled=True, period_seconds=3
    )
    assert may is False
    assert dwell == 2.0

    state, may, dwell = update_expiration_scalp_entry_verification(
        state, eligible=True, now_ts=13.0, enabled=True, period_seconds=3
    )
    assert may is True
    assert dwell == 3.0


def test_ineligible_resets_dwell():
    state, may, _ = update_expiration_scalp_entry_verification(
        None, eligible=True, now_ts=10.0, enabled=True, period_seconds=3
    )
    state, may, dwell = update_expiration_scalp_entry_verification(
        state, eligible=False, now_ts=12.0, enabled=True, period_seconds=3
    )
    assert state is None
    assert may is False
    assert dwell == 0.0

    state, may, dwell = update_expiration_scalp_entry_verification(
        state, eligible=True, now_ts=12.5, enabled=True, period_seconds=3
    )
    assert may is False
    assert state == {"started_at": 12.5}
    assert dwell == 0.0
