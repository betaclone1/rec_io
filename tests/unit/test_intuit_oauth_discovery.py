"""Tests for Intuit OpenID discovery used by QuickBooks OAuth helpers."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from backend.bookkeeper.quickbooks.quickbooks_online_rest import (
    AUTHORIZE_URL,
    TOKEN_URL,
    build_authorization_url,
    get_intuit_oauth_endpoints,
    refresh_access_token,
    reset_intuit_oauth_endpoints_cache,
)


@pytest.fixture(autouse=True)
def clear_endpoint_cache() -> None:
    reset_intuit_oauth_endpoints_cache()
    yield
    reset_intuit_oauth_endpoints_cache()


def _discovery_session_mock(payload: dict[str, str] | Exception) -> Mock:
    sess = Mock()
    if isinstance(payload, Exception):
        sess.get.side_effect = payload
        return sess
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json.return_value = payload
    sess.get.return_value = resp
    return sess


def test_get_intuit_oauth_endpoints_success_caches() -> None:
    payload = {
        "authorization_endpoint": "https://auth.example/oauth2/authorize",
        "token_endpoint": "https://token.example/oauth2/token",
    }
    with patch(
        "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.Session",
        return_value=_discovery_session_mock(payload),
    ):
        a1, t1 = get_intuit_oauth_endpoints()
        a2, t2 = get_intuit_oauth_endpoints()
    assert (a1, t1) == (payload["authorization_endpoint"], payload["token_endpoint"])
    assert (a2, t2) == (a1, t1)


def test_get_intuit_oauth_endpoints_fallback_no_cache_on_failure() -> None:
    with patch(
        "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.Session",
        return_value=_discovery_session_mock(RuntimeError("network")),
    ):
        assert get_intuit_oauth_endpoints() == (AUTHORIZE_URL, TOKEN_URL)
    # Next successful discovery should work (no stale "failed" cache).
    payload = {
        "authorization_endpoint": "https://a",
        "token_endpoint": "https://t",
    }
    with patch(
        "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.Session",
        return_value=_discovery_session_mock(payload),
    ):
        assert get_intuit_oauth_endpoints() == ("https://a", "https://t")


def test_build_authorization_url_uses_discovered_host() -> None:
    payload = {
        "authorization_endpoint": "https://auth.custom/connect/oauth2",
        "token_endpoint": "https://token.custom/bearer",
    }
    with patch(
        "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.Session",
        return_value=_discovery_session_mock(payload),
    ):
        url = build_authorization_url("cid", "http://127.0.0.1:8080/callback", "st")
    assert url.startswith("https://auth.custom/connect/oauth2?")
    assert "client_id=cid" in url
    assert "state=st" in url


def test_refresh_access_token_posts_to_discovered_token_endpoint() -> None:
    payload = {
        "authorization_endpoint": AUTHORIZE_URL,
        "token_endpoint": "https://discovered.token.example/v1/tokens/bearer",
    }
    post_resp = Mock()
    post_resp.status_code = 400
    post_resp.json.return_value = {"error": "invalid_request"}
    post_resp.text = ""
    with patch(
        "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.Session",
        return_value=_discovery_session_mock(payload),
    ):
        with patch(
            "backend.bookkeeper.quickbooks.quickbooks_online_rest.requests.post",
            return_value=post_resp,
        ) as post:
            with pytest.raises(RuntimeError, match="Refresh token failed"):
                refresh_access_token("x", "y", "z")
    post.assert_called_once()
    assert post.call_args[0][0] == "https://discovered.token.example/v1/tokens/bearer"
