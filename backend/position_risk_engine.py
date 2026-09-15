"""
position_risk_engine — HWS Scalp LVWAP stop decision sidecar.

SAFETY:
  - Never places/cancels orders; never calls the Kalshi order executor
  - Never imports trade_manager / trade_executor
  - active_trade_supervisor remains sole stop authority
  - Runs locally and on production; enrolls High Water Scalp only
"""

from __future__ import annotations

import os
import sys

# Supervisord may launch without PYTHONPATH; mirror other backend entrypoints.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import json
import logging
import signal
import threading
import time
from typing import Any, Dict, Optional

from backend.core.position_risk.audit import PositionRiskAudit
from backend.core.position_risk.book_health import (
    BookHealthState,
    book_usable_for_shadow_features,
    evaluate_book_health,
)
from backend.core.position_risk.enroll import EnrolledPosition, fetch_open_hws_positions
from backend.core.position_risk.features import compute_shadow_features
from backend.core.position_risk.lease import LeaseRegistry, ProtectionState
from backend.core.position_risk.metrics import LatencyTracker
from backend.core.position_risk.policy_hws_lvw_v1 import HwsLvwV1Actor
from backend.core.position_risk.safety import assert_safe_to_run_observe
from backend.core.position_risk.watchdog import ProtectionWatchdog

logger = logging.getLogger("position_risk_engine")

_STOP = threading.Event()


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [position_risk_engine] %(message)s",
    )


def _resolve_floor(pos: EnrolledPosition) -> Optional[float]:
    from backend.core.high_water_scalp import is_high_water_test_1, resolve_owned_stop_floor

    if is_high_water_test_1(pos.trade_strategy):
        return resolve_owned_stop_floor(
            pos.trade_strategy,
            pos.buy_price,
            pos.stop_loss_price,
            pos.stop_loss_offset,
        )
    return resolve_owned_stop_floor(
        pos.trade_strategy,
        pos.buy_price,
        pos.stop_loss_price,
        pos.stop_loss_offset,
    )


