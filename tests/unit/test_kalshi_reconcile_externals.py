"""Unit tests for Kalshi external ↔ QBO bank-move matching."""

from __future__ import annotations

from datetime import date

from backend.bookkeeper.kalshi_reconcile_externals import (
    ExternalTransferRow,
    QboKalshiBankMove,
    adjusted_reconcile_gap,
    match_externals_to_qbo,
)


def test_adjusted_gap_strips_unmirrored_withdrawal() -> None:
    # QBO still high by $1139.66 after Kalshi withdrawal not yet on books
    assert adjusted_reconcile_gap(1139.66, -1139.66) == 0.0


def test_adjusted_gap_strips_unmirrored_deposit() -> None:
    # Kalshi high by $10k after deposit not yet on QBO
    assert adjusted_reconcile_gap(-10000.0, 10000.0) == 0.0


def test_match_pairs_withdrawal_to_out_of_kalshi_transfer() -> None:
    ext = ExternalTransferRow(
        id=1,
        txn_date=date(2026, 7, 17),
        amount_cents=-113966,
        status="applied",
        from_name="Cash Transfer",
        to_name="ACH",
    )
    mv = QboKalshiBankMove(
        entity="Transfer",
        qbo_id="174",
        txn_date=date(2026, 7, 20),
        amount_dollars=1139.66,
        direction="out_of_kalshi",
        note="KALSHI",
        other_account="Revenue Checking",
    )
    result = match_externals_to_qbo([ext], [mv], match_window_days=14)
    assert len(result.matched) == 1
    assert result.unmatched == []
    assert result.unmirrored_signed_dollars == 0.0


def test_match_pairs_withdrawal_to_deposit_from_kalshi() -> None:
    ext = ExternalTransferRow(
        id=2,
        txn_date=date(2026, 7, 24),
        amount_cents=-563959,
        status="applied",
        from_name="Cash Transfer",
        to_name="ACH",
    )
    mv = QboKalshiBankMove(
        entity="Deposit",
        qbo_id="99",
        txn_date=date(2026, 7, 24),
        amount_dollars=5639.59,
        direction="out_of_kalshi",
        note="Kalshi",
        other_account="Revenue Checking",
    )
    result = match_externals_to_qbo([ext], [mv])
    assert len(result.matched) == 1
    assert result.unmirrored_signed_dollars == 0.0


def test_unmatched_outside_window_stays_unmirrored() -> None:
    ext = ExternalTransferRow(
        id=3,
        txn_date=date(2026, 7, 1),
        amount_cents=-10000,
        status="applied",
        from_name="Cash Transfer",
        to_name="ACH",
    )
    mv = QboKalshiBankMove(
        entity="Transfer",
        qbo_id="1",
        txn_date=date(2026, 7, 20),
        amount_dollars=100.0,
        direction="out_of_kalshi",
        note="",
        other_account="Bank",
    )
    result = match_externals_to_qbo([ext], [mv], match_window_days=7)
    assert result.matched == []
    assert result.unmirrored_signed_dollars == -100.0


def test_deposit_matches_into_kalshi() -> None:
    ext = ExternalTransferRow(
        id=4,
        txn_date=date(2026, 7, 8),
        amount_cents=1000000,
        status="applied",
        from_name="ACH",
        to_name="Cash Transfer",
    )
    mv = QboKalshiBankMove(
        entity="Transfer",
        qbo_id="153",
        txn_date=date(2026, 7, 9),
        amount_dollars=10000.0,
        direction="into_kalshi",
        note="KALSHI",
        other_account="Operational Checking",
    )
    result = match_externals_to_qbo([ext], [mv])
    assert len(result.matched) == 1
    assert result.unmirrored_signed_dollars == 0.0
