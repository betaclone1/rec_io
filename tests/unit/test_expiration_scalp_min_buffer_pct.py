"""Expiration Scalp min_buffer_pct entry gate (hot-path buffer_pct units)."""

from backend.util.auto_entry_expiration_scalp_gates import (
    evaluate_expiration_scalp_entry,
    expiration_scalp_min_buffer_pct_gate,
    parse_min_buffer_pct,
)


_BASE = {
    "min_time": 0,
    "max_time": 60,
    "min_probability": 55.0,
    "max_probability": 100.0,
    "min_ask": 0.90,
    "max_ask": 0.99,
    "min_movement": 0.0,
    "max_movement": 100.0,
}


def test_parse_min_buffer_pct_disabled_and_valid():
    assert parse_min_buffer_pct({}) == 0.0
    assert parse_min_buffer_pct({"min_buffer_pct": None}) == 0.0
    assert parse_min_buffer_pct({"min_buffer_pct": 0}) == 0.0
    assert parse_min_buffer_pct({"min_buffer_pct": -1}) == 0.0
    assert parse_min_buffer_pct({"min_buffer_pct": 0.0055}) == 0.0055
    assert parse_min_buffer_pct({"min_buffer_pct": "0.0055"}) == 0.0055


def test_min_buffer_pct_gate_trade_47329_style():
    # Trade 47329: buffer ~$3.58 on ~77842 spot → ~0.0046%; floor 0.0055 rejects.
    assert (
        expiration_scalp_min_buffer_pct_gate(buffer_pct=0.0046, min_buffer_pct=0.0055)
        == "buffer_pct_below_min"
    )
    assert (
        expiration_scalp_min_buffer_pct_gate(
            buffer_pct=0.0055,
            avg_60s_buffer_pct=0.0055,
            min_buffer_pct=0.0055,
        )
        is None
    )
    assert (
        expiration_scalp_min_buffer_pct_gate(
            buffer_pct=0.01,
            avg_60s_buffer_pct=0.01,
            min_buffer_pct=0.0055,
        )
        is None
    )
    assert expiration_scalp_min_buffer_pct_gate(buffer_pct=0.001, min_buffer_pct=0) is None
    assert (
        expiration_scalp_min_buffer_pct_gate(buffer_pct=None, min_buffer_pct=0.0055)
        == "missing_buffer_pct"
    )
    assert (
        expiration_scalp_min_buffer_pct_gate(
            buffer_pct=0.01,
            avg_60s_buffer_pct=0.004,
            min_buffer_pct=0.0055,
        )
        == "60s_avg_buffer_pct_below_min"
    )
    assert (
        expiration_scalp_min_buffer_pct_gate(
            buffer_pct=0.01,
            avg_60s_buffer_pct=None,
            min_buffer_pct=0.0055,
        )
        == "missing_60s_avg_buffer_pct"
    )


def test_evaluate_expiration_scalp_entry_min_buffer_pct():
    settings = {**_BASE, "min_buffer_pct": 0.0055}
    blocked, reason = evaluate_expiration_scalp_entry(
        settings,
        ttc_seconds=30,
        side="no",
        ask_dollars=0.989,
        probability=55.35,
        buffer_pct=0.0046,
        avg_60s_buffer_pct=0.0060,
    )
    assert blocked is None
    assert reason == "buffer_pct_below_min"

    blocked_60s, reason_60s = evaluate_expiration_scalp_entry(
        settings,
        ttc_seconds=30,
        side="no",
        ask_dollars=0.989,
        probability=55.35,
        buffer_pct=0.0060,
        avg_60s_buffer_pct=0.0046,
    )
    assert blocked_60s is None
    assert reason_60s == "60s_avg_buffer_pct_below_min"

    passed, reason_ok = evaluate_expiration_scalp_entry(
        settings,
        ttc_seconds=30,
        side="no",
        ask_dollars=0.989,
        probability=55.35,
        buffer_pct=0.0060,
        avg_60s_buffer_pct=0.0060,
    )
    assert reason_ok is None
    assert passed is not None
    assert passed["buffer_pct"] == 0.0060

    # Disabled floor ignores missing buffer_pct
    off, reason_off = evaluate_expiration_scalp_entry(
        {**_BASE, "min_buffer_pct": 0},
        ttc_seconds=30,
        side="yes",
        ask_dollars=0.95,
        probability=90.0,
        buffer_pct=None,
        avg_60s_buffer_pct=None,
    )
    assert reason_off is None
    assert off is not None
