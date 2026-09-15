"""PRE consume allowed on all hosts (including production)."""

from __future__ import annotations

from backend.core.position_risk.arming import assert_paper_consume_allowed
from backend.core.position_risk.safety import assert_safe_to_run_observe


def test_arming_ok_on_prod_markers(monkeypatch):
    monkeypatch.setenv("REC_IS_PRODUCTION", "1")
    monkeypatch.setenv("DB_HOST", "localhost")
    ok, reason = assert_paper_consume_allowed(True, "paper")
    assert ok, reason


def test_arming_ok_local(monkeypatch):
    monkeypatch.delenv("REC_IS_PRODUCTION", raising=False)
    monkeypatch.setenv("DB_HOST", "localhost")
    ok, reason = assert_paper_consume_allowed(True, "paper")
    assert ok, reason


def test_observe_ok_on_prod_markers(monkeypatch):
    monkeypatch.setenv("REC_IS_PRODUCTION", "1")
    monkeypatch.setenv("REC_PROJECT_ROOT", "/opt/rec_io_server")
    ok, reason = assert_safe_to_run_observe()
    assert ok, reason
