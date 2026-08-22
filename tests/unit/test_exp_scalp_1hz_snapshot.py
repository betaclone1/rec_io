"""BTC 15m Exp Scalp 1 Hz snapshot eval — no live_state substitute."""

from __future__ import annotations

from backend.core.exp_scalp_1hz_snapshot import (
    load_exp_scalp_decision_ladder,
    wait_for_new_exp_scalp_snapshot,
)
from backend.core.tradeflow_latest_only_lane import LatestOnlyLaneHub


def _env(wall: int, published_at: float, yes_ask: str = "0.90"):
    return {
        "generation_seq": 1,
        "wall_second": wall,
        "published_at": published_at,
        "data": {
            "event_ticker": "KXBTC15M-X",
            "ttc": 40,
            "strikes": [
                {
                    "ticker": "KXBTC15M-X",
                    "yes_ask_dollars": yes_ask,
                    "no_ask_dollars": "0.10",
                }
            ],
        },
    }


def test_load_rejects_stale_snapshot(monkeypatch):
    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.get_strike_snapshot_envelope",
        lambda *a, **k: _env(100, published_at=100.0),
    )
    ladder, reason = load_exp_scalp_decision_ladder(now=102.0)
    assert ladder is None
    assert reason == "stale"


def test_load_accepts_fresh_snapshot_and_stamps_wall(monkeypatch):
    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.get_strike_snapshot_envelope",
        lambda *a, **k: _env(100, published_at=100.2),
    )
    ladder, reason = load_exp_scalp_decision_ladder(now=100.4)
    assert reason is None
    assert ladder is not None
    assert ladder["wall_second"] == 100
    assert ladder["rec_snapshot_eval"] is True
    assert ladder["strikes"][0]["yes_ask_dollars"] == "0.90"


def test_load_missing_is_not_live_state_fallback(monkeypatch):
    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.get_strike_snapshot_envelope",
        lambda *a, **k: None,
    )
    ladder, reason = load_exp_scalp_decision_ladder(now=1.0)
    assert ladder is None
    assert reason == "disabled_or_missing"


def test_wait_accepts_snapshot_one_second_behind_target(monkeypatch):
    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.sleep_until_next_second_boundary",
        lambda: None,
    )
    t = {"now": 200.05}

    def fake_time():
        t["now"] += 0.01
        return t["now"]

    monkeypatch.setattr("backend.core.exp_scalp_1hz_snapshot.time.time", fake_time)
    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.get_strike_snapshot_envelope",
        lambda *a, **k: _env(199, published_at=199.9),
    )
    ladder, reason = wait_for_new_exp_scalp_snapshot(
        198, poll_deadline_sec=0.05, poll_sleep_sec=0.001
    )
    assert reason is None
    assert ladder is not None
    assert ladder["wall_second"] == 199


def test_wait_rejects_snapshot_two_seconds_behind_target(monkeypatch):
    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.sleep_until_next_second_boundary",
        lambda: None,
    )
    t = {"now": 200.05}

    def fake_time():
        t["now"] += 0.01
        return t["now"]

    monkeypatch.setattr("backend.core.exp_scalp_1hz_snapshot.time.time", fake_time)
    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.get_strike_snapshot_envelope",
        lambda *a, **k: _env(198, published_at=198.9),
    )
    ladder, reason = wait_for_new_exp_scalp_snapshot(
        190, poll_deadline_sec=0.05, poll_sleep_sec=0.001
    )
    assert ladder is None
    assert reason == "stale"


def test_wait_skips_duplicate_wall_second(monkeypatch):
    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.sleep_until_next_second_boundary",
        lambda: None,
    )
    t = {"now": 100.10}

    def fake_time():
        t["now"] += 0.02
        return t["now"]

    monkeypatch.setattr("backend.core.exp_scalp_1hz_snapshot.time.time", fake_time)
    monkeypatch.setattr(
        "backend.core.exp_scalp_1hz_snapshot.get_strike_snapshot_envelope",
        lambda *a, **k: _env(100, published_at=100.05),
    )
    ladder, reason = wait_for_new_exp_scalp_snapshot(
        100, poll_deadline_sec=0.05, poll_sleep_sec=0.001
    )
    assert ladder is None
    assert reason == "duplicate"


def test_blocking_eval_skips_same_snapshot_second():
    snaps = []

    def fetch(sym, mkt):
        return {
            "rec_snapshot_eval": True,
            "wall_second": 50,
            "event_ticker": "E",
            "ttc": 20,
            "strikes": [],
        }

    def evaluate(slot, lane):
        snaps.append(slot.generation_id)

    hub = LatestOnlyLaneHub(
        service="test",
        fetch_snap=fetch,
        evaluate_lane=evaluate,
        ladder_keys=lambda: [("BTC", "15m")],
        parallelism=1,
    )
    elapsed1 = hub.evaluate_latest_blocking("BTC", "15m")
    elapsed2 = hub.evaluate_latest_blocking("BTC", "15m")
    assert elapsed1 >= 0.0
    assert elapsed2 == 0.0
    assert snaps == ["snap:50"]
