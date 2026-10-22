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
    with patch.object(ats_mod, "_ats_fetch_flip_sell_monitor_row", return_value=(False, "1x", True, "2x", False, False)), \
         patch.object(ats_mod, "_ats_trade_log_entry_method", return_value="auto_entry"), \
         patch.object(ats_mod, "_ats_flip_sell_position_after_loss_prevention", side_effect=lambda c, **kw: (c, False)), \
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
    with patch.object(ats_mod, "_ats_fetch_flip_sell_monitor_row", return_value=(False, "1x", False, "1x", False, False)), \
         patch.object(ats_mod, "get_trade_strategy", return_value="Expiration Scalp"), \
         patch.object(ats_mod, "ctx_user", return_value="0001"), \
         patch.object(ats_mod, "ctx_mid", return_value="10036"):
        assert ats_mod.prepare_flip_sell_meta_for_auto_stop(trade, "stop_loss_floor", 10, "N") is None


def _er_trade():
    return {
        "trade_id": 77,
        "ticker": "KXBTC15M-TEST",
        "strike": "95000",
        "side": "Y",
        "position": 100,
        "contract": "BTC 15m",
        "monitor": "mon_0001_10066",
        "current_close_price": 0.86,
        "current_symbol_price": 95100.0,
        "current_probability": 10.0,
        "diff": None,
    }


def _er_patches(ats_mod, row):
    return [
        patch.object(ats_mod, "_ats_fetch_flip_sell_monitor_row", return_value=row),
        patch.object(ats_mod, "_ats_trade_log_entry_method", return_value="auto_entry"),
        patch.object(ats_mod, "_ats_flip_sell_position_after_loss_prevention", side_effect=lambda c, **kw: (c, False)),
        patch.object(ats_mod, "_ats_get_multiplier_from_monitor", return_value=1.0),
        patch.object(ats_mod, "_ats_get_paper_trade_from_monitor", side_effect=AssertionError("not used for ER")),
        patch.object(ats_mod, "_ats_get_bankroll_allotment", return_value=1000.0),
        patch.object(ats_mod, "get_trade_strategy", return_value="Expiration Reversal"),
        patch.object(ats_mod, "get_current_monitor_symbol", return_value="BTC"),
        patch.object(ats_mod, "ctx_user", return_value="0001"),
        patch.object(ats_mod, "ctx_mid", return_value="10066"),
        patch.object(ats_mod, "_ats_reversal_flip_blocked", return_value=False),
    ]


@pytest.mark.parametrize(
    "mon_paper,mon_test,exp_paper,exp_test",
    [
        (False, False, False, False),
        (True, False, True, False),
        (True, True, True, True),
        (False, True, True, True),
    ],
)
def test_prepare_flip_meta_expiration_reversal_follows_monitor_flags(
    ats_mod, mon_paper, mon_test, exp_paper, exp_test
):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _er_patches(ats_mod, (False, "1x", True, "2x", mon_paper, mon_test)):
            stack.enter_context(p)
        meta = ats_mod.prepare_flip_sell_meta_for_auto_stop(_er_trade(), "stop_loss_floor", 100, "N")
    assert meta is not None
    assert meta["expiration_reversal"] is True
    assert meta["paper_trade"] is exp_paper
    assert meta["test_filter"] is exp_test
    assert meta["position"] == 200
    assert meta["side"] == "N"
    assert meta["trade_strategy"] == "Expiration Reversal"


def test_prepare_flip_meta_expiration_reversal_floor_always_flips(ats_mod):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _er_patches(ats_mod, (False, "1x", False, "1x", False, False)):
            stack.enter_context(p)
        meta = ats_mod.prepare_flip_sell_meta_for_auto_stop(_er_trade(), "stop_loss_floor", 100, "N")
    assert meta is not None
    assert meta["paper_trade"] is False
    assert meta["position"] == 100


def test_prepare_flip_meta_expiration_reversal_prob_stop_respects_flag(ats_mod):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _er_patches(ats_mod, (False, "1x", True, "1x", False, False)):
            stack.enter_context(p)
        assert (
            ats_mod.prepare_flip_sell_meta_for_auto_stop(
                _er_trade(), "probability_auto_stop", 100, "N"
            )
            is None
        )


def test_prepare_flip_meta_expiration_reversal_dupe_pairing_blocks(ats_mod):
    from contextlib import ExitStack

    for mon_paper in (False, True):
        with ExitStack() as stack:
            for p in _er_patches(ats_mod, (False, "1x", True, "1x", mon_paper, False)):
                stack.enter_context(p)
            stack.enter_context(
                patch.object(ats_mod, "_ats_reversal_flip_blocked", return_value=True)
            )
            assert (
                ats_mod.prepare_flip_sell_meta_for_auto_stop(
                    _er_trade(), "stop_loss_floor", 100, "N"
                )
                is None
            )


def test_prepare_flip_meta_expiration_reversal_no_flip_of_flip(ats_mod):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _er_patches(ats_mod, (False, "1x", True, "1x", False, False)):
            stack.enter_context(p)
        stack.enter_context(
            patch.object(ats_mod, "_ats_trade_log_entry_method", return_value="flip_sell")
        )
        assert (
            ats_mod.prepare_flip_sell_meta_for_auto_stop(_er_trade(), "stop_loss_floor", 100, "N")
            is None
        )
