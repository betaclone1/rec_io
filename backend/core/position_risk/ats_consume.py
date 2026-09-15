"""ATS-side PRE decision consumption (validate only — no TM/TE imports).

active_trade_supervisor remains sole close authority. HWS stop trigger is
gross executable LVWAP vs floor from PRE — not the legacy opposite-ask touch.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Set

from backend.core.position_risk.arming import assert_paper_consume_allowed
from backend.core.position_risk.audit import get_audit
from backend.core.position_risk.decision import RiskDecision


# Hard guarantee: this module must never import trade_manager or trade_executor.
_FORBIDDEN_IMPORTS = frozenset(
    {"backend.trade_manager", "backend.trade_executor", "trade_manager", "trade_executor"}
)

TRIGGER_CATASTROPHIC = "pre_hws_catastrophic"
TRIGGER_MARGINAL = "pre_hws_marginal"

_accepted_dedupe: Set[str] = set()
_dedupe_lock = threading.Lock()


@dataclass
class ConsumeResult:
    action: str  # accept | reject | hold
    reason: str
    decision: Optional[Dict[str, Any]] = None
    dedupe_key: Optional[str] = None
    trigger_reason: Optional[str] = None
    run_legacy: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def clear_accepted_dedupe_for_tests() -> None:
    with _dedupe_lock:
        _accepted_dedupe.clear()


def _trigger_reason_for_kind(kind: Optional[str]) -> Optional[str]:
    k = (kind or "").strip().lower()
    if k == "catastrophic":
        return TRIGGER_CATASTROPHIC
    if k == "marginal":
        return TRIGGER_MARGINAL
    return None


def _audit_consume(event_type: str, trade: Dict[str, Any], result: ConsumeResult, **extra: Any) -> None:
    try:
        tid = trade.get("trade_id")
        get_audit().append(
            event_type,
            {
                "trade_id": tid,
                "action": result.action,
                "reason": result.reason,
                "dedupe_key": result.dedupe_key,
                "trigger_reason": result.trigger_reason,
                "run_legacy": result.run_legacy,
                "decision": result.decision,
                **extra,
            },
            trade_id=int(tid) if tid is not None else None,
            tenant_slot=extra.get("tenant_slot") or trade.get("tenant_slot"),
        )
    except Exception:
        pass


def load_latest_actionable_decision(
    trade_id: int,
    *,
    tenant_slot: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return get_audit().latest_actionable_decision(trade_id, tenant_slot=tenant_slot)


def consume_pre_decision(
    *,
    trade_id: int,
    tenant_slot: Optional[str] = None,
    paper_trade: bool = True,
    position_risk_mode: str = "paper",
    remaining_position_generation: Optional[int] = None,
    lease_ok: bool = True,
    book_fresh: bool = True,
) -> ConsumeResult:
    """Validate latest PRE decision for ATS. Never places orders. Never imports TM/TE."""
    _ = position_risk_mode

    ok, reason = assert_paper_consume_allowed(paper_trade, "paper")
    if not ok:
        return ConsumeResult(action="reject", reason=reason, run_legacy=False)

    decision_raw = load_latest_actionable_decision(trade_id, tenant_slot=tenant_slot)
    if decision_raw is None:
        return ConsumeResult(
            action="hold",
            reason="no_actionable_pre_decision",
            run_legacy=False,
        )

    try:
        decision = RiskDecision.from_dict(decision_raw)
    except Exception as exc:
        return ConsumeResult(
            action="reject",
            reason=f"invalid_decision_payload:{exc}",
            decision=decision_raw,
            run_legacy=False,
        )

    if decision.shadow_only or not decision.actionable:
        return ConsumeResult(
            action="hold",
            reason="decision_not_actionable",
            decision=decision.to_dict(),
            dedupe_key=decision.dedupe_key_str(),
            run_legacy=False,
        )

    if decision.decision_kind == "depth_insufficient":
        return ConsumeResult(
            action="hold",
            reason="DEPTH_INSUFFICIENT_not_actionable",
            decision=decision.to_dict(),
            dedupe_key=decision.dedupe_key_str(),
            run_legacy=False,
        )

    if remaining_position_generation is not None:
        if int(remaining_position_generation) != int(decision.remaining_position_generation):
            return ConsumeResult(
                action="reject",
                reason="remaining_position_generation_mismatch",
                decision=decision.to_dict(),
                dedupe_key=decision.dedupe_key_str(),
                run_legacy=False,
            )

    if not lease_ok:
        return ConsumeResult(
            action="hold",
            reason="lease_not_ok",
            decision=decision.to_dict(),
            dedupe_key=decision.dedupe_key_str(),
            run_legacy=False,
        )
    if not book_fresh:
        return ConsumeResult(
            action="hold",
            reason="book_not_fresh",
            decision=decision.to_dict(),
            dedupe_key=decision.dedupe_key_str(),
            run_legacy=False,
        )

    return ConsumeResult(
        action="accept",
        reason="pre_lvwap_floor",
        decision=decision.to_dict(),
        dedupe_key=decision.dedupe_key_str(),
        run_legacy=False,
    )


def consider_hws_pre_decision(
    trade: Dict[str, Any],
    *,
    stop_floor: Optional[float] = None,
    remaining: Optional[float] = None,
    paper_trade: Optional[bool] = None,
    position_risk_mode: Optional[str] = None,
    tenant_slot: Optional[str] = None,
    remaining_position_generation: Optional[int] = None,
    lease_ok: bool = True,
    book_fresh: bool = True,
    record_audit: bool = True,
) -> ConsumeResult:
    """HWS stop gate: accept PRE LVWAP floor decisions; otherwise hold (no legacy ask floor)."""
    pt = paper_trade if paper_trade is not None else bool(trade.get("paper_trade"))
    tid = trade.get("trade_id")
    try:
        tid_i = int(tid) if tid is not None else 0
    except (TypeError, ValueError):
        tid_i = 0
    slot = tenant_slot if tenant_slot is not None else trade.get("tenant_slot")
    mode_n = (
        str(position_risk_mode if position_risk_mode is not None else trade.get("position_risk_mode") or "paper")
        .strip()
        .lower()
        or "paper"
    )

    base = consume_pre_decision(
        trade_id=tid_i,
        tenant_slot=str(slot) if slot is not None else None,
        paper_trade=bool(pt),
        position_risk_mode=mode_n,
        remaining_position_generation=remaining_position_generation,
        lease_ok=lease_ok,
        book_fresh=book_fresh,
    )

    if base.action == "accept" and base.decision:
        kind = (base.decision.get("decision_kind") or "").strip().lower()
        trigger = _trigger_reason_for_kind(kind)
        key = base.dedupe_key or ""
        if not trigger:
            result = ConsumeResult(
                action="reject",
                reason=f"unknown_decision_kind:{kind}",
                decision=base.decision,
                dedupe_key=key or None,
                run_legacy=False,
            )
        else:
            with _dedupe_lock:
                if key and key in _accepted_dedupe:
                    result = ConsumeResult(
                        action="reject",
                        reason="dedupe_already_accepted",
                        decision=base.decision,
                        dedupe_key=key,
                        trigger_reason=trigger,
                        run_legacy=False,
                    )
                else:
                    if key:
                        _accepted_dedupe.add(key)
                    result = ConsumeResult(
                        action="accept",
                        reason=base.reason,
                        decision=base.decision,
                        dedupe_key=key or None,
                        trigger_reason=trigger,
                        run_legacy=False,
                    )
    else:
        result = ConsumeResult(
            action=base.action,
            reason=base.reason,
            decision=base.decision,
            dedupe_key=base.dedupe_key,
            run_legacy=False,
        )

    if record_audit:
        _audit_consume(
            "ats_consume",
            trade,
            result,
            tenant_slot=slot,
            stop_floor=stop_floor,
            remaining=remaining,
        )
    return result
