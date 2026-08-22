"""
Local 1 Hz Exp Scalp architecture: one snapshot per wall-second, decide on that
payload only, verify by contiguous 1s evals. No live_state substitute.

Mirrors 99019 gates (ask 0.90–0.99, TTC 15–60, min_prob 55, verify 5s).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.core.exp_scalp_1hz_snapshot import load_exp_scalp_decision_ladder
from backend.core.tradeflow_latest_only_lane import LatestOnlyLaneHub
from backend.util.auto_entry_expiration_scalp_gates import (
    evaluate_expiration_scalp_entry,
    update_expiration_scalp_entry_verification,
)

LOCAL_99019 = {
    "min_time": 15,
    "max_time": 60,
    "min_probability": 55,
    "max_probability": 100,
    "min_ask": 0.90,
    "max_ask": 0.99,
    "min_movement": 22.0,
    "max_movement": 100.0,
}

VERIFY_NEED_S = 5


@dataclass(frozen=True)
class SnapTick:
    wall: int
    ttc: int
    yes_ask: Optional[float]
    prob: Optional[float]
    skip: Optional[str] = None


def _run_1hz(ticks: list[SnapTick], *, verify_need: int = VERIFY_NEED_S):
    """One eval per distinct wall-second. Skip ticks do not eval."""
    last_wall: Optional[int] = None
    state: Optional[dict] = None
    events: list[tuple] = []
    evals = 0
    for tick in ticks:
        if tick.skip:
            events.append(("skip", tick.skip, tick.wall))
            continue
        if last_wall is not None and tick.wall == last_wall:
            events.append(("skip", "duplicate", tick.wall))
            continue
        last_wall = tick.wall
        evals += 1
        passed, reason = evaluate_expiration_scalp_entry(
            LOCAL_99019,
            ttc_seconds=tick.ttc,
            side="yes",
            ask_dollars=tick.yes_ask,
            probability=tick.prob,
            movement_percentile=8.2,
        )
        if passed is None:
            if state is not None:
                events.append(("abort", reason, tick.wall))
            else:
                events.append(("reject", reason, tick.wall))
            state = None
            continue
        state, may, dwell = update_expiration_scalp_entry_verification(
            state,
            eligible=True,
            now_ts=float(tick.wall),
            enabled=True,
            period_seconds=verify_need,
        )
        if may:
            events.append(("fire", dwell, tick.wall, passed["buy_price"]))
            state = None
        else:
            events.append(("wait", dwell, tick.wall))
    return events, evals


def _pin(start_wall: int, n: int, *, ask: float, ttc0: int = 60, prob: float = 63.0):
    return [
        SnapTick(wall=start_wall + i, ttc=ttc0 - i, yes_ask=ask, prob=prob)
        for i in range(n)
    ]


def test_winner_pin_fires_on_fifth_elapsed_snapshot_second():
    """14:59:04 local shape: in-band at window open, fire when dwell hits 5s."""
    events, evals = _run_1hz(_pin(100, 7, ask=0.978))
    fires = [e for e in events if e[0] == "fire"]
    assert evals == 7
    assert len(fires) == 1
    kind, dwell, wall, buy = fires[0]
    assert wall == 105
    assert dwell == 5.0
    assert buy == 0.978
    assert all(e[0] == "wait" for e in events if e[0] not in ("fire",) and e[2] < 105)


def test_choppy_90_89_never_completes_verify():
    """Wipe discovery book: 0.89 is out of band and zeros dwell."""
    ticks = []
    for i in range(12):
        ask = 0.90 if i % 2 == 0 else 0.89
        ticks.append(SnapTick(wall=200 + i, ttc=50 - i, yes_ask=ask, prob=57.0))
    events, evals = _run_1hz(ticks)
    assert evals == 12
    assert not any(e[0] == "fire" for e in events)
    assert any(e[0] == "abort" and e[1] == "ask_outside_band" for e in events)
    waits = [e for e in events if e[0] == "wait"]
    assert waits
    assert max(e[1] for e in waits) == 0.0


def test_ten_second_90_pin_does_fire():
    """1 Hz does not reject a $0.90 pin. Five contiguous in-band seconds still enter."""
    events, _ = _run_1hz(_pin(300, 8, ask=0.90, ttc0=40, prob=56.0))
    fires = [e for e in events if e[0] == "fire"]
    assert len(fires) == 1
    assert fires[0][2] == 305
    assert fires[0][3] == 0.90


def test_in_second_flicker_is_one_eval():
    """Same wall_second twice: second is duplicate, ask change is not a new look."""
    ticks = [
        SnapTick(wall=400, ttc=40, yes_ask=0.90, prob=60.0),
        SnapTick(wall=400, ttc=40, yes_ask=0.97, prob=60.0),
        SnapTick(wall=401, ttc=39, yes_ask=0.97, prob=60.0),
    ]
    events, evals = _run_1hz(ticks)
    assert evals == 2
    assert events[1] == ("skip", "duplicate", 400)
    assert events[0][0] == "wait"
    assert events[2][0] == "wait"


def test_blocking_hub_evals_each_new_wall_second_only():
    evals: list[str] = []

    def evaluate(slot, lane):
        evals.append(slot.generation_id)

    hub = LatestOnlyLaneHub(
        service="test",
        fetch_snap=lambda *a: None,
        evaluate_lane=evaluate,
        ladder_keys=lambda: [("BTC", "15m")],
        parallelism=1,
    )

    def snap(wall: int, ask: str) -> dict[str, Any]:
        return {
            "rec_snapshot_eval": True,
            "wall_second": wall,
            "event_ticker": "E",
            "ttc": 40,
            "strikes": [{"ticker": "T", "yes_ask_dollars": ask, "no_ask_dollars": "0.02"}],
        }

    assert hub.evaluate_latest_blocking("BTC", "15m", snap=snap(10, "0.90")) > 0.0
    # In-second flicker: same wall, different ask — no second eval.
    assert hub.evaluate_latest_blocking("BTC", "15m", snap=snap(10, "0.99")) == 0.0
    assert hub.evaluate_latest_blocking("BTC", "15m", snap=snap(11, "0.99")) > 0.0
    assert evals == ["snap:10", "snap:11"]


def test_missing_snapshot_does_not_call_live_state(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("live_state must not be the Exp Scalp decision source")

    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.get_strike_snapshot_envelope",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "backend.core.tradeflow_live_reads.strike_ladder",
        boom,
        raising=False,
    )
    ladder, reason = load_exp_scalp_decision_ladder(now=1.0)
    assert ladder is None
    assert reason == "disabled_or_missing"
    assert called["n"] == 0


def test_stale_skip_does_not_eval_or_abort():
    ticks = [
        SnapTick(wall=500, ttc=40, yes_ask=0.96, prob=60.0),
        SnapTick(wall=501, ttc=39, yes_ask=0.96, prob=60.0, skip="stale"),
        SnapTick(wall=502, ttc=38, yes_ask=0.96, prob=60.0),
    ]
    events, evals = _run_1hz(ticks)
    assert evals == 2
    assert events[1] == ("skip", "stale", 501)
    assert events[0][0] == "wait"
    assert events[2][0] == "wait"
    # Wall-clock dwell jumps the skipped second (current AES). Not snapshot-count.
    assert events[2][1] == 2.0


def test_skipped_seconds_can_complete_verify_without_five_in_band_evals():
    """Hole vs 'N consecutive snapshots': wall-clock dwell still advances across skips."""
    ticks = [
        SnapTick(wall=600, ttc=40, yes_ask=0.96, prob=60.0),
        SnapTick(wall=601, ttc=39, yes_ask=0.96, prob=60.0),
        SnapTick(wall=602, ttc=38, yes_ask=0.96, prob=60.0, skip="stale"),
        SnapTick(wall=603, ttc=37, yes_ask=0.96, prob=60.0, skip="stale"),
        SnapTick(wall=604, ttc=36, yes_ask=0.96, prob=60.0, skip="stale"),
        SnapTick(wall=605, ttc=35, yes_ask=0.96, prob=60.0),
    ]
    events, evals = _run_1hz(ticks)
    assert evals == 3
    fires = [e for e in events if e[0] == "fire"]
    assert len(fires) == 1
    assert fires[0][1] == 5.0


def test_out_of_window_never_starts_verify():
    events, evals = _run_1hz(
        [SnapTick(wall=700 + i, ttc=120 - i, yes_ask=0.97, prob=70.0) for i in range(6)]
    )
    assert evals == 6
    assert all(e[0] == "reject" and e[1] == "ttc_outside_window" for e in events)
