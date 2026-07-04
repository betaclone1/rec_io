"""Drawdown halt eligibility must follow global trading mode."""

from unittest.mock import patch

import backend.trading_mode as tm
from backend.balance_snapshot import (
    _drawdown_stepped_down_for_halt,
    drawdown_halt_applies_to_balance_table,
)


def test_drawdown_halt_live_mode_uses_live_tables_only():
    with patch.object(tm, "get_trading_mode", return_value="live"):
        assert drawdown_halt_applies_to_balance_table("users.account_balance_0001") is True
        assert drawdown_halt_applies_to_balance_table("users.account_balance_paper_0001") is False


def test_drawdown_halt_paper_mode_uses_paper_tables_only():
    with patch.object(tm, "get_trading_mode", return_value="paper"):
        assert drawdown_halt_applies_to_balance_table("users.account_balance_paper_0001") is True
        assert drawdown_halt_applies_to_balance_table("users.account_balance_0001") is False


def test_drawdown_stepped_down_cleared_for_mismatched_table():
    with patch.object(tm, "get_trading_mode", return_value="live"):
        assert (
            _drawdown_stepped_down_for_halt(
                "users.account_balance_paper_0001",
                True,
            )
            is False
        )
        assert (
            _drawdown_stepped_down_for_halt(
                "users.account_balance_0001",
                True,
            )
            is True
        )
