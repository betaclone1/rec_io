"""Expiration Scalp adverse_delta_15s_pct entry gate."""

from backend.util.auto_entry_expiration_scalp_gates import (
    expiration_scalp_adverse_delta_15s_gate,
    parse_adverse_delta_15s_pct,
)


def test_parse_adverse_delta_15s_pct_disabled_and_valid():
    assert parse_adverse_delta_15s_pct({}) == 0.0
    assert parse_adverse_delta_15s_pct({"adverse_delta_15s_pct": None}) == 0.0
    assert parse_adverse_delta_15s_pct({"adverse_delta_15s_pct": 0}) == 0.0
    assert parse_adverse_delta_15s_pct({"adverse_delta_15s_pct": -1}) == 0.0
    assert parse_adverse_delta_15s_pct({"adverse_delta_15s_pct": 0.0075}) == 0.0075
    assert parse_adverse_delta_15s_pct({"adverse_delta_15s_pct": "0.0075"}) == 0.0075


def test_adverse_delta_15s_disabled():
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="yes", delta_15s=-1.0, adverse_delta_15s_pct=0
        )
        is None
    )


def test_adverse_delta_15s_yes_veto_and_pass():
    thresh = 0.0075
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="yes", delta_15s=-0.0075, adverse_delta_15s_pct=thresh
        )
        == "adverse_delta_15s_yes"
    )
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="yes", delta_15s=-0.01, adverse_delta_15s_pct=thresh
        )
        == "adverse_delta_15s_yes"
    )
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="yes", delta_15s=-0.0074, adverse_delta_15s_pct=thresh
        )
        is None
    )
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="yes", delta_15s=0.01, adverse_delta_15s_pct=thresh
        )
        is None
    )


def test_adverse_delta_15s_no_veto_and_pass():
    thresh = 0.0075
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="no", delta_15s=0.0075, adverse_delta_15s_pct=thresh
        )
        == "adverse_delta_15s_no"
    )
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="no", delta_15s=0.01, adverse_delta_15s_pct=thresh
        )
        == "adverse_delta_15s_no"
    )
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="no", delta_15s=0.0074, adverse_delta_15s_pct=thresh
        )
        is None
    )
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="no", delta_15s=-0.01, adverse_delta_15s_pct=thresh
        )
        is None
    )


def test_adverse_delta_15s_fail_closed_missing():
    assert (
        expiration_scalp_adverse_delta_15s_gate(
            side="yes", delta_15s=None, adverse_delta_15s_pct=0.0075
        )
        == "missing_delta_15s"
    )
