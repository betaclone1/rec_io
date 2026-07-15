"""credits_history must target tenant schema users_NNNN, not legacy users."""

from __future__ import annotations

import backend.kalshi_account_sync_ws as kas


def test_credits_history_qualified_uses_tenant_schema(monkeypatch) -> None:
    monkeypatch.setattr(kas, "_kas_process_user_no", lambda: "0001")
    assert kas._credits_history_qualified() == "users_0001.credits_history_0001"


def test_credits_history_qualified_pads_slot(monkeypatch) -> None:
    monkeypatch.setattr(kas, "_kas_process_user_no", lambda: "3")
    assert kas._credits_history_qualified() == "users_0003.credits_history_0003"
