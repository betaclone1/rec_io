"""Policy hws_lvw_v1: shared dwell for all LVWAP floor breaches (no catastrophic override)."""

from __future__ import annotations

from backend.core.position_risk.book_health import TapeState
from backend.core.position_risk.policy_hws_lvw_v1 import HwsLvwV1Actor


def _book_yes_at(px: float, size: float = 100.0):
    return {f"{px:.2f}": str(size)}, {}


def _eval(actor, *, lv, floor=0.90, gen=1, t_ms=0, tape=TapeState.UNKNOWN.value, book_only=False, valid=True):
    yes, no = _book_yes_at(lv)
    return actor.evaluate(
        trade_id=1,
        tenant_slot="0001",
        ticker="T",
        side="Y",
        remaining=10,
        remaining_position_generation=1,
        yes=yes,
        no=no,
        floor=floor,
        book_seq=gen,
        book_gen=gen,
        book_valid=valid,
        tape_state=tape,
        book_only_enabled=book_only,
        mode="paper",
        ts_event_ms=t_ms,
        ts_recv_ms=t_ms,
    )


def test_deep_breach_requires_same_dwell_as_shallow():
    """Former 'catastrophic' depth must not emit on one generation."""
    a = HwsLvwV1Actor()
    d = _eval(a, lv=0.86, gen=1, t_ms=1000)  # floor 0.90 → -4c
    assert d["actionable"] is False
    assert d["decision_kind"] == "hold"
    assert d["reason"] == "lvwap_floor_accumulating"

    for g, t in ((2, 1100), (3, 1250)):
        d = _eval(a, lv=0.86, gen=g, t_ms=t)
    assert d["actionable"] is True
    assert d["decision_kind"] == "catastrophic"  # severity label only
    assert d["reason"] == "lvwap_floor_persistence"


def test_shallow_breach_needs_persistence_and_gens():
    a = HwsLvwV1Actor()
    d1 = _eval(a, lv=0.89, gen=1, t_ms=0)
    assert d1["decision_kind"] == "hold"
    assert d1["actionable"] is False
    d2 = _eval(a, lv=0.89, gen=2, t_ms=100)
    assert d2["actionable"] is False
    d3 = _eval(a, lv=0.89, gen=3, t_ms=200)
    assert d3["actionable"] is False  # only 200ms (<250)
    d4 = _eval(a, lv=0.89, gen=3, t_ms=250)
    assert d4["decision_kind"] == "marginal"
    assert d4["actionable"] is True


def test_hysteresis_rearm():
    a = HwsLvwV1Actor()
    for g, t in ((1, 0), (2, 100), (3, 250)):
        _eval(a, lv=0.89, gen=g, t_ms=t)
    assert a.state.armed is False
    d = _eval(a, lv=0.91, gen=10, t_ms=1000)
    assert d["decision_kind"] == "hold"
    assert a.state.armed is False
    for g, t in ((11, 1000), (12, 1200), (13, 1500)):
        d = _eval(a, lv=0.92, gen=g, t_ms=t)
    assert a.state.armed is True
    assert d["reason"] == "hysteresis_rearmed"


def test_depth_insufficient_shadow_only():
    a = HwsLvwV1Actor()
    d = a.evaluate(
        trade_id=1,
        tenant_slot="0001",
        ticker="T",
        side="Y",
        remaining=100,
        remaining_position_generation=1,
        yes={"0.80": "1"},
        no={},
        floor=0.90,
        book_seq=1,
        book_gen=1,
        book_valid=True,
        mode="paper",
        ts_event_ms=1,
        ts_recv_ms=1,
    )
    assert d["decision_kind"] == "depth_insufficient"
    assert d["actionable"] is False
    assert d["shadow_only"] is True


def test_gap_or_invalid_book_unknown():
    a = HwsLvwV1Actor()
    d = a.evaluate(
        trade_id=1,
        tenant_slot="0001",
        ticker="T",
        side="Y",
        remaining=10,
        remaining_position_generation=1,
        yes={"0.80": "10"},
        no={},
        floor=0.90,
        book_seq=1,
        book_gen=1,
        book_valid=False,
        data_health_reason="seq_gap",
        mode="paper",
        ts_event_ms=1,
        ts_recv_ms=1,
    )
    assert d["decision_kind"] == "unknown"
    assert d["actionable"] is False


def test_tape_unknown_does_not_block_lvwap_floor():
    """L2 VWAP floor is the patch trigger; tape UNKNOWN must not veto it."""
    a = HwsLvwV1Actor()
    for g, t in ((1, 0), (2, 100), (3, 250)):
        d = _eval(a, lv=0.89, gen=g, t_ms=t, tape=TapeState.UNKNOWN.value, book_only=False)
    assert d["actionable"] is True
    assert d["decision_kind"] == "marginal"
