"""stale_live_state logging must not spam on every hot-path read."""

from __future__ import annotations

import logging

import backend.core.tradeflow_live_reads as tlr


def test_stale_logs_once_then_throttles(monkeypatch, caplog):
    monkeypatch.setattr(tlr, "live_state_cache_enabled", lambda: True)
    monkeypatch.setattr(tlr, "_WARN_INTERVAL_SEC", 60.0)
    tlr._last_warn_mono.clear()
    tlr._last_fresh_state.clear()

    env = {"updated_at": 0}  # age via stub
    monkeypatch.setattr(tlr, "_envelope_age_sec", lambda _e: 10.0)
    monkeypatch.setattr(tlr, "tradeflow_live_state_max_age_sec", lambda: 3.0)

    with caplog.at_level(logging.WARNING, logger=tlr.logger.name):
        ok1, reason1, _ = tlr._check_fresh("strike_ladder", "kalshi:15m:BTC", env)
        ok2, reason2, _ = tlr._check_fresh("strike_ladder", "kalshi:15m:BTC", env)
    assert ok1 is False and reason1 == "stale"
    assert ok2 is False and reason2 == "stale"
    hits = [r for r in caplog.records if "stale_live_state" in r.getMessage()]
    assert len(hits) == 1


def test_fresh_clears_state_so_next_stale_logs(monkeypatch, caplog):
    monkeypatch.setattr(tlr, "live_state_cache_enabled", lambda: True)
    monkeypatch.setattr(tlr, "_WARN_INTERVAL_SEC", 60.0)
    tlr._last_warn_mono.clear()
    tlr._last_fresh_state.clear()

    ages = iter([10.0, 1.0, 10.0])
    monkeypatch.setattr(tlr, "_envelope_age_sec", lambda _e: next(ages))
    monkeypatch.setattr(tlr, "tradeflow_live_state_max_age_sec", lambda: 3.0)
    env = {"updated_at": 1}

    with caplog.at_level(logging.WARNING, logger=tlr.logger.name):
        tlr._check_fresh("strike_ladder", "kalshi:hourly:ETH", env)  # stale
        tlr._check_fresh("strike_ladder", "kalshi:hourly:ETH", env)  # ok
        tlr._check_fresh("strike_ladder", "kalshi:hourly:ETH", env)  # stale again
    hits = [r for r in caplog.records if "stale_live_state" in r.getMessage()]
    assert len(hits) == 2
