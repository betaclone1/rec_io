"""Unit tests for weekend_adjustment apply/revert math and ET window."""

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.core.weekend_adjustment import (
    adjusted_min_probability,
    build_apply_plan,
    build_revert_updates,
    is_weekend_adjustment_active_period,
    normalize_weekend_adjustment,
    reduced_position_size,
)

ET = ZoneInfo("America/New_York")


def _et(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=ET)


def test_normalize_weekend_adjustment():
    assert normalize_weekend_adjustment(None) == "none"
    assert normalize_weekend_adjustment("PAPER_ONLY") == "paper_only"
    assert normalize_weekend_adjustment("bogus") is None


def test_reduced_position_size():
    assert reduced_position_size(100, 0.50) == 50
    assert reduced_position_size(100, 0.25) == 25
    assert reduced_position_size(1, 0.25) == 1
    assert reduced_position_size(3, 0.25) == 1


def test_adjusted_min_probability_capped():
    assert adjusted_min_probability(55.0, 10.0) == 65.0
    assert adjusted_min_probability(55.0, 25.0) == 80.0
    assert adjusted_min_probability(95.0, 10.0) == 100.0
    assert adjusted_min_probability(90.0, 25.0) == 100.0


def test_is_weekend_adjustment_active_period_windows():
    # Fri late — inactive
    assert is_weekend_adjustment_active_period(_et(2026, 8, 28, 23, 59, 59)) is False
    # Sat before 00:00:30 — inactive
    assert is_weekend_adjustment_active_period(_et(2026, 8, 29, 0, 0, 29)) is False
    # Sat at 00:00:30 — active
    assert is_weekend_adjustment_active_period(_et(2026, 8, 29, 0, 0, 30)) is True
    # Sunday — active
    assert is_weekend_adjustment_active_period(_et(2026, 8, 30, 12, 0, 0)) is True
    # Mon before 00:00:20 — still active
    assert is_weekend_adjustment_active_period(_et(2026, 8, 31, 0, 0, 19)) is True
    # Mon at 00:00:20 — inactive (revert)
    assert is_weekend_adjustment_active_period(_et(2026, 8, 31, 0, 0, 20)) is False
    # Tue — inactive
    assert is_weekend_adjustment_active_period(_et(2026, 9, 1, 10, 0, 0)) is False


def test_build_apply_plan_paper_only():
    plan = build_apply_plan(
        "paper_only",
        paper_trade=False,
        position_size=10,
        min_probability=55.0,
        applied_at_iso="2026-08-29T00:00:30-04:00",
    )
    assert plan is not None
    snap, updates = plan
    assert snap["paper_trade"] is False
    assert snap["mode"] == "paper_only"
    assert updates == {"paper_trade": True}


def test_build_apply_plan_reduce_and_prob():
    snap50, up50 = build_apply_plan(
        "reduce_position_50",
        paper_trade=True,
        position_size=40,
        min_probability=55.0,
        applied_at_iso="t",
    )
    assert snap50["position_size"] == 40
    assert up50["position_size"] == 20

    snap25, up25 = build_apply_plan(
        "reduce_position_25",
        paper_trade=True,
        position_size=40,
        min_probability=55.0,
        applied_at_iso="t",
    )
    assert up25["position_size"] == 10

    snap10, up10 = build_apply_plan(
        "probability_adjustment_10",
        paper_trade=False,
        position_size=1,
        min_probability=55.0,
        applied_at_iso="t",
    )
    assert snap10["min_probability"] == 55.0
    assert up10["min_probability"] == 65.0

    assert build_apply_plan(
        "none",
        paper_trade=False,
        position_size=1,
        min_probability=55.0,
        applied_at_iso="t",
    ) is None


def test_build_revert_updates_roundtrip():
    assert build_revert_updates(None) is None
    assert build_revert_updates({"mode": "paper_only"}) is None
    out = build_revert_updates(
        {"mode": "paper_only", "paper_trade": False, "position_size": 40, "min_probability": 55.0}
    )
    assert out["paper_trade"] is False
    assert out["position_size"] == 40
    assert out["min_probability"] == 55.0
