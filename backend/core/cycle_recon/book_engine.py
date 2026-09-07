from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from backend.core.cycle_package import CyclePackage, _apply_delta, _parse_ts
from backend.core.cycle_recon.time_util import floor_second, to_et_display, to_iso_z

QualityState = str
ROLL_WINDOWS_S = (1, 3, 5, 10, 30, 60)


@dataclass
class QualityInterval:
    reason_code: str
    start_utc: str
    end_utc: str
    detail: Optional[str] = None
    recovered_at_utc: Optional[str] = None


@dataclass
class BookSample:
    timestamp_utc: str
    timestamp_et: str
    cycle_open_utc: str
    cycle_close_utc: str
    seconds_since_cycle_open: float
    ttc_seconds: float
    yes: Dict[str, str]
    no: Dict[str, str]
    yes_ask: Optional[float]
    no_ask: Optional[float]
    best_yes_bid: Optional[float]
    best_no_bid: Optional[float]
    spread_yes: Optional[float]
    midpoint_yes: Optional[float]
    book_age_ms: float
    stale: bool
    quality_state: QualityState
    quality_flags: List[str] = field(default_factory=list)
    source_event_index: Optional[int] = None
    # Rolling factual activity (YES-book / event stream), no risk labels
    rolling: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReconstructionResult:
    ticker: str
    quality_state: QualityState
    reason_codes: List[str]
    intervals: List[QualityInterval]
    samples_1s: List[BookSample]
    # Exact as-of snapshots: observation_ts -> (event_index, event_ts, yes, no)
    as_of_books: Dict[datetime, Tuple[int, datetime, Dict[str, str], Dict[str, str]]]
    # End-of-second checkpoints for regularized series
    second_books: List[Tuple[int, datetime, datetime, Dict[str, str], Dict[str, str]]]
    snapshot_level_rows: List[Dict[str, Any]]
    quality_evidence: Dict[str, Any]
    meta: Dict[str, Any]
    # Optional compact event rows if collected (prefer streaming callback)
    event_rows: List[Dict[str, Any]] = field(default_factory=list)


def _dec(v: Any) -> Decimal:
    return Decimal(str(v).strip())


def _best_bid(book: Dict[str, str]) -> Optional[float]:
    best: Optional[float] = None
    for px, sz in book.items():
        try:
            if float(sz) <= 0:
                continue
            p = float(px)
        except (TypeError, ValueError):
            continue
        if best is None or p > best:
            best = p
    return best


def _has_positive_size(book: Dict[str, str]) -> bool:
    for sz in book.values():
        try:
            if float(sz) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _touch_fields(yes: Dict[str, str], no: Dict[str, str]) -> Dict[str, Optional[float]]:
    """
    Lightweight YES/NO touch (same complement semantics as asks_from_book /
    touch_dollars_from_orderbook_snapshot) without Decimalizing the full ladder
    on every delta — that path dominated reconstruct wall time (~90%).
    """
    yb = _best_bid(yes)
    nb = _best_bid(no)
    # yes_ask = min complement of no bids = 1 - best_no_bid
    if nb is not None:
        yes_ask: Optional[float] = 1.0 - float(nb)
    elif yb is not None and not _has_positive_size(no):
        yes_ask = 1.0
    else:
        yes_ask = None
    if yb is not None:
        no_ask: Optional[float] = 1.0 - float(yb)
    elif nb is not None and not _has_positive_size(yes):
        no_ask = 1.0
    else:
        no_ask = None
    spread = None
    mid = None
    if yes_ask is not None and yb is not None:
        spread = float(yes_ask) - float(yb)
        mid = (float(yes_ask) + float(yb)) / 2.0
    return {
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "best_yes_bid": yb,
        "best_no_bid": nb,
        "spread_yes": spread,
        "midpoint_yes": mid,
    }


def _crossed(yes: Dict[str, str], no: Dict[str, str], *, yb: Optional[float] = None, nb: Optional[float] = None) -> bool:
    if yb is None:
        yb = _best_bid(yes)
    if nb is None:
        nb = _best_bid(no)
    if yb is None or nb is None:
        return False
    return (yb + nb) > 1.0001


