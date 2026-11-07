"""Phase 1 CPU plan: ATS wake-only, lane defaults, cooldown write throttle, health coalesce."""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
sys.argv = ["active_trade_supervisor.py", "unified"]

import backend.active_trade_supervisor as ats  # noqa: E402
import backend.auto_entry_supervisor as aes  # noqa: E402
import backend.core.strike_pipeline_health as sph  # noqa: E402
import backend.strike_table_generator_ws as stg_ws  # noqa: E402


def test_ats_on_live_state_wake_only(monkeypatch):
    ats._ats_live_state_wake.clear()
    called = {"n": 0}

    def _boom():
        called["n"] += 1

    monkeypatch.setattr(ats, "_ats_refresh_monitoring_all_bindings", _boom)
    ats._ats_on_live_state()
    assert ats._ats_live_state_wake.is_set()
    assert called["n"] == 0


def test_aes_lane_parallelism_default_12(monkeypatch):
    monkeypatch.delenv("AES_LANE_PARALLELISM", raising=False)
    assert aes._aes_lane_parallelism() == 12


def test_strike_regen_floor_default_1():
    assert float(stg_ws.STRIKE_REGEN_MIN_INTERVAL_SEC) >= 1.0


def test_cooldown_timer_display_write_throttled(monkeypatch):
    aes._aes_cooldown_timer_write_state.clear()
    monkeypatch.setattr(aes, "_AES_COOLDOWN_TIMER_WRITE_MIN_SEC", 1.0)
    monkeypatch.setattr(aes, "ctx_ident", lambda: "u0001_m1")
    monkeypatch.setattr(aes, "ctx_user", lambda: "0001")
    monkeypatch.setattr(aes, "ctx_mid", lambda: "1")
    notifies: list = []
    monkeypatch.setattr(
        aes, "_aes_preferences_notify", lambda *a, **k: notifies.append(a)
    )

    cursor = MagicMock()
    conn = MagicMock()
    assert aes._aes_maybe_write_cooldown_timer_display(cursor, 10, commit_conn=conn) is True
    assert cursor.execute.call_count == 1
    assert aes._aes_maybe_write_cooldown_timer_display(cursor, 9, commit_conn=conn) is False
    assert cursor.execute.call_count == 1
    # Advance past throttle window
    ident = "u0001_m1"
    pts, pval = aes._aes_cooldown_timer_write_state[ident]
    aes._aes_cooldown_timer_write_state[ident] = (pts - 2.0, pval)
    assert aes._aes_maybe_write_cooldown_timer_display(cursor, 8, commit_conn=conn) is True
    assert cursor.execute.call_count == 2
    assert len(notifies) == 2


def test_upsert_strike_pipeline_health_coalesces(monkeypatch):
    sph._upsert_coalesce_state.clear()
    monkeypatch.setenv("STRIKE_PIPELINE_HEALTH_UPSERT_MIN_INTERVAL_SEC", "5.0")
    executes = {"n": 0}

    class FakeCur:
        def execute(self, *_a, **_k):
            executes["n"] += 1

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCur()

        def commit(self):
            pass

    conn = FakeConn()
    kw = dict(
        exchange="kalshi",
        market="15m",
        symbol="BTC",
        healthy=True,
        reason="ok",
        max_age_sec=900,
    )
    sph.upsert_strike_pipeline_health(conn, **kw)
    sph.upsert_strike_pipeline_health(conn, **kw)
    assert executes["n"] == 1
    # State change always writes
    sph.upsert_strike_pipeline_health(conn, **{**kw, "healthy": False, "reason": "stale"})
    assert executes["n"] == 2
