"""
Restore monitor_list paper_trade / test_filter from drawdown halt snapshot.

Snapshot payload is stored in users.system_settings_<n>.drawdown_halt_monitor_snapshot (JSONB).
Legacy JSON files are still supported via restore_monitors_from_drawdown_snapshot_file.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

from psycopg2 import sql

_MONITOR_TABLE_BY_USER = {"0001": "users.monitor_list_0001"}


def drawdown_emergency_snapshot_path(project_root: str) -> str:
    """Legacy path; new halts persist snapshot in DB."""
    return os.path.join(project_root, "backend", "data", "drawdown_emergency_restore.json")


def validate_drawdown_monitor_snapshot(data: Any) -> Tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "snapshot must be a JSON object"
    try:
        if int(data.get("schema_version", 0)) != 1:
            return False, "unsupported schema_version; expected 1"
    except (TypeError, ValueError):
        return False, "invalid schema_version"
    monitors: List[Any] = list(data.get("monitors") or [])
    if not monitors:
        return False, "no monitors in snapshot"
    return True, "ok"


def apply_drawdown_monitor_snapshot_updates(
    cursor: Any,
    data: Dict[str, Any],
    *,
    user_number: str = "0001",
) -> Tuple[bool, str, int]:
    """
    UPDATE monitor rows from validated snapshot dict. Does not commit.
    Returns (ok, message, rowcount sum from UPDATEs).
    """
    u = str(user_number).strip()
    table = _MONITOR_TABLE_BY_USER.get(u)
    if not table:
        return False, f"no monitor table mapping for user {u}", 0
    ok, msg = validate_drawdown_monitor_snapshot(data)
    if not ok:
        return False, msg, 0
    monitors: List[Dict[str, Any]] = list(data.get("monitors") or [])
    parts = table.split(".")
    if len(parts) != 2:
        return False, f"invalid monitor table fqn {table!r}", 0
    sch_id, tbl_id = sql.Identifier(parts[0]), sql.Identifier(parts[1])
    upd = sql.SQL(
        """
        UPDATE {}.{}
        SET paper_trade = %s,
            test_filter = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """
    ).format(sch_id, tbl_id)
    updated = 0
    for m in monitors:
        mid = m.get("id")
        if mid is None:
            continue
        pt = m.get("paper_trade")
        tf = m.get("test_filter")
        if pt is None or tf is None:
            continue
        cursor.execute(upd, (bool(pt), bool(tf), int(mid)))
        updated += int(cursor.rowcount or 0)
    return True, "ok", updated


def restore_monitors_from_drawdown_snapshot_file(
    path: str,
    *,
    user_number: str = "0001",
) -> Tuple[bool, str, int]:
    """Apply snapshot from a JSON file. Commits on success."""
    if not os.path.isfile(path):
        return False, f"snapshot not found: {path}", 0
    with open(path, encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)

    from backend.core.config.database import get_postgresql_connection

    conn = get_postgresql_connection()
    if not conn:
        return False, "database connection failed", 0
    try:
        with conn.cursor() as cursor:
            ok, msg, n = apply_drawdown_monitor_snapshot_updates(
                cursor, data, user_number=user_number
            )
            if not ok:
                conn.rollback()
                return False, msg, 0
        conn.commit()
        return True, "ok", n
    except Exception as e:
        conn.rollback()
        return False, str(e), 0
    finally:
        conn.close()


def restore_monitors_from_db_snapshot_only(
    *,
    user_number: str = "0001",
) -> Tuple[bool, str, int]:
    """
    Read drawdown_halt_monitor_snapshot from system_settings, apply monitor updates, commit.
    Does not change trading_halt_active or clear the JSONB column (use API / full restore for that).
    """
    u = str(user_number).strip()
    if u not in _MONITOR_TABLE_BY_USER:
        return False, f"no monitor table mapping for user {u}", 0
    from backend.core.config.database import get_postgresql_connection
    from backend.core.system_settings_store import _settings_table_ident

    conn = get_postgresql_connection()
    if not conn:
        return False, "database connection failed", 0
    try:
        with conn.cursor() as cursor:
            ident = _settings_table_ident(u)
            cursor.execute(
                sql.SQL(
                    "SELECT drawdown_halt_monitor_snapshot FROM {} WHERE id = 1"
                ).format(ident)
            )
            row = cursor.fetchone()
            raw = row[0] if row else None
            if raw is None:
                return False, "no drawdown_halt_monitor_snapshot in system_settings", 0
            data = raw
            if isinstance(raw, str):
                data = json.loads(raw)
            if not isinstance(data, dict):
                return False, "invalid snapshot payload in system_settings", 0
            ok, msg, n = apply_drawdown_monitor_snapshot_updates(cursor, data, user_number=u)
            if not ok:
                conn.rollback()
                return False, msg, 0
        conn.commit()
        return True, "ok", n
    except Exception as e:
        conn.rollback()
        return False, str(e), 0
    finally:
        conn.close()
