"""ATS consume dedupe: at most one accept per decision generation key."""

from __future__ import annotations

import pytest

from backend.core.position_risk.ats_consume import (
    TRIGGER_CATASTROPHIC,
    clear_accepted_dedupe_for_tests,
    consider_hws_pre_decision,
)
from backend.core.position_risk.audit import PositionRiskAudit
from backend.core.position_risk.decision import RiskDecision


@pytest.fixture(autouse=True)
def _clear_dedupe(monkeypatch, tmp_path):
    clear_accepted_dedupe_for_tests()
    monkeypatch.setenv("REC_POSITION_RISK_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.delenv("REC_IS_PRODUCTION", raising=False)
    monkeypatch.delenv("REC_PROD_SSH_HOST", raising=False)
    monkeypatch.delenv("REC_PROD_DB_HOST", raising=False)
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("REC_DB_HOST", "localhost")
    import backend.core.position_risk.audit as audit_mod

    audit_mod._default_audit = PositionRiskAudit(enable_redis=False)
    yield
    clear_accepted_dedupe_for_tests()


def _seed_actionable(trade_id: int = 42, gen: int = 1):
    d = RiskDecision(
        trade_id=trade_id,
        tenant_slot="0001",
        ticker="T",
        side="Y",
        remaining=10,
        remaining_position_generation=1,
        policy_version="hws_lvw_v1",
        decision_generation=gen,
        decision_kind="catastrophic",
        actionable=True,
        shadow_only=False,
        floor=0.9,
        gross_lvwap=0.85,
    )
    from backend.core.position_risk.audit import get_audit

    get_audit().append(
        "decision_emit",
        {"decision": d.to_dict(), **d.to_dict()},
        trade_id=trade_id,
        tenant_slot="0001",
    )
    return d


def test_ats_consume_dedupe_second_accept_rejected():
    _seed_actionable(42, gen=7)
    trade = {"trade_id": 42, "paper_trade": True, "tenant_slot": "0001"}
    first = consider_hws_pre_decision(trade, tenant_slot="0001", record_audit=True)
    assert first.action == "accept"
    assert first.trigger_reason == TRIGGER_CATASTROPHIC
    assert first.run_legacy is False

    second = consider_hws_pre_decision(trade, tenant_slot="0001", record_audit=True)
    assert second.action == "reject"
    assert second.reason == "dedupe_already_accepted"
    assert second.run_legacy is False


def test_no_decision_holds():
    trade = {"trade_id": 77, "paper_trade": True}
    r = consider_hws_pre_decision(trade)
    assert r.action == "hold"
    assert r.reason == "no_actionable_pre_decision"
    assert r.run_legacy is False


def test_prod_host_accepts(monkeypatch):
    monkeypatch.setenv("REC_IS_PRODUCTION", "1")
    _seed_actionable(99, gen=1)
    trade = {"trade_id": 99, "paper_trade": True}
    r = consider_hws_pre_decision(trade)
    assert r.action == "accept"
    assert r.trigger_reason == TRIGGER_CATASTROPHIC
