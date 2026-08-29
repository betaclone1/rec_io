"""Global paper overlay must not leave live-flagged monitors stuck pending."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import backend.trading_mode as trading_mode
import backend.trade_executor as te
import backend.trade_manager as tm


def test_effective_paper_trade_overlays_global_paper():
    with patch.object(trading_mode, "get_trading_mode", return_value="paper"):
        assert trading_mode.effective_paper_trade(False) is True
        assert trading_mode.effective_paper_trade(True) is True
        assert trading_mode.effective_paper_trade("false") is True
    with patch.object(trading_mode, "get_trading_mode", return_value="live"):
        assert trading_mode.effective_paper_trade(False) is False
        assert trading_mode.effective_paper_trade(True) is True
        assert trading_mode.effective_paper_trade("true") is True


def test_executor_global_paper_notifies_trade_manager():
    with patch.object(te, "get_trading_mode", return_value="paper"):
        with patch.object(te, "log_event"):
            with patch.object(te, "_notify_trade_manager_executor_status") as notify:
                body, code = te.process_trigger_trade_request(
                    {"id": 79033, "ticket_id": "TICKET-x", "intent": "open"}
                )
    assert code == 403
    assert body["error"] == "global_paper_mode"
    notify.assert_called_once()
    payload = notify.call_args[0][0]
    assert payload["id"] == 79033
    assert payload["status"] == "error"
    assert payload["error_message"] == "global_paper_mode"
    assert payload["intent"] == "open"


def test_tm_global_paper_error_deletes_pending():
    with patch.object(
        tm,
        "_delete_pending_trade_for_rejection",
        return_value={"message": "deleted", "id": 79033},
    ) as delete_fn:
        body, err = tm.apply_update_trade_status_payload(
            {
                "id": 79033,
                "ticket_id": "TICKET-x",
                "status": "error",
                "error_message": "global_paper_mode",
                "intent": "open",
            }
        )
    assert err is None
    assert body["id"] == 79033
    delete_fn.assert_called_once_with(79033, "TICKET-x", "EXECUTOR REJECT")


def test_tm_pipeline_health_error_deletes_pending():
    with patch.object(
        tm,
        "_delete_pending_trade_for_rejection",
        return_value={"message": "deleted", "id": 1},
    ) as delete_fn:
        body, err = tm.apply_update_trade_status_payload(
            {
                "id": 1,
                "ticket_id": "TICKET-y",
                "status": "error",
                "error_message": "BLOCKED by WS strike pipeline health gate: reason=stale",
                "intent": "open",
            }
        )
    assert err is None
    delete_fn.assert_called_once_with(1, "TICKET-y", "EXECUTOR REJECT")


def test_delete_unfilled_pending_past_expiry_calls_reject_delete():
    pending_row = (
        79031,
        "KXBTC15M-26AUG281500-00",
        "BTC",
        "High Water Scalp",
        "BTC 3:00pm",
        "2026-08-28",
        "15m",
        None,
        "TICKET-pending",
        1,
    )
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = [pending_row]
    conn.cursor.return_value.__enter__.return_value = cur
    with patch.object(tm, "get_postgresql_connection", return_value=conn):
        with patch.object(
            tm, "_filter_trades_past_contract_expiration", return_value=[pending_row[:7]]
        ):
            with patch.object(
                tm,
                "_delete_pending_trade_for_rejection",
                return_value={"message": "deleted", "id": 79031},
            ) as delete_fn:
                tm._delete_unfilled_pending_past_expiry(
                    now_est=MagicMock(), scheduled_minute=15
                )
    delete_fn.assert_called_once_with(79031, "TICKET-pending", "CYCLE_EXPIRED_UNFILLED")
