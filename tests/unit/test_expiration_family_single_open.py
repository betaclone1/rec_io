"""Expiration-family monitors: one in-flight trade per ticker (either side)."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
if "backend.auto_entry_supervisor" not in sys.modules:
    sys.argv = ["auto_entry_supervisor.py", "btc15m_exp_scalp"]

import backend.auto_entry_supervisor as aes  # noqa: E402
import backend.trade_manager as tm  # noqa: E402


def _pg_with_row(row):
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.__enter__ = lambda s: cur
    cur.__exit__ = lambda s, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


def _open_payload(**kw):
    p = {
        "monitor": "mon_0001_10063",
        "ticker": "KXBTC15M-26OCT110845-45",
        "side": "Y",
        "ticket_id": "TICKET-new",
        "entry_method": "auto_entry",
    }
    p.update(kw)
    return p


@pytest.mark.parametrize(
    "strategy",
    ["Expiration Scalp", "Expiration Reversal", "High Water Scalp", "High Water Test 1"],
)
def test_tm_rejects_second_open_on_ticker_for_expiration_family(strategy):
    conn, _ = _pg_with_row((94831, "N", "open"))
    with patch.object(tm, "_monitor_key_matches_worker", return_value=True), \
         patch.object(tm, "get_postgresql_connection", return_value=conn), \
         patch.object(tm, "_fetch_monitor_state", return_value={"strategy": strategy}), \
         patch.object(tm, "log_event"):
        with pytest.raises(HTTPException) as exc:
            tm._reject_expiration_family_second_open(_open_payload())
    assert exc.value.status_code == 409
    assert exc.value.detail == "expiration_family_ticker_in_flight"


def test_tm_allows_open_when_no_in_flight_trade():
    conn, _ = _pg_with_row(None)
    with patch.object(tm, "_monitor_key_matches_worker", return_value=True), \
         patch.object(tm, "get_postgresql_connection", return_value=conn), \
         patch.object(tm, "_fetch_monitor_state", return_value={"strategy": "Expiration Scalp"}):
        tm._reject_expiration_family_second_open(_open_payload())


def test_tm_does_not_apply_to_other_strategies():
    conn, cur = _pg_with_row((1, "N", "open"))
    with patch.object(tm, "_monitor_key_matches_worker", return_value=True), \
         patch.object(tm, "get_postgresql_connection", return_value=conn), \
         patch.object(tm, "_fetch_monitor_state", return_value={"strategy": "Hourly HTC"}):
        tm._reject_expiration_family_second_open(_open_payload())
    cur.execute.assert_not_called()


def test_tm_flip_sell_is_not_blocked():
    with patch.object(tm, "_monitor_key_matches_worker", return_value=True), \
         patch.object(tm, "get_postgresql_connection") as pg:
        tm._reject_expiration_family_second_open(_open_payload(entry_method="flip_sell"))
    pg.assert_not_called()


def test_aes_any_side_blocks_opposite_side_from_warm_cache():
    tok = aes._aes_open_ticker_sides.set({("KXBTC15M-26OCT110845-45", "no")})
    try:
        with patch.object(aes, "ctx_user", return_value="0001"), \
             patch.object(aes, "ctx_mid", return_value="10063"), \
             patch.object(aes, "is_reverse_monitor", return_value=False):
            strike = {"ticker": "KXBTC15M-26OCT110845-45", "side": "yes"}
            assert aes.is_strike_already_traded(strike) is False
            assert aes.is_strike_already_traded(strike, any_side=True) is True
    finally:
        aes._aes_open_ticker_sides.reset(tok)


def test_aes_any_side_blocks_opposite_side_from_db():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.return_value = [(94831, "KXBTC15M-26OCT110845-45", "N", "open")]
    tok = aes._aes_open_ticker_sides.set(None)
    try:
        with patch.object(aes, "ctx_user", return_value="0001"), \
             patch.object(aes, "ctx_mid", return_value="10063"), \
             patch.object(aes, "is_reverse_monitor", return_value=False), \
             patch.object(aes, "get_db_connection", return_value=conn):
            strike = {"ticker": "KXBTC15M-26OCT110845-45", "side": "yes"}
            assert aes.is_strike_already_traded(strike) is False
            assert aes.is_strike_already_traded(strike, any_side=True) is True
    finally:
        aes._aes_open_ticker_sides.reset(tok)
