"""Weekend adjustment: apply/revert discrete monitor_list transforms for Sat–Mon ET.

Preference column: weekend_adjustment (user setting, never mutated by the job).
Applied state: weekend_adjustment_snapshot JSONB (NULL = not applied).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

WEEKEND_ADJUSTMENT_NONE = "none"
WEEKEND_ADJUSTMENT_MODES = frozenset(
    {
        WEEKEND_ADJUSTMENT_NONE,
        "paper_only",
        "reduce_position_50",
        "reduce_position_25",
        "probability_adjustment_10",
        "probability_adjustment_25",
    }
)

# Saturday apply at/after 00:00:30 ET; Monday revert at/after 00:00:20 ET.
_SAT_APPLY_TIME = time(0, 0, 30)
_MON_REVERT_TIME = time(0, 0, 20)


def normalize_weekend_adjustment(value: Any) -> Optional[str]:
    """Return a valid mode string, or None if invalid."""
    if value is None:
        return WEEKEND_ADJUSTMENT_NONE
    s = str(value).strip().lower()
    if s in WEEKEND_ADJUSTMENT_MODES:
        return s
    return None


def is_weekend_adjustment_active_period(now_et: datetime) -> bool:
    """True when weekend transforms should be live on monitor_list.

    Active from Sat 00:00:30 ET through Mon 00:00:19 ET (inclusive of that second window).
    """
    wd = now_et.weekday()  # Mon=0 ... Sat=5 Sun=6
    t = now_et.time()
    if wd == 5:  # Saturday
        return t >= _SAT_APPLY_TIME
    if wd == 6:  # Sunday
        return True
    if wd == 0:  # Monday
        return t < _MON_REVERT_TIME
    return False


def reduced_position_size(weekday_size: int, fraction: float) -> int:
    """Integer position_size after weekend reduce; minimum 1."""
    try:
        base = int(weekday_size)
    except (TypeError, ValueError):
        base = 1
    if base < 1:
        base = 1
    return max(1, int(math.floor(base * fraction)))


def adjusted_min_probability(weekday_min: float, points: float) -> float:
    """Raise min_probability by points, capped at 100."""
    try:
        base = float(weekday_min)
    except (TypeError, ValueError):
        base = 0.0
    return min(100.0, base + float(points))


def build_apply_plan(
    mode: str,
    *,
    paper_trade: Any,
    position_size: Any,
    min_probability: Any,
    applied_at_iso: str,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Return (snapshot, live_updates) for applying mode, or None if no-op/invalid.

    snapshot holds weekday originals for fields the mode touches plus mode/applied_at.
    live_updates are the column values to write.
    """
    mode_n = normalize_weekend_adjustment(mode)
    if not mode_n or mode_n == WEEKEND_ADJUSTMENT_NONE:
        return None

    snapshot: Dict[str, Any] = {"mode": mode_n, "applied_at": applied_at_iso}
    updates: Dict[str, Any] = {}

    if mode_n == "paper_only":
        snapshot["paper_trade"] = bool(paper_trade)
        updates["paper_trade"] = True
    elif mode_n == "reduce_position_50":
        try:
            ps = int(position_size) if position_size is not None else 1
        except (TypeError, ValueError):
            ps = 1
        snapshot["position_size"] = ps
        updates["position_size"] = reduced_position_size(ps, 0.50)
    elif mode_n == "reduce_position_25":
        try:
            ps = int(position_size) if position_size is not None else 1
        except (TypeError, ValueError):
            ps = 1
        snapshot["position_size"] = ps
        updates["position_size"] = reduced_position_size(ps, 0.25)
    elif mode_n == "probability_adjustment_10":
        try:
            mp = float(min_probability) if min_probability is not None else 0.0
        except (TypeError, ValueError):
            mp = 0.0
        snapshot["min_probability"] = mp
        updates["min_probability"] = adjusted_min_probability(mp, 10.0)
    elif mode_n == "probability_adjustment_25":
        try:
            mp = float(min_probability) if min_probability is not None else 0.0
        except (TypeError, ValueError):
            mp = 0.0
        snapshot["min_probability"] = mp
        updates["min_probability"] = adjusted_min_probability(mp, 25.0)
    else:
        return None

    return snapshot, updates


def build_revert_updates(snapshot: Any) -> Optional[Dict[str, Any]]:
    """Map snapshot JSON back to live column updates (excludes clearing snapshot)."""
    if snapshot is None:
        return None
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(snapshot, dict):
        return None

    updates: Dict[str, Any] = {}
    if "paper_trade" in snapshot:
        updates["paper_trade"] = bool(snapshot["paper_trade"])
    if "position_size" in snapshot:
        try:
            updates["position_size"] = max(1, int(snapshot["position_size"]))
        except (TypeError, ValueError):
            updates["position_size"] = 1
    if "min_probability" in snapshot:
        try:
            updates["min_probability"] = float(snapshot["min_probability"])
        except (TypeError, ValueError):
            updates["min_probability"] = 0.0
    return updates if updates else None


def _snapshot_is_set(raw: Any) -> bool:
    if raw is None:
        return False
    if isinstance(raw, dict):
        return bool(raw)
    if isinstance(raw, str):
        s = raw.strip()
        return s not in ("", "null", "NULL", "{}")
    return True


