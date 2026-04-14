"""ContextVar binding for web tenant (session token resolution)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.requests import Request

import backend.web.tenant_asgi as tenant_asgi_mod
from backend.web.tenant_asgi import get_web_api_user_no


@pytest.fixture(autouse=True)
def clear_web_user_no():
    yield
    tenant_asgi_mod._web_api_user_no.set(None)


def test_attach_request_sets_user_no_from_bearer_token() -> None:
    from backend.web.tenant_asgi import attach_request_user_no

    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer testtoken")],
        "query_string": b"",
    }
    req = Request(scope)
    fake_rec = {"username": "alice", "expires": "2099-01-01T00:00:00+00:00"}
    with patch("backend.web.tenant_asgi.find_valid_token", return_value=("0002", fake_rec)):
        attach_request_user_no(req)
        assert get_web_api_user_no() == "0002"
