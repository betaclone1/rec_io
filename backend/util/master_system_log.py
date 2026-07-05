"""Dual-sink master system event log (human file + PostgreSQL system.event_log).

Fail-open: callers must never break trading/restart paths if logging fails.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.core.config.database import get_system_postgresql_connection
from backend.util.paths import get_logs_dir

_EST = ZoneInfo("America/New_York")
_FALLBACK_LOGGER = logging.getLogger("master_system_log")

_VALID_SEVERITIES = frozenset({"info", "warning", "critical"})
_VALID_CATEGORIES = frozenset(
    {
        "RESTART",
        "WS",
        "DEPLOY",
        "TRADING_HALT",
        "MAINTENANCE",
        "ANOMALY",
        "MONITOR",
        "BACKUP",
    }
)

_file_lock = threading.Lock()
_file_handler: Optional[RotatingFileHandler] = None

# Operator/deploy actions always log; watchdog services stay quiet during maintenance.
_SOURCES_EXEMPT_MAINTENANCE_SUPPRESSION = frozenset(
    {
        "MASTER_RESTART",
        "git_update",
        "simple_git_pull",
        "record_system_version",
        "admin_routes",
    }
)


def system_in_maintenance_mode() -> bool:
    """True when core.system_state.mode is maintenance (MASTER_RESTART in progress)."""
    conn = get_system_postgresql_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT mode FROM core.system_state WHERE id = 1")
            row = cur.fetchone()
        return bool(row and row[0] == "maintenance")
    except Exception:
        return False
    finally:
        conn.close()


def _est_now() -> datetime:
    return datetime.now(_EST).replace(tzinfo=None)


def _format_est_iso(dt: datetime) -> str:
    aware = dt.replace(tzinfo=_EST) if dt.tzinfo is None else dt.astimezone(_EST)
    s = aware.strftime("%Y-%m-%dT%H:%M:%S")
    z = aware.strftime("%z")
    return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)


def _normalize_severity(severity: str) -> str:
    s = (severity or "info").strip().lower()
    return s if s in _VALID_SEVERITIES else "info"


def _normalize_category(category: str) -> str:
    c = (category or "ANOMALY").strip().upper()
    return c if c in _VALID_CATEGORIES else "ANOMALY"


def _normalize_detail_ref(detail_ref: Optional[str]) -> Optional[str]:
    if not detail_ref:
        return None
    ref = str(detail_ref).strip()
    if not ref:
        return None
    if ref.startswith("logs/"):
        ref = ref[5:]
    for suffix in (".out.log", ".err.log", ".log"):
        if ref.endswith(suffix):
            ref = ref[: -len(suffix)]
            break
    return ref or None


def _log_viewer_script_name(detail_ref: Optional[str]) -> Optional[str]:
    """Script name for log-viewer.html (basename without logs/ or .out.log)."""
    return _normalize_detail_ref(detail_ref)


def format_master_event_line(
    *,
    timestamp: datetime,
    category: str,
    severity: str,
    source: str,
    message: str,
    detail_ref: Optional[str] = None,
) -> str:
    cat = _normalize_category(category)
    sev = _normalize_severity(severity).upper()
    src = (source or "unknown").strip()[:28].ljust(28)
    detail = _normalize_detail_ref(detail_ref)
    line = (
        f"{_format_est_iso(timestamp)} | {sev:8} | {cat:13} | {src} | {message.strip()}"
    )
    if detail:
        line += f" | detail={detail}"
    return line


def _get_file_handler() -> RotatingFileHandler:
    global _file_handler
    if _file_handler is not None:
        return _file_handler
    log_dir = get_logs_dir()
    path = f"{log_dir}/master_events.log"
    handler = RotatingFileHandler(
        path,
        maxBytes=20 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _file_handler = handler
    return handler


def _write_file_line(line: str) -> None:
    with _file_lock:
        handler = _get_file_handler()
        record = logging.LogRecord(
            name="master_system_log",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=line,
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        handler.flush()


def _write_db_row(
    *,
    timestamp: datetime,
    category: str,
    severity: str,
    source: str,
    message: str,
    detail_ref: Optional[str],
    metadata: dict[str, Any],
) -> None:
    conn = get_system_postgresql_connection()
    if not conn:
        raise RuntimeError("no system DB connection")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO system.event_log
                    (timestamp, category, severity, source, message, detail_ref, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    timestamp,
                    category,
                    severity,
                    source,
                    message,
                    detail_ref,
                    json.dumps(metadata or {}),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def log_system_event(
    category: str,
    message: str,
    source: str,
    severity: str = "info",
    detail_ref: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Append one curated system event to master_events.log and system.event_log."""
    src = (source or "unknown").strip() or "unknown"
    if src not in _SOURCES_EXEMPT_MAINTENANCE_SUPPRESSION and system_in_maintenance_mode():
        return

    ts = _est_now()
    cat = _normalize_category(category)
    sev = _normalize_severity(severity)
    msg = (message or "").strip() or "(no message)"
    detail = _normalize_detail_ref(detail_ref)
    meta = dict(metadata or {})

    line = format_master_event_line(
        timestamp=ts,
        category=cat,
        severity=sev,
        source=src,
        message=msg,
        detail_ref=detail,
    )

    try:
        _write_file_line(line)
    except Exception as e:
        _FALLBACK_LOGGER.warning("master_system_log file write failed: %s", e)

    try:
        _write_db_row(
            timestamp=ts,
            category=cat,
            severity=sev,
            source=src,
            message=msg,
            detail_ref=detail,
            metadata=meta,
        )
    except Exception as e:
        _FALLBACK_LOGGER.warning("master_system_log DB write failed: %s", e)


def detail_ref_for_service(service_name: str, log_type: str = "out") -> str:
    """Supervisor program name suitable for log-viewer detail links."""
    name = (service_name or "").strip()
    if log_type == "err":
        return name
    return name