def apply_weekend_adjustment_to_row(
    cursor,
    monitor_list_sql: str,
    monitor_id: int,
    *,
    now_et: datetime,
    force: bool = False,
) -> Dict[str, Any]:
    """Apply weekend adjustment for one monitor if preference set and not already applied.

    monitor_list_sql: already-qualified identifier safe for SQL (e.g. users_0001.monitor_list_0001).
    Returns status dict with keys: status, applied, needs_position_recalc, monitor_id, mode.
    """
    cursor.execute(
        f"""
        SELECT weekend_adjustment, weekend_adjustment_snapshot,
               paper_trade, position_size, min_probability
        FROM {monitor_list_sql}
        WHERE id = %s
          AND (status IS NULL OR status <> 'ARCHIVED')
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return {"status": "error", "message": "monitor_not_found", "monitor_id": monitor_id}

    mode_raw, snap_raw, paper_trade, position_size, min_probability = row
    mode = normalize_weekend_adjustment(mode_raw) or WEEKEND_ADJUSTMENT_NONE
    if mode == WEEKEND_ADJUSTMENT_NONE:
        return {
            "status": "ok",
            "applied": False,
            "needs_position_recalc": False,
            "monitor_id": monitor_id,
            "mode": mode,
            "reason": "none",
        }
    if _snapshot_is_set(snap_raw) and not force:
        return {
            "status": "ok",
            "applied": False,
            "needs_position_recalc": False,
            "monitor_id": monitor_id,
            "mode": mode,
            "reason": "already_applied",
        }

    plan = build_apply_plan(
        mode,
        paper_trade=paper_trade,
        position_size=position_size,
        min_probability=min_probability,
        applied_at_iso=now_et.isoformat(),
    )
    if not plan:
        return {
            "status": "ok",
            "applied": False,
            "needs_position_recalc": False,
            "monitor_id": monitor_id,
            "mode": mode,
            "reason": "no_plan",
        }

    snapshot, updates = plan
    set_parts = ["weekend_adjustment_snapshot = %s::jsonb"]
    values: List[Any] = [json.dumps(snapshot)]
    for col, val in updates.items():
        set_parts.append(f"{col} = %s")
        values.append(val)
    values.append(monitor_id)
    cursor.execute(
        f"UPDATE {monitor_list_sql} SET {', '.join(set_parts)} WHERE id = %s",
        values,
    )
    return {
        "status": "ok",
        "applied": True,
        "needs_position_recalc": "position_size" in updates,
        "monitor_id": monitor_id,
        "mode": mode,
    }


def revert_weekend_adjustment_to_row(
    cursor,
    monitor_list_sql: str,
    monitor_id: int,
) -> Dict[str, Any]:
    """Revert one monitor from weekend_adjustment_snapshot and clear the snapshot."""
    cursor.execute(
        f"""
        SELECT weekend_adjustment_snapshot
        FROM {monitor_list_sql}
        WHERE id = %s
          AND (status IS NULL OR status <> 'ARCHIVED')
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return {"status": "error", "message": "monitor_not_found", "monitor_id": monitor_id}

    snap_raw = row[0]
    if not _snapshot_is_set(snap_raw):
        return {
            "status": "ok",
            "reverted": False,
            "needs_position_recalc": False,
            "monitor_id": monitor_id,
            "reason": "no_snapshot",
        }

    updates = build_revert_updates(snap_raw)
    if not updates:
        cursor.execute(
            f"""
            UPDATE {monitor_list_sql}
            SET weekend_adjustment_snapshot = NULL
            WHERE id = %s
            """,
            (monitor_id,),
        )
        return {
            "status": "ok",
            "reverted": True,
            "needs_position_recalc": False,
            "monitor_id": monitor_id,
            "reason": "cleared_empty_snapshot",
        }

    set_parts = ["weekend_adjustment_snapshot = NULL"]
    values: List[Any] = []
    for col, val in updates.items():
        set_parts.append(f"{col} = %s")
        values.append(val)
    values.append(monitor_id)
    cursor.execute(
        f"UPDATE {monitor_list_sql} SET {', '.join(set_parts)} WHERE id = %s",
        values,
    )
    return {
        "status": "ok",
        "reverted": True,
        "needs_position_recalc": "position_size" in updates,
        "monitor_id": monitor_id,
    }


def reconcile_weekend_adjustments(
    cursor,
    monitor_list_sql: str,
    now_et: datetime,
) -> Dict[str, Any]:
    """Apply or revert all non-archived monitors for the current ET weekend window."""
    active = is_weekend_adjustment_active_period(now_et)
    cursor.execute(
        f"""
        SELECT id, weekend_adjustment, weekend_adjustment_snapshot
        FROM {monitor_list_sql}
        WHERE status IS NULL OR status <> 'ARCHIVED'
        ORDER BY id
        """
    )
    rows = cursor.fetchall() or []
    applied = 0
    reverted = 0
    skipped = 0
    position_recalc_ids: List[int] = []

    for mid, mode_raw, snap_raw in rows:
        mode = normalize_weekend_adjustment(mode_raw) or WEEKEND_ADJUSTMENT_NONE
        has_snap = _snapshot_is_set(snap_raw)
        if active:
            if mode == WEEKEND_ADJUSTMENT_NONE or has_snap:
                skipped += 1
                continue
            result = apply_weekend_adjustment_to_row(
                cursor, monitor_list_sql, int(mid), now_et=now_et
            )
            if result.get("applied"):
                applied += 1
                if result.get("needs_position_recalc"):
                    position_recalc_ids.append(int(mid))
            else:
                skipped += 1
        else:
            if not has_snap:
                skipped += 1
                continue
            result = revert_weekend_adjustment_to_row(
                cursor, monitor_list_sql, int(mid)
            )
            if result.get("reverted"):
                reverted += 1
                if result.get("needs_position_recalc"):
                    position_recalc_ids.append(int(mid))
            else:
                skipped += 1

    return {
        "status": "ok",
        "active_period": active,
        "applied": applied,
        "reverted": reverted,
        "skipped": skipped,
        "position_recalc_ids": position_recalc_ids,
        "examined": len(rows),
    }