def _snapshot_level_rows(
    *,
    ticker: str,
    snapshot_seq: str,
    ts: datetime,
    reason: Optional[str],
    yes: Dict[str, str],
    no: Dict[str, str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for side, book in (("yes", yes), ("no", no)):
        for px, sz in book.items():
            rows.append(
                {
                    "ticker": ticker,
                    "snapshot_seq": snapshot_seq,
                    "timestamp_utc": to_iso_z(ts),
                    "reason": reason,
                    "side": side,
                    "price": px,
                    "size": sz,
                }
            )
    return rows


def collect_lifecycle_targets(
    pkg: CyclePackage,
    *,
    entry: Optional[datetime] = None,
    close: Optional[datetime] = None,
    pre_entry_offsets: Sequence[int] = (120, 90, 60, 30, 15, 10, 5, 1),
    include_open_seconds: bool = True,
) -> List[datetime]:
    targets = [pkg.open_utc, pkg.close_utc]
    if entry is not None:
        for off in pre_entry_offsets:
            targets.append(entry - timedelta(seconds=off))
        targets.append(entry)
        if close is not None and close > entry and include_open_seconds:
            t = entry.replace(microsecond=0) + timedelta(seconds=1)
            end = close.replace(microsecond=0)
            while t < end:
                targets.append(t)
                t += timedelta(seconds=1)
            targets.append(close)
    # unique sorted
    seen: Set[datetime] = set()
    out: List[datetime] = []
    for t in sorted(targets):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def reconstruct_book(
    pkg: CyclePackage,
    *,
    gap_threshold_s: float = 10.0,
    stale_threshold_s: float = 2.0,
    as_of_targets: Optional[Sequence[datetime]] = None,
    event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    collect_events: bool = False,
) -> ReconstructionResult:
    """
    Authoritative snapshot+delta reconstruction.

    - ``as_of_targets``: exact observation timestamps; book state is the last event
      with ``event_ts <= target`` (no end-of-second lookahead).
    - ``event_sink``: optional streaming callback for compact event rows (memory).
    - Duplicate detection is by source ``seq`` only.
    - Successful RESYNC restores continuity; gap intervals record recovery timestamps.
    """
    reason_codes: List[str] = []
    intervals: List[QualityInterval] = []
    snapshot_level_rows: List[Dict[str, Any]] = []
    event_rows: List[Dict[str, Any]] = []
    evidence: Dict[str, Any] = {
        "delta_duplicate_count": 0,
        "delta_duplicate_examples": [],
        "resync_count": 0,
        "resync_events": [],
        "timestamp_gap_count": 0,
        "negative_depth_count": 0,
        "out_of_order_count": 0,
        "crossed_book_count": 0,
    }

    if not pkg.snapshots:
        return ReconstructionResult(
            ticker=pkg.market_ticker,
            quality_state="INVALID",
            reason_codes=["SNAPSHOT_MISSING"],
            intervals=[],
            samples_1s=[],
            as_of_books={},
            second_books=[],
            snapshot_level_rows=[],
            quality_evidence=evidence,
            meta={"deltas": len(pkg.deltas)},
        )

    start = None
    for s in pkg.snapshots:
        if (s.get("yes") or {}) or (s.get("no") or {}):
            start = s
            break
    if start is None:
        return ReconstructionResult(
            ticker=pkg.market_ticker,
            quality_state="INVALID",
            reason_codes=["SNAPSHOT_MISSING"],
            intervals=[],
            samples_1s=[],
            as_of_books={},
            second_books=[],
            snapshot_level_rows=[],
            quality_evidence=evidence,
            meta={},
        )

    yes: Dict[str, str] = dict(start.get("yes") or {})
    no: Dict[str, str] = dict(start.get("no") or {})
    current_era = str(start.get("seq") or "")
    event_index = 0
    seen_seqs: Set[str] = set()
    prev_delta_ts: Optional[datetime] = None
    cur_sec: Optional[datetime] = None
    last_idx = 0
    last_ts = _parse_ts(start["received_at"])
    last_yes_ask: Optional[float] = _touch_fields(yes, no)["yes_ask"]
    second_map: Dict[datetime, Tuple[int, datetime, Dict[str, str], Dict[str, str]]] = {}

    # Per-second activity for rolling windows
    sec_event_count: Dict[datetime, int] = defaultdict(int)
    sec_qty: Dict[datetime, float] = defaultdict(float)
    sec_quote_jumps: Dict[datetime, int] = defaultdict(int)
    sec_yes_ask: Dict[datetime, Optional[float]] = {}

    targets = sorted(as_of_targets or [])
    target_i = 0
    as_of_books: Dict[datetime, Tuple[int, datetime, Dict[str, str], Dict[str, str]]] = {}
    open_gap: Optional[QualityInterval] = None

    def emit_event(row: Dict[str, Any]) -> None:
        if event_sink is not None:
            event_sink(row)
        elif collect_events:
            event_rows.append(row)

    def flush_second() -> None:
        nonlocal cur_sec
        if cur_sec is None:
            return
        second_map[cur_sec] = (last_idx, last_ts, dict(yes), dict(no))
        sec_yes_ask[cur_sec] = last_yes_ask

    def capture_targets_before(ts_next: datetime) -> None:
        """
        Finalize as-of for targets with target < ts_next using the current book
        (last applied event at last_ts). Skip targets before any event (last_ts > target).
        """
        nonlocal target_i
        while target_i < len(targets) and targets[target_i] < ts_next:
            tgt = targets[target_i]
            if last_ts <= tgt:
                as_of_books[tgt] = (last_idx, last_ts, dict(yes), dict(no))
            # else: observation precedes all events — leave absent
            target_i += 1

    # Opening snapshot
    snapshot_level_rows.extend(
        _snapshot_level_rows(
            ticker=pkg.market_ticker,
            snapshot_seq=current_era,
            ts=last_ts,
            reason=str(start.get("reason") or "initial"),
            yes=yes,
            no=no,
        )
    )
    emit_event(
        {
            "ticker": pkg.market_ticker,
            "event_index": event_index,
            "event_type": "snapshot",
            "timestamp_utc": to_iso_z(last_ts),
            "timestamp_raw": str(start.get("received_at") or ""),
            "seq": current_era,
            "snapshot_seq": current_era,
            "side": None,
            "price": None,
            "delta": None,
            "level_count_yes": len(yes),
            "level_count_no": len(no),
            "quality_flags": [],
        }
    )
    cur_sec = floor_second(last_ts)
    last_idx = event_index
    event_index += 1
    # Do not capture as-of here — wait until next event exceeds each target.

    for d in pkg.deltas:
        flags: List[str] = []
        era = str(d.get("snapshot_seq") or "")
        seq = str(d.get("seq") or "").strip()
        ts = _parse_ts(d["received_at"])
        raw_ts = str(d.get("received_at") or "")

        # Capture as-of for targets strictly before this event (book still prior state)
        capture_targets_before(ts)

        if seq:
            if seq in seen_seqs:
                flags.append("DELTA_DUPLICATE")
                evidence["delta_duplicate_count"] += 1
                if len(evidence["delta_duplicate_examples"]) < 5:
                    evidence["delta_duplicate_examples"].append(
                        {"seq": seq, "received_at": raw_ts, "side": d.get("side"), "price": d.get("price")}
                    )
                if "DELTA_DUPLICATE" not in reason_codes:
                    reason_codes.append("DELTA_DUPLICATE")
            else:
                seen_seqs.add(seq)

        if prev_delta_ts is not None and ts < prev_delta_ts:
            flags.append("DELTA_OUT_OF_ORDER")
            evidence["out_of_order_count"] += 1
            if "DELTA_OUT_OF_ORDER" not in reason_codes:
                reason_codes.append("DELTA_OUT_OF_ORDER")

        if prev_delta_ts is not None:
            gap = (ts - prev_delta_ts).total_seconds()
            if gap >= gap_threshold_s:
                flags.append("TIMESTAMP_GAP")
                evidence["timestamp_gap_count"] += 1
                if "TIMESTAMP_GAP" not in reason_codes:
                    reason_codes.append("TIMESTAMP_GAP")
                if open_gap is None:
                    open_gap = QualityInterval(
                        reason_code="TIMESTAMP_GAP",
                        start_utc=to_iso_z(prev_delta_ts),
                        end_utc=to_iso_z(ts),
                        detail=f"gap_s={gap:.3f}",
                        recovered_at_utc=to_iso_z(ts),
                    )
                    intervals.append(open_gap)
                else:
                    intervals.append(
                        QualityInterval(
                            reason_code="TIMESTAMP_GAP",
                            start_utc=to_iso_z(prev_delta_ts),
                            end_utc=to_iso_z(ts),
                            detail=f"gap_s={gap:.3f}",
                            recovered_at_utc=to_iso_z(ts),
                        )
                    )
                open_gap = None

        if era and current_era and era != current_era:
            flags.append("RESYNC")
            evidence["resync_count"] += 1
            matched = next((s for s in pkg.snapshots if str(s.get("seq")) == era), None)
            if matched is not None:
                # capture_targets_before(ts) already ran at loop head with pre-resync book
                flush_second()
                cur_sec = None
                my = matched.get("yes") or {}
                mn = matched.get("no") or {}
                yes = dict(my) if (my or mn) else {}
                no = dict(mn) if (my or mn) else {}
                current_era = era
                mts = _parse_ts(matched["received_at"])
                # Successful resync restores trust from this timestamp
                evidence["resync_events"].append(
                    {
                        "snapshot_seq": era,
                        "timestamp_utc": to_iso_z(mts),
                        "status": "recovered",
                        "level_count_yes": len(yes),
                        "level_count_no": len(no),
                    }
                )
                snapshot_level_rows.extend(
                    _snapshot_level_rows(
                        ticker=pkg.market_ticker,
                        snapshot_seq=era,
                        ts=mts,
                        reason=str(matched.get("reason") or "resync"),
                        yes=yes,
                        no=no,
                    )
                )
                emit_event(
                    {
                        "ticker": pkg.market_ticker,
                        "event_index": event_index,
                        "event_type": "snapshot",
                        "timestamp_utc": to_iso_z(mts),
                        "timestamp_raw": str(matched.get("received_at") or ""),
                        "seq": era,
                        "snapshot_seq": era,
                        "side": None,
                        "price": None,
                        "delta": None,
                        "level_count_yes": len(yes),
                        "level_count_no": len(no),
                        "quality_flags": ["RESYNC"],
                    }
                )
                last_yes_ask = _touch_fields(yes, no)["yes_ask"]
                last_idx = event_index
                last_ts = mts
                cur_sec = floor_second(mts)
                event_index += 1
                # Informational only when snapshot present — does not alone degrade
                # (recorded in evidence.resync_events)
            else:
                current_era = era
                flags.append("RESYNC_SNAPSHOT_MISSING")
                evidence["resync_events"].append(
                    {"snapshot_seq": era, "timestamp_utc": to_iso_z(ts), "status": "missing_snapshot"}
                )
                if "RESYNC_SNAPSHOT_MISSING" not in reason_codes:
                    reason_codes.append("RESYNC_SNAPSHOT_MISSING")

        side = str(d.get("side") or "")
        try:
            book = yes if side.strip().lower() == "yes" else no
            px = str(_dec(d.get("price")).quantize(Decimal("0.000001")))
            cur = _dec(book.get(px, "0"))
            new_sz = cur + _dec(d.get("delta"))
            if new_sz < 0:
                flags.append("NEGATIVE_DEPTH")
                evidence["negative_depth_count"] += 1
                if "NEGATIVE_DEPTH" not in reason_codes:
                    reason_codes.append("NEGATIVE_DEPTH")
        except (InvalidOperation, ValueError, TypeError):
            flags.append("DELTA_PARSE_ERROR")
            if "DELTA_PARSE_ERROR" not in reason_codes:
                reason_codes.append("DELTA_PARSE_ERROR")

        sec = floor_second(ts)
        if cur_sec is not None and sec != cur_sec:
            flush_second()
            cur_sec = None

        qty = 0.0
        try:
            qty = abs(float(d.get("delta") or 0))
        except (TypeError, ValueError):
            qty = 0.0

        _apply_delta(yes, no, d.get("side", ""), d.get("price"), d.get("delta"))
        touch = _touch_fields(yes, no)
        if _crossed(yes, no, yb=touch["best_yes_bid"], nb=touch["best_no_bid"]):
            flags.append("CROSSED_BOOK")
            evidence["crossed_book_count"] += 1
            if "CROSSED_BOOK" not in reason_codes:
                reason_codes.append("CROSSED_BOOK")

        jump = 0
        if last_yes_ask is not None and touch["yes_ask"] is not None:
            if abs(float(touch["yes_ask"]) - float(last_yes_ask)) > 1e-12:
                jump = 1
        last_yes_ask = touch["yes_ask"]

        sec_event_count[sec] += 1
        sec_qty[sec] += qty
        sec_quote_jumps[sec] += jump

        emit_event(
            {
                "ticker": pkg.market_ticker,
                "event_index": event_index,
                "event_type": "delta",
                "timestamp_utc": to_iso_z(ts),
                "timestamp_raw": raw_ts,
                "seq": seq or None,
                "snapshot_seq": era or None,
                "side": side.strip().lower() or None,
                "price": str(d.get("price") or "") or None,
                "delta": str(d.get("delta") or "") or None,
                "level_count_yes": len(yes),
                "level_count_no": len(no),
                "quality_flags": flags,
            }
        )
        cur_sec = sec
        last_idx = event_index
        last_ts = ts
        event_index += 1
        prev_delta_ts = ts

    flush_second()
    # Finalize remaining targets using final book when last_ts <= target
    while target_i < len(targets):
        tgt = targets[target_i]
        if last_ts <= tgt:
            as_of_books[tgt] = (last_idx, last_ts, dict(yes), dict(no))
        target_i += 1

    second_books = [
        (idx, sec, ets, y, n)
        for sec, (idx, ets, y, n) in sorted(second_map.items(), key=lambda kv: kv[0])
    ]

    # Build 1s samples + rolling activity
    samples: List[BookSample] = []
    sorted_secs = sorted(sec_event_count.keys())
    if second_books:
        open_s = floor_second(pkg.open_utc)
        close_s = floor_second(pkg.close_utc)
        ei = 0
        cur_idx, cur_sec_b, cur_ets, cur_yes, cur_no = second_books[0]
        t = open_s
        while t <= close_s:
            while ei + 1 < len(second_books) and second_books[ei + 1][1] <= t:
                ei += 1
                cur_idx, cur_sec_b, cur_ets, cur_yes, cur_no = second_books[ei]
            if cur_sec_b > t:
                t += timedelta(seconds=1)
                continue

            age_ms = max(0.0, (t - cur_ets).total_seconds() * 1000.0)
            in_gap = False
            gap_flags: List[str] = []
            for iv in intervals:
                if iv.reason_code != "TIMESTAMP_GAP":
                    continue
                a = _parse_ts(iv.start_utc)
                b = _parse_ts(iv.end_utc)
                if a < t <= b:
                    in_gap = True
                    gap_flags.append("TIMESTAMP_GAP")
                    break
            stale = age_ms >= stale_threshold_s * 1000.0 or in_gap
            flags = list(gap_flags)
            qstate: QualityState = "COMPLETE"
            if stale:
                qstate = "DEGRADED"
                flags.append("STALE_SAMPLE")

            touch = _touch_fields(cur_yes, cur_no)
            rolling: Dict[str, Any] = {}
            for w in ROLL_WINDOWS_S:
                # trailing window ending at t: (t-w, t]
                lo = t - timedelta(seconds=w - 1)
                ec = 0
                qty = 0.0
                jumps = 0
                for s in sorted_secs:
                    if lo <= s <= t:
                        ec += sec_event_count.get(s, 0)
                        qty += sec_qty.get(s, 0.0)
                        jumps += sec_quote_jumps.get(s, 0)
                # yes ask change over window ends
                ask_start = sec_yes_ask.get(lo) if lo in sec_yes_ask else None
                ask_end = sec_yes_ask.get(t)
                ask_change = None
                if ask_start is not None and ask_end is not None:
                    ask_change = float(ask_end) - float(ask_start)
                rolling[f"w{w}s"] = {
                    "update_event_count": ec,
                    "update_quantity_abs": qty,
                    "quote_jump_count_yes_ask": jumps,
                    "yes_ask_change": ask_change,
                    "definition": (
                        f"Trailing {w}s ending at sample second; "
                        "update_event_count=delta+snapshot events; "
                        "update_quantity_abs=sum(|delta|); "
                        "quote_jump_count_yes_ask=count of YES-ask changes between consecutive events; "
                        "yes_ask_change=end-start YES ask over window when both known"
                    ),
                }

            samples.append(
                BookSample(
                    timestamp_utc=to_iso_z(t),
                    timestamp_et=to_et_display(t),
                    cycle_open_utc=to_iso_z(pkg.open_utc),
                    cycle_close_utc=to_iso_z(pkg.close_utc),
                    seconds_since_cycle_open=(t - pkg.open_utc).total_seconds(),
                    ttc_seconds=max(0.0, (pkg.close_utc - t).total_seconds()),
                    yes=dict(cur_yes),
                    no=dict(cur_no),
                    yes_ask=touch["yes_ask"],
                    no_ask=touch["no_ask"],
                    best_yes_bid=touch["best_yes_bid"],
                    best_no_bid=touch["best_no_bid"],
                    spread_yes=touch["spread_yes"],
                    midpoint_yes=touch["midpoint_yes"],
                    book_age_ms=age_ms,
                    stale=stale,
                    quality_state=qstate,
                    quality_flags=flags,
                    source_event_index=cur_idx,
                    rolling=rolling,
                )
            )
            t += timedelta(seconds=1)

    # Market quality: DEGRADED if material continuity/integrity issues remain.
    # Successful RESYNC is recorded in evidence only and restores trust.
    material = {
        "TIMESTAMP_GAP",
        "NEGATIVE_DEPTH",
        "DELTA_OUT_OF_ORDER",
        "DELTA_DUPLICATE",
        "RESYNC_SNAPSHOT_MISSING",
        "SNAPSHOT_MISSING",
        "CROSSED_BOOK",
        "DELTA_PARSE_ERROR",
    }
    if "SNAPSHOT_MISSING" in reason_codes:
        q = "INVALID"
    elif material & set(reason_codes):
        q = "DEGRADED"
    else:
        q = "COMPLETE"

    return ReconstructionResult(
        ticker=pkg.market_ticker,
        quality_state=q,
        reason_codes=reason_codes,
        intervals=intervals,
        samples_1s=samples,
        as_of_books=as_of_books,
        second_books=second_books,
        snapshot_level_rows=snapshot_level_rows,
        quality_evidence=evidence,
        meta={
            "snapshot_count": len(pkg.snapshots),
            "delta_count": len(pkg.deltas),
            "event_count": event_index,
            "sample_1s_count": len(samples),
            "second_checkpoint_count": len(second_books),
            "as_of_target_count": len(targets),
            "as_of_captured_count": len(as_of_books),
            "snapshot_level_row_count": len(snapshot_level_rows),
            "gap_threshold_s": gap_threshold_s,
            "stale_threshold_s": stale_threshold_s,
            "cycle_open_utc": to_iso_z(pkg.open_utc),
            "cycle_close_utc": to_iso_z(pkg.close_utc),
            "floor_strike": str(pkg.floor_strike) if pkg.floor_strike is not None else None,
            "market_result": pkg.market_result,
        },
        event_rows=event_rows,
    )


def book_at_or_before_as_of(
    as_of_books: Dict[datetime, Tuple[int, datetime, Dict[str, str], Dict[str, str]]],
    ts: datetime,
) -> Optional[Tuple[int, datetime, Dict[str, str], Dict[str, str]]]:
    hit = as_of_books.get(ts)
    if hit is not None:
        return hit
    # nearest earlier target key
    prev = [k for k in as_of_books if k <= ts]
    if not prev:
        return None
    return as_of_books[max(prev)]
