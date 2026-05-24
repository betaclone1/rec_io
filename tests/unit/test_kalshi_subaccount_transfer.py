"""Kalshi subaccount transfer helpers."""

from backend.bookkeeper.kalshi_subaccount_transfer import (
    KALSHI_SUBACCOUNT_NUMBER_TO_NAME,
    subaccount_name_to_number,
)


def test_subaccount_name_to_number():
    assert subaccount_name_to_number("CASH") == 0
    assert subaccount_name_to_number("PRIMARY") == 0
    assert subaccount_name_to_number("Master Trading Bankroll") == 1
    assert subaccount_name_to_number("undefined_2") == 2
    assert subaccount_name_to_number("Cash Transfer") == 2
    assert subaccount_name_to_number("undefined_3") == 3


def test_kalshi_subaccount_number_to_name():
    assert KALSHI_SUBACCOUNT_NUMBER_TO_NAME[0] == "CASH"
    assert KALSHI_SUBACCOUNT_NUMBER_TO_NAME[2] == "undefined_2"
