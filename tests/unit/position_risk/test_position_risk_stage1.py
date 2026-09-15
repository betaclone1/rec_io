"""Unit tests for Stage 1 position_risk observe library."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.position_risk.book_health import BookHealthState, evaluate_book_health
from backend.core.position_risk.enroll import EnrolledPosition
from backend.core.position_risk.features import compute_shadow_features
from backend.core.position_risk.lease import LeaseRegistry, ProtectionState
from backend.core.position_risk.persistence_grid import first_breach_times
from backend.core.position_risk.replay import replay_frames
from backend.core.position_risk.safety import assert_safe_to_run_observe
from backend.core.position_risk.synthetic_scenarios import (
    flash_collapse_reference_v1,
    gradual_collapse_reference_v1,
)
from backend.core.position_risk.watchdog import ProtectionWatchdog

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "position_risk"


def test_safety_local_ok_without_enable(monkeypatch):
    monkeypatch.delenv("REC_ENABLE_POSITION_RISK_ENGINE", raising=False)
    monkeypatch.delenv("REC_IS_PRODUCTION", raising=False)
    monkeypatch.delenv("REC_PROD_SSH_HOST", raising=False)
    monkeypatch.delenv("REC_PROD_DB_HOST", raising=False)
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("REC_DB_HOST", "localhost")
    ok, reason = assert_safe_to_run_observe()
    assert ok, reason


def test_safety_prod_allowed(monkeypatch):
    """PRE may start on production hosts (HWS Scalp VWAP)."""
    cases = [
        {"REC_IS_PRODUCTION": "1"},
        {"REC_PROJECT_ROOT": "/opt/rec_io_server"},
        {"DB_HOST": "165.22.13.146"},
    ]
    for case in cases:
        for k in (
            "REC_IS_PRODUCTION",
            "REC_PROJECT_ROOT",
            "DB_HOST",
            "REC_DB_HOST",
            "REC_PROD_DB_HOST",
            "REC_PROD_SSH_HOST",
        ):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("DB_HOST", "localhost")
        for k, v in case.items():
            monkeypatch.setenv(k, v)
        ok, reason = assert_safe_to_run_observe()
        assert ok, f"expected ok for {case}, got {reason}"


def test_safety_prod_cwd_mocked(monkeypatch, tmp_path):
    from backend.core.position_risk import safety as safety_mod

    monkeypatch.delenv("REC_IS_PRODUCTION", raising=False)
    monkeypatch.delenv("REC_PROJECT_ROOT", raising=False)
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setattr(safety_mod.os, "getcwd", lambda: "/opt/rec_io_server")
    ok, reason = assert_safe_to_run_observe()
    assert ok, reason


def test_safety_observe_ok(monkeypatch):
    monkeypatch.setenv("REC_ENABLE_POSITION_RISK_ENGINE", "1")
    monkeypatch.setenv("REC_POSITION_RISK_MODE", "observe")
    monkeypatch.delenv("REC_IS_PRODUCTION", raising=False)
    monkeypatch.delenv("REC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("REC_PROD_SSH_HOST", raising=False)
    monkeypatch.delenv("REC_PROD_DB_HOST", raising=False)
    monkeypatch.delenv("REC_POSITION_RISK_ALLOW_ON_PRODUCTION", raising=False)
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("REC_DB_HOST", "localhost")
    ok, reason = assert_safe_to_run_observe()
    assert ok, reason


def test_no_allow_prod_constant_or_bypass():
    import backend.core.position_risk as pr
    import backend.core.position_risk.safety as safety_mod

    assert not hasattr(pr, "ENV_ALLOW_PROD")
    assert not hasattr(pr, "OBSOLETE_ALLOW_PROD_ENV")
    for mod in (pr, safety_mod):
        src = Path(mod.__file__).read_text()
        assert "ENV_ALLOW_PROD" not in src
        assert "ALLOW_ON_PRODUCTION" not in src
    # PRE is intentionally allowed on production for HWS Scalp VWAP.
    ok, _ = assert_safe_to_run_observe()
    assert ok


def test_quiet_book_not_stale_when_transport_ok():
    h = evaluate_book_health(
        snapshot_valid=True,
        seq=10,
        last_seq=10,
        ts_ms=1_000,
        redis_written_ms=1_001,
        received_ms=1_000 + 10_000,
        ws_transport_ok=True,
        max_apply_age_ms=5000,
    )
    assert h.state == BookHealthState.QUIET_HEALTHY


def test_stale_when_transport_bad():
    h = evaluate_book_health(
        snapshot_valid=True,
        seq=10,
        last_seq=10,
        ts_ms=1_000,
        redis_written_ms=1_001,
        received_ms=1_000 + 10_000,
        ws_transport_ok=False,
        max_apply_age_ms=5000,
    )
    assert h.state == BookHealthState.STALE


def test_seq_gap_resync():
    h = evaluate_book_health(
        snapshot_valid=True,
        seq=20,
        last_seq=10,
        ts_ms=1_000,
        redis_written_ms=1_001,
        received_ms=1_002,
        ws_transport_ok=True,
    )
    assert h.state == BookHealthState.RESYNCING
    assert h.gap is True


def test_tape_unknown_on_features():
    feat = compute_shadow_features(
        ticker="T",
        side="N",
        size=10,
        yes={},
        no={"0.95": "100"},
        floor_owned=0.9,
        seq=1,
        ts_ms=0,
    )
    assert feat.tape_state == "UNKNOWN"
    assert feat.liquidation_vwap == pytest.approx(0.95)
    assert feat.fill_coverage == pytest.approx(1.0)


def test_gradual_synthetic_breach_times():
    frames = gradual_collapse_reference_v1()
    result = replay_frames(frames, ticker="gradual_collapse_reference_v1")
    series = [(x["t_ms"], x["liquidation_vwap"]) for x in result["vwap_series"]]
    b95 = first_breach_times(series, threshold=0.95)
    b90 = first_breach_times(series, threshold=0.90)
    b88 = first_breach_times(series, threshold=0.88)
    assert b95 is not None and b95.t_ms == 7600
    assert b90 is not None and b90.t_ms == 13500
    assert b88 is not None and b88.t_ms == 20200
    assert result["tape_state"] == "UNKNOWN"
    assert "59597" not in json.dumps(result)


def test_flash_synthetic_timeline():
    frames = flash_collapse_reference_v1()
    result = replay_frames(frames, ticker="flash_collapse_reference_v1")
    series = result["vwap_series"]
    assert series[0]["liquidation_vwap"] == pytest.approx(0.98)
    assert series[1]["liquidation_vwap"] == pytest.approx(0.917)
    assert series[2]["liquidation_vwap"] == pytest.approx(0.793)
    assert series[3]["liquidation_vwap"] == pytest.approx(0.681)
    assert series[2]["t_ms"] == 25
    assert series[3]["t_ms"] == 50


def test_persistence_grid_analysis_only():
    frames = gradual_collapse_reference_v1()
    result = replay_frames(frames)
    grid = result["persistence_grid"]
    assert any(g["kind"] == "persistence_candidate" and g["persist_ms"] == 250 for g in grid)


def test_lease_re_enrollment():
    reg = LeaseRegistry()
    p1 = EnrolledPosition(
        tenant_slot="0001",
        trade_id=1,
        status="open",
        ticker="KXBTC15M-X",
        side="Y",
        trade_strategy="High Water Scalp",
        position=10,
        close_filled_count=0,
        remaining=10,
        buy_price=0.98,
        stop_loss_offset=None,
        limit_close_price=0.99,
        paper_trade=False,
        market="15m",
    )
    reg.reconcile([p1])
    lease = reg.get("0001:1")
    assert lease is not None
    assert lease.state == ProtectionState.ENROLLING
    lease.heartbeat()
    assert lease.state == ProtectionState.PROTECTED
    reg.reconcile([p1])
    assert reg.get("0001:1") is not None
    reg.reconcile([])
    assert reg.get("0001:1") is None


def test_watchdog_uncovered_and_stall():
    reg = LeaseRegistry()
    wd = ProtectionWatchdog(
        reg, heartbeat_stall_ms=1, critical_stall_ms=2, uncovered_critical_ms=0
    )
    pos = EnrolledPosition(
        tenant_slot="0001",
        trade_id=9,
        status="open",
        ticker="T",
        side="N",
        trade_strategy="High Water Scalp",
        position=1,
        close_filled_count=0,
        remaining=1,
        buy_price=0.9,
        stop_loss_offset=None,
        limit_close_price=0.99,
        paper_trade=True,
        market="15m",
    )
    alarms = wd.evaluate([pos])
    assert any(a.code == "uncovered_open_hws" for a in alarms)


def test_manifest_provenance_not_synthetic_named_as_trade_ids(tmp_path, monkeypatch):
    """Must not rewrite checked-in fixtures; use tmp_path for synthetic writes."""
    from backend.core.position_risk import fixture_manifest as fm
    from backend.core.position_risk.synthetic_scenarios import write_synthetic_fixtures

    syn_dir = tmp_path / "synthetic"
    write_synthetic_fixtures(syn_dir)
    assert (syn_dir / "gradual_collapse_reference_v1.json").is_file()
    assert (syn_dir / "flash_collapse_reference_v1.json").is_file()

    # Read-only build against repo historical CSV (no write to FIXTURE_ROOT)
    man = fm.build_manifest()
    assert man["safety"]["no_exit_intent"] is True
    syn = man["synthetic_scenarios"]
    assert "gradual_collapse_reference_v1" in syn
    assert "NOT trade 59597" in syn["gradual_collapse_reference_v1"]["note"]
    hist = {h["trade_id"]: h for h in man["historical"]}
    assert 59597 in hist
    assert "synthetic" not in (hist[59597].get("l2_package_path") or "")
    if hist[59597].get("l2_package_path"):
        assert hist[59597]["status"] in ("RESOLVED_L2", "SUPPLEMENTAL")
        assert hist[59597]["l2_package_sha256"]
    assert hist[59597]["ticker"] == "KXBTC15M-26SEP070230-30" or hist[59597][
        "status"
    ] == "UNRESOLVED"

    # Optional: write manifest into tmp only
    out = tmp_path / "manifest.json"
    out.write_text(__import__("json").dumps(man, indent=2))
    assert out.is_file()


def test_lease_protected_degraded_stalled_recovered():
    """Fake open position: PROTECTED → degraded → stall alarm → recovered."""
    import time

    reg = LeaseRegistry()
    wd = ProtectionWatchdog(
        reg, heartbeat_stall_ms=50, critical_stall_ms=80, uncovered_critical_ms=1000
    )
    pos = EnrolledPosition(
        tenant_slot="0001",
        trade_id=42,
        status="open",
        ticker="KXBTC15M-FAKE",
        side="N",
        trade_strategy="High Water Scalp",
        position=10,
        close_filled_count=0,
        remaining=10,
        buy_price=0.98,
        stop_loss_offset=None,
        limit_close_price=0.99,
        paper_trade=True,
        market="15m",
    )
    reg.reconcile([pos])
    lease = reg.get("0001:42")
    assert lease is not None
    lease.heartbeat(reason="ok")
    assert lease.state == ProtectionState.PROTECTED

    lease.mark_degraded("seq_gap")
    assert lease.state == ProtectionState.DEGRADED
    alarms = wd.evaluate([pos])
    assert any(a.code == "lease_degraded" for a in alarms)

    # Force stall by backdating heartbeat
    lease.last_heartbeat_mono = time.monotonic() - 1.0
    alarms = wd.evaluate([pos])
    assert any(a.code == "actor_stall" and a.severity == "critical" for a in alarms)

    lease.heartbeat(reason="ok")
    assert lease.state == ProtectionState.PROTECTED
    alarms = wd.evaluate([pos])
    assert not any(a.code == "actor_stall" for a in alarms)
    assert not any(a.code == "lease_degraded" for a in alarms)


def test_engine_source_has_no_executor_path():
    import backend.position_risk_engine as eng

    src = Path(eng.__file__).read_text()
    assert "cancel_order" not in src
    assert "/trades" not in src
    assert "publish_trade_manager_command" not in src
    assert "EXIT_INTENT" not in src
    assert "trigger_auto_stop" not in src


def test_close_method_pre_hws_triggers():
    """ATS maps PRE trigger reasons to distinct close_method values (source check;
    importing active_trade_supervisor requires a monitor worker context)."""
    src = (
        Path(__file__).resolve().parents[3]
        / "backend"
        / "active_trade_supervisor.py"
    ).read_text(encoding="utf-8")
    assert '"pre_hws_catastrophic": "auto_pre_hws_catastrophic"' in src
    assert '"pre_hws_marginal": "auto_pre_hws_marginal"' in src
    assert "consider_hws_pre_decision" in src
