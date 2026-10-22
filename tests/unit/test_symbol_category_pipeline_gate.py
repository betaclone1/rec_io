"""symbols_list.live_data_level selects the pipeline health package. Category stays the asset class."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core import strike_pipeline_health as sph


@pytest.fixture(autouse=True)
def _strict_on(monkeypatch):
    monkeypatch.setenv("STRIKE_PIPELINE_HEALTH_STRICT_MODE", "1")
    yield


def _mock_conn(*, category_row, level_row=("full",), health_fetchone=None, health_fetchall=None):
    """category_row, then live_data_level, then health fetchone."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.side_effect = [category_row, level_row, health_fetchone]
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
    conn, cur = _mock_conn(
        category_row=("commodity",), level_row=("market",), health_fetchone=row
    )
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
    conn, _ = _mock_conn(
        category_row=("commodity",), level_row=("market",), health_fetchone=None
    )
    ok, rsn = sph.evaluate_pipeline_gate_conn(
        conn, exchange="kalshi", market="15m", symbol="GOLD"
    )
    assert ok is False
    assert rsn == "commodity_pipeline_health_missing"


def test_crypto_market_level_uses_lean_package():
    row = (True, "ok", 1.0, 2.0)
    conn, cur = _mock_conn(
        category_row=("crypto",), level_row=("market",), health_fetchone=row
    )
    with patch.object(sph, "_spot_series_passes_gate", return_value=(True, "ok")):
        ok, rsn = sph.evaluate_pipeline_gate_conn(
            conn, exchange="kalshi", market="15m", symbol="SOL"
        )
    assert ok is True
    assert rsn == "ok"
    sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("commodity_pipeline_health" in s for s in sqls)


def test_commodity_full_level_uses_strike_table():
    row = (True, "ok", 1.0, 2.0)
    conn, cur = _mock_conn(
        category_row=("commodity",), level_row=("full",), health_fetchone=row
    )
    with patch.object(sph, "_spot_series_passes_gate", return_value=(True, "ok")):
        ok, rsn = sph.evaluate_pipeline_gate_conn(
            conn, exchange="kalshi", market="15m", symbol="GOLD"
        )
    assert ok is True
    sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("strike_pipeline_health" in s for s in sqls)
    assert not any("commodity_pipeline_health" in s for s in sqls)


def test_none_level_fails_closed():
    conn, _ = _mock_conn(category_row=("crypto",), level_row=("none",))
    ok, rsn = sph.evaluate_pipeline_gate_conn(
        conn, exchange="kalshi", market="15m", symbol="DOGE"
    )
    assert ok is False
    assert rsn == "live_data_level_none"


def test_price_only_checks_spot():
    conn, _ = _mock_conn(category_row=("crypto",), level_row=("price_only",))
    with patch.object(sph, "_spot_series_passes_gate", return_value=(True, "ok")) as spot:
        ok, rsn = sph.evaluate_pipeline_gate_conn(
            conn, exchange="kalshi", market="15m", symbol="XRP"
        )
    assert ok is True
    assert rsn == "ok"
    spot.assert_called_once()


def test_strict_mode_off_skips_category():
    conn = MagicMock()
    with patch.object(sph, "strike_pipeline_health_strict_mode_enabled", return_value=False):
        ok, rsn = sph.evaluate_pipeline_gate_conn(
            conn, exchange="kalshi", market="15m", symbol="GOLD"
        )
    assert ok is True
    assert rsn == "ok"
    conn.cursor.assert_not_called()
