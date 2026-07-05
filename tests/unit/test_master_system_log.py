"""Unit tests for master system event log helper."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend.util.master_system_log import (
    _normalize_category,
    _normalize_detail_ref,
    _normalize_severity,
    format_master_event_line,
    log_system_event,
)


def test_normalize_severity():
    assert _normalize_severity("CRITICAL") == "critical"
    assert _normalize_severity("bogus") == "info"


def test_normalize_category():
    assert _normalize_category("restart") == "RESTART"
    assert _normalize_category("unknown") == "ANOMALY"


def test_normalize_detail_ref():
    assert _normalize_detail_ref("logs/system_monitor.out.log") == "system_monitor"
    assert _normalize_detail_ref("market_watchdog_ws_kalshi") == "market_watchdog_ws_kalshi"
    assert _normalize_detail_ref(None) is None


def test_format_master_event_line():
    ts = datetime(2026, 7, 4, 14, 51, 32, tzinfo=ZoneInfo("America/New_York"))
    line = format_master_event_line(
        timestamp=ts,
        category="RESTART",
        severity="critical",
        source="system_monitor",
        message="3 services down",
        detail_ref="system_monitor.out.log",
    )
    assert "2026-07-04T14:51:32-04:00" in line or "2026-07-04T14:51:32-05:00" in line
    assert "CRITICAL" in line
    assert "RESTART" in line
    assert "system_monitor" in line
    assert "detail=system_monitor" in line


def test_log_system_event_fail_open_on_db():
    with patch("backend.util.master_system_log._write_file_line") as mock_file:
        with patch("backend.util.master_system_log._write_db_row", side_effect=RuntimeError("db down")):
            log_system_event(
                category="ANOMALY",
                message="test event",
                source="test",
                severity="info",
            )
    mock_file.assert_called_once()


def test_log_system_event_writes_db():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("backend.util.master_system_log._write_file_line"):
        with patch(
            "backend.util.master_system_log.get_system_postgresql_connection",
            return_value=mock_conn,
        ):
            log_system_event(
                category="DEPLOY",
                message="Pulled main",
                source="git_update",
                severity="info",
                detail_ref="supervisord",
            )

    mock_cursor.execute.assert_called_once()
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


def test_log_system_event_suppressed_during_maintenance():
    with patch("backend.util.master_system_log.system_in_maintenance_mode", return_value=True):
        with patch("backend.util.master_system_log._write_file_line") as mock_file:
            with patch("backend.util.master_system_log._write_db_row") as mock_db:
                log_system_event(
                    category="ANOMALY",
                    message="should not appear",
                    source="system_monitor",
                    severity="warning",
                )
    mock_file.assert_not_called()
    mock_db.assert_not_called()


def test_log_system_event_not_suppressed_for_master_restart_during_maintenance():
    with patch("backend.util.master_system_log.system_in_maintenance_mode", return_value=True):
        with patch("backend.util.master_system_log._write_file_line") as mock_file:
            with patch("backend.util.master_system_log._write_db_row"):
                log_system_event(
                    category="RESTART",
                    message="MASTER RESTART completed successfully",
                    source="MASTER_RESTART",
                    severity="info",
                )
    mock_file.assert_called_once()
