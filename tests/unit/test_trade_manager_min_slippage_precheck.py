"""TM early min_slippage gate reuses initial_proj_price (no second orderbook fetch).

Projected entry slippage = estimated fill (initial_proj_price) - trigger price (buy_price),
same sign convention as the persisted ``slippage`` column. Gate enabled only when
min_slippage < 0 (0.0000 disables; range -0.2000..0.0000).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import backend.trade_manager as tm


def test_min_slippage_for_db_helper():
    assert tm._min_slippage_for_db({}) == 0.0
    assert tm._min_slippage_for_db({"min_slippage": None}) == 0.0
    assert tm._min_slippage_for_db({"min_slippage": 0}) == 0.0
    assert tm._min_slippage_for_db({"min_slippage": 0.05}) == 0.0  # positive disables
    assert tm._min_slippage_for_db({"min_slippage": -0.05}) == -0.05
    assert tm._min_slippage_for_db({"min_slippage": "-0.0500"}) == -0.05


def test_min_slippage_precheck_disabled_when_unset_or_nonnegative():
    proj = {"initial_proj_price": 0.50}
    assert tm._min_slippage_precheck_message({"buy_price": 0.90}, proj) is None
    assert tm._min_slippage_precheck_message({"min_slippage": 0, "buy_price": 0.90}, proj) is None
    assert tm._min_slippage_precheck_message({"min_slippage": None, "buy_price": 0.90}, proj) is None
    # Positive is treated as disabled (only -0.1..0 is meaningful)
    assert tm._min_slippage_precheck_message({"min_slippage": 0.02, "buy_price": 0.90}, proj) is None


def test_min_slippage_precheck_rejects_below_floor():
    # proj slippage = 0.65 - 0.90 = -0.25, below floor -0.10 -> reject
    msg = tm._min_slippage_precheck_message(
        {"min_slippage": -0.10, "buy_price": 0.90},
        {"initial_proj_price": 0.65, "available_contracts": 1000, "reason": "ok"},
    )
    assert msg is not None
    assert "min_slippage_rejected" in msg
    assert "projected_slippage=-0.2500" in msg
    assert "min_slippage=-0.1000" in msg


def test_min_slippage_precheck_passes_at_or_above_floor():
    # proj slippage = 0.88 - 0.90 = -0.02, above floor -0.10 -> allow
    assert (
        tm._min_slippage_precheck_message(
            {"min_slippage": -0.10, "buy_price": 0.90},
            {"initial_proj_price": 0.88, "reason": "ok"},
        )
        is None
    )
    # exact floor allowed (proj slippage == min_slippage)
    assert (
        tm._min_slippage_precheck_message(
            {"min_slippage": -0.10, "buy_price": 0.90},
            {"initial_proj_price": 0.80, "reason": "ok"},
        )
        is None
    )
    # better-than-intended fill (positive slippage) always allowed
    assert (
        tm._min_slippage_precheck_message(
            {"min_slippage": -0.05, "buy_price": 0.60},
            {"initial_proj_price": 0.62, "reason": "ok"},
        )
        is None
    )


def test_min_slippage_precheck_rejects_missing_projection_like_executor():
    msg = tm._min_slippage_precheck_message(
        {"min_slippage": -0.05, "buy_price": 0.90},
        {"initial_proj_price": None, "reason": "orderbook_miss"},
    )
    assert msg is not None
    assert "min_slippage_no_orderbook:orderbook_miss" in msg

    msg2 = tm._min_slippage_precheck_message({"min_slippage": -0.05, "buy_price": 0.90}, None)
    assert msg2 is not None
    assert "min_slippage_no_orderbook" in msg2

    # Missing trigger price also cannot be evaluated
    msg3 = tm._min_slippage_precheck_message(
        {"min_slippage": -0.05},
        {"initial_proj_price": 0.65, "reason": "ok"},
    )
    assert msg3 is not None
    assert "min_slippage_no_orderbook" in msg3


def test_min_slippage_precheck_matches_trades_25608_and_26399_shape():
    """Prod paper fills that would have been blocked by a -0.10 slippage floor."""
    assert tm._min_slippage_precheck_message(
        {"min_slippage": -0.10, "buy_price": 0.9},
        {"initial_proj_price": 0.65, "available_contracts": 157628.03},
    )
    assert tm._min_slippage_precheck_message(
        {"min_slippage": -0.10, "buy_price": 0.932},
        {"initial_proj_price": 0.65786322, "available_contracts": 18723.35},
    )


@patch("backend.trade_manager.send_trigger_to_executor")
@patch("backend.trade_manager._delete_pending_trade_for_rejection")
@patch("backend.trade_manager.insert_trade")
@patch("backend.trade_manager.log_event")
@patch("backend.trade_manager._enrich_open_trade_execution_from_monitor")
@patch("backend.trade_manager._project_orderbook_entry")
@patch("backend.trade_manager._is_trading_enabled", return_value=True)
@patch("backend.trade_manager.get_postgresql_connection", return_value=None)
def test_add_trade_slippage_precheck_deletes_pending_without_executor(
    _mock_pg,
    _mock_trading,
    mock_proj,
    mock_enrich,
    mock_log_event,
    mock_insert,
    mock_delete,
    mock_exec,
):
    """Paper/live: projected slippage below floor → insert pending, delete, never send_trigger."""
    import asyncio

    mock_proj.return_value = {
        "ok": True,
        "reason": "ok",
        "initial_proj_price": 0.65,
        "initial_proj_fees": 8.59,
        "available_contracts": 1000,
    }

    def _enrich(data):
        # min_fill disabled so only the slippage gate fires
        data["min_slippage"] = -0.10
        data["time_in_force"] = "immediate_or_cancel"
        data["order_type"] = "market"

    mock_enrich.side_effect = _enrich
    mock_insert.return_value = (26399, True)
    mock_delete.return_value = {
        "message": "Pending trade deleted due to slippage failure",
        "id": 26399,
    }

    req = MagicMock()
    req.json = AsyncMock(
        return_value={
            "ticket_id": "TICKET-test-minslip",
            "date": "2026-07-16",
            "time": "12:00:00",
            "symbol": "BTC",
            "strike": "$58,526",
            "side": "N",
            "buy_price": 0.9,
            "position": 539,
            "ticker": "KXBTC15M-TEST",
            "monitor": "mon_0001_10046",
            "paper_trade": True,
            "exchange": "kalshi",
            "trade_strategy": "Expiration Scalp",
            "contract": "BTC 7:15pm",
        }
    )

    result = asyncio.run(tm.add_trade(req))

    assert result["id"] == 26399
    mock_insert.assert_called_once()
    mock_delete.assert_called_once_with(26399, "TICKET-test-minslip", "SLIPPAGE FAILURE")
    mock_exec.assert_not_called()
    precheck_logs = [
        c.args[1]
        for c in mock_log_event.call_args_list
        if len(c.args) > 1 and "SLIPPAGE FAILURE (precheck)" in str(c.args[1])
    ]
    assert precheck_logs
    assert any("projected_slippage=-0.2500" in m for m in precheck_logs)
