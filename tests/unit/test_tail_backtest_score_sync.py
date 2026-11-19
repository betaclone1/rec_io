"""Env/knob smoke for the decoupled tail score sync agent."""

from __future__ import annotations

import os

import pytest


def test_sync_enabled_defaults_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAIL_BACKTEST_SCORE_SYNC", raising=False)
    from backend.core import tail_backtest_score_sync as m

    assert m.sync_enabled() is True


def test_sync_enabled_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAIL_BACKTEST_SCORE_SYNC", "0")
    from backend.core import tail_backtest_score_sync as m

    assert m.sync_enabled() is False


def test_interval_and_lookback_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "TAIL_BACKTEST_SCORE_SYNC_INTERVAL_SEC",
        "TAIL_BACKTEST_SCORE_SYNC_LOOKBACK_DAYS",
        "TAIL_BACKTEST_SCORE_SYNC_WORKERS",
    ):
        monkeypatch.delenv(k, raising=False)
    from backend.core import tail_backtest_score_sync as m

    assert m.interval_sec() == 900.0
    assert m.lookback_days() == 2
    assert m.pull_workers() == 1
