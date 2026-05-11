"""Symbol-wide loss prevention state sync and effective-state resolution."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)

SYMBOL_WIDE_SUFFIX = "_symbol_wide"
_MONITOR_LIST_RE = re.compile(r"(?:^|[.])monitor_list_(\d{4})$", re.IGNORECASE)
_SIZING_STATES = {
    "one_contract",
    "win_streak_one_contract",
    "symbol_one_contract",
    "sim_loss_50",
    "sim_loss_25",
    "sim_loss_1c",
    "live_loss_1c",
}


def normalize_loss_prevention_state_for_sizing(value: Any) -> str:
    """Strip origin markers before applying existing sizing rules."""
    state = str(value or "").strip().lower().replace("-", "_")
    if state.endswith(SYMBOL_WIDE_SUFFIX):
        state = state[: -len(SYMBOL_WIDE_SUFFIX)]
    if state in ("", "none", "null"):
        return "off"
    return state


def is_symbol_wide_loss_prevention_state(value: Any) -> bool:
    return str(value or "").strip().lower().replace("-", "_").endswith(SYMBOL_WIDE_SUFFIX)


def symbol_wide_loss_prevention_state(value: Any) -> str:
    """Persist non-off symbol-wide states with an origin suffix."""
    state = normalize_loss_prevention_state_for_sizing(value)
    if state == "off":
        return "off"
    return f"{state}{SYMBOL_WIDE_SUFFIX}"


def is_loss_prevention_sizing_state(value: Any) -> bool:
    return normalize_loss_prevention_state_for_sizing(value) in _SIZING_STATES


def _monitor_list_slot(monitor_list_qualified: str) -> Optional[str]:
    match = _MONITOR_LIST_RE.search(str(monitor_list_qualified or "").strip())
    return match.group(1) if match else None


def _fetch_monitor_lp_row(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> Optional[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT id,
               name,
               symbol,
               loss_prevention_state,
               COALESCE(loss_prevention_duration, 4),
               simulated_loss_prevention_cooldown_start_time,
               original_loss_prevention_cooldown_start_time,
               COALESCE(loss_prevention_cooldown_loss_count, 0),
               live_loss_prevention_cooldown_start_time,
               COALESCE(loss_prevention_toggle, FALSE),
               COALESCE(symbol_wide_loss_prevention, FALSE)
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "symbol": row[2],
        "loss_prevention_state": row[3],
        "loss_prevention_duration": row[4],
        "simulated_loss_prevention_cooldown_start_time": row[5],
        "original_loss_prevention_cooldown_start_time": row[6],
        "loss_prevention_cooldown_loss_count": row[7],
        "live_loss_prevention_cooldown_start_time": row[8],
        "loss_prevention_toggle": row[9],
        "symbol_wide_loss_prevention": row[10],
    }


def configured_symbol_wide_monitor_ids(
    cursor,
    monitor_list_qualified: str,
) -> list[str]:
    """Return user_0001 hero monitor ids referenced by live_symbol_status.monitor_follow."""
    slot = _monitor_list_slot(monitor_list_qualified)
    if slot != "0001":
        return []

    try:
        cursor.execute(
            f"""
            SELECT DISTINCT m.id
            FROM live_data.live_symbol_status AS lss
            JOIN {monitor_list_qualified} AS m
              ON UPPER(m.symbol) = UPPER(lss.symbol)
             AND BTRIM(COALESCE(m.name, '')) = BTRIM(COALESCE(lss.monitor_follow, ''))
            WHERE BTRIM(COALESCE(lss.monitor_follow, '')) <> ''
            ORDER BY m.id
            """
        )
        return [str(row[0]) for row in (cursor.fetchall() or [])]
    except Exception as exc:
        _log.debug("symbol-wide LP configured monitor lookup failed: %s", exc)
        return []


def sync_symbol_wide_loss_prevention_from_monitor(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> bool:
    """Copy a user_0001 hero monitor's LP fields into live_symbol_status.

    The row to update is selected by the manually configured
    live_symbol_status.monitor_follow name. ``monitor_follow_id`` is a derived
    cache and is refreshed on every successful sync. Directly updating
    live_symbol_status lets the existing DB trigger publish fanout.
    """
    slot = _monitor_list_slot(monitor_list_qualified)
    if slot != "0001":
        return False

    try:
        monitor = _fetch_monitor_lp_row(cursor, monitor_list_qualified, str(monitor_id))
    except Exception as exc:
        _log.debug("symbol-wide LP sync skipped; monitor row unavailable: %s", exc)
        return False

    if not monitor:
        return False

    monitor_name = str(monitor.get("name") or "").strip()
    symbol = str(monitor.get("symbol") or "").strip().upper()
    if not monitor_name or not symbol:
        return False

    live_state = symbol_wide_loss_prevention_state(monitor.get("loss_prevention_state"))
    try:
        cursor.execute(
            """
            UPDATE live_data.live_symbol_status
            SET monitor_follow_id = %s,
                loss_prevention_state = %s,
                loss_prevention_duration = %s,
                simulated_loss_prevention_cooldown_start_time = %s,
                original_loss_prevention_cooldown_start_time = %s,
                loss_prevention_cooldown_loss_count = %s,
                live_loss_prevention_cooldown_start_time = %s,
                loss_prevention_updated_at = CURRENT_TIMESTAMP
            WHERE UPPER(symbol) = %s
              AND BTRIM(COALESCE(monitor_follow, '')) = %s
            RETURNING symbol
            """,
            (
                int(monitor["id"]),
                live_state,
                int(monitor.get("loss_prevention_duration") or 4),
                monitor.get("simulated_loss_prevention_cooldown_start_time"),
                monitor.get("original_loss_prevention_cooldown_start_time"),
                int(monitor.get("loss_prevention_cooldown_loss_count") or 0),
                monitor.get("live_loss_prevention_cooldown_start_time"),
                symbol,
                monitor_name,
            ),
        )
        updated = cursor.fetchone() is not None
        if not updated:
            _log.debug(
                "symbol-wide LP sync found no live_symbol_status follower for symbol=%s monitor=%s",
                symbol,
                monitor_name,
            )
        return updated
    except Exception as exc:
        _log.debug(
            "symbol-wide LP sync failed for symbol=%s monitor=%s: %s",
            symbol,
            monitor_name,
            exc,
        )
        return False


def resolve_effective_loss_prevention_state(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> str:
    """Return local LP state or the symbol-wide override when enabled."""
    try:
        monitor = _fetch_monitor_lp_row(cursor, monitor_list_qualified, str(monitor_id))
    except Exception as exc:
        _log.debug("effective LP read failed for monitor=%s: %s", monitor_id, exc)
        return "off"

    if not monitor:
        return "off"

    if not bool(monitor.get("loss_prevention_toggle")):
        return "off"

    local_state = normalize_loss_prevention_state_for_sizing(monitor.get("loss_prevention_state"))
    if not bool(monitor.get("symbol_wide_loss_prevention")):
        return local_state

    symbol = str(monitor.get("symbol") or "").strip().upper()
    if not symbol:
        return local_state

    try:
        cursor.execute(
            """
            SELECT loss_prevention_state
            FROM live_data.live_symbol_status
            WHERE UPPER(symbol) = %s
            LIMIT 1
            """,
            (symbol,),
        )
        row = cursor.fetchone()
    except Exception as exc:
        _log.debug("symbol-wide LP state read failed for symbol=%s: %s", symbol, exc)
        return local_state

    if not row:
        return local_state

    symbol_state = symbol_wide_loss_prevention_state(row[0])
    if normalize_loss_prevention_state_for_sizing(symbol_state) == "off":
        return local_state
    return symbol_state
