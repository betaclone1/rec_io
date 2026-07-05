"""Auth route tests for master system event log API."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch


def test_master_events_forbidden_for_non_admin():
    from backend.web.auth_routes import admin_master_events

    with patch(
        "backend.web.auth_routes.resolved_tenant_user_no_for_app",
        return_value="0001",
    ):
        with patch(
            "backend.web.auth_routes._session_is_master_admin",
            return_value=False,
        ):
            resp = asyncio.run(admin_master_events())
    assert resp.status_code == 403


def test_master_events_returns_rows():
    from backend.web.auth_routes import admin_master_events

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = (1,)
    mock_cur.fetchall.return_value = [
        (
            1,
            "2026-07-04 14:51:32",
            "RESTART",
            "critical",
            "system_monitor",
            "Services down",
            "system_monitor",
            {},
        )
    ]

    with patch(
        "backend.web.auth_routes.resolved_tenant_user_no_for_app",
        return_value="0001",
    ):
        with patch(
            "backend.web.auth_routes._session_is_master_admin",
            return_value=True,
        ):
            with patch(
                "backend.web.auth_routes.get_system_postgresql_connection",
                return_value=mock_conn,
            ):
                resp = asyncio.run(
                    admin_master_events(limit=10, offset=0, category=None, severity=None, since=None)
                )

    body = resp if isinstance(resp, dict) else resp.body
    if not isinstance(body, dict):
        import json
        body = json.loads(body)
    assert body["total"] == 1
    assert len(body["events"]) == 1
    assert body["events"][0]["category"] == "RESTART"
