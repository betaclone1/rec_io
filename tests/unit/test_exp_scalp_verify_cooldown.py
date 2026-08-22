"""Exp Scalp verify must survive TRADE_COOLDOWN look-skips."""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
sys.argv = ["auto_entry_supervisor.py", "unified"]

import backend.auto_entry_supervisor as aes  # noqa: E402


def setup_function():
    aes.last_trade_times.clear()


def test_peek_does_not_claim_cooldown():
    key = "99019-64143-yes"
    assert aes.strike_on_trade_cooldown(key) is False
    assert key not in aes.last_trade_times
    assert aes.can_trade_strike(key) is True
    assert key in aes.last_trade_times
    assert aes.strike_on_trade_cooldown(key) is True
    assert aes.can_trade_strike(key) is False


def test_cooldown_skip_keeps_verify_out_of_stale_abort():
    key = "99019-64143-yes"
    dedupe = (key, "yes")
    verify_bucket = {dedupe: {"started_at": 100.0}}
    seen = set()

    aes.last_trade_times[key] = time.time()
    retained = aes._exp_scalp_retain_verify_during_cooldown(key, seen, dedupe)

    assert retained is True
    assert dedupe in seen
    stale = [k for k in verify_bucket if k not in seen]
    assert stale == []


def test_no_cooldown_does_not_mark_seen():
    key = "99019-64143-yes"
    dedupe = (key, "yes")
    seen = set()
    assert aes._exp_scalp_retain_verify_during_cooldown(key, seen, dedupe) is False
    assert seen == set()
