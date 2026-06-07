"""Unit tests for CFB feed-health (tick drought)."""

from __future__ import annotations

import time

import pytest

from backend.core.cfbenchmarks_feed_health import CfBenchmarksFeedHealth


@pytest.fixture(autouse=True)
def _enable_feed_health(monkeypatch):
    monkeypatch.setenv("CFB_FEED_STALE_TICK_SEC", "60")
    monkeypatch.setenv("CFB_FEED_STALE_GRACE_SEC", "0")


def test_grace_period_blocks_stale_check(monkeypatch):
    monkeypatch.setenv("CFB_FEED_STALE_GRACE_SEC", "300")
    fh = CfBenchmarksFeedHealth(["BRTI"])
    fh.begin_session()
    healthy, summary, reason = fh.evaluate()
    assert healthy is True
    assert reason is None
    assert "grace" in summary


def test_missing_index_tick_triggers_reconnect():
    fh = CfBenchmarksFeedHealth(["BRTI", "ETHUSD_RTI"])
    fh.begin_session()
    fh.record_tick("BRTI")
    fh._session_start_mono = time.monotonic() - 120.0
    healthy, summary, reason = fh.evaluate()
    assert healthy is False
    assert reason is not None
    assert "ETHUSD_RTI" in reason
    assert "no_tick_since_connect" in reason
    assert "unhealthy" in summary


def test_recent_tick_healthy():
    fh = CfBenchmarksFeedHealth(["BRTI"])
    fh.begin_session()
    fh.record_tick("BRTI")
    healthy, _summary, reason = fh.evaluate()
    assert healthy is True
    assert reason is None


def test_disabled_when_stale_sec_zero(monkeypatch):
    monkeypatch.setenv("CFB_FEED_STALE_TICK_SEC", "0")
    fh = CfBenchmarksFeedHealth(["BRTI"])
    fh.begin_session()
    fh._session_start_mono = time.monotonic() - 9999.0
    healthy, summary, reason = fh.evaluate()
    assert healthy is True
    assert reason is None
    assert summary == "disabled"
