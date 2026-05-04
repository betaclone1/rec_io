"""Tests for intuit_tid logging on Intuit / QBO HTTP responses."""

from __future__ import annotations

import logging
from unittest.mock import Mock, patch

import pytest

from backend.bookkeeper.quickbooks.quickbooks_online_rest import (
    refresh_access_token,
    reset_intuit_oauth_endpoints_cache,
)


@pytest.fixture(autouse=True)
def clear_oauth_cache() -> None:
    reset_intuit_oauth_endpoints_cache()
    yield
    reset_intuit_oauth_endpoints_cache()


def test_refresh_error_logs_and_raises_with_intuit_tid(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    disc = Mock()
    disc.get.return_value.raise_for_status = Mock()
    disc.get.return_value.json.return_value = {
        "authorization_endpoint": "https://appcenter.intuit.com/connect/oauth2",
        "token_endpoint": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
    }
    post_resp = Mock()
    post_resp.status_code = 401
    post_resp.headers = {"intuit_tid": "tid-abc-123"}
    post_resp.json.return_value = {"error": "invalid_client"}
    post_resp.text = ""

    with patch(
        "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.Session",
        return_value=disc,
    ):
        with patch(
            "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.post",
            return_value=post_resp,
        ):
            with pytest.raises(RuntimeError, match="intuit_tid=tid-abc-123"):
                refresh_access_token("x", "y", "z")

    assert "tid-abc-123" in caplog.text
    assert "intuit_tid=tid-abc-123" in caplog.text


def test_refresh_success_logs_debug_intuit_tid(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    disc = Mock()
    disc.get.return_value.raise_for_status = Mock()
    disc.get.return_value.json.return_value = {
        "authorization_endpoint": "https://appcenter.intuit.com/connect/oauth2",
        "token_endpoint": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
    }
    post_resp = Mock()
    post_resp.status_code = 200
    post_resp.headers = {"intuit_tid": "tid-ok-999"}
    post_resp.json.return_value = {
        "access_token": "at",
        "refresh_token": "rt",
    }

    with patch(
        "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.Session",
        return_value=disc,
    ):
        with patch(
            "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.post",
            return_value=post_resp,
        ):
            out = refresh_access_token("x", "y", "z")

    assert out.get("access_token") == "at"
    assert "tid-ok-999" in caplog.text
    assert "oauth_refresh_token" in caplog.text
