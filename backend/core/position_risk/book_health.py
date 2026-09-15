"""Book / transport health — quiet books are not stale solely from lack of deltas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class BookHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    QUIET_HEALTHY = "QUIET_HEALTHY"
    RESYNCING = "RESYNCING"
    STALE = "STALE"
    INVALID = "INVALID"
    MISSING = "MISSING"


class TapeState(str, Enum):
    UNKNOWN = "UNKNOWN"  # Stage 1: public trades not ingested
    OK = "OK"
    STALE = "STALE"
    MISSING = "MISSING"


@dataclass
class BookHealth:
    state: BookHealthState
    seq: Optional[int]
    last_seq: Optional[int]
    ts_ms: Optional[int]
    redis_written_ms: Optional[int]
    received_ms: Optional[int]
    gap: bool
    reason: str
    tape: TapeState = TapeState.UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "seq": self.seq,
            "last_seq": self.last_seq,
            "ts_ms": self.ts_ms,
            "redis_written_ms": self.redis_written_ms,
            "received_ms": self.received_ms,
            "gap": self.gap,
            "reason": self.reason,
            "tape": self.tape.value,
        }


def evaluate_book_health(
    *,
    snapshot_valid: Optional[bool],
    seq: Optional[int],
    last_seq: Optional[int],
    ts_ms: Optional[int],
    redis_written_ms: Optional[int],
    received_ms: Optional[int],
    ws_transport_ok: Optional[bool] = None,
    max_apply_age_ms: int = 5000,
    expect_seq_monotonic: bool = True,
) -> BookHealth:
    """
    Validity from transport/sequence evidence, not from 'levels unchanged'.

    - Missing snapshot → MISSING
    - valid=False → INVALID
    - seq gap (seq > last+1) → RESYNCING
    - apply age beyond max while transport not ok → STALE
    - apply age beyond max but transport ok / unknown → QUIET_HEALTHY if seq stable
    - else HEALTHY
    """
    tape = TapeState.UNKNOWN
    if snapshot_valid is None and seq is None and ts_ms is None:
        return BookHealth(
            BookHealthState.MISSING,
            seq,
            last_seq,
            ts_ms,
            redis_written_ms,
            received_ms,
            False,
            "no_snapshot",
            tape,
        )
    if snapshot_valid is False:
        return BookHealth(
            BookHealthState.INVALID,
            seq,
            last_seq,
            ts_ms,
            redis_written_ms,
            received_ms,
            False,
            "snapshot_valid_false",
            tape,
        )

    gap = False
    if seq is not None and last_seq is not None:
        if int(seq) < int(last_seq):
            # Sequence rewind → real resync / snapshot replace.
            return BookHealth(
                BookHealthState.RESYNCING,
                seq,
                last_seq,
                ts_ms,
                redis_written_ms,
                received_ms,
                True,
                f"seq_rewind last={last_seq} seq={seq}",
                tape,
            )
        if expect_seq_monotonic and int(seq) > int(last_seq) + 1:
            # Strict continuity (event-stream consumers). Poll-of-latest hot
            # cache must pass expect_seq_monotonic=False — forward jumps are normal.
            gap = True
            return BookHealth(
                BookHealthState.RESYNCING,
                seq,
                last_seq,
                ts_ms,
                redis_written_ms,
                received_ms,
                True,
                f"seq_gap last={last_seq} seq={seq}",
                tape,
            )
        if int(seq) > int(last_seq) + 1:
            gap = True  # informational only when not strict

    age = None
    if ts_ms is not None and received_ms is not None:
        age = max(0, int(received_ms) - int(ts_ms))

    if age is not None and age > max_apply_age_ms:
        if ws_transport_ok is False:
            return BookHealth(
                BookHealthState.STALE,
                seq,
                last_seq,
                ts_ms,
                redis_written_ms,
                received_ms,
                gap,
                f"stale_transport age_ms={age}",
                tape,
            )
        # Quiet but transport OK / unknown: not broken solely due to no new levels.
        return BookHealth(
            BookHealthState.QUIET_HEALTHY,
            seq,
            last_seq,
            ts_ms,
            redis_written_ms,
            received_ms,
            gap,
            f"quiet age_ms={age} transport={ws_transport_ok}",
            tape,
        )

    return BookHealth(
        BookHealthState.HEALTHY,
        seq,
        last_seq,
        ts_ms,
        redis_written_ms,
        received_ms,
        gap,
        "ok",
        tape,
    )


def book_usable_for_shadow_features(health: BookHealth) -> bool:
    return health.state in (
        BookHealthState.HEALTHY,
        BookHealthState.QUIET_HEALTHY,
    )
