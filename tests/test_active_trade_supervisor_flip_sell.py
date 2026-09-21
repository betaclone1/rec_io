#!/usr/bin/env python3
"""Tests for flip-sell preparation (combined close path)."""

import os
import sys
from unittest.mock import patch

import pytest

os.environ.setdefault("REC_USER_NO", "0001")
os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")


@pytest.fixture(scope="module")
def ats_mod():
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    if "backend.active_trade_supervisor" not in sys.modules:
        sys.argv = ["active_trade_supervisor.py", "unified"]
    import backend.active_trade_supervisor as ats  # noqa: E402

    return ats


def test_parse_flip_sell_multiplier(ats_mod):
    p = ats_mod.parse_flip_sell_multiplier
    assert p(None) == 1.0
    assert p("") == 1.0
    assert p("1") == 1.0
    assert p("2") == 2.0
    assert p("3x") == 3.0
    assert p("  1.5x ") == 1.5
    assert p("bad") == 1.0
    assert p("-1") == 1.0


def test_strict_boolean(ats_mod):
    f = ats_mod._ats_monitor_flip_boolean_strictly_true
    assert f(True) is True
    assert f(False) is False
    assert f(None) is False
    assert f(1) is False
    assert f("true") is False


def test_prepare_flip_meta_floor(ats_mod):
    trade = {
        "trade_id": 42,
        "ticker": "KXBTC15M-TEST",
        "strike": "95000",
        "side": "Y",
        "position": 1000,
        "contract": "BTC 15m",
        "monitor": "mon_0001_10036",
        "current_close_price": 0.42,
        "current_symbol_price": 95100.0,
        "current_probability": 35.0,
        "diff": None,
    }
    with patch.object(ats_mod, "_ats_fetch_flip_sell_monitor_row", return_value=(False, "1x", True, "2x", False)), \
         patch.object(ats_mod, "_ats_trade_log_entry_method", return_value="auto_entry"), \
         patch.object(ats_mod, "_ats_flip_sell_position_after_loss_prevention", side_effect=lambda c: (c, False)), \
         patch.object(ats_mod, "_ats_get_multiplier_from_monitor", return_value=1.0), \
         patch.object(ats_mod, "_ats_get_paper_trade_from_monitor", return_value=False), \
         patch.object(ats_mod, "_ats_get_bankroll_allotment", return_value=1000.0), \
         patch.object(ats_mod, "get_trade_strategy", return_value="Hourly HTC"), \
         patch.object(ats_mod, "get_current_monitor_symbol", return_value="BTC"), \
         patch.object(ats_mod, "ctx_user", return_value="0001"), \
         patch.object(ats_mod, "ctx_mid", return_value="10036"):
        meta = ats_mod.prepare_flip_sell_meta_for_auto_stop(trade, "stop_loss_floor", 1000, "N")
    assert meta is not None
    assert meta["entry_method"] == "flip_sell"
    assert meta["side"] == "N"
    assert meta["position"] == 2000


def test_prepare_skips_when_floor_false(ats_mod):
    trade = {
        "trade_id": 42,
        "ticker": "T",
        "strike": "1",
        "side": "Y",
        "current_close_price": 0.4,
        "current_symbol_price": 1.0,
    }
    with patch.object(ats_mod, "_ats_fetch_flip_sell_monitor_row", return_value=(False, "1x", False, "1x", False)), \
         patch.object(ats_mod, "ctx_user", return_value="0001"), \
         patch.object(ats_mod, "ctx_mid", return_value="10036"):
        assert ats_mod.prepare_flip_sell_meta_for_auto_stop(trade, "stop_loss_floor", 10, "N") is None
