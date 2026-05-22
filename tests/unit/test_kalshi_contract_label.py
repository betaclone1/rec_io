"""Kalshi ticker → human contract label (15m and hourly)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")

from backend.trade_manager import (  # noqa: E402
    _coalesce_trade_contract,
    derive_contract_label_from_kalshi_ticker,
)


def test_15m_ticker_derives_minute_contract():
    assert (
        derive_contract_label_from_kalshi_ticker("ETH", "KXETH15M-26MAY211545-45")
        == "ETH 3:45pm"
    )
    assert (
        derive_contract_label_from_kalshi_ticker("BTC", "KXBTC15M-26MAY211815-15")
        == "BTC 6:15pm"
    )


def test_coalesce_replaces_legacy_market_suffix():
    assert (
        _coalesce_trade_contract("BTC", "BTC Market", "KXBTC15M-26MAY211815-15")
        == "BTC 6:15pm"
    )
