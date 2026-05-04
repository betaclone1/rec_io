"""Signed OAuth state for Intuit QuickBooks browser flow."""

from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

from backend.bookkeeper.intuit_oauth_routes import (
    build_signed_state,
    parse_signed_state,
)


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REC_INTUIT_OAUTH_STATE_SECRET", "test-secret-key-for-hmac-only")


def test_state_round_trip(secret: None) -> None:
    t = build_signed_state("0001", "production")
    p = parse_signed_state(t)
    assert p["user_no"] == "0001"
    assert p["environment"] == "production"


def test_state_rejects_tamper(secret: None) -> None:
    t = build_signed_state("0001", "sandbox")
    bad = t[:-5] + "xxxxx"
    with pytest.raises(HTTPException) as ei:
        parse_signed_state(bad)
    assert ei.value.status_code == 400


def test_state_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REC_INTUIT_OAUTH_STATE_SECRET", raising=False)
    with pytest.raises(HTTPException) as ei:
        build_signed_state("0001", "production")
    assert ei.value.status_code == 503
