"""Unit tests for Stage 0 tradeflow decision trace helpers."""

import os

from backend.core import tradeflow_decision_trace as dtrace


def test_ladder_identity_fingerprint():
    snap = {
        "event_ticker": "KXBTCD-TEST",
        "ttc": 900,
        "strikes": [
            {
                "ticker": "A",
                "yes_ask_dollars": "0.40",
                "no_ask_dollars": "0.62",
                "probability": 55,
                "active_side": "yes",
            }
        ],
    }
    a = dtrace.ladder_identity(snap)
    b = dtrace.ladder_identity(snap)
    assert a["ok"] is True
    assert a["asks_sha1"] == b["asks_sha1"]
    assert a["strike_n"] == 1
    assert dtrace.ladder_identity(None)["ok"] is False


def test_pass_trace_roundtrip(monkeypatch):
    monkeypatch.setenv("TRADEFLOW_DECISION_TRACE", "1")
    lines = []
    dtrace.set_trace_logger(lines.append)
    pid = dtrace.begin_pass(service="aes")
    assert pid.startswith("aes-")
    dtrace.trace("unit", monitor="10001", reason="ok")
    dtrace.end_pass(groups=1)
    joined = "\n".join(lines)
    assert "pass_begin" in joined
    assert "pass_end" in joined
    assert "unit" in joined
    monkeypatch.delenv("TRADEFLOW_DECISION_TRACE", raising=False)
    dtrace.set_trace_logger(None)
