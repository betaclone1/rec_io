"""Unit tests for Stage 2 PRE core (liquidation, policy, arming, consume)."""

from __future__ import annotations

import pytest

from backend.core.position_risk.arming import assert_paper_consume_allowed
from backend.core.position_risk.ats_consume import consume_pre_decision
from backend.core.position_risk.audit import PositionRiskAudit
from backend.core.position_risk.liquidation import walk_executable_liquidation
from backend.core.position_risk.policy_hws_lvw_v1 import HwsLvwV1Actor
from backend.core.position_risk.safety import assert_safe_for_paper_consume


def _local_env(monkeypatch):
    monkeypatch.delenv("REC_IS_PRODUCTION", raising=False)
    monkeypatch.delenv("REC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("REC_PROD_SSH_HOST", raising=False)
    monkeypatch.delenv("REC_PROD_DB_HOST", raising=False)
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("REC_DB_HOST", "localhost")


def test_yes_walks_yes_bids_gross_only():
    yes = {"0.90": "5", "0.89": "5"}
    no = {"0.10": "100"}  # implies YES ask 0.90
    out = walk_executable_liquidation(yes, no, "yes", 10)
    assert out["ok"] is True
    assert out["gross_lvwap"] == pytest.approx(0.895)
    assert out["net_lvwap"] == pytest.approx(0.895)  # no fee/slip configured


def test_no_walks_implied_from_yes_asks():
    # YES asks from complementary NO bids: NO bid 0.10 → YES ask 0.90 → NO bid implied 0.10
    yes = {"0.50": "1"}
    no = {"0.12": "4", "0.11": "6"}  # YES asks 0.88 and 0.89
    out = walk_executable_liquidation(yes, no, "no", 10)
    assert out["ok"] is True
    # implied NO bids: 1-0.88=0.12 (4), 1-0.89=0.11 (6) → VWAP = (0.12*4 + 0.11*6)/10
    assert out["gross_lvwap"] == pytest.approx(0.114)


def test_depth_insufficient_no_fabricated_vwap():
    yes = {"0.90": "2"}
    out = walk_executable_liquidation(yes, {}, "yes", 10)
    assert out["ok"] is False
    assert out["gross_lvwap"] is None
    assert out["reason"] == "DEPTH_INSUFFICIENT"


def test_policy_deep_breach_requires_dwell():
    actor = HwsLvwV1Actor()
    yes = {"0.85": "10"}  # LVWAP 0.85, floor 0.90 → deep, but same dwell
    d0 = actor.evaluate(
        trade_id=1,
        tenant_slot="0001",
        ticker="T",
        side="yes",
        remaining=10,
        remaining_position_generation=10,
        yes=yes,
        no={},
        floor=0.90,
        book_seq=1,
        book_gen=1,
        book_valid=True,
        tape_state="UNKNOWN",
        book_only_enabled=False,
        mode="shadow",
        ts_event_ms=1000,
        ts_recv_ms=1000,
    )
    assert d0["actionable"] is False

    for i, gen in enumerate((2, 3), start=1):
        d = actor.evaluate(
            trade_id=1,
            tenant_slot="0001",
            ticker="T",
            side="yes",
            remaining=10,
            remaining_position_generation=10,
            yes=yes,
            no={},
            floor=0.90,
            book_seq=gen,
            book_gen=gen,
            book_valid=True,
            tape_state="UNKNOWN",
            book_only_enabled=False,
            mode="shadow",
            ts_event_ms=1000 + i * 130,
            ts_recv_ms=1000 + i * 130,
        )
    assert d["decision_kind"] == "catastrophic"
    assert d["actionable"] is True
    assert d["reason"] == "lvwap_floor_persistence"


def test_policy_shallow_breach_needs_persistence():
    actor = HwsLvwV1Actor()
    yes = {"0.885": "10"}  # below 0.90 but above 0.87
    for i, gen in enumerate((1, 2, 3)):
        d = actor.evaluate(
            trade_id=2,
            tenant_slot="0001",
            ticker="T",
            side="yes",
            remaining=10,
            remaining_position_generation=10,
            yes=yes,
            no={},
            floor=0.90,
            book_seq=gen,
            book_gen=gen,
            book_valid=True,
            tape_state="UNKNOWN",
            book_only_enabled=False,
            mode="shadow",
            ts_event_ms=1000 + i * 130,
            ts_recv_ms=1000 + i * 130,
        )
    assert d["decision_kind"] == "marginal"
    assert d["actionable"] is True


def test_paper_consume_gates(monkeypatch, tmp_path):
    _local_env(monkeypatch)
    ok, reason = assert_paper_consume_allowed(True, "paper")
    assert ok, reason
    ok2, _ = assert_safe_for_paper_consume()
    assert ok2

    monkeypatch.setenv("REC_IS_PRODUCTION", "1")
    ok3, reason3 = assert_paper_consume_allowed(True, "paper")
    assert ok3, reason3


def test_ats_consume_accept(monkeypatch, tmp_path):
    _local_env(monkeypatch)
    monkeypatch.setenv("REC_POSITION_RISK_AUDIT_DIR", str(tmp_path))

    r = consume_pre_decision(trade_id=99, paper_trade=True)
    assert r.action == "hold"
    assert r.reason == "no_actionable_pre_decision"

    from backend.core.position_risk import audit as audit_mod

    audit_mod._default_audit = PositionRiskAudit(enable_redis=False)
    audit_mod._default_audit.append(
        "decision_emit",
        {
            "decision": {
                "trade_id": 99,
                "tenant_slot": "0001",
                "ticker": "T",
                "side": "yes",
                "remaining": 10,
                "remaining_position_generation": 10,
                "policy_version": "hws_lvw_v1",
                "decision_generation": 1,
                "decision_kind": "catastrophic",
                "actionable": True,
                "shadow_only": False,
                "floor": 0.9,
                "gross_lvwap": 0.85,
            },
            "actionable": True,
            "shadow_only": False,
        },
        trade_id=99,
        tenant_slot="0001",
    )

    r2 = consume_pre_decision(
        trade_id=99,
        tenant_slot="0001",
        remaining_position_generation=10,
        lease_ok=True,
        book_fresh=True,
    )
    assert r2.action == "accept"
