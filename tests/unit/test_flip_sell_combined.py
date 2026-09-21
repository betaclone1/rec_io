#!/usr/bin/env python3
"""Unit tests for combined flip-sell fill allocation."""

from backend.core.flip_sell_combined import (
    FLIP_SELL_COMBINED_INTENT,
    allocate_combined_flip_fees,
    allocate_combined_flip_fills,
    close_fill_is_complete,
    combined_order_count,
    normalize_flip_sell_payload,
)


def test_allocate_full_close_and_flip():
    c, f = allocate_combined_flip_fills(20, 10, 10)
    assert c == 10
    assert f == 10


def test_allocate_close_first_partial_flip():
    c, f = allocate_combined_flip_fills(14, 10, 10)
    assert c == 10
    assert f == 4


def test_allocate_incomplete_close_zero_flip():
    c, f = allocate_combined_flip_fills(7, 10, 10)
    assert c == 7
    assert f == 0


def test_allocate_zero_fill():
    assert allocate_combined_flip_fills(0, 10, 10) == (0.0, 0.0)


def test_fees_prorate():
    cf, ff = allocate_combined_flip_fees(1.0, 10, 10)
    assert cf == 0.5
    assert ff == 0.5


def test_fees_all_close():
    cf, ff = allocate_combined_flip_fees(0.8, 8, 0)
    assert cf == 0.8
    assert ff == 0.0


def test_combined_count():
    assert combined_order_count(10, 20) == 30
    assert combined_order_count(10, 0) == 10


def test_close_fill_complete():
    assert close_fill_is_complete(10, 10)
    assert close_fill_is_complete(9.99, 10)
    assert not close_fill_is_complete(9.9, 10)


def test_normalize_flip_payload():
    assert normalize_flip_sell_payload(None) is None
    assert normalize_flip_sell_payload({"side": "Y", "position": 0}) is None
    out = normalize_flip_sell_payload({"side": "yes", "position": 5.4, "entry_method": "flip_sell"})
    assert out is not None
    assert out["side"] == "Y"
    assert out["position"] == 5
    assert out["entry_method"] == "flip_sell"
    assert FLIP_SELL_COMBINED_INTENT == "close_with_flip_sell"
