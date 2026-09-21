"""Pre-dwell Exp Scalp VERIFY ABORT must INFO-log (adverse gate common path)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
if "backend.auto_entry_supervisor" not in sys.modules:
    sys.argv = ["auto_entry_supervisor.py", "btc15m_exp_scalp"]

import backend.auto_entry_supervisor as aes  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_pre_dwell_throttle():
    aes._exp_scalp_pre_dwell_veto_log_mono.clear()
    yield
    aes._exp_scalp_pre_dwell_veto_log_mono.clear()


def test_pre_dwell_veto_logs_with_phase(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(aes, "log", lambda msg: lines.append(str(msg)))
    monkeypatch.setattr(aes, "_EXP_SCALP_PRE_DWELL_VETO_LOG_INTERVAL_SEC", 0.0)

    bucket: dict = {}
    aes._exp_scalp_verify_abort(
        bucket,
        ("99019-81214", "yes"),
        now_ts=100.0,
        need_s=6,
        reason="adverse_delta_15s_yes",
        strike_key="99019-81214",
        side_key="yes",
        log_tag="[AUTO ENTRY EXPIRATION SCALP]",
        extra="delta_15s=-0.012 adverse_delta_15s_pct=0.0075",
    )

    assert len(lines) == 1
    assert "VERIFY ABORT" in lines[0]
    assert "phase=pre_dwell" in lines[0]
    assert "dwell=0.0s" in lines[0]
    assert "reason=adverse_delta_15s_yes" in lines[0]
    assert "delta_15s=-0.012" in lines[0]


def test_in_dwell_abort_always_logs(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(aes, "log", lambda msg: lines.append(str(msg)))

    bucket = {("99019-81214", "yes"): {"started_at": 90.0}}
    aes._exp_scalp_verify_abort(
        bucket,
        ("99019-81214", "yes"),
        now_ts=95.5,
        need_s=6,
        reason="adverse_delta_15s_yes",
        strike_key="99019-81214",
        side_key="yes",
        log_tag="[AUTO ENTRY EXPIRATION SCALP]",
        extra="delta_15s=-0.02 adverse_delta_15s_pct=0.0075",
    )

    assert ("99019-81214", "yes") not in bucket
    assert len(lines) == 1
    assert "phase=in_dwell" in lines[0]
    assert "dwell=5.5s" in lines[0]


def test_pre_dwell_veto_throttled(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(aes, "log", lambda msg: lines.append(str(msg)))
    monkeypatch.setattr(aes, "_EXP_SCALP_PRE_DWELL_VETO_LOG_INTERVAL_SEC", 5.0)

    mono = {"t": 1000.0}
    monkeypatch.setattr(aes.time, "monotonic", lambda: mono["t"])

    kwargs = dict(
        now_ts=100.0,
        need_s=6,
        reason="adverse_delta_15s_yes",
        strike_key="99019-81214",
        side_key="yes",
        log_tag="[AUTO ENTRY EXPIRATION SCALP]",
        extra="delta_15s=-0.01",
    )
    key = ("99019-81214", "yes")
    aes._exp_scalp_verify_abort({}, key, **kwargs)
    mono["t"] = 1002.0
    aes._exp_scalp_verify_abort({}, key, **kwargs)  # within 5s — suppressed
    mono["t"] = 1006.0
    aes._exp_scalp_verify_abort({}, key, **kwargs)  # past interval — logs again

    assert len(lines) == 2
    assert all("phase=pre_dwell" in line for line in lines)
