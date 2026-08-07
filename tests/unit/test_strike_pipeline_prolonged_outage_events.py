"""Prolonged strike-pipeline outages → System Event Log."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.core.strike_pipeline_health import (
    note_pipeline_health_for_system_event,
    reset_prolonged_outage_event_state,
)


@pytest.fixture(autouse=True)
def _clear_outage_state(monkeypatch):
    reset_prolonged_outage_event_state()
    monkeypatch.setenv("STRIKE_PIPELINE_PROLONGED_OUTAGE_SEC", "90")
    yield
    reset_prolonged_outage_event_state()


def test_brief_unhealthy_does_not_emit():
    with patch("backend.util.master_system_log.log_system_event") as mock_log:
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="BTC",
            healthy=False,
            reason="missing_floor_strike",
            now_mono=1000.0,
        )
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="BTC",
            healthy=False,
            reason="missing_floor_strike",
            now_mono=1045.0,
        )
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="BTC",
            healthy=True,
            reason="ok",
            now_mono=1050.0,
        )
        mock_log.assert_not_called()


def test_prolonged_outage_emits_once_then_recovery():
    with patch("backend.util.master_system_log.log_system_event") as mock_log:
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="BTC",
            healthy=False,
            reason="missing_floor_strike",
            now_mono=1000.0,
        )
        mock_log.assert_not_called()

        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="BTC",
            healthy=False,
            reason="missing_floor_strike",
            now_mono=1090.0,
        )
        assert mock_log.call_count == 1
        kwargs = mock_log.call_args.kwargs
        assert kwargs["category"] == "ANOMALY"
        assert kwargs["severity"] == "warning"
        assert kwargs["source"] == "strike_pipeline"
        assert kwargs["detail_ref"] == "strike_table_generator_ws_15m"
        assert "prolonged outage" in kwargs["message"]
        assert "BTC" in kwargs["message"]
        assert kwargs["metadata"]["event"] == "prolonged_outage"

        # Still unhealthy: do not re-emit
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="BTC",
            healthy=False,
            reason="missing_floor_strike",
            now_mono=1200.0,
        )
        assert mock_log.call_count == 1

        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="BTC",
            healthy=True,
            reason="ok",
            now_mono=1210.0,
        )
        assert mock_log.call_count == 2
        rec = mock_log.call_args.kwargs
        assert rec["severity"] == "info"
        assert "recovered" in rec["message"]
        assert rec["metadata"]["event"] == "outage_recovered"


def test_symbols_tracked_independently():
    with patch("backend.util.master_system_log.log_system_event") as mock_log:
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="BTC",
            healthy=False,
            reason="missing_floor_strike",
            now_mono=1000.0,
        )
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="DOGE",
            healthy=False,
            reason="missing_floor_strike",
            now_mono=1000.0,
        )
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="BTC",
            healthy=False,
            reason="missing_floor_strike",
            now_mono=1090.0,
        )
        assert mock_log.call_count == 1
        assert "BTC" in mock_log.call_args.kwargs["message"]

        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="15m",
            symbol="DOGE",
            healthy=False,
            reason="missing_floor_strike",
            now_mono=1091.0,
        )
        assert mock_log.call_count == 2
        assert "DOGE" in mock_log.call_args.kwargs["message"]


def test_recovery_without_prior_event_is_silent():
    """Healthy again before threshold — no outage event, no recovery noise."""
    with patch("backend.util.master_system_log.log_system_event") as mock_log:
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="hourly",
            symbol="BTC",
            healthy=False,
            reason="stale_market",
            now_mono=1000.0,
        )
        note_pipeline_health_for_system_event(
            exchange="kalshi",
            market="hourly",
            symbol="BTC",
            healthy=True,
            reason="ok",
            now_mono=1020.0,
        )
        mock_log.assert_not_called()


def test_default_prolonged_outage_threshold_is_15m(monkeypatch):
    monkeypatch.delenv("STRIKE_PIPELINE_PROLONGED_OUTAGE_SEC", raising=False)
    from backend.core.strike_pipeline_health import prolonged_outage_event_sec

    assert prolonged_outage_event_sec() == 900
