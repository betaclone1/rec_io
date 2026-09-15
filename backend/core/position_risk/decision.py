"""Versioned, idempotent RiskDecision for PRE → ATS handoff."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple


POLICY_HWS_LVW_V1 = "hws_lvw_v1"


@dataclass
class RiskDecision:
    trade_id: int
    tenant_slot: str
    ticker: str
    side: str
    remaining: float
    remaining_position_generation: int
    policy_version: str
    decision_generation: int
    decision_kind: str  # catastrophic | marginal | depth_insufficient | unknown | clear | hold
    actionable: bool
    shadow_only: bool
    floor: Optional[float]
    gross_lvwap: Optional[float]
    estimated_taker_fee: Optional[float] = None
    slippage_reserve: Optional[float] = None
    net_lvwap: Optional[float] = None
    coverage: Optional[float] = None
    worst_consumed_price: Optional[float] = None
    book_seq: Optional[int] = None
    book_gen: Optional[int] = None
    tape_state: str = "UNKNOWN"
    data_health_reason: str = ""
    reason: str = ""
    mode: str = "legacy"
    book_only_enabled: bool = False
    ts_event_ms: Optional[int] = None
    ts_recv_ms: Optional[int] = None
    ts_eval_ms: Optional[int] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def dedupe_key(self) -> Tuple[int, int, str, int]:
        return make_dedupe_key(
            self.trade_id,
            self.remaining_position_generation,
            self.policy_version,
            self.decision_generation,
        )

    def dedupe_key_str(self) -> str:
        tid, rgen, pol, dgen = self.dedupe_key()
        return f"{tid}:{rgen}:{pol}:{dgen}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["dedupe_key"] = self.dedupe_key_str()
        return d

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "RiskDecision":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in raw.items() if k in known}
        extras = dict(raw.get("extras") or {})
        for k, v in raw.items():
            if k not in known and k not in ("dedupe_key",):
                extras.setdefault(k, v)
        kwargs["extras"] = extras
        return cls(**kwargs)


def make_dedupe_key(
    trade_id: int,
    remaining_position_generation: int,
    policy_version: str,
    decision_generation: int,
) -> Tuple[int, int, str, int]:
    return (
        int(trade_id),
        int(remaining_position_generation),
        str(policy_version),
        int(decision_generation),
    )
