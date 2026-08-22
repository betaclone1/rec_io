"""
Latest-only mailbox lanes for tradeflow (AES/ATS).

A lane holds at most the latest captured snap for one (symbol, market).
A newer publish replaces the mailbox and cancels in-flight *evaluation*
(not tickets already decided for handoff to TM). The anti-staleness rule is
"do not queue a backlog of snapshots" — once AES/ATS decides to fire on the
snap it evaluated, it should hand that ticket to TM; TM/TE own downstream checks.
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

LadderKey = Tuple[str, str]


def snap_generation_id(snap: Optional[Dict[str, Any]]) -> str:
    """
    Decision identity for latest-only cancel/mailbox.

    Prefer a decision-relevant fingerprint over raw publisher ``generation_id`` when
    the publisher id advances on every orderbook flicker (too fine for AES/ATS gates).
    Publisher id is used only when ``TRADEFLOW_LANE_USE_PUBLISHER_GEN=1``.
    """
    if not snap or not isinstance(snap, dict):
        return ""
    use_pub = os.getenv("TRADEFLOW_LANE_USE_PUBLISHER_GEN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if use_pub:
        gid = snap.get("generation_id")
        if gid is not None and str(gid).strip():
            return str(gid).strip()
    return decision_generation_id(snap)


def _ttc_bucket(ttc_raw: Any) -> Any:
    """
    Bucket TTC so countdown ticks alone do not thrash the mailbox.

    Ask/cent changes still advance the gen. Default bucket is 1s
    (``TRADEFLOW_LANE_TTC_BUCKET_SEC``); raise to 5+ only to reduce cancel thrash.
    """
    try:
        ttc_i = int(float(ttc_raw))
    except (TypeError, ValueError):
        return ttc_raw
    try:
        bucket = int(os.getenv("TRADEFLOW_LANE_TTC_BUCKET_SEC", "1"))
    except (TypeError, ValueError):
        bucket = 1
    if bucket <= 1:
        return ttc_i
    return (ttc_i // bucket) * bucket


def decision_generation_id(snap: Dict[str, Any]) -> str:
    """
    Coarser gen: event + bucketed TTC + asks rounded to 1¢ for first N strikes.

    Ask flicker below 1¢ within the same TTC bucket does not cancel in-flight eval.

    Exp Scalp 1 Hz snapshots (``rec_snapshot_eval``) use wall-clock second only so
    in-second book flicker does not cancel or skip the snapshot that was published.
    """
    if snap.get("rec_snapshot_eval"):
        try:
            return f"snap:{int(snap.get('wall_second'))}"
        except (TypeError, ValueError):
            pass
    strikes = snap.get("strikes") or []
    if not isinstance(strikes, list):
        strikes = []
    ttc_raw = snap.get("ttc")
    if ttc_raw is None:
        ttc_raw = snap.get("ttc_seconds")
    ttc_i = _ttc_bucket(ttc_raw) if ttc_raw is not None else None
    parts = [
        str(snap.get("event_ticker") or ""),
        str(ttc_i if ttc_i is not None else ""),
    ]
    n_strike = 12
    try:
        n_strike = max(4, min(int(os.getenv("TRADEFLOW_LANE_DECISION_STRIKES", "12")), 32))
    except (TypeError, ValueError):
        n_strike = 12
    for row in strikes[:n_strike]:
        if not isinstance(row, dict):
            continue
        parts.append(
            f"{row.get('ticker')}|{_ask_cent(row.get('yes_ask_dollars'))}|{_ask_cent(row.get('no_ask_dollars'))}"
        )
    return "d:" + "|".join(parts)


def _ask_cent(raw: Any) -> str:
    try:
        return f"{round(float(raw), 2):.2f}"
    except (TypeError, ValueError):
        return ""


@dataclass
class LaneSnapshot:
    symbol: str
    market: str
    generation_id: str
    snap: Dict[str, Any]
    epoch: int
    captured_mono: float


def _reeval_sec() -> float:
    """Min quiet time after an eval before same-gen mailboxes schedule again."""
    try:
        return max(0.2, min(float(os.getenv("TRADEFLOW_LANE_REEVAL_SEC", "1")), 30.0))
    except (TypeError, ValueError):
        return 1.0


class LatestOnlyLadderLane:
    """One mailbox + cancel epoch for a single (symbol, market)."""

    def __init__(self, symbol: str, market: str) -> None:
        self.symbol = (symbol or "").strip().upper()
        self.market = (market or "").strip().lower()
        self._lock = threading.Lock()
        self._mailbox: Optional[LaneSnapshot] = None
        self._epoch = 0
        self._eval_lock = threading.Lock()
        self._last_eval_end_mono: float = 0.0

    @property
    def key(self) -> LadderKey:
        return (self.symbol, self.market)

    def publish(self, snap: Optional[Dict[str, Any]]) -> Optional[LaneSnapshot]:
        """
        Replace mailbox with latest snap when decision gen advances.

        Same decision generation_id: keep epoch (do not cancel in-flight eval) and
        refresh snap payload. Returns None (caller may still schedule a re-eval via
        ``should_reeval`` so quiet/same-gen stretches cannot skip entry windows).
        """
        if not snap or not isinstance(snap, dict):
            return None
        gid = snap_generation_id(snap)
        if not gid:
            gid = f"anon:{uuid.uuid4().hex[:12]}"
        with self._lock:
            if (
                self._mailbox is not None
                and self._mailbox.generation_id == gid
            ):
                # Refresh frozen payload for next eval; do not cancel current.
                self._mailbox = LaneSnapshot(
                    symbol=self.symbol,
                    market=self.market,
                    generation_id=gid,
                    snap=copy.deepcopy(snap),
                    epoch=self._mailbox.epoch,
                    captured_mono=time.monotonic(),
                )
                return None
            self._epoch += 1
            slot = LaneSnapshot(
                symbol=self.symbol,
                market=self.market,
                generation_id=gid,
                snap=copy.deepcopy(snap),
                epoch=self._epoch,
                captured_mono=time.monotonic(),
            )
            self._mailbox = slot
            return slot

    def current(self) -> Optional[LaneSnapshot]:
        with self._lock:
            return self._mailbox

    def is_current(self, epoch: int, generation_id: str) -> bool:
        with self._lock:
            if self._mailbox is None:
                return False
            return (
                self._mailbox.epoch == epoch
                and self._mailbox.generation_id == generation_id
            )

    def should_reeval(self) -> bool:
        """True when mailbox has work and no eval has run recently (same-gen wakeups)."""
        if self._mailbox is None:
            return False
        if self._eval_lock.locked():
            return False
        return (time.monotonic() - self._last_eval_end_mono) >= _reeval_sec()

    def try_begin_eval(self) -> Optional[LaneSnapshot]:
        """
        Non-blocking: if another eval holds the lane, skip (latest stays in mailbox).
        Caller should re-check after in-flight eval finishes if mailbox advanced.
        """
        if not self._eval_lock.acquire(blocking=False):
            return None
        slot = self.current()
        if slot is None:
            self._eval_lock.release()
            return None
        return slot

    def end_eval(self) -> Optional[LaneSnapshot]:
        """Release eval lock; return mailbox if a newer gen arrived during eval."""
        try:
            return self.current()
        finally:
            self._last_eval_end_mono = time.monotonic()
            try:
                self._eval_lock.release()
            except RuntimeError:
                pass


EvalFn = Callable[[LaneSnapshot, "LatestOnlyLadderLane"], None]


class LatestOnlyLaneHub:
    """Independent latest-only lanes; parallel monitor work inside each eval."""

    def __init__(
        self,
        *,
        service: str,
        fetch_snap: Callable[[str, str], Optional[Dict[str, Any]]],
        evaluate_lane: EvalFn,
        ladder_keys: Callable[[], Sequence[LadderKey]],
        parallelism: int = 32,
    ) -> None:
        self.service = service
        self._fetch_snap = fetch_snap
        self._evaluate_lane = evaluate_lane
        self._ladder_keys = ladder_keys
        self.parallelism = max(1, min(int(parallelism), 64))
        self._lanes: Dict[LadderKey, LatestOnlyLadderLane] = {}
        self._lanes_lock = threading.Lock()
        self._wake = threading.Event()

    def lane(self, symbol: str, market: str) -> LatestOnlyLadderLane:
        key = ((symbol or "").strip().upper(), (market or "").strip().lower())
        with self._lanes_lock:
            lane = self._lanes.get(key)
            if lane is None:
                lane = LatestOnlyLadderLane(key[0], key[1])
                self._lanes[key] = lane
            return lane

    def ensure_lanes(self) -> None:
        for sym, mkt in self._ladder_keys():
            self.lane(sym, mkt)

    def evaluate_latest_blocking(
        self,
        symbol: str,
        market: str,
        snap: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Publish ``snap`` (or fetch) and evaluate on the caller thread.

        Returns elapsed seconds. ``-1.0`` means no snap. ``0.0`` means same
        generation as the last eval (duplicate snapshot second) and no work.
        """
        sym = (symbol or "").strip().upper()
        mkt = (market or "").strip().lower()
        if mkt not in ("hourly", "15m") or not sym:
            return -1.0
        payload = snap if snap is not None else self._fetch_snap(sym, mkt)
        if not payload:
            return -1.0
        lane = self.lane(sym, mkt)
        slot = lane.publish(payload)
        if slot is None:
            return 0.0
        t0 = time.perf_counter()
        self._eval_worker(lane)
        return time.perf_counter() - t0

    def on_ladder_notify(self, symbol: str, market: str) -> None:
        """Fetch latest, publish to mailbox, schedule eval (or same-gen re-eval)."""
        sym = (symbol or "").strip().upper()
        mkt = (market or "").strip().lower()
        if mkt not in ("hourly", "15m") or not sym:
            return
        snap = self._fetch_snap(sym, mkt)
        lane = self.lane(sym, mkt)
        slot = lane.publish(snap)
        if slot is not None:
            self._trace(
                "lane_mailbox",
                symbol=sym,
                market=mkt,
                generation_id=slot.generation_id,
                epoch=slot.epoch,
            )
            self._schedule_eval(lane)
            return
        # Same decision gen: still re-run on an interval so quiet books / frozen
        # fingerprints cannot skip Exp Scalp TTC entry windows.
        if lane.should_reeval():
            cur = lane.current()
            if cur is None:
                return
            self._trace(
                "lane_reeval",
                symbol=sym,
                market=mkt,
                generation_id=cur.generation_id,
                epoch=cur.epoch,
            )
            self._schedule_eval(lane)

    def failsafe_refresh_all(self) -> None:
        for sym, mkt in self._ladder_keys():
            self.on_ladder_notify(sym, mkt)

    def _schedule_eval(self, lane: LatestOnlyLadderLane) -> None:
        t = threading.Thread(
            target=self._eval_worker,
            args=(lane,),
            name=f"{self.service}_lane_{lane.symbol}_{lane.market}",
            daemon=True,
        )
        t.start()

    def _eval_worker(self, lane: LatestOnlyLadderLane) -> None:
        while True:
            slot = lane.try_begin_eval()
            if slot is None:
                return
            t0 = time.perf_counter()
            self._trace(
                "lane_eval_begin",
                symbol=slot.symbol,
                market=slot.market,
                generation_id=slot.generation_id,
                epoch=slot.epoch,
            )
            try:
                self._evaluate_lane(slot, lane)
            except Exception as exc:
                logger.exception(
                    "[%s] lane eval failed %s/%s gen=%s: %s",
                    self.service,
                    slot.symbol,
                    slot.market,
                    slot.generation_id,
                    exc,
                )
            finally:
                after = lane.end_eval()
                self._trace(
                    "lane_eval_end",
                    symbol=slot.symbol,
                    market=slot.market,
                    generation_id=slot.generation_id,
                    epoch=slot.epoch,
                    elapsed_s=round(time.perf_counter() - t0, 4),
                    still_current=1
                    if after and after.epoch == slot.epoch
                    else 0,
                )
            # If mailbox advanced during eval, loop to process latest.
            cur = lane.current()
            if cur is None or cur.epoch == slot.epoch:
                return

    def run_bindings_parallel(
        self,
        *,
        lane: LatestOnlyLadderLane,
        slot: LaneSnapshot,
        bindings: Sequence[Tuple[str, str]],
        worker: Callable[[str, str, LaneSnapshot, LatestOnlyLadderLane], None],
    ) -> None:
        """Run bind workers in parallel; each should check lane.is_current before fire."""
        if not bindings:
            return
        workers = min(self.parallelism, len(bindings))
        if workers <= 1:
            for u, m in bindings:
                if not lane.is_current(slot.epoch, slot.generation_id):
                    self._trace(
                        "lane_eval_cancelled",
                        symbol=slot.symbol,
                        market=slot.market,
                        generation_id=slot.generation_id,
                        reason="gen_advanced",
                    )
                    return
                try:
                    worker(u, m, slot, lane)
                except Exception as exc:
                    logger.warning(
                        "[%s] bind worker failed %s_%s: %s", self.service, u, m, exc
                    )
            return
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"{self.service}_bind") as pool:
            futs = {
                pool.submit(worker, u, m, slot, lane): (u, m) for u, m in bindings
            }
            for fut in as_completed(futs):
                u, m = futs[fut]
                try:
                    fut.result()
                except Exception as exc:
                    logger.warning(
                        "[%s] bind worker failed %s_%s: %s", self.service, u, m, exc
                    )
                if not lane.is_current(slot.epoch, slot.generation_id):
                    self._trace(
                        "lane_eval_cancelled",
                        symbol=slot.symbol,
                        market=slot.market,
                        generation_id=slot.generation_id,
                        reason="gen_advanced",
                    )
                    # Remaining futures may still run; they must refuse fire via is_current.
                    break

    def _trace(self, kind: str, **fields: Any) -> None:
        try:
            from backend.core.tradeflow_decision_trace import decision_trace_enabled, trace

            if not decision_trace_enabled():
                return
            trace(kind, service=self.service, **fields)
        except Exception:
            pass
