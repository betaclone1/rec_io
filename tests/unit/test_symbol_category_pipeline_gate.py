"""symbols_list.category selects crypto vs commodity pipeline health package."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core import strike_pipeline_health as sph


@pytest.fixture(autouse=True)
def _strict_on(monkeypatch):
    monkeypatch.setenv("STRIKE_PIPELINE_HEALTH_STRICT_MODE", "1")
    yield


def _mock_conn(*, category_row, health_fetchone=None, health_fetchall=None):
    """category_row is first fetchone; health_fetchone/fetchall for package queries."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.side_effect = [category_row, health_fetchone]
    cur.fetchall.return_value = health_fetchall if health_fetchall is not None else []
    return conn, cur


def test_missing_symbol_category_fails_closed():
    conn, _ = _mock_conn(category_row=None)
    ok, rsn = sph.evaluate_pipeline_gate_conn(
        conn, exchange="kalshi", market="15m", symbol="GOLD"
    )
    assert ok is False
    assert rsn == "symbol_category_missing"


def test_invalid_category_fails_closed():
    conn, _ = _mock_conn(category_row=("fx",))
    ok, rsn = sph.evaluate_pipeline_gate_conn(
        conn, exchange="kalshi", market="15m", symbol="EUR"
    )
    assert ok is False
    assert rsn == "symbol_category_invalid:fx"


def test_crypto_uses_strike_table():
    row = (True, "ok", 1.0, 2.0)
    conn, cur = _mock_conn(category_row=("crypto",), health_fetchone=row)
    with patch.object(sph, "_spot_series_passes_gate", return_value=(True, "ok")):
        ok, rsn = sph.evaluate_pipeline_gate_conn(
            conn, exchange="kalshi", market="15m", symbol="BTC"
        )
    assert ok is True
    assert rsn == "ok"
    sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("strike_pipeline_health" in s for s in sqls)
    assert not any("commodity_pipeline_health" in s for s in sqls)


def test_commodity_uses_commodity_table():
    row = (True, "ok", 1.0, 2.0)
    conn, cur = _mock_conn(category_row=("commodity",), health_fetchone=row)
    with patch.object(sph, "_spot_series_passes_gate", return_value=(True, "ok")):
        ok, rsn = sph.evaluate_pipeline_gate_conn(
            conn, exchange="kalshi", market="15m", symbol="GOLD"
        )
    assert ok is True
    assert rsn == "ok"
    sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("commodity_pipeline_health" in s for s in sqls)
    assert not any("FROM live_data.strike_pipeline_health" in s for s in sqls)


def test_commodity_missing_health_row():
    conn, _ = _mock_conn(category_row=("commodity",), health_fetchone=None)
    ok, rsn = sph.evaluate_pipeline_gate_conn(
        conn, exchange="kalshi", market="15m", symbol="GOLD"
    )
    assert ok is False
    assert rsn == "commodity_pipeline_health_missing"


def test_strict_mode_off_skips_category():
    conn = MagicMock()
    with patch.object(sph, "strike_pipeline_health_strict_mode_enabled", return_value=False):
        ok, rsn = sph.evaluate_pipeline_gate_conn(
            conn, exchange="kalshi", market="15m", symbol="GOLD"
        )
    assert ok is True
    assert rsn == "ok"
    conn.cursor.assert_not_called()
