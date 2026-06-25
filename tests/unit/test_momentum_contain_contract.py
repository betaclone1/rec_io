"""Momentum Contain hourly contract normalization (MC-only helpers)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
sys.argv = ["auto_entry_supervisor_0001_10023"]

from backend.auto_entry_supervisor import _mc_normalize_hourly_contract  # noqa: E402


def test_mc_normalize_collapses_hourly_colon_zero_aliases():
    assert _mc_normalize_hourly_contract("BTC 11:00am") == "BTC 11am"
    assert _mc_normalize_hourly_contract("BTC 11am") == "BTC 11am"
    assert _mc_normalize_hourly_contract("ETH 12:00pm") == "ETH 12pm"
    assert _mc_normalize_hourly_contract("BTC 12pm") == "BTC 12pm"


def test_mc_normalize_leaves_true_15m_labels_unchanged():
    assert _mc_normalize_hourly_contract("BTC 11:15am") == "BTC 11:15am"
    assert _mc_normalize_hourly_contract("ETH 3:45pm") == "ETH 3:45pm"
