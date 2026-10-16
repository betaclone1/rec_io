"""Expiration-family loss prevention: flip sells keep full size (same-trade exception)."""

from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def ats_mod():
    import os
    import sys

    os.environ.setdefault("REC_USER_NO", "0001")
    os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    if "backend.active_trade_supervisor" not in sys.modules:
        sys.argv = ["active_trade_supervisor.py", "unified"]
    import backend.active_trade_supervisor as ats  # noqa: E402

    return ats


@pytest.mark.parametrize(
    "strategy",
    [
        "Expiration Scalp",
        "Expiration Reversal",
        "High Water Scalp",
        "High Water Test 1",
    ],
)
def test_expiration_flip_skips_loss_prevention_sizing(ats_mod, strategy):
    with patch.object(ats_mod, "get_trade_strategy", return_value=strategy):
        pos, lp_flag = ats_mod._ats_flip_sell_position_after_loss_prevention(
            50, strategy=strategy
        )
    assert pos == 50
    assert lp_flag is False


def test_htc_flip_still_applies_loss_prevention_sizing(ats_mod):
    with patch.object(ats_mod, "get_trade_strategy", return_value="Hourly HTC"), patch(
        "backend.core.symbol_wide_loss_prevention.resolve_effective_loss_prevention_state",
        return_value="live_loss_1c",
    ), patch(
        "backend.core.symbol_wide_loss_prevention.normalize_loss_prevention_state_for_sizing",
        return_value="live_loss_1c",
    ), patch.object(ats_mod, "get_db_connection") as gdc:
        conn = gdc.return_value
        cur = conn.cursor.return_value.__enter__.return_value
        cur  # unused; resolve is mocked
        pos, lp_flag = ats_mod._ats_flip_sell_position_after_loss_prevention(
            50, strategy="Hourly HTC"
        )
    assert pos == 1
    assert lp_flag is True
