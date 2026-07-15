"""TM early min_fill gate reuses initial_proj_price (no second orderbook fetch)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import backend.trade_manager as tm


def test_min_fill_price_for_db_helper():
    assert tm._min_fill_price_for_db({}) == 0.0
    assert tm._min_fill_price_for_db({"min_fill_price": None}) == 0.0
    assert tm._min_fill_price_for_db({"min_fill_price": 0}) == 0.0
    assert tm._min_fill_price_for_db({"min_fill_price": 0.85}) == 0.85
    assert tm._min_fill_price_for_db({"min_fill_price": "0.8500"}) == 0.85


def test_min_fill_precheck_disabled_when_unset_or_zero():
    assert tm._min_fill_price_precheck_message({}, {"initial_proj_price": 0.50}) is None
    assert (
        tm._min_fill_price_precheck_message(
            {"min_fill_price": 0}, {"initial_proj_price": 0.50}
        )
        is None
    )
    assert (
        tm._min_fill_price_precheck_message(
            {"min_fill_price": None}, {"initial_proj_price": 0.50}
        )
        is None
    )


def test_min_fill_precheck_rejects_below_floor():
    msg = tm._min_fill_price_precheck_message(
        {"min_fill_price": 0.85, "buy_price": 0.90},
        {"initial_proj_price": 0.65, "available_contracts": 1000, "reason": "ok"},
    )
    assert msg is not None
    assert "min_fill_price_rejected" in msg
    assert "estimated_fill=0.6500" in msg
    assert "min_fill_price=0.8500" in msg
    assert "trigger_buy_price=0.9" in msg


def test_min_fill_precheck_passes_at_or_above_floor():
    assert (
        tm._min_fill_price_precheck_message(
            {"min_fill_price": 0.85},
            {"initial_proj_price": 0.85, "reason": "ok"},
        )
        is None
    )
    assert (
        tm._min_fill_price_precheck_message(
            {"min_fill_price": 0.85},
            {"initial_proj_price": 0.90, "reason": "ok"},
        )
        is None
    )


def test_min_fill_precheck_rejects_missing_projection_like_executor():
    msg = tm._min_fill_price_precheck_message(
        {"min_fill_price": 0.85},
        {"initial_proj_price": None, "reason": "orderbook_miss"},
    )
    assert msg is not None
    assert "min_fill_price_no_orderbook:orderbook_miss" in msg

    msg2 = tm._min_fill_price_precheck_message({"min_fill_price": 0.85}, None)
    assert msg2 is not None
    assert "min_fill_price_no_orderbook" in msg2


def test_min_fill_precheck_matches_trades_25608_and_26399_shape():
    """Prod paper fills that would have been blocked by this gate."""
    assert tm._min_fill_price_precheck_message(
        {"min_fill_price": 0.85, "buy_price": 0.9},
        {"initial_proj_price": 0.65, "available_contracts": 157628.03},
    )
    assert tm._min_fill_price_precheck_message(
        {"min_fill_price": 0.85, "buy_price": 0.932},
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
def test_add_trade_precheck_deletes_pending_without_executor(
    _mock_pg,
    _mock_trading,
    mock_proj,
    mock_enrich,
    mock_log_event,
    mock_insert,
    mock_delete,
    mock_exec,
):
    """Paper/live: below min_fill → insert pending, delete, never send_trigger."""
    import asyncio

    mock_proj.return_value = {
        "ok": True,
        "reason": "ok",
        "initial_proj_price": 0.65,
        "initial_proj_fees": 8.59,
        "available_contracts": 1000,
    }

    def _enrich(data):
        data["min_fill_price"] = 0.85
        data["time_in_force"] = "immediate_or_cancel"
        data["order_type"] = "market"

    mock_enrich.side_effect = _enrich
    mock_insert.return_value = (25608, True)
    mock_delete.return_value = {
        "message": "Pending trade deleted due to slippage failure",
        "id": 25608,
    }

    req = MagicMock()
    req.json = AsyncMock(
        return_value={
            "ticket_id": "TICKET-test-minfill",
            "date": "2026-07-15",
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

    assert result["id"] == 25608
    mock_insert.assert_called_once()
    mock_delete.assert_called_once_with(25608, "TICKET-test-minfill", "SLIPPAGE FAILURE")
    mock_exec.assert_not_called()
    precheck_logs = [
        c.args[1]
        for c in mock_log_event.call_args_list
        if len(c.args) > 1 and "SLIPPAGE FAILURE (precheck)" in str(c.args[1])
    ]
    assert precheck_logs
    assert "estimated_fill=0.6500" in precheck_logs[0]
