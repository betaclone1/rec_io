"""TM Expiration Reversal: live flip open after a paper parent close."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import backend.trade_manager as tm


def _pg_with_row(row):
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.__enter__ = lambda s: cur
    cur.__exit__ = lambda s, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


_FLIP_ROW = (
    "KXBTC15M-26OCT101215-15",
    "N",
    200.0,
    0.86,
    "BTC",
    "15m",
    "mon_0001_10066",
    1,
    False,
    "pending",
)


def test_live_flip_open_sends_standalone_open_order():
    sent = []
    with patch.object(tm, "_is_trading_enabled", return_value=True), \
         patch.object(tm, "get_postgresql_connection", return_value=_pg_with_row(_FLIP_ROW)), \
         patch.object(tm, "send_trigger_to_executor", side_effect=sent.append), \
         patch.object(tm, "notify_active_trade_supervisor_direct") as notify, \
         patch.object(tm, "log_event"), \
         patch.object(tm, "_delete_pending_trade_for_rejection") as delete:
        tm._tm_send_expiration_reversal_live_flip_open(
            501, {"ticket_id": "TICKET-flip"}, "BTC", {"id": 500}
        )
    assert len(sent) == 1
    p = sent[0]
    assert p["id"] == 501
    assert p["intent"] == "open"
    assert p["side"] == "N"
    assert p["count_fp"] == "200.00"
    assert p["order_type"] == "market"
    assert p["time_in_force"] == "immediate_or_cancel"
    assert p["ticker"] == "KXBTC15M-26OCT101215-15"
    assert "flip_trade_id" not in p
    notify.assert_called_once_with(501, "TICKET-flip", "pending")
    delete.assert_not_called()


def test_live_flip_open_refuses_paper_row():
    row = _FLIP_ROW[:8] + (True, "pending")
    with patch.object(tm, "_is_trading_enabled", return_value=True), \
         patch.object(tm, "get_postgresql_connection", return_value=_pg_with_row(row)), \
         patch.object(tm, "send_trigger_to_executor") as send:
        tm._tm_send_expiration_reversal_live_flip_open(
            501, {"ticket_id": "TICKET-flip"}, "BTC", {"id": 500}
        )
    send.assert_not_called()


def test_live_flip_open_trading_disabled_deletes_pending():
    with patch.object(tm, "_is_trading_enabled", return_value=False), \
         patch.object(tm, "send_trigger_to_executor") as send, \
         patch.object(tm, "_delete_pending_trade_for_rejection") as delete:
        tm._tm_send_expiration_reversal_live_flip_open(
            501, {"ticket_id": "TICKET-flip"}, "BTC", {"id": 500}
        )
    send.assert_not_called()
    delete.assert_called_once_with(501, "TICKET-flip", "ER_FLIP_TRADING_DISABLED")
