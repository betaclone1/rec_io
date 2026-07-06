"""Venue market_result backfill and win_loss_confirmed confirmation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core.kalshi_lifecycle_trade_outcome import compute_win_loss_confirmed_from_venue


def test_compute_win_loss_confirmed_early_loss_no_side_settled_no():
    """NO held to expiry win vs recorded early-exit loss is not confirmed."""
    assert compute_win_loss_confirmed_from_venue("N", "no", "L") is False
    assert compute_win_loss_confirmed_from_venue("N", "no", "W") is True


def test_finalize_closed_wlc_skips_without_market_result():
    import backend.trade_manager as tm

    cursor = MagicMock()
    cursor.fetchone.return_value = ("N", "L", "closed", None)

    tm._finalize_closed_trade_win_loss_confirmed(cursor, 26406)

    cursor.execute.assert_called_once()
    cursor.execute.return_value = None


def test_finalize_closed_wlc_uses_venue_result():
    import backend.trade_manager as tm

    cursor = MagicMock()
    cursor.fetchone.return_value = ("N", "L", "closed", "no")

    tm._finalize_closed_trade_win_loss_confirmed(cursor, 26406)

    assert cursor.execute.call_count == 2
    update_sql, update_args = cursor.execute.call_args_list[1][0]
    assert "win_loss_confirmed" in update_sql
    assert update_args == (False, 26406)


@patch("backend.trade_manager.get_postgresql_connection")
def test_distinct_tickers_missing_market_result_prioritizes_expired(mock_conn):
    import backend.trade_manager as tm

    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [("KXBTCD-26JUL0519-T63399.99",)],
        [("KXBTCD-26JUL0518-T63099.99",)],
    ]
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value = cursor
    mock_conn.return_value = pg

    tickers, expired_n = tm._distinct_tickers_missing_market_result(50)

    assert tickers == [
        "KXBTCD-26JUL0519-T63399.99",
        "KXBTCD-26JUL0518-T63099.99",
    ]
    assert expired_n == 1
    assert cursor.execute.call_count == 2
    expired_sql = cursor.execute.call_args_list[0][0][0]
    closed_sql = cursor.execute.call_args_list[1][0][0]
    assert "status = 'expired'" in expired_sql
    assert "status = 'closed'" in closed_sql
    assert "LIMIT" in closed_sql


@patch("backend.core.kalshi_lifecycle_trade_outcome.apply_lifecycle_market_result_for_ticker")
@patch("backend.core.kalshi_event_market_fetch.normalized_result_for_market_in_payload")
@patch("backend.core.kalshi_event_market_fetch.fetch_event_payload")
@patch("backend.core.kalshi_event_market_fetch.event_ticker_from_market_ticker")
@patch("backend.trade_manager._distinct_tickers_missing_market_result")
@patch("backend.trade_manager._trade_manager_scheduler_shutdown")
def test_backfill_missing_market_results_applies_closed_ticker(
    mock_shutdown,
    mock_tickers,
    mock_event_ticker,
    mock_fetch,
    mock_norm,
    mock_apply,
):
    import backend.trade_manager as tm

    mock_shutdown.is_set.return_value = False
    mock_tickers.return_value = (["KXBTCD-26JUL0518-T63099.99"], 0)
    mock_event_ticker.return_value = "KXBTCD-26JUL0518"
    mock_fetch.return_value = {"markets": []}
    mock_norm.return_value = "no"
    mock_apply.return_value = 1

    tm.backfill_missing_market_results_from_kalshi(limit=10)

    mock_apply.assert_called_once_with("KXBTCD-26JUL0518-T63099.99", "no")
