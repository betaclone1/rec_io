"""Expiration Reversal: strategy identity, family membership, flip flags, settings guard."""

from __future__ import annotations

import pytest

from backend.core.aes_btc15m_exp_scalp_cutout import is_btc15m_exp_scalp_cutout_row
from backend.core.expiration_reversal import flip_execution_flags, is_expiration_reversal
from backend.core.high_water_scalp import is_expiration_scalp_entry_strategy, is_high_water_family


def test_identity():
    assert is_expiration_reversal("Expiration Reversal")
    assert is_expiration_reversal(" Expiration Reversal ")
    assert not is_expiration_reversal("Expiration Scalp")
    assert not is_expiration_reversal("Momentum Reversal")
    assert not is_expiration_reversal(None)


def test_expiration_scalp_family_includes_er():
    assert is_expiration_scalp_entry_strategy("Expiration Reversal")
    assert is_expiration_scalp_entry_strategy("Expiration Scalp")
    assert not is_high_water_family("Expiration Reversal")


def test_btc15m_cutout_membership_includes_er():
    row = {"symbol": "BTC", "market": "15m", "strategy": "Expiration Reversal"}
    assert is_btc15m_exp_scalp_cutout_row(row)
    assert not is_btc15m_exp_scalp_cutout_row({**row, "market": "hourly"})
    assert not is_btc15m_exp_scalp_cutout_row({**row, "symbol": "ETH"})


@pytest.mark.parametrize(
    "paper,test,expected",
    [
        (False, False, (False, False)),
        (True, False, (True, False)),
        (False, True, (True, True)),
        (True, True, (True, True)),
        ("true", None, (True, False)),
        (None, None, (False, False)),
    ],
)
def test_flip_execution_flags(paper, test, expected):
    assert flip_execution_flags(paper, test) == expected


class _FakeCursor:
    def __init__(self, strategy):
        self._strategy = strategy
        self.executed = []
        self._last = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._last = sql

    def fetchone(self):
        if "SELECT strategy" in self._last:
            return (self._strategy,)
        if "SELECT id FROM" in self._last:
            return (10066,)
        return None


@pytest.mark.parametrize("flip_value", [False, "false", 0, None])
def test_settings_reject_flip_off_for_er(flip_value):
    from backend.core.auto_entry_settings_store import apply_auto_entry_settings
    from backend.core.tenant_context import TenantContext

    ctx = TenantContext.from_schema("users_0001")
    cur = _FakeCursor("Expiration Reversal")
    out = apply_auto_entry_settings(
        cur, "10066", {"flip_sell_floor": flip_value}, tenant_context=ctx
    )
    assert out["status"] == "error"
    assert "Expiration Reversal" in out["message"]
    assert not any("UPDATE" in s for s, _ in cur.executed)


def test_settings_flip_off_passes_guard_for_expiration_scalp(monkeypatch):
    import backend.core.auto_entry_settings_store as store
    from backend.core.tenant_context import TenantContext

    monkeypatch.setattr(store, "monitor_list_flip_columns_available", lambda *a, **k: False)
    monkeypatch.setattr(store, "monitor_list_position_risk_columns_available", lambda *a, **k: False)
    cur = _FakeCursor("Expiration Scalp")
    out = store.apply_auto_entry_settings(
        cur,
        "10056",
        {"flip_sell_floor": False},
        tenant_context=TenantContext.from_schema("users_0001"),
    )
    assert out == {"status": "error", "message": "No valid fields to update"}
    assert any("SELECT strategy" in s for s, _ in cur.executed)
