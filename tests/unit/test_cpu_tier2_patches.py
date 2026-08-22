"""Tier 2 CPU patches: ATS mark refresh scoping + strike dead-symbol backoff."""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
sys.argv = ["active_trade_supervisor.py", "unified"]

import backend.active_trade_supervisor as ats  # noqa: E402
import backend.strike_table_generator_ws as stg_ws  # noqa: E402


def test_ats_refresh_skips_when_no_tracked_trades(monkeypatch):
    monkeypatch.setattr(ats, "ATS_UNIFIED_POOL", True)
    monkeypatch.setattr(
        ats,
        "_unified_pool_monitor_bindings_with_tracked_trades",
        lambda: [],
    )
    called = {"n": 0}

    def _boom(*_a, **_k):
        called["n"] += 1

    monkeypatch.setattr(ats, "update_active_trade_monitoring_data", _boom)
    ats._ats_refresh_monitoring_all_bindings()
    assert called["n"] == 0


def test_ats_refresh_only_tracked_bindings(monkeypatch):
    monkeypatch.setattr(ats, "ATS_UNIFIED_POOL", True)
    bindings = [("0001", "10041"), ("0001", "10052")]
    monkeypatch.setattr(
        ats,
        "_unified_pool_monitor_bindings_with_tracked_trades",
        lambda: bindings,
    )
    seen: list[tuple[str, str]] = []

    def fake_bind(u, m):
        from contextlib import contextmanager

        @contextmanager
        def cm():
            seen.append((u, m))
            tok_u = ats._ats_bind_u.set(u)
            tok_m = ats._ats_bind_m.set(m)
            try:
                yield
            finally:
                ats._ats_bind_u.reset(tok_u)
                ats._ats_bind_m.reset(tok_m)

        return cm()

    monkeypatch.setattr(ats, "ats_monitor_bind", fake_bind)
    called: list[str] = []
    monkeypatch.setattr(
        ats,
        "update_active_trade_monitoring_data",
        lambda: called.append(ats.ctx_mid()),
    )
    ats._ats_refresh_monitoring_all_bindings()
    assert seen == bindings
    assert called == ["10041", "10052"]


def test_strike_precheck_missing_floor_strike():
    gen = MagicMock()
    gen.data_exchange = "kalshi"
    gen.pipeline_health_market = "15m"
    gen.symbol = "doge"
    gen.market_stream_age_sec.return_value = 1.0
    with patch("backend.core.live_state_config.live_state_cache_enabled", return_value=True):
        with patch("backend.core.live_state_cache.get_market_data") as gm:
            gm.return_value = {"markets": [{}]}
            assert stg_ws._strike_regen_precheck_skip(gen) == "missing_floor_strike"


def test_strike_precheck_stale_market_stream():
    gen = MagicMock()
    gen.data_exchange = "kalshi"
    gen.pipeline_health_market = "hourly"
    gen.symbol = "eth"
    gen.market_stream_age_sec.return_value = 45.0
    with patch("backend.core.live_state_config.live_state_cache_enabled", return_value=True):
        with patch("backend.core.live_state_cache.get_market_data") as gm:
            gm.return_value = {"markets": [{"floor_strike": 1900.0}]}
            reason = stg_ws._strike_regen_precheck_skip(gen)
            assert reason is not None
            assert reason.startswith("market_stream_stale:")


def test_strike_refresh_dead_backoff_skips_generate(monkeypatch):
    monkeypatch.setenv("STRIKE_REGEN_DEAD_SYMBOL_BACKOFF_SEC", "5")
    stg_ws.STRIKE_REGEN_DEAD_SYMBOL_BACKOFF_SEC = 5.0
    stg_ws._last_regen_mono.clear()
    stg_ws._last_dead_regen_skip_mono.clear()

    gen = MagicMock()
    gen.generate_strike_table = MagicMock()
    generators = {"DOGE": gen}

    with patch.object(stg_ws, "_strike_regen_precheck_skip", return_value="missing_floor_strike"):
        stg_ws._refresh_symbol(
            generators,
            "DOGE",
            raw_unhealthy_since={"DOGE": None},
            degrade_confirm_sec=30,
        )
        gen.generate_strike_table.assert_not_called()
        assert "DOGE" in stg_ws._last_dead_regen_skip_mono

        gen.generate_strike_table.reset_mock()
        stg_ws._refresh_symbol(
            generators,
            "DOGE",
            raw_unhealthy_since={"DOGE": None},
            degrade_confirm_sec=30,
        )
        gen.generate_strike_table.assert_not_called()

        stg_ws._last_dead_regen_skip_mono["DOGE"] = time.monotonic() - 10
        with patch.object(stg_ws, "_strike_regen_precheck_skip", return_value=None):
            gen.generate_strike_table.return_value = (True, "EV", 3)
            gen.evaluate_pipeline_health.return_value = (True, "ok")
            stg_ws._refresh_symbol(
                generators,
                "DOGE",
                raw_unhealthy_since={"DOGE": None},
                degrade_confirm_sec=30,
            )
            gen.generate_strike_table.assert_called_once()
            assert "DOGE" not in stg_ws._last_dead_regen_skip_mono
