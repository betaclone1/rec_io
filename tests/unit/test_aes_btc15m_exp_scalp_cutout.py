"""BTC 15m Expiration Scalp cutout membership helpers."""

from __future__ import annotations

from backend.core.aes_btc15m_exp_scalp_cutout import (
    CUTOUT_ARGV,
    filter_cutout_rows_only,
    filter_out_cutout_rows,
    is_btc15m_exp_scalp_cutout_row,
    row_matches_cutout_fields,
)


def test_membership_exact():
    assert is_btc15m_exp_scalp_cutout_row(
        {"symbol": "BTC", "market": "15m", "strategy": "Expiration Scalp"}
    )
    assert row_matches_cutout_fields(
        symbol="btc", market="15M", strategy="Expiration Scalp"
    )


def test_membership_rejects_near_misses():
    assert not is_btc15m_exp_scalp_cutout_row(
        {"symbol": "ETH", "market": "15m", "strategy": "Expiration Scalp"}
    )
    assert not is_btc15m_exp_scalp_cutout_row(
        {"symbol": "BTC", "market": "hourly", "strategy": "Expiration Scalp"}
    )
    assert not is_btc15m_exp_scalp_cutout_row(
        {"symbol": "BTC", "market": "15m", "strategy": "Hourly HTC"}
    )


def test_filters_partition():
    rows = [
        {"monitor_id": "1", "symbol": "BTC", "market": "15m", "strategy": "Expiration Scalp"},
        {"monitor_id": "2", "symbol": "BTC", "market": "15m", "strategy": "Rising Devil"},
        {"monitor_id": "3", "symbol": "ETH", "market": "15m", "strategy": "Expiration Scalp"},
    ]
    only = filter_cutout_rows_only(rows)
    rest = filter_out_cutout_rows(rows)
    assert [r["monitor_id"] for r in only] == ["1"]
    assert [r["monitor_id"] for r in rest] == ["2", "3"]
    assert CUTOUT_ARGV == "btc15m_exp_scalp"