class ObserveEngine:
    def __init__(self) -> None:
        self.leases = LeaseRegistry()
        self.watchdog = ProtectionWatchdog(self.leases)
        self.metrics = LatencyTracker()
        self.audit = PositionRiskAudit()
        self._actors: Dict[str, HwsLvwV1Actor] = {}
        self._last_features: Dict[str, dict] = {}
        self._last_health: Dict[str, dict] = {}
        self._last_decisions: Dict[str, dict] = {}
        self._seq_by_ticker: Dict[str, int] = {}
        self._prev_best: Dict[str, float] = {}
        self._prev_ts: Dict[str, int] = {}
        self._prev_depth: Dict[str, float] = {}
        self._status_path = os.getenv(
            "REC_POSITION_RISK_STATUS_PATH",
            "backend/data/position_risk/status.json",
        )
        self._lock = threading.RLock()

    def _db_conn(self):
        from backend.core.config.database import get_system_postgresql_connection

        return get_system_postgresql_connection()

    def _actor_for(self, pos: EnrolledPosition) -> HwsLvwV1Actor:
        key = pos.key()
        actor = self._actors.get(key)
        if actor is None:
            actor = HwsLvwV1Actor()
            actor.reset_for_position_generation(pos.remaining_position_generation)
            self._actors[key] = actor
            self.audit.append(
                "enrollment",
                {
                    **pos.to_dict(),
                    "policy_version": pos.position_risk_policy,
                },
                trade_id=pos.trade_id,
                tenant_slot=pos.tenant_slot,
            )
        return actor

    def reconcile_once(self) -> list[EnrolledPosition]:
        t0 = time.perf_counter()
        conn = self._db_conn()
        try:
            positions = fetch_open_hws_positions(conn)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        self.leases.reconcile(positions)
        wanted = {p.key() for p in positions}
        for key in list(self._actors.keys()):
            if key not in wanted:
                del self._actors[key]
        self.metrics.record("enroll_reconcile_ms", (time.perf_counter() - t0) * 1000.0)
        for pos in positions:
            lease = self.leases.get(pos.key())
            if lease and lease.state == ProtectionState.ENROLLING:
                lease.heartbeat(reason="enrolled")
                if lease.enroll_latency_ms is not None:
                    self.metrics.record("tm_open_to_protected_ms", lease.enroll_latency_ms)
                self.audit.append(
                    "lease_state",
                    {"key": pos.key(), "state": lease.state.value, "reason": lease.reason},
                    trade_id=pos.trade_id,
                    tenant_slot=pos.tenant_slot,
                )
        return positions

    def _load_book(self, ticker: str):
        from backend.core.orderbook_hot_subscriber import load_orderbook_cache_snapshot

        t0 = time.perf_counter()
        try:
            snap = load_orderbook_cache_snapshot(ticker)
            self.watchdog.note_redis(True)
        except Exception as e:
            self.watchdog.note_redis(False, str(e))
            self.metrics.record("book_load_ms", (time.perf_counter() - t0) * 1000.0)
            return None
        self.metrics.record("book_load_ms", (time.perf_counter() - t0) * 1000.0)
        return snap

    def evaluate_position(self, pos: EnrolledPosition) -> None:
        lease = self.leases.get(pos.key())
        if not lease:
            return
        recv_ms = int(time.time() * 1000)
        snap = self._load_book(pos.ticker)
        last_seq = self._seq_by_ticker.get(pos.ticker)
        actor = self._actor_for(pos)

        if snap is None:
            health = evaluate_book_health(
                snapshot_valid=None,
                seq=None,
                last_seq=last_seq,
                ts_ms=None,
                redis_written_ms=None,
                received_ms=recv_ms,
                ws_transport_ok=None,
            )
            lease.mark_degraded(health.reason)
            self._last_health[pos.key()] = health.to_dict()
            lease.heartbeat(reason=health.reason)
            decision = actor.evaluate(
                trade_id=pos.trade_id,
                tenant_slot=pos.tenant_slot,
                ticker=pos.ticker,
                side=pos.side,
                remaining=pos.remaining,
                remaining_position_generation=pos.remaining_position_generation,
                yes={},
                no={},
                floor=_resolve_floor(pos),
                book_seq=None,
                book_gen=None,
                book_valid=False,
                data_health_reason=health.reason,
                tape_state=health.tape.value,
                book_only_enabled=pos.position_risk_book_only_enabled,
                mode=pos.position_risk_mode,
                ts_event_ms=None,
                ts_recv_ms=recv_ms,
            )
            self._record_decision(pos, decision)
            return

        health = evaluate_book_health(
            snapshot_valid=True,
            seq=snap.seq,
            last_seq=last_seq,
            ts_ms=snap.ts_ms,
            redis_written_ms=snap.redis_written_ms,
            received_ms=recv_ms,
            ws_transport_ok=True,
            # Poll latest hot OB: forward seq jumps are normal, not RESYNCING.
            expect_seq_monotonic=False,
        )
        if snap.seq is not None:
            self._seq_by_ticker[pos.ticker] = int(snap.seq)
        self._last_health[pos.key()] = health.to_dict()

        if health.state == BookHealthState.RESYNCING:
            lease.mark_resyncing(health.reason)
            lease.heartbeat(reason=health.reason)
            decision = actor.evaluate(
                trade_id=pos.trade_id,
                tenant_slot=pos.tenant_slot,
                ticker=pos.ticker,
                side=pos.side,
                remaining=pos.remaining,
                remaining_position_generation=pos.remaining_position_generation,
                yes=snap.yes,
                no=snap.no,
                floor=_resolve_floor(pos),
                book_seq=snap.seq,
                book_gen=snap.seq,
                book_valid=False,
                data_health_reason=health.reason,
                tape_state=health.tape.value,
                book_only_enabled=pos.position_risk_book_only_enabled,
                mode=pos.position_risk_mode,
                ts_event_ms=snap.ts_ms,
                ts_recv_ms=recv_ms,
            )
            self._record_decision(pos, decision)
            return
        if not book_usable_for_shadow_features(health):
            lease.mark_degraded(health.reason)
            lease.heartbeat(reason=health.reason)
            decision = actor.evaluate(
                trade_id=pos.trade_id,
                tenant_slot=pos.tenant_slot,
                ticker=pos.ticker,
                side=pos.side,
                remaining=pos.remaining,
                remaining_position_generation=pos.remaining_position_generation,
                yes=snap.yes,
                no=snap.no,
                floor=_resolve_floor(pos),
                book_seq=snap.seq,
                book_gen=snap.seq,
                book_valid=False,
                data_health_reason=health.reason,
                tape_state=health.tape.value,
                book_only_enabled=pos.position_risk_book_only_enabled,
                mode=pos.position_risk_mode,
                ts_event_ms=snap.ts_ms,
                ts_recv_ms=recv_ms,
            )
            self._record_decision(pos, decision)
            return

        if snap.apply_to_receive_ms is not None:
            self.metrics.record("receive_lag_ms", float(snap.apply_to_receive_ms))
        if snap.apply_to_hot_ms is not None:
            self.metrics.record("apply_to_hot_ms", float(snap.apply_to_hot_ms))

        floor = _resolve_floor(pos)
        t_eval = time.perf_counter()
        feat = compute_shadow_features(
            ticker=pos.ticker,
            side=pos.side,
            size=pos.remaining,
            yes=snap.yes,
            no=snap.no,
            floor_owned=floor,
            seq=snap.seq,
            ts_ms=snap.ts_ms,
            prev_best=self._prev_best.get(pos.key()),
            prev_ts_ms=self._prev_ts.get(pos.key()),
            prev_depth_above_floor=self._prev_depth.get(pos.key()),
        )
        self.metrics.record("evaluate_ms", (time.perf_counter() - t_eval) * 1000.0)
        self.metrics.record("feature_eval_ms", feat.eval_mono_ms)

        decision = actor.evaluate(
            trade_id=pos.trade_id,
            tenant_slot=pos.tenant_slot,
            ticker=pos.ticker,
            side=pos.side,
            remaining=pos.remaining,
            remaining_position_generation=pos.remaining_position_generation,
            yes=snap.yes,
            no=snap.no,
            floor=floor,
            book_seq=snap.seq,
            book_gen=snap.seq,
            book_valid=True,
            data_health_reason=health.reason,
            tape_state=health.tape.value,
            book_only_enabled=pos.position_risk_book_only_enabled,
            mode=pos.position_risk_mode,
            ts_event_ms=snap.ts_ms,
            ts_recv_ms=recv_ms,
        )
        self._record_decision(pos, decision)

        with self._lock:
            self._last_features[pos.key()] = feat.to_dict()
            if feat.best_executable is not None:
                self._prev_best[pos.key()] = feat.best_executable
            if feat.ts_ms is not None:
                self._prev_ts[pos.key()] = feat.ts_ms
            if feat.depth_above_floor is not None:
                self._prev_depth[pos.key()] = feat.depth_above_floor

        lease.last_feature_mono = time.monotonic()
        lease.last_seq = snap.seq
        lease.heartbeat(reason="ok")
        self.metrics.record("publish_shadow_ms", 0.1)

    def _record_decision(self, pos: EnrolledPosition, decision: Dict[str, Any]) -> None:
        with self._lock:
            prev = self._last_decisions.get(pos.key())
            self._last_decisions[pos.key()] = decision
        # Persist material transitions and all actionable emits.
        material = False
        if prev is None:
            material = True
        elif prev.get("decision_kind") != decision.get("decision_kind"):
            material = True
        elif prev.get("dedupe_key") != decision.get("dedupe_key"):
            material = True
        elif decision.get("actionable"):
            material = True
        if not material:
            return
        event_type = "decision_emit" if decision.get("actionable") else "pre_evaluation"
        self.audit.append(
            event_type,
            {
                "decision": decision,
                "actionable": bool(decision.get("actionable")),
                "shadow_only": bool(decision.get("shadow_only")),
                "dedupe_key": decision.get("dedupe_key"),
                "ticker": pos.ticker,
                "mode": pos.position_risk_mode,
                "policy": pos.position_risk_policy,
            },
            trade_id=pos.trade_id,
            tenant_slot=pos.tenant_slot,
        )

    def write_status(self, positions: list[EnrolledPosition], alarms: list) -> None:
        path = self._status_path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload: Dict[str, Any] = {
            "ts": time.time(),
            "mode": "observe",
            "stage": 2,
            "authority": "none — active_trade_supervisor sole stop authority",
            "positions": [],
            "leases": self.leases.snapshot(),
            "alarms": [
                {"severity": a.severity, "code": a.code, "message": a.message, "key": a.key}
                for a in alarms
            ],
            "latency": self.metrics.summary(),
        }
        for pos in positions:
            payload["positions"].append(
                {
                    **pos.to_dict(),
                    "lease": next(
                        (x for x in payload["leases"] if x["key"] == pos.key()),
                        None,
                    ),
                    "health": self._last_health.get(pos.key()),
                    "features": self._last_features.get(pos.key()),
                    "decision": self._last_decisions.get(pos.key()),
                }
            )
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        os.replace(tmp, path)

    def loop(self, *, reconcile_sec: float = 2.0, eval_sec: float = 0.25) -> None:
        logger.info("observe loop start reconcile=%ss eval=%ss", reconcile_sec, eval_sec)
        last_recon = 0.0
        positions: list[EnrolledPosition] = []
        while not _STOP.is_set():
            now = time.monotonic()
            if now - last_recon >= reconcile_sec:
                try:
                    positions = self.reconcile_once()
                except Exception:
                    logger.exception("reconcile failed")
                    positions = []
                last_recon = now
            for pos in positions:
                try:
                    self.evaluate_position(pos)
                except Exception:
                    logger.exception("eval failed %s", pos.key())
            alarms = self.watchdog.evaluate(positions)
            try:
                self.write_status(positions, alarms)
            except Exception:
                logger.exception("status write failed")
            _STOP.wait(eval_sec)
        logger.info("observe loop stopped")


def main(argv: Optional[list[str]] = None) -> int:
    _setup_logging()
    ok, reason = assert_safe_to_run_observe()
    if not ok:
        logger.error("refusing to start: %s", reason)
        return 2

    def _sig(*_a):
        _STOP.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    logger.info(
        "STARTING position_risk_engine Stage2 OBSERVE+POLICY "
        "(no orders, no money authority, ATS remains stop authority)"
    )
    engine = ObserveEngine()
    engine.loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
