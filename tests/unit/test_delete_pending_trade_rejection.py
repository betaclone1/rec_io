"""Open rejection must not delete trades that already have Kalshi fills."""

from unittest.mock import MagicMock, patch

from backend.trade_manager import (
    _delete_pending_trade_for_rejection,
    _pending_row_has_retained_venue_fills,
)


def _conn_with_cursor(cur):
    conn = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = cur
    cm.__exit__.return_value = None
    conn.cursor.return_value = cm
    return conn


def test_pending_row_has_retained_venue_fills_heuristics():
    # Virgin pending INSERT seeds position = initial_count
    assert _pending_row_has_retained_venue_fills(1517, 1517) is False
    assert _pending_row_has_retained_venue_fills(0, 1517) is False
    # Partial top-up pending: cumulative filled < request
    assert _pending_row_has_retained_venue_fills(1625.62, 1631) is True
    assert _pending_row_has_retained_venue_fills(1, 1631) is True


@patch("backend.trade_manager.notify_active_trade_supervisor_direct_with_monitor")
@patch("backend.trade_manager.notify_active_trade_supervisor_direct")
@patch("backend.trade_manager.log_event")
@patch("backend.trade_manager.get_postgresql_connection")
def test_rejection_preserves_partial_fill(mock_conn, _log_event, mock_notify, mock_notify_mon):
    select_cur = MagicMock()
    select_cur.fetchone.return_value = ("mon_0001_10043", 1625.62, 1631)
    update_cur = MagicMock()
    update_cur.rowcount = 1
    mock_conn.side_effect = [_conn_with_cursor(select_cur), _conn_with_cursor(update_cur)]

    result = _delete_pending_trade_for_rejection(28023, "TICKET-x", "SLIPPAGE FAILURE")

    assert result["status"] == "partial"
    assert "preserved" in result["message"].lower()
    update_sql = update_cur.execute.call_args[0][0]
    assert "UPDATE" in update_sql.upper()
    assert "DELETE" not in update_sql.upper()
    assert update_cur.execute.call_args[0][1] == ("partial", 28023)
    mock_notify_mon.assert_called_once()
    mock_notify.assert_not_called()


@patch("backend.trade_manager.notify_active_trade_supervisor_direct_with_monitor")
@patch("backend.trade_manager.notify_active_trade_supervisor_direct")
@patch("backend.trade_manager.log_event")
@patch("backend.trade_manager.get_postgresql_connection")
def test_rejection_deletes_zero_fill_pending(mock_conn, _log_event, mock_notify, mock_notify_mon):
    select_cur = MagicMock()
    select_cur.fetchone.return_value = ("mon_0001_10043", 0, 1631)
    delete_cur = MagicMock()
    delete_cur.rowcount = 1
    mock_conn.side_effect = [_conn_with_cursor(select_cur), _conn_with_cursor(delete_cur)]

    result = _delete_pending_trade_for_rejection(28023, "TICKET-x", "SLIPPAGE FAILURE")

    assert "deleted" in result["message"].lower()
    assert "DELETE" in delete_cur.execute.call_args[0][0].upper()
    mock_notify_mon.assert_called_once()
    mock_notify.assert_not_called()


@patch("backend.trade_manager.notify_active_trade_supervisor_direct_with_monitor")
@patch("backend.trade_manager.notify_active_trade_supervisor_direct")
@patch("backend.trade_manager.log_event")
@patch("backend.trade_manager.get_postgresql_connection")
def test_rejection_deletes_virgin_pending_seeded_position(
    mock_conn, _log_event, mock_notify, mock_notify_mon
):
    """position == initial_count is request size, not a venue fill (prod 28185)."""
    select_cur = MagicMock()
    select_cur.fetchone.return_value = ("mon_0001_10043", 1517, 1517)
    delete_cur = MagicMock()
    delete_cur.rowcount = 1
    mock_conn.side_effect = [_conn_with_cursor(select_cur), _conn_with_cursor(delete_cur)]

    result = _delete_pending_trade_for_rejection(28185, "TICKET-x", "SLIPPAGE FAILURE")

    assert "deleted" in result["message"].lower()
    assert "DELETE" in delete_cur.execute.call_args[0][0].upper()
    mock_notify_mon.assert_called_once()
    mock_notify.assert_not_called()
