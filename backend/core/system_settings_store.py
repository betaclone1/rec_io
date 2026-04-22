"""
DB-backed global/system settings per user (users.system_settings_<user_no>).

Drawdown controls (v1): drawdown_trading_halt, drawdown_reset_threshold_pct (percent drawdown from
sticky bankroll_current that triggers step-down + emergency monitor halt).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from psycopg2 import sql

from backend.trading_mode import _norm_slot

_LOG = logging.getLogger(__name__)

_DEFAULT_HALT = True
_DEFAULT_THRESHOLD_PCT = Decimal("50.00")

_USER_SLOT_RE = re.compile(r"^\d{4}$")

_ET = ZoneInfo("America/New_York")

# Machine codes written into drawdown_halt_monitor_snapshot.reason (monitor_manager).
_HALT_REASON_LABELS: Dict[str, str] = {
    "bankroll_drawdown_step_down_50pct": "Drawdown protection",
}


def utc_now_iso_and_est_wall_for_halt_snapshot() -> Tuple[str, str]:
    """UTC ISO for snapshot audit + US/Eastern wall clock string (no offset suffix)."""
    now_utc = datetime.now(timezone.utc)
    est_wall = now_utc.astimezone(_ET).strftime("%Y-%m-%d %H:%M:%S")
    return (now_utc.isoformat(), est_wall)


def _utc_iso_to_est_wall_display(iso_s: str) -> Optional[str]:
    """Parse snapshot created_at_utc into Eastern wall time YYYY-MM-DD HH:MM:SS."""
    if not iso_s or not str(iso_s).strip():
        return None
    s = str(iso_s).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ET).strftime("%Y-%m-%d %H:%M:%S")


def trading_halt_ui_fields_from_snapshot(
    trading_halt_active: bool, snapshot_raw: Any
) -> Dict[str, Optional[str]]:
    """
    Derive API / WS fields from drawdown_halt_monitor_snapshot JSONB (no new DDL).
    When latch is off, callers should omit or ignore.
    """
    empty: Dict[str, Optional[str]] = {
        "trading_halt_reason": None,
        "trading_halt_reason_code": None,
        "trading_halt_initiated_at_est": None,
    }
    if not trading_halt_active or snapshot_raw is None:
        return empty
    data: Any = snapshot_raw
    if isinstance(snapshot_raw, str):
        try:
            data = json.loads(snapshot_raw)
        except Exception:
            return empty
    if not isinstance(data, dict):
        return empty
    code_raw = data.get("reason")
    code = str(code_raw).strip() if code_raw is not None else ""
    label = _HALT_REASON_LABELS.get(code) if code else None
    if not label and code:
        label = code.replace("_", " ").title()
    if not label:
        label = "Trading halt"
    est = data.get("halt_initiated_at_est")
    if isinstance(est, str) and est.strip():
        initiated_est = est.strip()
    else:
        created = data.get("created_at_utc")
        initiated_est = (
            _utc_iso_to_est_wall_display(str(created))
            if created is not None
            else None
        )
    return {
        "trading_halt_reason": label,
        "trading_halt_reason_code": code or None,
        "trading_halt_initiated_at_est": initiated_est,
    }


def parse_user_number_from_account_balance_table(account_balance_table: str) -> Optional[str]:
    """Derive user numeric suffix from users.account_balance_0001 or users.account_balance_paper_0001."""
    if not account_balance_table:
        return None
    m = re.search(r"_(\d+)$", str(account_balance_table).strip())
    return m.group(1) if m else None


def _settings_table_ident(user_number: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(
        sql.Identifier(f"users_{user_number}"),
        sql.Identifier(f"system_settings_{user_number}"),
    )


def get_drawdown_trading_controls(
    cursor: Any,
    *,
    user_number: str,
) -> Tuple[bool, Decimal]:
    """
    Return (drawdown_trading_halt, drawdown_reset_threshold_pct).
    On missing table/row, defaults (True, 50).
    """
    u = str(user_number).strip()
    if not _USER_SLOT_RE.match(u):
        return _DEFAULT_HALT, _DEFAULT_THRESHOLD_PCT

    try:
        ident = _settings_table_ident(u)
        cursor.execute(
            sql.SQL(
                "SELECT drawdown_trading_halt, drawdown_reset_threshold_pct FROM {} WHERE id = 1"
            ).format(ident)
        )
        row = cursor.fetchone()
        if not row:
            return _DEFAULT_HALT, _DEFAULT_THRESHOLD_PCT
        halt = bool(row[0]) if row[0] is not None else _DEFAULT_HALT
        pct = row[1]
        if pct is None:
            d_pct = _DEFAULT_THRESHOLD_PCT
        else:
            d_pct = Decimal(str(pct))
        return halt, d_pct
    except Exception as e:
        _LOG.debug("system_settings read failed for user %s: %s (using defaults)", u, e)
        return _DEFAULT_HALT, _DEFAULT_THRESHOLD_PCT


def fetch_system_settings_row(user_number: str) -> Optional[dict]:
    """Load full row for API; returns dict or None."""
    u = str(user_number).strip()
    if not _USER_SLOT_RE.match(u):
        return None
    from backend.core.config.database import get_postgresql_connection

    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            ident = _settings_table_ident(u)
            cursor.execute(
                sql.SQL(
                    """
                    SELECT id, drawdown_trading_halt, drawdown_reset_threshold_pct,
                           COALESCE(trading_halt_active, false), updated_at,
                           drawdown_halt_monitor_snapshot
                    FROM {}
                    WHERE id = 1
                    """
                ).format(ident)
            )
            row = cursor.fetchone()
            if not row:
                return None
            halt_active = bool(row[3])
            snap = row[5] if len(row) > 5 else None
            halt_meta = trading_halt_ui_fields_from_snapshot(halt_active, snap)
            return {
                "id": int(row[0]),
                "drawdown_trading_halt": bool(row[1]),
                "drawdown_reset_threshold_pct": float(row[2]) if row[2] is not None else float(_DEFAULT_THRESHOLD_PCT),
                "trading_halt_active": halt_active,
                "updated_at": row[4].isoformat() if row[4] is not None else None,
                **halt_meta,
            }
    finally:
        conn.close()


def update_system_settings_drawdown(
    user_number: str,
    *,
    drawdown_trading_halt: Optional[bool] = None,
    drawdown_reset_threshold_pct: Optional[float] = None,
) -> Tuple[bool, str]:
    """Update drawdown fields; returns (ok, message)."""
    u = str(user_number).strip()
    if not _USER_SLOT_RE.match(u):
        return False, "unsupported user"
    if drawdown_trading_halt is None and drawdown_reset_threshold_pct is None:
        return False, "no fields to update"

    if drawdown_reset_threshold_pct is not None:
        p = float(drawdown_reset_threshold_pct)
        if p <= 0 or p >= 100:
            return False, "drawdown_reset_threshold_pct must be between 0 and 100 (exclusive)"

    from backend.core.config.database import get_postgresql_connection

    conn = get_postgresql_connection()
    if not conn:
        return False, "database connection failed"
    try:
        with conn.cursor() as cursor:
            ident = _settings_table_ident(u)
            if drawdown_trading_halt is not None and drawdown_reset_threshold_pct is not None:
                q = sql.SQL(
                    """
                    UPDATE {}
                    SET drawdown_trading_halt = %s,
                        drawdown_reset_threshold_pct = %s,
                        updated_at = NOW()
                    WHERE id = 1
                    """
                ).format(ident)
                cursor.execute(
                    q,
                    (bool(drawdown_trading_halt), float(drawdown_reset_threshold_pct)),
                )
            elif drawdown_trading_halt is not None:
                q = sql.SQL(
                    "UPDATE {} SET drawdown_trading_halt = %s, updated_at = NOW() WHERE id = 1"
                ).format(ident)
                cursor.execute(q, (bool(drawdown_trading_halt),))
            else:
                q = sql.SQL(
                    "UPDATE {} SET drawdown_reset_threshold_pct = %s, updated_at = NOW() WHERE id = 1"
                ).format(ident)
                cursor.execute(q, (float(drawdown_reset_threshold_pct),))
            if cursor.rowcount == 0:
                conn.rollback()
                return False, "system_settings row missing"
        conn.commit()
        return True, "ok"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def set_drawdown_halt_monitor_snapshot_with_cursor(
    cursor: Any,
    user_number: str,
    snapshot: Optional[dict],
) -> int:
    """Set drawdown_halt_monitor_snapshot (JSONB). Use snapshot=None to NULL the column."""
    from psycopg2.extras import Json

    u = str(user_number).strip()
    if not _USER_SLOT_RE.match(u):
        return 0
    ident = _settings_table_ident(u)
    val = Json(snapshot) if snapshot is not None else None
    cursor.execute(
        sql.SQL(
            """
            UPDATE {}
            SET drawdown_halt_monitor_snapshot = %s,
                updated_at = NOW()
            WHERE id = 1
            """
        ).format(ident),
        (val,),
    )
    return int(cursor.rowcount or 0)


def set_trading_halt_active_with_cursor(cursor: Any, user_number: str, active: bool) -> int:
    """Set trading_halt_active using an existing cursor (same transaction). Returns rowcount."""
    u = str(user_number).strip()
    if not _USER_SLOT_RE.match(u):
        return 0
    ident = _settings_table_ident(u)
    cursor.execute(
        sql.SQL(
            "UPDATE {} SET trading_halt_active = %s, updated_at = NOW() WHERE id = 1"
        ).format(ident),
        (bool(active),),
    )
    return int(cursor.rowcount or 0)


def set_trading_halt_active(user_number: str, active: bool) -> Tuple[bool, str]:
    """Update trading_halt_active only."""
    u = str(user_number).strip()
    if not _USER_SLOT_RE.match(u):
        return False, "unsupported user"
    from backend.core.config.database import get_postgresql_connection

    conn = get_postgresql_connection()
    if not conn:
        return False, "database connection failed"
    try:
        with conn.cursor() as cursor:
            n = set_trading_halt_active_with_cursor(cursor, u, active)
            if n == 0:
                conn.rollback()
                return False, "system_settings row missing"
        conn.commit()
        return True, "ok"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def _fanout_monitor_list_trading_halt_ws(user_number: str) -> None:
    """Publish trading_halt_active on preferences Redis (same envelope as monitor_manager)."""
    try:
        from backend.core.trading_redis_comms import publish_preferences_ws_message, use_trading_redis_comms

        if not use_trading_redis_comms():
            return
        u = str(user_number).strip()
        row = fetch_system_settings_row(u)
        halt_active = bool(row.get("trading_halt_active")) if row else False
        payload: Dict[str, Any] = {
            "type": "monitor_list_updated",
            "message": "system_settings_trading_halt",
            "trading_halt_active": halt_active,
            "tenant_user_no": _norm_slot(u),
        }
        if row:
            payload["trading_halt_reason"] = row.get("trading_halt_reason")
            payload["trading_halt_reason_code"] = row.get("trading_halt_reason_code")
            payload["trading_halt_initiated_at_est"] = row.get(
                "trading_halt_initiated_at_est"
            )
        publish_preferences_ws_message(payload)
    except Exception:
        pass


def clear_trading_halt_alert(user_number: str) -> Tuple[bool, str]:
    """Clear latch only; monitors stay on current paper/test settings."""
    ok, msg = set_trading_halt_active(user_number, False)
    if ok:
        _fanout_monitor_list_trading_halt_ws(user_number)
    return ok, msg


def restore_trade_operations_from_snapshot(user_number: str) -> Tuple[bool, str, int]:
    """
    Restore paper_trade / test_filter from drawdown_halt_monitor_snapshot (JSONB), clear trading_halt_active,
    and NULL the snapshot column. Single transaction.
    Returns (ok, message, monitors_rows_touched aggregate rowcount from updates).
    """
    from backend.core.drawdown_emergency_restore import apply_drawdown_monitor_snapshot_updates

    u = str(user_number).strip()
    if not _USER_SLOT_RE.match(u):
        return False, "unsupported user", 0

    from backend.core.config.database import get_postgresql_connection

    conn = get_postgresql_connection()
    if not conn:
        return False, "database connection failed", 0
    try:
        with conn.cursor() as cursor:
            ident = _settings_table_ident(u)
            cursor.execute(
                sql.SQL(
                    "SELECT drawdown_halt_monitor_snapshot FROM {} WHERE id = 1 FOR UPDATE"
                ).format(ident)
            )
            row = cursor.fetchone()
            raw = row[0] if row else None
            if raw is None:
                conn.rollback()
                return False, "no drawdown_halt_monitor_snapshot in system_settings", 0

            data = raw
            if isinstance(raw, str):
                data = json.loads(raw)
            if not isinstance(data, dict):
                conn.rollback()
                return False, "invalid snapshot payload in system_settings", 0
            ok, msg, n = apply_drawdown_monitor_snapshot_updates(cursor, data, user_number=u)
            if not ok:
                conn.rollback()
                return False, msg, 0
            cursor.execute(
                sql.SQL(
                    """
                    UPDATE {}
                    SET trading_halt_active = FALSE,
                        drawdown_halt_monitor_snapshot = NULL,
                        updated_at = NOW()
                    WHERE id = 1
                    """
                ).format(ident),
            )
        conn.commit()
        _fanout_monitor_list_trading_halt_ws(u)
        return True, "ok", n
    except Exception as e:
        conn.rollback()
        return False, str(e), 0
    finally:
        conn.close()
