"""Latest-only mailbox lane unit tests."""

from __future__ import annotations

import time

from backend.core.tradeflow_latest_only_lane import (
    LatestOnlyLadderLane,
    decision_generation_id,
    snap_generation_id,
)


def test_publish_replaces_mailbox_and_bumps_epoch():
    lane = LatestOnlyLadderLane("BTC", "15m")
    s1 = lane.publish({"generation_id": "g1", "event_ticker": "E1", "ttc": 10, "strikes": []})
    s2 = lane.publish({"generation_id": "g2", "event_ticker": "E1", "ttc": 9, "strikes": []})
    assert s1 is not None and s2 is not None
    assert s2.epoch == s1.epoch + 1
    assert lane.current().generation_id == s2.generation_id
    assert not lane.is_current(s1.epoch, s1.generation_id)
    assert lane.is_current(s2.epoch, s2.generation_id)


def test_publish_same_decision_gen_does_not_cancel():
    lane = LatestOnlyLadderLane("BTC", "15m")
    snap = {
        "event_ticker": "KXBTC15M-X",
        "ttc": 60,
        "strikes": [{"ticker": "T", "yes_ask_dollars": "0.431", "no_ask_dollars": "0.571"}],
    }
    s1 = lane.publish(snap)
    assert s1 is not None
    slot = lane.try_begin_eval()
    assert slot is not None
    # Identical decision gen (asks round to same cent): must not bump epoch / cancel.
    again = lane.publish(
        {
            "event_ticker": "KXBTC15M-X",
            "ttc": 60,
            "strikes": [{"ticker": "T", "yes_ask_dollars": "0.434", "no_ask_dollars": "0.569"}],
        }
    )
    assert again is None
    assert lane.is_current(slot.epoch, slot.generation_id)
    lane.end_eval()


def test_try_begin_eval_is_nonblocking_and_releases():
    lane = LatestOnlyLadderLane("ETH", "hourly")
    lane.publish({"event_ticker": "E", "ttc": 100, "strikes": []})
    slot = lane.try_begin_eval()
    assert slot is not None
    assert lane.try_begin_eval() is None  # lock held
    after = lane.end_eval()
    assert after is not None
    again = lane.try_begin_eval()
    assert again is not None
    lane.end_eval()


def test_snap_generation_id_uses_decision_fingerprint_by_default(monkeypatch):
    monkeypatch.delenv("TRADEFLOW_LANE_USE_PUBLISHER_GEN", raising=False)
    snap = {
        "generation_id": "publisher-rapid-id",
        "event_ticker": "EVT",
        "ttc": 12.7,
        "strikes": [{"ticker": "T", "yes_ask_dollars": "0.401", "no_ask_dollars": "0.599"}],
    }
    gid = snap_generation_id(snap)
    assert gid.startswith("d:")
    assert "publisher-rapid-id" not in gid
    assert decision_generation_id(snap) == gid


def test_exp_scalp_snapshot_gen_is_wall_second_not_asks():
    snap_a = {
        "rec_snapshot_eval": True,
        "wall_second": 1780000000,
        "event_ticker": "KXBTC15M-X",
        "ttc": 40,
        "strikes": [{"ticker": "T", "yes_ask_dollars": "0.90", "no_ask_dollars": "0.10"}],
    }
    snap_b = {
        **snap_a,
        "strikes": [{"ticker": "T", "yes_ask_dollars": "0.97", "no_ask_dollars": "0.03"}],
    }
    assert snap_generation_id(snap_a) == "snap:1780000000"
    assert snap_generation_id(snap_b) == "snap:1780000000"
    lane = LatestOnlyLadderLane("BTC", "15m")
    s1 = lane.publish(snap_a)
    s2 = lane.publish(snap_b)
    assert s1 is not None
    assert s2 is None
    snap_c = {**snap_a, "wall_second": 1780000001}
    s3 = lane.publish(snap_c)
    assert s3 is not None
    assert s3.epoch == s1.epoch + 1


def test_publish_during_eval_marks_stale_on_new_decision_gen(monkeypatch):
    monkeypatch.setenv("TRADEFLOW_LANE_TTC_BUCKET_SEC", "5")
    lane = LatestOnlyLadderLane("BTC", "15m")
    lane.publish({"event_ticker": "E", "ttc": 50, "strikes": []})
    slot = lane.try_begin_eval()
    assert slot is not None
    time.sleep(0.01)
    # Cross a 5s TTC bucket (50 -> 44) so gen advances while eval is in flight.
    lane.publish({"event_ticker": "E", "ttc": 44, "strikes": []})
    assert not lane.is_current(slot.epoch, slot.generation_id)
    lane.end_eval()


def test_same_gen_should_reeval_after_interval(monkeypatch):
    monkeypatch.setenv("TRADEFLOW_LANE_REEVAL_SEC", "0.2")
    lane = LatestOnlyLadderLane("BTC", "15m")
    lane.publish(
        {
            "event_ticker": "E",
            "ttc": 80,
            "strikes": [{"ticker": "T", "yes_ask_dollars": "0.90", "no_ask_dollars": "0.10"}],
        }
    )
    slot = lane.try_begin_eval()
    assert slot is not None
    lane.end_eval()
    assert lane.should_reeval() is False
    time.sleep(0.25)
    # Same gen refresh must not cancel, but should allow periodic re-eval.
    assert (
        lane.publish(
            {
                "event_ticker": "E",
                "ttc": 80,
                "strikes": [{"ticker": "T", "yes_ask_dollars": "0.90", "no_ask_dollars": "0.10"}],
            }
        )
        is None
    )
    assert lane.should_reeval() is True


def test_hub_schedules_reeval_on_same_gen(monkeypatch):
    monkeypatch.setenv("TRADEFLOW_LANE_REEVAL_SEC", "0.05")
    from backend.core.tradeflow_latest_only_lane import LatestOnlyLaneHub

    snap = {
        "event_ticker": "E",
        "ttc": 90,
        "strikes": [{"ticker": "T", "yes_ask_dollars": "0.91", "no_ask_dollars": "0.09"}],
    }
    evals = []

    def fetch(sym, mkt):
        return dict(snap)

    def evaluate(slot, lane):
        evals.append(slot.generation_id)

    hub = LatestOnlyLaneHub(
        service="test",
        fetch_snap=fetch,
        evaluate_lane=evaluate,
        ladder_keys=lambda: [("BTC", "15m")],
        parallelism=1,
    )
    hub.on_ladder_notify("BTC", "15m")
    time.sleep(0.15)
    assert len(evals) >= 1
    first_n = len(evals)
    hub.on_ladder_notify("BTC", "15m")  # same gen, too soon
    time.sleep(0.05)
    assert len(evals) == first_n
    time.sleep(0.1)
    hub.on_ladder_notify("BTC", "15m")  # same gen, reeval due
    time.sleep(0.15)
    assert len(evals) > first_n
