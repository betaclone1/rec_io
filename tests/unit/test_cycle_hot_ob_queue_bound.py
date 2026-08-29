"""Bounded OB cycle queue — protect live Redis path from PG archive backlog."""

from __future__ import annotations

import queue

import pytest

from backend.core import cycle_hot_tables as cht


@pytest.fixture(autouse=True)
def _reset_queue_state(monkeypatch):
    with cht._ob_lock:
        cht._ob_q = None
        cht._ob_thread = None
        cht._ob_stop.clear()
        cht._ob_drain_done.clear()
    cht._enqueued = 0
    cht._ob_dropped = 0
    cht._ob_shed_count = 0
    monkeypatch.setenv("CYCLE_HOT_OB_QUEUE_MAX", "20")
    monkeypatch.setenv("CYCLE_HOT_OB_QUEUE_SHED", "10")
    yield
    with cht._ob_lock:
        if cht._ob_q is not None:
            while True:
                try:
                    cht._ob_q.get_nowait()
                except queue.Empty:
                    break
        cht._ob_q = None
        cht._ob_thread = None


def test_shed_keeps_latest_snapshot_per_ticker_drops_deltas():
    items = [
        ("delta", ("T1", "yes", "0.1", "1", 1, None, "t")),
        ("snapshot", ("T1", {"0.1": "1"}, {}, 1, "snapshot", "t")),
        ("snapshot", ("T1", {"0.2": "2"}, {}, 2, "snapshot", "t")),
        ("delta", ("T2", "no", "0.3", "1", 3, None, "t")),
        ("snapshot", ("T2", {}, {"0.3": "1"}, 3, "snapshot", "t")),
    ]
    kept = cht._shed_ob_queue_items(items)
    assert len(kept) == 2
    by_mt = {payload[0]: payload[3] for kind, payload in kept}
    assert by_mt["T1"] == 2
    assert by_mt["T2"] == 3


def test_ob_put_sheds_under_pressure_instead_of_growing():
    # Don't start writer thread — stub queue only.
    with cht._ob_lock:
        cht._ob_q = queue.Queue(maxsize=20)
        cht._ob_thread = type("T", (), {"is_alive": lambda self: True})()

    for i in range(25):
        cht._ob_put(("delta", (f"T{i}", "yes", "0.1", "1", i, None, "t")))

    assert cht._ob_q.qsize() <= 20
    assert cht._ob_shed_count >= 1 or cht._ob_dropped >= 1


def test_reset_ob_cycle_queue_discards_all():
    with cht._ob_lock:
        cht._ob_q = queue.Queue(maxsize=50)
        cht._ob_thread = type("T", (), {"is_alive": lambda self: True})()
        for i in range(10):
            cht._ob_q.put_nowait(("delta", (f"T{i}",)))
    n = cht.reset_ob_cycle_queue(reason="test")
    assert n == 10
    assert cht._ob_q.qsize() == 0
