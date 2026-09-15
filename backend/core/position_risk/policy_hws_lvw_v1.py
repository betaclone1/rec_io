"""Policy hws_lvw_v1 — stateful per-position actor (gross LVWAP vs floor).

Material difference vs legacy HWS floor: trigger uses full-size executable
gross LVWAP vs stop floor, not opposite-ask / hard book touch.

Shared persistence for every breach (no catastrophic dwell override):
  LVWAP < floor for >=250ms AND >=3 distinct valid book generations → emit
  hysteresis rearm: LVWAP >= floor + 0.02 for >=500ms AND >=3 gens
  DEPTH_INSUFFICIENT: shadow-only (never actionable close)

Severity label (catastrophic vs marginal) is audit-only after persistence is met
(depth vs floor-0.03); it does not change timing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from backend.core.position_risk.book_health import TapeState
from backend.core.position_risk.decision import POLICY_HWS_LVW_V1, RiskDecision
from backend.core.position_risk.liquidation import walk_executable_liquidation

POLICY_VERSION = POLICY_HWS_LVW_V1
# Audit severity threshold only (does not skip dwell).
SEVERITY_CENTS = 0.03
HYSTERESIS_CENTS = 0.02
PERSIST_MS = 250
HYSTERESIS_MS = 500
PERSIST_GENS = 3
HYSTERESIS_GENS = 3

# Back-compat aliases for imports/tests
CATASTROPHIC_CENTS = SEVERITY_CENTS
MARGINAL_MS = PERSIST_MS
MARGINAL_GENS = PERSIST_GENS


@dataclass
class HwsLvwActorState:
    remaining_position_generation: int = 0
    decision_generation: int = 0
    # Breach persistence tracking (all depths below floor)
    breach_first_event_ms: Optional[int] = None
    breach_first_recv_ms: Optional[int] = None
    breach_gens: Set[int] = field(default_factory=set)
    # After emit clears / awaiting rearm
    armed: bool = True
    hysteresis_first_event_ms: Optional[int] = None
    hysteresis_first_recv_ms: Optional[int] = None
    hysteresis_gens: Set[int] = field(default_factory=set)
    last_decision: Optional[RiskDecision] = None


class HwsLvwV1Actor:
    def __init__(self) -> None:
        self.state = HwsLvwActorState()

    def reset_for_position_generation(self, generation: int) -> None:
        self.state = HwsLvwActorState(remaining_position_generation=int(generation))

    def evaluate(
        self,
        *,
        trade_id: int,
        tenant_slot: str,
        ticker: str,
        side: str,
        remaining: float,
        remaining_position_generation: int,
        yes: Dict[str, str],
        no: Dict[str, str],
        floor: Optional[float],
        book_seq: Optional[int],
        book_gen: Optional[int],
        book_valid: bool,
        data_health_reason: str = "",
        tape_state: str = TapeState.UNKNOWN.value,
        book_only_enabled: bool = False,
        mode: str = "shadow",
        ts_event_ms: Optional[int] = None,
        ts_recv_ms: Optional[int] = None,
        estimated_taker_fee_per_contract: Optional[float] = None,
        slippage_reserve: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Return a decision dict (RiskDecision.to_dict() plus state summary)."""
        if int(remaining_position_generation) != self.state.remaining_position_generation:
            self.reset_for_position_generation(remaining_position_generation)

        now_event = ts_event_ms
        now_recv = ts_recv_ms
        gen = int(book_gen if book_gen is not None else (book_seq or 0))

        base_kwargs = dict(
            trade_id=int(trade_id),
            tenant_slot=str(tenant_slot),
            ticker=str(ticker),
            side=str(side),
            remaining=float(remaining),
            remaining_position_generation=int(remaining_position_generation),
            policy_version=POLICY_VERSION,
            floor=floor,
            book_seq=book_seq,
            book_gen=gen,
            tape_state=str(tape_state or TapeState.UNKNOWN.value),
            data_health_reason=str(data_health_reason or ""),
            mode=str(mode or "legacy"),
            book_only_enabled=bool(book_only_enabled),
            ts_event_ms=ts_event_ms,
            ts_recv_ms=ts_recv_ms,
            ts_eval_ms=ts_recv_ms,
        )

        if not book_valid or floor is None or remaining <= 0:
            self.state.decision_generation += 1
            d = RiskDecision(
                **base_kwargs,
                decision_generation=self.state.decision_generation,
                decision_kind="unknown",
                actionable=False,
                shadow_only=True,
                gross_lvwap=None,
                reason=data_health_reason or "book_invalid_or_no_floor",
            )
            self.state.last_decision = d
            return {**d.to_dict(), "state": "unknown"}

        liq = walk_executable_liquidation(
            yes,
            no,
            side,
            remaining,
            estimated_taker_fee_per_contract=estimated_taker_fee_per_contract,
            slippage_reserve=slippage_reserve,
        )
        gross = liq.get("gross_lvwap")
        fee = liq.get("estimated_taker_fee")
        slip = liq.get("slippage_reserve")
        net = liq.get("net_lvwap")

        if not liq.get("full_coverage"):
            self.state.decision_generation += 1
            d = RiskDecision(
                **base_kwargs,
                decision_generation=self.state.decision_generation,
                decision_kind="depth_insufficient",
                actionable=False,
                shadow_only=True,
                gross_lvwap=None,
                estimated_taker_fee=fee,
                slippage_reserve=slip,
                net_lvwap=net,
                coverage=liq.get("coverage"),
                worst_consumed_price=liq.get("worst_consumed_price"),
                reason="DEPTH_INSUFFICIENT",
                extras={"levels_consumed": liq.get("levels_consumed")},
            )
            self.state.last_decision = d
            self._clear_breach()
            return {**d.to_dict(), "state": "depth_insufficient"}

        fl = float(floor)
        lv = float(gross)
        severity_line = fl - SEVERITY_CENTS
        hysteresis_line = fl + HYSTERESIS_CENTS

        # Any LVWAP below floor → same persistence (no immediate catastrophic emit).
        if lv < fl - 1e-12:
            if not self.state.armed:
                self.state.decision_generation += 1
                d = RiskDecision(
                    **base_kwargs,
                    decision_generation=self.state.decision_generation,
                    decision_kind="hold",
                    actionable=False,
                    shadow_only=True,
                    gross_lvwap=lv,
                    estimated_taker_fee=fee,
                    slippage_reserve=slip,
                    net_lvwap=net,
                    coverage=liq.get("coverage"),
                    worst_consumed_price=liq.get("worst_consumed_price"),
                    reason="disarmed_awaiting_hysteresis",
                )
                self.state.last_decision = d
                self._clear_hysteresis()
                return {**d.to_dict(), "state": "disarmed"}

            if self.state.breach_first_event_ms is None:
                self.state.breach_first_event_ms = now_event
                self.state.breach_first_recv_ms = now_recv
                self.state.breach_gens = {gen}
            else:
                self.state.breach_gens.add(gen)

            elapsed = self._elapsed_ms(
                self.state.breach_first_event_ms,
                self.state.breach_first_recv_ms,
                now_event,
                now_recv,
            )
            if (
                elapsed is not None
                and elapsed >= PERSIST_MS
                and len(self.state.breach_gens) >= PERSIST_GENS
            ):
                self.state.decision_generation += 1
                deep = lv <= severity_line + 1e-12
                kind = "catastrophic" if deep else "marginal"
                d = RiskDecision(
                    **base_kwargs,
                    decision_generation=self.state.decision_generation,
                    decision_kind=kind,
                    actionable=True,
                    shadow_only=False,
                    gross_lvwap=lv,
                    estimated_taker_fee=fee,
                    slippage_reserve=slip,
                    net_lvwap=net,
                    coverage=liq.get("coverage"),
                    worst_consumed_price=liq.get("worst_consumed_price"),
                    reason="lvwap_floor_persistence",
                    extras={
                        "levels_consumed": liq.get("levels_consumed"),
                        "persist_ms": elapsed,
                        "persist_gens": sorted(self.state.breach_gens),
                        "severity_deep": deep,
                    },
                )
                self.state.last_decision = d
                self.state.armed = False
                self._clear_breach()
                return {**d.to_dict(), "state": "floor_emit"}

            self.state.decision_generation += 1
            d = RiskDecision(
                **base_kwargs,
                decision_generation=self.state.decision_generation,
                decision_kind="hold",
                actionable=False,
                shadow_only=True,
                gross_lvwap=lv,
                estimated_taker_fee=fee,
                slippage_reserve=slip,
                net_lvwap=net,
                coverage=liq.get("coverage"),
                worst_consumed_price=liq.get("worst_consumed_price"),
                reason="lvwap_floor_accumulating",
                extras={
                    "persist_ms": elapsed,
                    "persist_gens": sorted(self.state.breach_gens),
                },
            )
            self.state.last_decision = d
            self._clear_hysteresis()
            return {**d.to_dict(), "state": "floor_accumulating"}

        # At or above floor
        self._clear_breach()
        if self.state.armed:
            self.state.decision_generation += 1
            d = RiskDecision(
                **base_kwargs,
                decision_generation=self.state.decision_generation,
                decision_kind="clear",
                actionable=False,
                shadow_only=True,
                gross_lvwap=lv,
                estimated_taker_fee=fee,
                slippage_reserve=slip,
                net_lvwap=net,
                coverage=liq.get("coverage"),
                worst_consumed_price=liq.get("worst_consumed_price"),
                reason="above_floor",
            )
            self.state.last_decision = d
            return {**d.to_dict(), "state": "clear"}

        # Disarmed: require hysteresis to rearm
        if lv + 1e-12 >= hysteresis_line:
            if self.state.hysteresis_first_event_ms is None:
                self.state.hysteresis_first_event_ms = now_event
                self.state.hysteresis_first_recv_ms = now_recv
                self.state.hysteresis_gens = {gen}
            else:
                self.state.hysteresis_gens.add(gen)
            elapsed = self._elapsed_ms(
                self.state.hysteresis_first_event_ms,
                self.state.hysteresis_first_recv_ms,
                now_event,
                now_recv,
            )
            if (
                elapsed is not None
                and elapsed >= HYSTERESIS_MS
                and len(self.state.hysteresis_gens) >= HYSTERESIS_GENS
            ):
                self.state.armed = True
                self._clear_hysteresis()
                self.state.decision_generation += 1
                d = RiskDecision(
                    **base_kwargs,
                    decision_generation=self.state.decision_generation,
                    decision_kind="clear",
                    actionable=False,
                    shadow_only=True,
                    gross_lvwap=lv,
                    estimated_taker_fee=fee,
                    slippage_reserve=slip,
                    net_lvwap=net,
                    coverage=liq.get("coverage"),
                    worst_consumed_price=liq.get("worst_consumed_price"),
                    reason="hysteresis_rearmed",
                    extras={"hysteresis_ms": elapsed},
                )
                self.state.last_decision = d
                return {**d.to_dict(), "state": "rearmed"}
        else:
            self._clear_hysteresis()

        self.state.decision_generation += 1
        d = RiskDecision(
            **base_kwargs,
            decision_generation=self.state.decision_generation,
            decision_kind="hold",
            actionable=False,
            shadow_only=True,
            gross_lvwap=lv,
            estimated_taker_fee=fee,
            slippage_reserve=slip,
            net_lvwap=net,
            coverage=liq.get("coverage"),
            worst_consumed_price=liq.get("worst_consumed_price"),
            reason="disarmed_hysteresis_pending",
        )
        self.state.last_decision = d
        return {**d.to_dict(), "state": "disarmed"}

    def ack_latched(self) -> None:
        """No-op retained for callers; latch removed with dwell override."""
        return None

    def _clear_breach(self) -> None:
        self.state.breach_first_event_ms = None
        self.state.breach_first_recv_ms = None
        self.state.breach_gens = set()

    def _clear_marginal(self) -> None:
        # Alias used by older call sites / tests
        self._clear_breach()

    def _clear_hysteresis(self) -> None:
        self.state.hysteresis_first_event_ms = None
        self.state.hysteresis_first_recv_ms = None
        self.state.hysteresis_gens = set()

    @staticmethod
    def _elapsed_ms(
        first_event: Optional[int],
        first_recv: Optional[int],
        now_event: Optional[int],
        now_recv: Optional[int],
    ) -> Optional[int]:
        if first_event is not None and now_event is not None:
            return max(0, int(now_event) - int(first_event))
        if first_recv is not None and now_recv is not None:
            return max(0, int(now_recv) - int(first_recv))
        return None
