#!/usr/bin/env python3
"""
MONITOR MANAGER - Core Monitor Management System
Foundation for comprehensive monitor state management, database synchronization,
and frontend coordination across all monitor components.

This is the starting point - will expand to handle:
- All monitor settings and preferences
- Trade state management
- Real-time frontend synchronization
- Database consistency across all monitor tables
- Event-driven updates for all monitor components
- Cross-service coordination
- Monitor lifecycle management
"""

import psycopg2
import psycopg2.pool
from psycopg2 import sql
import json
import logging
import requests
import subprocess
import sys
import os
import re
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, List
from flask import Flask, request, jsonify
from backend.core.unified_config import UnifiedConfigManager
from backend.core.time_eastern import merge_psycopg2_connect_kwargs, now_est, today_est
from backend.core.port_config import get_port, default_pool_user_number
from backend.trading_mode import (
    account_balance_table_for_user,
    monitor_list_fqn,
    sql_ident_qualified_table,
    strategy_list_fqn,
    trades_table_fqn,
    _norm_slot,
)


def _mm_resolve_user_no(explicit: Optional[str]) -> str:
    """Trading slot for this MM worker or an explicit value from the API (e.g. session-forwarded)."""
    if explicit is None:
        return _norm_slot(default_pool_user_number())
    s = str(explicit).strip()
    if s.lower().startswith("user_"):
        s = s[5:]
    return _norm_slot(s)


def _mm_worker_slot() -> str:
    """This monitor_manager process tenant (REC_USER_NO / supervisor suffix)."""
    return _mm_resolve_user_no(None)


def _mm_monitor_list_qualified() -> sql.Composed:
    sch, tbl = monitor_list_fqn(_mm_worker_slot()).split(".", 1)
    return sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))


def _mm_trades_qualified() -> sql.Composed:
    sch, tbl = trades_table_fqn(_mm_worker_slot()).split(".", 1)
    return sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))


def _latest_bankroll_cents(cursor, user_no: str) -> int:
    """Latest equity cents for the slot (same basis as /api/monitors/allocation)."""
    ab_ident = sql_ident_qualified_table(account_balance_table_for_user(_norm_slot(user_no)))
    cursor.execute(
        sql.SQL(
            """
            SELECT bankroll_current, portfolio
            FROM {}
            ORDER BY timestamp DESC NULLS LAST, id DESC
            LIMIT 1
            """
        ).format(ab_ident)
    )
    row = cursor.fetchone()
    if not row:
        return 0
    bc, pf = row[0], row[1]
    bankroll_value = int(bc) if bc is not None else 0
    portfolio_value = int(pf) if pf is not None else 0
    return bankroll_value if bankroll_value > 0 else portfolio_value
from backend.core.config.database import get_system_postgresql_connection
import threading
import time

# One bounded pool per monitor_manager process (avoids a fresh TCP connection per API call).
_mm_pg_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_mm_pg_pool_lock = threading.Lock()


class _MMPooledConnectionProxy:
    """Wrap raw psycopg2 connection so close() returns pooled conns."""

    __slots__ = ("_conn", "_pool", "_returned")

    def __init__(self, conn: Any, pool: Optional[psycopg2.pool.ThreadedConnectionPool]):
        self._conn = conn
        self._pool = pool
        self._returned = False

    def close(self):
        if self._returned:
            return
        self._returned = True
        if self._pool is not None:
            try:
                self._pool.putconn(self._conn)
                return
            except Exception:
                pass
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *args):
        try:
            return self._conn.__exit__(*args)
        finally:
            self.close()

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def _est_formatter():
    class ESTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            if datefmt:
                return dt.strftime(datefmt)
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return ESTFormatter(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_logging():
    log = logging.getLogger("monitor_manager")
    if log.handlers:
        return log
    handler = _FlushingStreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_est_formatter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


_logger = _configure_logging()
HEARTBEAT_INTERVAL_SEC = 300

app = Flask(__name__)

class MonitorManager:
    def __init__(self):
        self.unified_config = UnifiedConfigManager()
        self.db_config = self.unified_config.get_database_config()
        self.service_name = "monitor_manager"
        self.project_root = self.unified_config.project_root
        self.python_executable = self.unified_config.get('runtime.python_executable', sys.executable)
        
        # Foundation for future expansion
        self.active_monitors = {}  # Will track all active monitors
        self.monitor_states = {}   # Will track state of all monitor components
        self.frontend_connections = set()  # Will track frontend connections

        # Regime Monitor (LIVE<->PAPER) cooldown bookkeeping (in-memory only)
        # Keyed by monitor name (e.g. "mon_0001_10001")
        self._regime_last_switch_at: Dict[str, float] = {}
        
        # Port allocation for monitor processes
        self.monitor_port_base = 8013
        
        # Daily cleanup scheduler
        self.last_cleanup_date = None
        self.cleanup_thread = None
        self.cleanup_running = False
        
    def get_database_connection(self):
        """
        Tenant DB connection from a bounded in-process pool.

        This path intentionally avoids direct-connect fallback so connection pressure stays
        bounded and observable instead of silently creating new sessions.
        """
        global _mm_pg_pool
        psycopg2_config = self.db_config.copy()
        if "name" in psycopg2_config:
            psycopg2_config["database"] = psycopg2_config.pop("name")
        merged = merge_psycopg2_connect_kwargs(psycopg2_config)
        with _mm_pg_pool_lock:
            if _mm_pg_pool is None:
                max_conn = max(
                    1,
                    int(os.environ.get("REC_MONITOR_MANAGER_PG_POOL_MAX", "4")),
                )
                try:
                    _mm_pg_pool = psycopg2.pool.ThreadedConnectionPool(
                        1, max_conn, **merged
                    )
                except Exception as e:
                    raise RuntimeError(f"monitor_manager DB pool init failed: {e}") from e
        wait_ms = max(0, int(os.environ.get("REC_MONITOR_MANAGER_PG_POOL_WAIT_MS", "5000")))
        deadline = time.time() + (wait_ms / 1000.0)
        while True:
            try:
                raw = _mm_pg_pool.getconn()
                return _MMPooledConnectionProxy(raw, _mm_pg_pool)
            except psycopg2.pool.PoolError:
                if time.time() >= deadline:
                    raise RuntimeError(
                        f"monitor_manager DB pool exhausted for {wait_ms}ms "
                        f"(max={getattr(_mm_pg_pool, 'maxconn', 'unknown')})"
                    )
                time.sleep(0.05)
    
    def log_event(self, event_type: str, message: str, data: Optional[Dict] = None):
        """Centralized logging for monitor manager events. Uses standard logger (EST, flush)."""
        extra = f" | Data: {json.dumps(data)}" if data else ""
        msg = message + extra
        if event_type in ("ERROR", "STARTUP_ERROR", "WEBSOCKET_ERROR", "LOG_CLEANUP_ERROR", "ORPHANED_LOG_CLEANUP_ERROR"):
            _logger.error("%s: %s", event_type, msg)
        elif event_type in ("CREATE", "SUCCESS", "BANKROLL_UPDATE", "STARTUP", "INFO"):
            _logger.info("%s: %s", event_type, msg)
        else:
            _logger.debug("%s: %s", event_type, msg)
    
    # === MONITOR PROCESS MANAGEMENT ===
    
    def get_active_monitors(self) -> List[Dict]:
        """Get monitors that should have AES/ATS script iterations running.
        Uses only status: 'active' = scripts run, 'inactive' = they do not.
        auto_trade / auto_trade_status are for auto-trading behavior only, not script lifecycle."""
        try:
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                ml = _mm_monitor_list_qualified()
                cursor.execute(
                    sql.SQL(
                        "SELECT id, name, status FROM {} WHERE status = 'active' ORDER BY id"
                    ).format(ml)
                )
                
                monitors = []
                for row in cursor.fetchall():
                    monitor_id = row[0]
                    name = row[1]
                    status = row[2]
                    
                    # Extract user_number and monitor_id from name (e.g., "mon_0001_10001")
                    if name.startswith("mon_"):
                        parts = name.split("_")
                        if len(parts) >= 3:
                            user_number = parts[1]  # 0001
                            monitor_id = parts[2]   # 10001
                        else:
                            user_number = _mm_worker_slot()
                            monitor_id = str(monitor_id)
                    else:
                        user_number = _mm_worker_slot()
                        monitor_id = str(monitor_id)
                    
                    monitors.append({
                        'id': monitor_id,
                        'name': name,
                        'status': status,
                        'user_number': user_number,
                        'monitor_id': monitor_id
                    })
                
                conn.close()
                return monitors
                
        except Exception as e:
            self.log_event("ERROR", f"Error getting active monitors from database: {e}")
            return []
    
    def get_running_monitor_processes(self) -> List[str]:
        """Get list of currently running monitor-specific processes"""
        try:
            from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
            
            result = subprocess.run(
                [get_supervisorctl_path(), "-c", get_supervisor_config_path(), "status"],
                capture_output=True, text=True, timeout=10
            )
            
            running_processes = []
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 2:
                            process_name = parts[0]
                            status = parts[1]
                            
                            # Check if it's a monitor-specific process
                            if ((process_name.startswith('auto_entry_supervisor_') or 
                                 process_name.startswith('active_trade_supervisor_')) and
                                status == "RUNNING"):
                                running_processes.append(process_name)
            
            return running_processes
            
        except Exception as e:
            self.log_event("ERROR", f"Error getting running monitor processes: {e}")
            return []
    
    def _create_environment_variables(self) -> str:
        """Create environment variables string for supervisor"""
        try:
            env_vars = [
                f'PATH="{self.unified_config.get("runtime.venv_path", "")}/bin"',
                f'PYTHONPATH="{self.project_root}"',
                'PYTHONGC=1',
                'PYTHONDNSCACHE=1',
                f'TRADING_SYSTEM_HOST="{self.unified_config.get("runtime.system_host", "localhost")}"',
                f'REC_SYSTEM_HOST="{self.unified_config.get("runtime.system_host", "localhost")}"',
                f'REC_PROJECT_ROOT="{self.project_root}"',
                f'REC_ENVIRONMENT="{self.unified_config.get("system.environment", "development")}"',
                f'DB_HOST="{self.db_config.get("host", "localhost")}"',
                f'DB_NAME="{self.db_config.get("name", "rec_io_db")}"',
                f'DB_USER="{self.db_config.get("user", "rec_io_user")}"',
                f'DB_PASSWORD="{self.db_config.get("password", "rec_io_password")}"',
                f'DB_PORT="{self.db_config.get("port", 5432)}"',
                f'POSTGRES_HOST="{self.db_config.get("host", "localhost")}"',
                f'POSTGRES_DB="{self.db_config.get("name", "rec_io_db")}"',
                f'POSTGRES_USER="{self.db_config.get("user", "rec_io_user")}"',
                f'POSTGRES_PASSWORD="{self.db_config.get("password", "rec_io_password")}"',
                f'POSTGRES_PORT="{self.db_config.get("port", 5432)}"',
                f'REC_DB_HOST="{self.db_config.get("host", "localhost")}"',
                f'REC_DB_NAME="{self.db_config.get("name", "rec_io_db")}"',
                f'REC_DB_USER="{self.db_config.get("user", "rec_io_user")}"',
                f'REC_DB_PASS="{self.db_config.get("password", "rec_io_password")}"',
                f'REC_DB_PORT="{self.db_config.get("port", 5432)}"',
                f'REC_DB_SSLMODE="{self.db_config.get("sslmode", "disable")}"',
                'TZ="America/New_York"'
            ]
            
            return ','.join(env_vars)
            
        except Exception as e:
            self.log_event("ERROR", f"Error creating environment variables: {e}")
            return f'PATH="{self.unified_config.get("runtime.venv_path", "")}/bin",PYTHONPATH="{self.project_root}",PYTHONGC=1,PYTHONDNSCACHE=1'
    
    def create_monitor_config_section(self, monitor: Dict, port_offset: int) -> str:
        """Create supervisor config section for a monitor"""
        user_number = monitor['user_number']
        monitor_id = monitor['monitor_id']
        monitor_identifier = f"{user_number}_{monitor_id}"
        
        # Get environment variables
        env_vars = self._create_environment_variables()
        
        # Get log file paths
        log_dir = os.path.join(self.project_root, 'logs')
        
        # Use new port functions for consistent port assignment
        from backend.core.port_config import get_monitor_port, register_monitor_ports
        
        # Register ports for this monitor to ensure consistency
        register_monitor_ports(monitor_identifier)
        
        # Get monitor-specific ports
        auto_entry_port = get_monitor_port("auto_entry_supervisor", monitor_identifier)
        active_trade_port = get_monitor_port("active_trade_supervisor", monitor_identifier)
        
        auto_entry_config = f"""[program:auto_entry_supervisor_{monitor_identifier}]
command={self.python_executable} {self.project_root}/backend/auto_entry_supervisor.py {monitor_identifier}
directory={self.project_root}
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile={log_dir}/auto_entry_supervisor_{monitor_identifier}.err.log
stdout_logfile={log_dir}/auto_entry_supervisor_{monitor_identifier}.out.log
environment={env_vars}

"""
        
        active_trade_config = f"""[program:active_trade_supervisor_{monitor_identifier}]
command={self.python_executable} {self.project_root}/backend/active_trade_supervisor.py {monitor_identifier}
directory={self.project_root}
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile={log_dir}/active_trade_supervisor_{monitor_identifier}.err.log
stdout_logfile={log_dir}/active_trade_supervisor_{monitor_identifier}.out.log
environment={env_vars}

"""
        
        return auto_entry_config + active_trade_config
    
    def spawn_monitor_processes(self, monitor: Dict) -> bool:
        """Spawn processes for a specific monitor by regenerating supervisor config"""
        try:
            self.log_event("INFO", f"Regenerating supervisor config for monitor {monitor['user_number']}_{monitor['monitor_id']}")
            
            # Regenerate supervisor configuration
            result = subprocess.run([
                sys.executable,
                os.path.join(self.project_root, 'scripts', 'config', 'generate_unified_supervisor_config.py')
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error regenerating supervisor config: {result.stderr}")
                return False
            
            # Reread and update supervisor
            from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
            
            result = subprocess.run([
                get_supervisorctl_path(), 
                "-c", get_supervisor_config_path(), 
                "reread"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error rereading supervisor config: {result.stderr}")
                return False
            
            result = subprocess.run([
                get_supervisorctl_path(), 
                "-c", get_supervisor_config_path(), 
                "update"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error updating supervisor: {result.stderr}")
                return False
            
            self.log_event("SUCCESS", f"Supervisor config regenerated and updated for monitor {monitor['user_number']}_{monitor['monitor_id']}")
            return True
            
        except Exception as e:
            self.log_event("ERROR", f"Error spawning monitor processes: {e}")
            return False
    
    def remove_monitor_processes(self, monitor: Dict) -> bool:
        """Remove processes for a specific monitor by regenerating supervisor config"""
        try:
            self.log_event("INFO", f"Regenerating supervisor config to remove monitor {monitor['user_number']}_{monitor['monitor_id']}")
            
            # Regenerate supervisor configuration
            result = subprocess.run([
                sys.executable,
                os.path.join(self.project_root, 'scripts', 'config', 'generate_unified_supervisor_config.py')
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error regenerating supervisor config: {result.stderr}")
                return False
            
            # Reread and update supervisor
            from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
            
            result = subprocess.run([
                get_supervisorctl_path(), 
                "-c", get_supervisor_config_path(), 
                "reread"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error rereading supervisor config: {result.stderr}")
                return False
            
            result = subprocess.run([
                get_supervisorctl_path(), 
                "-c", get_supervisor_config_path(), 
                "update"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error updating supervisor: {result.stderr}")
                return False
            
            self.log_event("SUCCESS", f"Supervisor config regenerated and updated to remove monitor {monitor['user_number']}_{monitor['monitor_id']}")
            _logger.info("Monitor deactivated monitor_id=%s", monitor.get("monitor_id") or monitor.get("name", ""))
            return True
            
        except Exception as e:
            self.log_event("ERROR", f"Error removing monitor processes: {e}")
            return False
    
    def sync_monitor_processes(self) -> bool:
        """
        Sync unified AES/ATS user-level processes with DB state.

        Legacy per-monitor process mode is no longer used by the generated supervisor config.
        We reconcile by trading user slot (0001/0002/...) so one regen covers all monitors.
        """
        self.log_event("INFO", "Syncing monitor processes with database state")
        
        # Get active monitors from database
        active_monitors = self.get_active_monitors()
        self.log_event("INFO", f"Found {len(active_monitors)} active monitors in database")
        
        # Get currently running monitor processes
        running_processes = self.get_running_monitor_processes()
        self.log_event("INFO", f"Found {len(running_processes)} running monitor processes")
        
        # Extract running unified user slots from process names.
        running_users = set()
        for process_name in running_processes:
            if process_name.startswith('auto_entry_supervisor_'):
                suffix = process_name.replace('auto_entry_supervisor_', '')
                if re.fullmatch(r"\d{4}", suffix):
                    running_users.add(suffix)
            elif process_name.startswith('active_trade_supervisor_'):
                suffix = process_name.replace('active_trade_supervisor_', '')
                if re.fullmatch(r"\d{4}", suffix):
                    running_users.add(suffix)
        
        # Active user slots from monitor rows.
        active_users = set()
        for monitor in active_monitors:
            u = _norm_slot(monitor.get("user_number"))
            active_users.add(u)
        
        # Each monitor_manager worker only owns its own tenant slot.
        # Do not remove other users' unified supervisors from this process.
        worker_user = _mm_worker_slot()
        worker_has_active = worker_user in active_users
        worker_running = worker_user in running_users
        if worker_has_active and not worker_running:
            self.log_event("INFO", f"Spawning unified monitor processes for user {worker_user}")
            self.spawn_monitor_processes(
                {"user_number": worker_user, "monitor_id": worker_user}
            )
        elif (not worker_has_active) and worker_running:
            self.log_event("INFO", f"Removing unified monitor processes for user {worker_user}")
            self.remove_monitor_processes(
                {"user_number": worker_user, "monitor_id": worker_user}
            )
        
        self.log_event("SUCCESS", "Monitor process sync completed")
        
        self._notify_frontend_monitor_list_updated("Monitor process sync completed")
        return True

    def _deliver_preferences_ws(
        self,
        redis_message: Dict[str, Any],
        *,
        http_path: Optional[str],
        http_payload: Optional[Dict[str, Any]] = None,
        context: str = "preferences",
    ) -> None:
        """Push UI events through Redis (trading plane). When USE_TRADING_REDIS_COMMS is on, do not fall back
        to blocking HTTP on localhost; that path was timing out under load and defeats the refactor."""
        try:
            from backend.core.trading_redis_comms import (
                publish_preferences_ws_message,
                use_trading_redis_comms,
            )

            if use_trading_redis_comms():
                if publish_preferences_ws_message(redis_message):
                    return
                _logger.debug(
                    "Trading Redis preferences publish failed (%s); skipping main_app HTTP fallback",
                    context,
                )
                return

            if not http_path:
                return
            mp = get_port("main_app")
            body = http_payload if http_payload is not None else redis_message
            timeout_s = float(os.getenv("MONITOR_MANAGER_MAIN_HTTP_TIMEOUT", "15"))
            requests.post(
                f"http://localhost:{mp}{http_path}",
                json=body,
                timeout=timeout_s,
            )
        except Exception as e:
            self.log_event("WEBSOCKET_ERROR", f"Failed frontend fanout ({context}): {e}")

    def _notify_frontend_monitor_list_updated(self, message: str = "Monitor list updated") -> None:
        """Whenever monitor_manager changes monitor_list, alert frontend so displays refresh."""
        slot = _mm_resolve_user_no(None)
        body: Dict[str, Any] = {
            "type": "monitor_list_updated",
            "message": message,
            "tenant_user_no": slot,
        }
        try:
            from backend.core.system_settings_store import fetch_system_settings_row

            row = fetch_system_settings_row(slot)
            body["trading_halt_active"] = bool(row.get("trading_halt_active")) if row else False
            if row:
                body["trading_halt_reason"] = row.get("trading_halt_reason")
                body["trading_halt_reason_code"] = row.get("trading_halt_reason_code")
                body["trading_halt_initiated_at_est"] = row.get(
                    "trading_halt_initiated_at_est"
                )
        except Exception:
            body["trading_halt_active"] = False
        self._deliver_preferences_ws(
            body,
            http_path=None,
            http_payload=body,
            context="monitor_list_updated",
        )

    def _notify_frontend_monitor_total_position(
        self, monitor_id: int, total_position: int, multiplier: float = None
    ) -> None:
        slot = _mm_resolve_user_no(None)
        msg: Dict[str, Any] = {
            "type": "monitor_total_position_updated",
            "monitor_id": monitor_id,
            "total_position": total_position,
            "tenant_user_no": slot,
        }
        if multiplier is not None:
            msg["multiplier"] = multiplier
        self._deliver_preferences_ws(
            msg,
            http_path=None,
            http_payload={
                "monitor_id": monitor_id,
                "total_position": total_position,
                "multiplier": multiplier,
            },
            context="monitor_total_position",
        )

    def _notify_frontend_monitor_statistics(self, payload: dict) -> None:
        msg = {
            "type": "monitor_statistics_update",
            "tenant_user_no": _mm_resolve_user_no(None),
            **payload,
        }
        self._deliver_preferences_ws(
            msg,
            http_path=None,
            http_payload=msg,
            context="monitor_statistics",
        )

    # === CORE FUNCTIONALITY (Starting Point) ===

    def apply_drawdown_emergency_monitor_halt(self) -> Dict[str, Any]:
        """
        Persist all monitors' paper_trade / test_filter to users.system_settings_0001.drawdown_halt_monitor_snapshot,
        then force every monitor row to paper_trade=TRUE and test_filter=TRUE and set trading_halt_active.
        """
        from backend.core.system_settings_store import (
            set_drawdown_halt_monitor_snapshot_with_cursor,
            set_trading_halt_active_with_cursor,
            utc_now_iso_and_est_wall_for_halt_snapshot,
        )

        conn = None
        try:
            conn = self.get_database_connection()
            slot = _mm_worker_slot()
            ml = _mm_monitor_list_qualified()
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT id, name, status, paper_trade, test_filter FROM {} ORDER BY id"
                    ).format(ml)
                )
                rows = cursor.fetchall()

                monitors: List[Dict[str, Any]] = []
                for mid, name, status, paper_trade, test_filter in rows:
                    monitors.append(
                        {
                            "id": int(mid),
                            "name": str(name) if name is not None else "",
                            "status": str(status) if status is not None else "",
                            "paper_trade": bool(paper_trade) if paper_trade is not None else False,
                            "test_filter": bool(test_filter) if test_filter is not None else False,
                        }
                    )

                created_utc_iso, halt_est_wall = utc_now_iso_and_est_wall_for_halt_snapshot()
                snapshot: Dict[str, Any] = {
                    "schema_version": 1,
                    "created_at_utc": created_utc_iso,
                    "halt_initiated_at_est": halt_est_wall,
                    "reason": "bankroll_drawdown_step_down_50pct",
                    "monitor_list_table": monitor_list_fqn(slot),
                    "user_number": slot,
                    "monitors": monitors,
                }

                cursor.execute(
                    sql.SQL(
                        "UPDATE {} SET paper_trade = TRUE, test_filter = TRUE, "
                        "updated_at = CURRENT_TIMESTAMP"
                    ).format(ml)
                )
                n_updated = cursor.rowcount
                n_snap = set_drawdown_halt_monitor_snapshot_with_cursor(
                    cursor, slot, snapshot
                )
                if n_snap == 0:
                    conn.rollback()
                    return {
                        "status": "error",
                        "message": "system_settings row missing or snapshot not saved",
                    }
                set_trading_halt_active_with_cursor(cursor, slot, True)
            conn.commit()

            out = {
                "status": "success",
                "snapshot_storage": f"users_{slot}.system_settings_{slot}.drawdown_halt_monitor_snapshot",
                "monitors_snapshotted": len(monitors),
                "monitors_updated": int(n_updated),
            }
            self.log_event(
                "DRAWDOWN_EMERGENCY_HALT",
                "Drawdown step-down: snapshot saved and all monitors forced to paper + test_filter.",
                out,
            )
            return out
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            self.log_event("ERROR", f"Drawdown emergency monitor halt failed: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def handle_bankroll_update(self, bankroll_stepped_down: bool = False) -> Dict[str, Any]:
        """
        Handle bankroll update from Kalshi sync_balance, paper apply_balance_snapshot, or trading_mode ripple.
        Reads latest row from account_balance_0001 or account_balance_paper_0001 (trading_mode). Updates
        bankroll_allotment_total and total_position for active monitors.
        """
        try:
            self.log_event("BANKROLL_UPDATE", "Processing bankroll update notification")

            emergency_halt_result: Optional[Dict[str, Any]] = None
            if bankroll_stepped_down:
                emergency_halt_result = self.apply_drawdown_emergency_monitor_halt()
                if emergency_halt_result.get("status") != "success":
                    self.log_event(
                        "DRAWDOWN_EMERGENCY_HALT_FAILED",
                        "Drawdown detected but emergency halt did not complete cleanly; check prior ERROR.",
                        emergency_halt_result,
                    )

            # Keep bankroll/allotment sync behavior.
            allotment_result = self.update_monitor_bankroll_allotments(0)  # bankroll parameter not used anymore

            combined_result: Dict[str, Any] = {
                "status": "success",
                "allotment_update": allotment_result,
                "bankroll_stepped_down": bankroll_stepped_down,
                "message": "Bankroll update processed successfully",
            }
            if emergency_halt_result is not None:
                combined_result["drawdown_emergency_halt"] = emergency_halt_result
                if emergency_halt_result.get("status") != "success":
                    combined_result["status"] = "error"
                    combined_result["message"] = (
                        "Drawdown emergency halt failed; see drawdown_emergency_halt in response."
                    )

            self.log_event("BANKROLL_UPDATE", "Bankroll update processed successfully", combined_result)
            self._notify_frontend_monitor_list_updated("Bankroll / monitor list updated")
            return combined_result

        except Exception as e:
            self.log_event("ERROR", f"Bankroll update failed: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    # DEPRECATED: update_total_position method removed - monitor_manager now only works with monitor_list table

    def update_monitor_bankroll_allotments(self, bankroll: float) -> Dict[str, Any]:
        """
        Update bankroll_allotment_total for all active monitors based on current bankroll
        """
        conn = None
        try:
            conn = self.get_database_connection()

            un = _mm_resolve_user_no(None)
            ml_ident = sql_ident_qualified_table(monitor_list_fqn(un))
            with conn.cursor() as cursor:
                ab_ident = sql_ident_qualified_table(account_balance_table_for_user(un))
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT bankroll_current, portfolio
                        FROM {}
                        ORDER BY timestamp DESC NULLS LAST, id DESC
                        LIMIT 1
                        """
                    ).format(ab_ident)
                )
                bankroll_result = cursor.fetchone()
                if not bankroll_result:
                    return {"status": "error", "message": "No bankroll data found"}

                bc = bankroll_result[0]
                pf = bankroll_result[1]
                bankroll_value = int(bc) if bc is not None else 0
                portfolio_value = int(pf) if pf is not None else 0
                bankroll_cents = bankroll_value if bankroll_value > 0 else portfolio_value

                cursor.execute(
                    sql.SQL(
                        """
                        SELECT id, name, bankroll_allotment_pct
                        FROM {}
                        WHERE status = 'active'
                        """
                    ).format(ml_ident)
                )
                monitors = list(cursor.fetchall())

            updated_count = 0
            for monitor_id, monitor_name, allotment_pct in monitors:
                if allotment_pct is None:
                    continue
                allotment_total_cents = int(allotment_pct * bankroll_cents)
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                """
                                UPDATE {}
                                SET bankroll_allotment_total = %s
                                WHERE id = %s
                                """
                            ).format(ml_ident),
                            (allotment_total_cents, monitor_id),
                        )
                        cursor.execute(
                            sql.SQL(
                                """
                                SELECT position_size, position_type, multiplier, current_max_pct_exposure
                                FROM {}
                                WHERE id = %s
                                """
                            ).format(ml_ident),
                            (monitor_id,),
                        )
                        pos_result = cursor.fetchone()
                        if not pos_result or len(pos_result) < 4:
                            conn.commit()
                            continue
                        (
                            position_size,
                            position_type,
                            multiplier,
                            current_max_pct_exposure,
                        ) = pos_result
                        multiplier_value = float(multiplier or 0)
                        max_pct_cap = None
                        try:
                            if current_max_pct_exposure is not None:
                                max_pct_cap = float(current_max_pct_exposure)
                        except (TypeError, ValueError):
                            max_pct_cap = None

                        if multiplier_value == 0:
                            new_total_position = 1
                        elif position_type == "percent":
                            allotment_dollars = allotment_total_cents / 100
                            base_pct = (position_size or 0) / 100.0
                            effective_pct = base_pct * multiplier_value
                            if max_pct_cap is not None and max_pct_cap > 0:
                                effective_pct = min(effective_pct, max_pct_cap)
                            new_total_position = int(round(allotment_dollars * effective_pct))
                            if new_total_position < 1:
                                new_total_position = 1
                        else:
                            new_total_position = int(position_size * multiplier_value)

                        cursor.execute(
                            sql.SQL(
                                """
                                UPDATE {}
                                SET total_position = %s
                                WHERE id = %s
                                """
                            ).format(ml_ident),
                            (new_total_position, monitor_id),
                        )
                    conn.commit()
                    self._notify_frontend_monitor_total_position(
                        monitor_id, new_total_position, multiplier_value
                    )
                    updated_count += 1
                except Exception as mon_e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    _logger.warning(
                        "update_monitor_bankroll_allotments: monitor id=%s name=%r: %s",
                        monitor_id,
                        monitor_name,
                        mon_e,
                    )

            return {
                "status": "success",
                "message": f"Updated {updated_count} monitors",
                "updated_count": updated_count,
                "bankroll_cents": bankroll_cents,
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()
    
    # DEPRECATED: push_frontend_updates method removed - monitor_manager now only works with monitor_list table
    
    # === FUTURE EXPANSION FOUNDATION ===
    
    def handle_monitor_settings_update(self, monitor_id: str, settings: Dict[str, Any]):
        """Future: Handle updates to any monitor settings"""
        # TODO: Implement comprehensive monitor settings management
        pass
    
    def handle_trade_state_update(self, trade_id: str, state: Dict[str, Any]):
        """Future: Handle trade state changes"""
        # TODO: Implement trade state management
        pass
    
    def handle_frontend_connection(self, connection_id: str):
        """Future: Handle frontend connection management"""
        # TODO: Implement frontend connection tracking
        pass
    
    def sync_all_monitor_states(self):
        """Future: Synchronize all monitor states across the system"""
        # TODO: Implement comprehensive state synchronization
        pass
    
    def validate_monitor_consistency(self):
        """Future: Validate consistency across all monitor components"""
        # TODO: Implement consistency validation
        pass

    def initialize_bankroll_allotments(self) -> Dict[str, Any]:
        """
        Initialize bankroll allotments on first launch
        """
        return self.update_monitor_bankroll_allotments(0)  # bankroll parameter not used anymore

    def update_monitor_position_variables(
        self,
        monitor_id: int,
        position_size: int = None,
        position_type: str = None,
        multiplier: float = None,
        *,
        user_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update monitor position variables and recalculate total_position
        Called when frontend sends position variable updates
        """
        import time
        start_time = time.time()
        conn = None
        un = _mm_resolve_user_no(user_number)
        ml_ident = sql_ident_qualified_table(monitor_list_fqn(un))
        try:
            conn = self.get_database_connection()
            self.log_event("TIMING", f"DB connection: {time.time() - start_time:.3f}s")

            with conn.cursor() as cursor:
                update_fields = []
                values = []

                if position_size is not None:
                    update_fields.append("position_size = %s")
                    values.append(position_size)

                if position_type is not None:
                    update_fields.append("position_type = %s")
                    values.append(position_type)

                if multiplier is not None:
                    update_fields.append("multiplier = %s")
                    values.append(multiplier)

                if not update_fields:
                    return {"status": "error", "message": "No position variables to update"}

                values.append(monitor_id)
                update_start = time.time()
                cursor.execute(
                    sql.SQL(
                        "UPDATE {} SET "
                        + ", ".join(update_fields)
                        + " WHERE id = %s AND (status IS NULL OR status <> %s)"
                    ).format(ml_ident),
                    values + ["ARCHIVED"],
                )
                self.log_event("TIMING", f"Position update: {time.time() - update_start:.3f}s")

                if cursor.rowcount == 0:
                    return {"status": "error", "message": "Monitor not found or archived"}

                fetch_start = time.time()
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT position_size, position_type, multiplier,
                               bankroll_allotment_total, bankroll_allotment_pct, current_max_pct_exposure
                        FROM {}
                        WHERE id = %s
                        """
                    ).format(ml_ident),
                    (monitor_id,),
                )
                self.log_event("TIMING", f"Fetch settings: {time.time() - fetch_start:.3f}s")

                result = cursor.fetchone()
                if not result:
                    return {"status": "error", "message": "Failed to retrieve monitor settings"}

                (
                    position_size,
                    position_type,
                    multiplier,
                    bankroll_allotment_total,
                    bankroll_allotment_pct,
                    current_max_pct_exposure,
                ) = result

                multiplier_value = float(multiplier or 0)
                max_pct_cap = None
                try:
                    if current_max_pct_exposure is not None:
                        max_pct_cap = float(current_max_pct_exposure)
                except (TypeError, ValueError):
                    max_pct_cap = None

                if multiplier_value == 0:
                    new_total_position = 1
                elif position_type == "percent":
                    allotment_cents = int(bankroll_allotment_total or 0)
                    if allotment_cents <= 0 and bankroll_allotment_pct is not None:
                        try:
                            pct = float(bankroll_allotment_pct)
                        except (TypeError, ValueError):
                            pct = 0.0
                        if pct > 0:
                            br = _latest_bankroll_cents(cursor, un)
                            allotment_cents = int(round(pct * br))
                    allotment_dollars = allotment_cents / 100.0
                    base_pct = (position_size or 0) / 100.0
                    effective_pct = base_pct * multiplier_value
                    if max_pct_cap is not None and max_pct_cap > 0:
                        effective_pct = min(effective_pct, max_pct_cap)
                    new_total_position = int(round(allotment_dollars * effective_pct))
                    if new_total_position < 1:
                        new_total_position = 1
                else:
                    new_total_position = int((position_size or 0) * multiplier_value)

                total_update_start = time.time()
                cursor.execute(
                    sql.SQL(
                        """
                        UPDATE {}
                        SET total_position = %s
                        WHERE id = %s
                        """
                    ).format(ml_ident),
                    (new_total_position, monitor_id),
                )
                self.log_event("TIMING", f"Total position update: {time.time() - total_update_start:.3f}s")

                commit_start = time.time()
                conn.commit()
                self.log_event("TIMING", f"Commit: {time.time() - commit_start:.3f}s")

                self._notify_frontend_monitor_total_position(
                    monitor_id, new_total_position, multiplier_value
                )

                self._notify_frontend_monitor_list_updated("Monitor position variables updated")
                total_time = time.time() - start_time
                self.log_event("TIMING", f"Total function time: {total_time:.3f}s")

                return {
                    "status": "success",
                    "message": "Monitor position variables updated and total_position recalculated",
                    "monitor_id": monitor_id,
                    "total_position": new_total_position,
                }

        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def recalculate_monitor_total_positions(self) -> Dict[str, Any]:
        """
        Recalculate total_position for all monitors based on their current settings
        Called when position variables (size, type, multiplier) change
        """
        conn = None
        try:
            conn = self.get_database_connection()
            un = _mm_resolve_user_no(None)
            ml_ident = sql_ident_qualified_table(monitor_list_fqn(un))

            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT id,
                               name,
                               position_size,
                               position_type,
                               multiplier,
                               bankroll_allotment_total,
                               bankroll_allotment_pct,
                               current_max_pct_exposure,
                               performance_based_allocation
                        FROM {}
                        WHERE status = 'active'
                        """
                    ).format(ml_ident)
                )
                monitors = list(cursor.fetchall())

            updated_count = 0
            for row in monitors:
                if not row or len(row) < 9:
                    continue
                (
                    monitor_id,
                    monitor_name,
                    position_size,
                    position_type,
                    multiplier,
                    bankroll_allotment_total,
                    bankroll_allotment_pct,
                    current_max_pct_exposure,
                    performance_based_allocation,
                ) = row
                if position_size is None or position_type is None or multiplier is None:
                    continue

                multiplier_value = float(multiplier or 0)
                max_pct_cap = None
                try:
                    if current_max_pct_exposure is not None:
                        max_pct_cap = float(current_max_pct_exposure)
                except (TypeError, ValueError):
                    max_pct_cap = None

                if multiplier_value == 0:
                    new_total_position = 1
                elif position_type == "percent":
                    allotment_cents = int(bankroll_allotment_total or 0)
                    if allotment_cents <= 0 and bankroll_allotment_pct is not None:
                        try:
                            pct = float(bankroll_allotment_pct)
                        except (TypeError, ValueError):
                            pct = 0.0
                        if pct > 0:
                            with conn.cursor() as c2:
                                br = _latest_bankroll_cents(c2, un)
                            allotment_cents = int(round(pct * br))
                    allotment_dollars = allotment_cents / 100.0
                    base_pct = (position_size or 0) / 100.0
                    effective_pct = base_pct * multiplier_value
                    if performance_based_allocation and max_pct_cap is not None and max_pct_cap > 0:
                        effective_pct = min(effective_pct, max_pct_cap)
                    new_total_position = int(round(allotment_dollars * effective_pct))
                    if new_total_position < 1:
                        new_total_position = 1
                else:
                    new_total_position = int(position_size * multiplier_value)

                try:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                """
                                UPDATE {}
                                SET total_position = %s
                                WHERE id = %s
                                """
                            ).format(ml_ident),
                            (new_total_position, monitor_id),
                        )
                    conn.commit()
                    self._notify_frontend_monitor_total_position(
                        monitor_id, new_total_position, multiplier_value
                    )
                    updated_count += 1
                except Exception as mon_e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    _logger.warning(
                        "recalculate_monitor_total_positions: monitor id=%s: %s",
                        monitor_id,
                        mon_e,
                    )

            return {
                "status": "success",
                "message": f"Recalculated total_position for {updated_count} monitors",
                "updated_count": updated_count,
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    @staticmethod
    def _unpack_cycle_stats_row(cycle_stats) -> tuple:
        """
        Safe (total_cycles, winning_cycles) from COUNT/SUM aggregate row.
        Avoids tuple index errors when a row is short and fixes truthiness bugs
        (e.g. total_cycles==0 must not skip reading winning_cycles).
        """
        if not cycle_stats or len(cycle_stats) < 2:
            return (0, 0)
        raw_tc, raw_wc = cycle_stats[0], cycle_stats[1]
        total_cycles = int(raw_tc) if raw_tc is not None else 0
        winning_cycles = int(raw_wc) if raw_wc is not None else 0
        return (total_cycles, winning_cycles)

    def update_monitor_statistics_from_trades(self) -> Dict[str, Any]:
        """
        Update monitor statistics by querying the trades database and calculating metrics
        for each active/inactive monitor (excluding ARCHIVED monitors)
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                ml = _mm_monitor_list_qualified()
                tr = _mm_trades_qualified()
                # Get all active and inactive monitors (excluding ARCHIVED)
                cursor.execute(
                    sql.SQL(
                        "SELECT id, name, symbol FROM {} "
                        "WHERE status IN ('active', 'inactive') ORDER BY id"
                    ).format(ml)
                )
                
                monitors = cursor.fetchall()
                updated_count = 0
                errors: List[str] = []
                
                for row in monitors:
                    if not row or len(row) < 3:
                        self.log_event(
                            "ERROR",
                            f"Skipping invalid monitor_list row (expected id, name, symbol): {row!r}",
                        )
                        continue
                    monitor_id, monitor_name, symbol = row[0], row[1], row[2]
                    try:
                        # Extract monitor identifier from name (e.g., "mon_0001_10001")
                        monitor_identifier = monitor_name
                        
                        # Get the strategy for this monitor
                        cursor.execute(
                            sql.SQL("SELECT strategy FROM {} WHERE id = %s").format(ml),
                            (monitor_id,),
                        )
                        strategy_row = cursor.fetchone()
                        strategy = "Hourly HTC"
                        if strategy_row and len(strategy_row) >= 1 and strategy_row[0] is not None:
                            raw_s = str(strategy_row[0]).strip()
                            if raw_s:
                                strategy = raw_s
                        
                        # Check if this is Momentum Contain or Momentum Breakout
                        is_momentum_contain = strategy and "Momentum Contain" in strategy
                        is_momentum_breakout = strategy and "Momentum Breakout" in strategy
                        is_cycle_based_win_loss = is_momentum_contain or is_momentum_breakout
                        
                        if is_cycle_based_win_loss:
                            cursor.execute(
                                sql.SQL(
                                    """
                                WITH cycle_grouped AS (
                                    SELECT 
                                        ticker,
                                        CASE 
                                            WHEN ticker LIKE '%-%' THEN 
                                                regexp_replace(ticker, '-[^-]*$', '')
                                            ELSE ticker
                                        END as cycle_id
                                    FROM {} 
                                    WHERE monitor = %s 
                                    AND status IN ('closed', 'settled') 
                                    AND (test_filter IS NULL OR test_filter = FALSE)
                                    AND ticker IS NOT NULL
                                ),
                                cycle_results AS (
                                    SELECT 
                                        cg.cycle_id,
                                        COUNT(CASE WHEN t.win_loss = 'W' THEN 1 END) as cycle_wins,
                                        COUNT(CASE WHEN t.win_loss = 'L' THEN 1 END) as cycle_losses,
                                        COUNT(*) as cycle_trade_count
                                    FROM cycle_grouped cg
                                    JOIN {} t ON t.ticker = cg.ticker
                                    WHERE t.monitor = %s 
                                    AND t.status IN ('closed', 'settled') 
                                    AND (t.test_filter IS NULL OR t.test_filter = FALSE)
                                    GROUP BY cg.cycle_id
                                ),
                                cycle_summary AS (
                                    SELECT 
                                        cycle_id,
                                        CASE WHEN cycle_losses > 0 THEN 0 ELSE 1 END as is_winning_cycle
                                    FROM cycle_results
                                )
                                SELECT 
                                    COUNT(*) as total_cycles,
                                    SUM(is_winning_cycle) as winning_cycles
                                FROM cycle_summary
                            """
                                ).format(tr, tr),
                                (monitor_identifier, monitor_identifier),
                            )
                            
                            cycle_stats = cursor.fetchone()
                            total_cycles, winning_cycles = self._unpack_cycle_stats_row(cycle_stats)
                            
                            win_loss_rate = 0.0
                            if total_cycles > 0:
                                win_loss_rate = round((winning_cycles / total_cycles) * 100, 1)
                            
                            cursor.execute(
                                sql.SQL(
                                    """
                                SELECT 
                                    COUNT(*) as total_trades,
                                    COALESCE(SUM(ret_pct), 0) as total_ret_pct,
                                    COALESCE(SUM(pnl), 0) as total_pnl
                                FROM {} 
                                WHERE monitor = %s AND status IN ('closed', 'settled') AND (test_filter IS NULL OR test_filter = FALSE)
                            """
                                ).format(tr),
                                (monitor_identifier,),
                            )
                            
                            trade_stats = cursor.fetchone()
                            if trade_stats and len(trade_stats) >= 3:
                                total_trades, total_ret_pct, total_pnl = (
                                    trade_stats[0],
                                    trade_stats[1],
                                    trade_stats[2],
                                )
                                ret_pct_sum = total_ret_pct
                                pnl_show = float(total_pnl) if total_pnl is not None else 0.0
                                
                                cursor.execute(
                                    sql.SQL(
                                        """
                                    UPDATE {} 
                                    SET 
                                        trades = %s,
                                        win_loss = %s,
                                        ret_pct = %s,
                                        pnl = %s
                                    WHERE id = %s
                                """
                                    ).format(ml),
                                    (
                                        total_trades,
                                        win_loss_rate,
                                        ret_pct_sum,
                                        total_pnl,
                                        monitor_id,
                                    ),
                                )
                                
                                updated_count += 1
                                
                                self.log_event(
                                    "STATS_UPDATE",
                                    f"Updated monitor {monitor_name}: trades={total_trades}, cycles={total_cycles}, winning_cycles={winning_cycles}, W/L={win_loss_rate}% (cycle-based), ret_pct={ret_pct_sum}%, PNL=${pnl_show:.2f}",
                                )
                        else:
                            cursor.execute(
                                sql.SQL(
                                    """
                            SELECT 
                                COUNT(*) as total_trades,
                                COUNT(CASE WHEN win_loss = 'W' THEN 1 END) as wins,
                                COUNT(CASE WHEN win_loss = 'L' THEN 1 END) as losses,
                                COALESCE(SUM(ret_pct), 0) as total_ret_pct,
                                COALESCE(SUM(pnl), 0) as total_pnl
                                FROM {} 
                                WHERE monitor = %s AND status IN ('closed', 'settled') AND (test_filter IS NULL OR test_filter = FALSE)
                            """
                                ).format(tr),
                                (monitor_identifier,),
                            )
                            
                            trade_stats = cursor.fetchone()
                            if trade_stats and len(trade_stats) >= 5:
                                total_trades, wins, losses, total_ret_pct, total_pnl = (
                                    trade_stats[0],
                                    trade_stats[1],
                                    trade_stats[2],
                                    trade_stats[3],
                                    trade_stats[4],
                                )
                                
                                win_loss_rate = 0.0
                                if total_trades > 0:
                                    win_loss_rate = round((wins / total_trades) * 100, 1)
                                
                                ret_pct_sum = total_ret_pct
                                pnl_show = float(total_pnl) if total_pnl is not None else 0.0
                                
                                cursor.execute(
                                    sql.SQL(
                                        """
                                    UPDATE {} 
                                    SET 
                                        trades = %s,
                                        win_loss = %s,
                                        ret_pct = %s,
                                        pnl = %s
                                    WHERE id = %s
                                """
                                    ).format(ml),
                                    (
                                        total_trades,
                                        win_loss_rate,
                                        ret_pct_sum,
                                        total_pnl,
                                        monitor_id,
                                    ),
                                )
                                
                                updated_count += 1
                                
                                self.log_event(
                                    "STATS_UPDATE",
                                    f"Updated monitor {monitor_name}: trades={total_trades}, W/L={win_loss_rate}%, ret_pct={ret_pct_sum}%, PNL=${pnl_show:.2f}",
                                )
                    except Exception as mon_err:
                        msg = f"monitor id={monitor_id} name={monitor_name!r}: {mon_err}"
                        errors.append(msg)
                        self.log_event("ERROR", f"Monitor statistics partial failure — {msg}")
                
                conn.commit()
                if updated_count > 0:
                    self._notify_frontend_monitor_list_updated("Monitor statistics updated")
                out: Dict[str, Any] = {
                    "status": "success",
                    "message": f"Updated statistics for {updated_count} monitors",
                    "updated_count": updated_count,
                }
                if errors:
                    out["partial_errors"] = errors
                    out["message"] += f" ({len(errors)} monitor(s) skipped due to errors)"
                return out
                
        except Exception as e:
            self.log_event("ERROR", f"Error updating monitor statistics from trades: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def _parse_monitor_name_for_user_and_id(self, monitor_name: str) -> Optional[Dict[str, str]]:
        """
        Parse monitor identifier like "mon_0001_10001" into (user_number, monitor_id).
        """
        if not monitor_name:
            return None
        parts = str(monitor_name).split("_")
        if len(parts) < 3:
            return None
        if parts[0].lower() != "mon":
            return None
        return {"user_number": parts[-2], "monitor_id": parts[-1]}

    def _regime_window_to_interval(self, regime_window: str) -> Optional[str]:
        """
        Convert regime_window selector into a Postgres interval expression string.
        """
        window = (regime_window or "").strip()
        mapping = {
            "30d": "30 days",
            "7d": "7 days",
            "1d": "1 day",
            "12h": "12 hours",
        }
        return mapping.get(window)

    def _evaluate_and_switch_regime(self, monitor_name: str, force_immediate: bool = False) -> None:
        """
        After a trade close, evaluate rolling SUM(ret_pct) for the monitor's
        configured regime_window and switch monitor_list.paper_trade accordingly.
        Matches dashboard tile / trade-history style return (sum of per-trade ret_pct).
        """
        if not monitor_name:
            return

        parsed = self._parse_monitor_name_for_user_and_id(monitor_name)
        if not parsed:
            return

        user_number = _norm_slot(parsed["user_number"])
        monitor_id = parsed["monitor_id"]
        ml_ident = sql_ident_qualified_table(monitor_list_fqn(user_number))
        tr_ident = sql_ident_qualified_table(trades_table_fqn(user_number))

        # MVP threshold is fixed at 0.0 (PnL/fees already reflected in ret_pct at trade close).
        threshold = 0.0
        cooldown_seconds = 3600  # in-process safety valve to prevent flapping

        conn = None
        try:
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                    SELECT regime_monitor_enabled, regime_window, paper_trade
                    FROM {}
                    WHERE id = %s
                    """
                    ).format(ml_ident),
                    (monitor_id,),
                )
                row = cursor.fetchone()
                if not row or len(row) < 3:
                    return

                regime_enabled, regime_window, current_paper_trade = row[0], row[1], row[2]
                if not regime_enabled:
                    return

                interval_str = self._regime_window_to_interval(regime_window or "30d")
                if not interval_str:
                    interval_str = "30 days"

                cursor.execute(
                    sql.SQL(
                        """
                    SELECT
                      COALESCE(SUM(ret_pct), 0),
                      COUNT(*)
                    FROM {}
                    WHERE monitor = %s
                      AND LOWER(TRIM(status)) IN ('closed', 'settled')
                      AND (test_filter IS NULL OR test_filter = FALSE)
                      AND ret_pct IS NOT NULL
                      AND (CASE
                             WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}'
                             THEN closed_at::timestamptz
                             ELSE created_at
                           END) >= NOW() - %s::interval
                    """
                    ).format(tr_ident),
                    (monitor_name, interval_str),
                )
                win_row = cursor.fetchone()
                if not win_row or len(win_row) < 2:
                    return
                window_ret_pct, window_trade_count = win_row[0], win_row[1]

                window_ret_pct = float(window_ret_pct or 0.0)
                window_trade_count = int(window_trade_count or 0)
                if window_trade_count <= 0:
                    return

                desired_paper_trade = window_ret_pct < threshold
                current_paper_trade = bool(current_paper_trade)

                if desired_paper_trade == current_paper_trade:
                    return

                now_ts = time.time()
                last_switch_ts = self._regime_last_switch_at.get(monitor_name)
                if (not force_immediate) and last_switch_ts is not None and (now_ts - last_switch_ts) < cooldown_seconds:
                    self.log_event(
                        "REGIME_COOLDOWN",
                        f"Skipping regime switch for {monitor_name} due to cooldown",
                        {
                            "window_ret_pct": window_ret_pct,
                            "window_trade_count": window_trade_count,
                            "cooldown_seconds": cooldown_seconds,
                            "elapsed_seconds": round(now_ts - last_switch_ts, 2),
                        },
                    )
                    return

                cursor.execute(
                    sql.SQL(
                        """
                    UPDATE {}
                    SET paper_trade = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """
                    ).format(ml_ident),
                    (desired_paper_trade, monitor_id),
                )
                conn.commit()

                self._regime_last_switch_at[monitor_name] = now_ts
                self.log_event(
                    "REGIME_SWITCH",
                    f"Regime switch applied for {monitor_name}",
                    {
                        "desired_paper_trade": desired_paper_trade,
                        "window_ret_pct": window_ret_pct,
                        "window_trade_count": window_trade_count,
                        "regime_window": regime_window,
                    },
                )
                self._notify_frontend_monitor_list_updated(
                    f"Regime switch: {monitor_name} -> {'PAPER' if desired_paper_trade else 'LIVE'}"
                )

        except Exception as e:
            self.log_event("ERROR", f"Regime monitor evaluation failed for {monitor_name}: {e}")
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def handle_trade_status_update(self, trade_id: int, status: str, monitor: str = None, bulk_update: bool = False, ticker: str = None) -> Dict[str, Any]:
        """
        Handle trade status updates and automatically update monitor statistics if needed
        Called when trades are closed, settled, or have other status changes
        """
        try:
            # Only update monitor statistics for closed or settled trades
            if status in ['closed', 'settled'] and monitor:
                if bulk_update:
                    self.log_event("TRADE_UPDATE", f"Bulk trade closure for ticker {ticker}, monitor {monitor}, updating statistics")
                else:
                    self.log_event("TRADE_UPDATE", f"Trade {trade_id} {status} for monitor {monitor}, updating statistics")
                
                # Update statistics for the specific monitor
                result = self.update_monitor_statistics_from_trades()
                
                self._notify_frontend_monitor_statistics(
                    {
                        "monitor": monitor,
                        "trade_id": trade_id,
                        "status": status,
                        "bulk_update": bulk_update,
                        "ticker": ticker,
                        "timestamp": time.time(),
                    }
                )

                # Regime Monitor: evaluate rolling performance and switch LIVE/PAPER if enabled.
                try:
                    if status in ("closed", "settled") and monitor:
                        self._evaluate_and_switch_regime(monitor)
                except Exception as e:
                    self.log_event("ERROR", f"Regime evaluation hook failed: {e}")

                try:
                    from backend.core.performance_rollups import schedule_performance_rollup_recompute

                    schedule_performance_rollup_recompute(_mm_worker_slot())
                except Exception as e:
                    self.log_event("ERROR", f"Performance rollup recompute schedule failed: {e}")

                return result
            else:
                return {"status": "skipped", "message": f"Trade status {status} does not require statistics update"}
                
        except Exception as e:
            self.log_event("ERROR", f"Error handling trade status update: {e}")
            return {"status": "error", "message": str(e)}

    def reconcile_regime_for_monitor(self, monitor_id: int, user_number: str = "0001", force_immediate: bool = False) -> Dict[str, Any]:
        """Immediately run regime evaluation for a single monitor."""
        conn = None
        try:
            slot = _norm_slot(user_number)
            ml_ident = sql_ident_qualified_table(monitor_list_fqn(slot))
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SELECT name FROM {} WHERE id = %s").format(ml_ident),
                    (monitor_id,),
                )
                row = cursor.fetchone()
                if not row or not row[0]:
                    return {"status": "error", "message": f"Monitor not found: {monitor_id}"}
                monitor_name = row[0]

            self._evaluate_and_switch_regime(monitor_name, force_immediate=force_immediate)
            return {
                "status": "success",
                "message": f"Regime reconcile completed for monitor {monitor_name}",
                "monitor": monitor_name,
            }
        except Exception as e:
            self.log_event("ERROR", f"Error reconciling regime for monitor {monitor_id}: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def reconcile_regime_full_sweep(self, user_number: str = "0001", force_immediate: bool = False) -> Dict[str, Any]:
        """Run regime evaluation across the monitor list immediately."""
        conn = None
        try:
            slot = _norm_slot(user_number)
            ml_ident = sql_ident_qualified_table(monitor_list_fqn(slot))
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                    SELECT name
                    FROM {}
                    WHERE name IS NOT NULL
                      AND status != 'ARCHIVED'
                    ORDER BY id
                    """
                    ).format(ml_ident)
                )
                monitor_names = [row[0] for row in cursor.fetchall() if row and row[0]]

            reconciled = 0
            for monitor_name in monitor_names:
                self._evaluate_and_switch_regime(monitor_name, force_immediate=force_immediate)
                reconciled += 1

            return {
                "status": "success",
                "message": f"Regime full sweep completed ({reconciled} monitors checked)",
                "count": reconciled,
            }
        except Exception as e:
            self.log_event("ERROR", f"Error running regime full sweep: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def periodic_monitor_statistics_update(self) -> Dict[str, Any]:
        """
        Periodically update all monitor statistics from trades database
        This can be called on a schedule or manually for maintenance
        """
        try:
            self.log_event("PERIODIC_UPDATE", "Starting periodic monitor statistics update")
            
            result = self.update_monitor_statistics_from_trades()
            
            if result.get('status') == 'success':
                self.log_event("PERIODIC_UPDATE", f"Periodic update completed: {result.get('message')}")
            else:
                self.log_event("PERIODIC_UPDATE_ERROR", f"Periodic update failed: {result.get('message')}")
            
            return result
            
        except Exception as e:
            self.log_event("ERROR", f"Error in periodic monitor statistics update: {e}")
            return {"status": "error", "message": str(e)}

    def get_monitor_statistics(self, monitor_id: int) -> Dict[str, Any]:
        """
        Get current statistics for a specific monitor
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                ml = _mm_monitor_list_qualified()
                cursor.execute(
                    sql.SQL(
                        """
                    SELECT 
                        id, name, symbol, strategy, trades, win_loss, ret_pct, pnl,
                        bankroll_allotment_total, total_position, status
                    FROM {} 
                    WHERE id = %s
                """
                    ).format(ml),
                    (monitor_id,),
                )
                
                result = cursor.fetchone()
                if result and len(result) >= 11:
                    monitor_id, name, symbol, strategy, trades, win_loss, ret_pct, pnl, bankroll_allotment_total, total_position, status = result
                    
                    return {
                        "status": "success",
                        "monitor": {
                            "id": monitor_id,
                            "name": name,
                            "symbol": symbol,
                            "strategy": strategy,
                            "trades": trades,
                            "win_loss": win_loss,
                            "ret_pct": ret_pct,
                            "pnl": pnl,
                            "bankroll_allotment_total": bankroll_allotment_total,
                            "total_position": total_position,
                            "status": status
                        }
                    }
                if result and len(result) < 11:
                    return {
                        "status": "error",
                        "message": "Monitor row shape mismatch (expected 11 columns)",
                    }
                return {"status": "error", "message": "Monitor not found"}
                
        except Exception as e:
            self.log_event("ERROR", f"Error getting monitor statistics: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def get_all_monitor_statistics(self) -> Dict[str, Any]:
        """
        Get current statistics for all monitors
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                ml = _mm_monitor_list_qualified()
                cursor.execute(
                    sql.SQL(
                        """
                    SELECT 
                        id, name, symbol, strategy, trades, win_loss, ret_pct, pnl,
                        bankroll_allotment_total, total_position, status
                    FROM {} 
                    ORDER BY id
                """
                    ).format(ml)
                )
                
                monitors = []
                for row in cursor.fetchall():
                    if not row or len(row) < 11:
                        self.log_event(
                            "ERROR",
                            f"Skipping monitor row with unexpected width (expected 11 cols): {row!r}",
                        )
                        continue
                    monitor_id, name, symbol, strategy, trades, win_loss, ret_pct, pnl, bankroll_allotment_total, total_position, status = row
                    
                    monitors.append({
                        "id": monitor_id,
                        "name": name,
                        "symbol": symbol,
                        "strategy": strategy,
                        "trades": trades,
                        "win_loss": win_loss,
                        "ret_pct": ret_pct,
                        "pnl": pnl,
                        "bankroll_allotment_total": bankroll_allotment_total,
                        "total_position": total_position,
                        "status": status
                    })
                
                return {
                    "status": "success",
                    "monitors": monitors,
                    "count": len(monitors)
                }
                
        except Exception as e:
            self.log_event("ERROR", f"Error getting all monitor statistics: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def cleanup_inactive_monitor_logs(self):
        """Clean up log files for inactive and archived monitors"""
        try:
            _logger.debug("Starting cleanup of inactive monitor logs")
            
            # Get inactive and archived monitor IDs from database
            inactive_monitor_ids = self._get_inactive_monitor_ids()
            
            if not inactive_monitor_ids:
                _logger.debug("No inactive monitors found, skipping log cleanup")
                return
            
            _logger.debug("Found %s inactive monitors: %s", len(inactive_monitor_ids), inactive_monitor_ids)
            
            # Create monitor_log_archive directory if it doesn't exist
            archive_dir = os.path.join(self.project_root, "logs", "log_archive", "monitor_log_archive")
            os.makedirs(archive_dir, exist_ok=True)
            
            # Move log files for inactive monitors
            moved_count = 0
            for monitor_id in inactive_monitor_ids:
                moved_count += self._move_monitor_logs_to_archive(monitor_id, archive_dir)
            
            _logger.debug("Log cleanup completed: %s files moved to archive", moved_count)
            self.log_event("LOG_CLEANUP", f"Cleaned up {moved_count} log files for {len(inactive_monitor_ids)} inactive monitors")
            
        except Exception as e:
            _logger.error("Error during log cleanup: %s", e)
            self.log_event("LOG_CLEANUP_ERROR", f"Log cleanup failed: {str(e)}")
    
    def _get_inactive_monitor_ids(self) -> List[str]:
        """Get list of monitor IDs that are inactive or archived"""
        try:
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                ml = _mm_monitor_list_qualified()
                cursor.execute(
                    sql.SQL(
                        "SELECT id FROM {} WHERE status IN ('inactive', 'ARCHIVED') ORDER BY id"
                    ).format(ml)
                )
                return [str(row[0]) for row in cursor.fetchall()]
        except Exception as e:
            _logger.error("Error getting inactive monitor IDs: %s", e)
            return []
    
    def _move_monitor_logs_to_archive(self, monitor_id: str, archive_dir: str) -> int:
        """Move all log files for a specific monitor to the archive directory"""
        moved_count = 0
        logs_dir = os.path.join(self.project_root, "logs")
        
        # Define log file patterns for this monitor - catch all log file types
        slot = _mm_worker_slot()
        log_patterns = [
            f"active_trade_supervisor_{slot}_{monitor_id}*.log",
            f"auto_entry_supervisor_{slot}_{monitor_id}*.log",
        ]
        
        try:
            import glob
            
            for pattern in log_patterns:
                log_files = glob.glob(os.path.join(logs_dir, pattern))
                
                for log_file in log_files:
                    if os.path.isfile(log_file):
                        filename = os.path.basename(log_file)
                        destination = os.path.join(archive_dir, filename)
                        
                        # Move the file
                        os.rename(log_file, destination)
                        moved_count += 1
                        _logger.debug("Moved: %s -> monitor_log_archive/", filename)
            
        except Exception as e:
            _logger.error("Error moving logs for monitor %s: %s", monitor_id, e)
        
        return moved_count
    
    def cleanup_orphaned_monitor_logs(self):
        """Clean up log files for monitors that don't exist in the database"""
        try:
            _logger.debug("Starting cleanup of orphaned monitor logs")
            
            # Get all monitor IDs from database
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                ml = _mm_monitor_list_qualified()
                cursor.execute(sql.SQL("SELECT id FROM {} ORDER BY id").format(ml))
                valid_monitor_ids = {str(row[0]) for row in cursor.fetchall()}
            
            # Create monitor_log_archive directory if it doesn't exist
            archive_dir = os.path.join(self.project_root, "logs", "log_archive", "monitor_log_archive")
            os.makedirs(archive_dir, exist_ok=True)
            
            logs_dir = os.path.join(self.project_root, "logs")
            moved_count = 0
            
            # Find all monitor log files
            import glob
            all_log_files = glob.glob(
                os.path.join(logs_dir, f"*_{_mm_worker_slot()}_*.log")
            )
            
            for log_file in all_log_files:
                filename = os.path.basename(log_file)
                
                # Extract monitor ID from filename
                # Pattern: service_<slot>_MONITOR_ID.suffix.log
                parts = filename.split("_")
                slot = _mm_worker_slot()
                try:
                    idx_slot = parts.index(slot)
                    if idx_slot + 1 < len(parts):
                        monitor_id = parts[idx_slot + 1].split(".")[0]
                    else:
                        continue
                except ValueError:
                    continue
                
                # Check if this monitor ID exists in database
                if monitor_id not in valid_monitor_ids:
                    destination = os.path.join(archive_dir, filename)
                    os.rename(log_file, destination)
                    moved_count += 1
                    _logger.debug("Moved orphaned: %s -> monitor_log_archive/", filename)
            
            _logger.debug("Orphaned log cleanup completed: %s files moved to archive", moved_count)
            if moved_count > 0:
                self.log_event("ORPHANED_LOG_CLEANUP", f"Cleaned up {moved_count} orphaned log files")
            
        except Exception as e:
            _logger.error("Error during orphaned log cleanup: %s", e)
            self.log_event("ORPHANED_LOG_CLEANUP_ERROR", f"Orphaned log cleanup failed: {str(e)}")
    
    def perform_startup_cleanup(self):
        """Perform cleanup tasks on startup"""
        try:
            _logger.debug("Performing startup cleanup")
            
            # Clean up inactive monitor logs
            self.cleanup_inactive_monitor_logs()
            
            # Clean up orphaned monitor logs
            self.cleanup_orphaned_monitor_logs()
            
            _logger.debug("Startup cleanup completed")
            
        except Exception as e:
            _logger.error("Error during startup cleanup: %s", e)
    
    def start_daily_cleanup_scheduler(self):
        """Start the daily cleanup scheduler thread"""
        if not self.cleanup_running:
            self.cleanup_running = True
            self.cleanup_thread = threading.Thread(target=self._daily_cleanup_loop, daemon=True)
            self.cleanup_thread.start()
            _logger.debug("Daily cleanup scheduler started")

    def start_total_position_refresher(self, interval_seconds: int = 30):
        """Start a lightweight background loop that periodically validates/recalculates total_position.

        This is a temporary safety net for the legacy position sizing system: on each run we call
        recalculate_monitor_total_positions(), which walks active monitors and recomputes
        total_position from the current position_size / position_type / multiplier /
        bankroll_allotment_total and caps. It is intentionally low-touch and scoped to
        correcting drift; the long-term solution will live in the Redis refactor.
        """
        def _loop():
            _logger.debug("Total position refresher loop started (interval=%ss)", interval_seconds)
            while True:
                try:
                    result = self.recalculate_monitor_total_positions()
                    if isinstance(result, dict) and result.get("status") == "success":
                        _logger.debug(
                            "Total position refresher: %s",
                            result.get("message", "recalculated"),
                        )
                    else:
                        _logger.debug("Total position refresher: %s", result)
                except Exception as e:
                    _logger.error("Total position refresher error: %s", e)
                time.sleep(interval_seconds)

        threading.Thread(target=_loop, daemon=True).start()
    
    def stop_daily_cleanup_scheduler(self):
        """Stop the daily cleanup scheduler thread"""
        self.cleanup_running = False
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)
        _logger.debug("Daily cleanup scheduler stopped")
    
    def _daily_cleanup_loop(self):
        """Main loop for daily cleanup scheduler"""
        while self.cleanup_running:
            try:
                current_time = now_est().time()
                current_date = today_est()
                
                # Check if it's midnight (00:00) Eastern and we haven't run cleanup today
                if (current_time.hour == 0 and current_time.minute == 0 and 
                    self.last_cleanup_date != current_date):
                    
                    _logger.debug("Midnight detected - running daily log cleanup")
                    self.perform_startup_cleanup()
                    self.last_cleanup_date = current_date
                    _logger.debug("Daily cleanup completed")
                
                # Sleep for 1 minute to check again
                time.sleep(60)
                
            except Exception as e:
                _logger.error("Error in daily cleanup scheduler: %s", e)
                time.sleep(300)  # Wait 5 minutes on error

# Global instance
monitor_manager = MonitorManager()

# Initialize bankroll allotments on startup
try:
    monitor_manager.log_event("STARTUP", "Monitor manager starting up, initializing bankroll allotments")
    init_result = monitor_manager.initialize_bankroll_allotments()
    monitor_manager.log_event("STARTUP", f"Startup initialization completed: {init_result}")
    
    # Also initialize monitor statistics on startup
    monitor_manager.log_event("STARTUP", "Initializing monitor statistics from trades database")
    stats_result = monitor_manager.update_monitor_statistics_from_trades()
    monitor_manager.log_event("STARTUP", f"Monitor statistics initialization completed: {stats_result}")

    try:
        monitor_manager.log_event("STARTUP", "Recomputing performance rollup tables (totals + per-monitor)")
        from backend.core.performance_rollups import recompute_performance_rollups_for_slot

        rollup_result = recompute_performance_rollups_for_slot(_mm_worker_slot())
        monitor_manager.log_event("STARTUP", f"Performance rollups startup recompute: {rollup_result}")
    except Exception as rollup_err:
        monitor_manager.log_event(
            "STARTUP_ERROR", f"Performance rollups startup recompute failed: {rollup_err}"
        )

    # Align LIVE/PAPER with rolling performance for monitors that have regime monitoring enabled.
    # force_immediate=True: first evaluation after process start should not sit behind cooldown.
    try:
        monitor_manager.log_event("STARTUP", "Running regime monitor reconciliation on startup")
        regime_result = monitor_manager.reconcile_regime_full_sweep(
            user_number="0001", force_immediate=True
        )
        monitor_manager.log_event(
            "STARTUP", f"Startup regime reconciliation completed: {regime_result}"
        )
    except Exception as regime_err:
        monitor_manager.log_event(
            "STARTUP_ERROR", f"Startup regime reconciliation failed: {regime_err}"
        )

except Exception as e:
    monitor_manager.log_event("STARTUP_ERROR", f"Failed to initialize on startup: {str(e)}")

# === API ENDPOINTS (Starting Point) ===

@app.route('/api/bankroll_updated', methods=['POST'])
def bankroll_updated():
    """Endpoint called by kalshi_account_sync when bankroll changes. Body may include bankroll_stepped_down=True after a configured drawdown step-down; monitor_manager then snapshots monitors and forces paper + test_filter."""
    payload = request.get_json(silent=True) or {}
    bankroll_stepped_down = payload.get("bankroll_stepped_down", False)
    return jsonify(monitor_manager.handle_bankroll_update(bankroll_stepped_down=bankroll_stepped_down))

@app.route('/api/sync_bankroll_allotments', methods=['POST'])
def sync_bankroll_allotments():
    """Manually trigger bankroll allotment sync - updates bankroll_allotment_total for all active monitors"""
    try:
        _logger.debug("Manual bankroll allotment sync requested")
        result = monitor_manager.handle_bankroll_update()
        return jsonify(result)
    except Exception as e:
        _logger.error("Error in manual bankroll allotment sync: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/update_monitor_position', methods=['POST'])
def update_monitor_position_variables():
    """Update monitor position variables and recalculate total_position"""
    try:
        data = request.get_json() or {}
        monitor_id_raw = data.get('monitor_id')
        position_size = data.get('position_size')
        position_type = data.get('position_type')
        multiplier = data.get('multiplier')

        user_slot: Optional[str] = None
        if isinstance(monitor_id_raw, str) and monitor_id_raw.startswith('mon_'):
            parts = monitor_id_raw.split('_')
            if len(parts) >= 3 and parts[1].isdigit():
                user_slot = _norm_slot(parts[1])
        if user_slot is None:
            raw_u = data.get('user_number') or data.get('user_id')
            if raw_u is not None:
                user_slot = _mm_resolve_user_no(str(raw_u))
            else:
                user_slot = _mm_resolve_user_no(None)

        # Extract numeric monitor ID from format like "mon_0001_10019" or "10019"
        if isinstance(monitor_id_raw, str) and '_' in monitor_id_raw:
            parts = monitor_id_raw.split('_')
            if len(parts) >= 3:
                monitor_id = int(parts[-1])
            else:
                monitor_id = int(monitor_id_raw)
        else:
            monitor_id = int(monitor_id_raw) if monitor_id_raw is not None else None

        if monitor_id is None:
            return jsonify({'success': False, 'error': 'Invalid monitor_id'}), 400

        _logger.debug(
            "Updating monitor %s (from %s) slot=%s position variables",
            monitor_id,
            monitor_id_raw,
            user_slot,
        )
        _logger.debug("Position size: %s, type: %s, multiplier: %s", position_size, position_type, multiplier)

        result = monitor_manager.update_monitor_position_variables(
            monitor_id,
            position_size,
            position_type,
            multiplier,
            user_number=user_slot,
        )

        if result.get('status') == 'error':
            return jsonify({'success': False, 'error': result.get('message')}), 500

        total_position = result.get('total_position', 0)

        return jsonify({'success': True, 'total_position': total_position})

    except Exception as e:
        _logger.error("Error updating monitor position: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/sync_monitor_processes', methods=['POST'])
def sync_monitor_processes():
    """Manually trigger monitor process sync"""
    try:
        _logger.debug("Manual monitor process sync requested")
        
        # Use monitor_manager's built-in sync method
        success = monitor_manager.sync_monitor_processes()
        
        if success:
            return jsonify({'success': True, 'message': 'Monitor processes synced successfully'})
        else:
            return jsonify({'success': False, 'error': 'Monitor process sync failed'}), 500
        
    except Exception as e:
        _logger.error("Error in manual sync: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/initialize_allotments', methods=['POST'])
def initialize_allotments():
    """Endpoint to recalculate total_position for all monitors when position variables change"""
    return jsonify(monitor_manager.recalculate_monitor_total_positions())

@app.route('/api/update_monitor_statistics', methods=['POST'])
def update_monitor_statistics():
    """Update monitor statistics from trades database"""
    try:
        _logger.debug("Manual monitor statistics update requested")
        
        # Use monitor_manager's built-in method
        result = monitor_manager.update_monitor_statistics_from_trades()
        
        if result.get('status') == 'success':
            return jsonify({'success': True, 'message': result.get('message')})
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 500
        
    except Exception as e:
        _logger.error("Error in manual statistics update: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/periodic_monitor_statistics_update', methods=['POST'])
def periodic_monitor_statistics_update():
    """Trigger periodic update of all monitor statistics"""
    try:
        _logger.debug("Periodic monitor statistics update requested")
        
        # Use monitor_manager's built-in method
        result = monitor_manager.periodic_monitor_statistics_update()
        
        if result.get('status') == 'success':
            return jsonify({'success': True, 'message': result.get('message')})
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 500
        
    except Exception as e:
        _logger.error("Error in periodic statistics update: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500

def _strategy_defaults_tuple_to_dict(result) -> Dict[str, Any]:
    """Map strategy_list row tuple (from get_strategy_default_settings SELECT) to a dict."""
    return {
        "win_streak_threshold": result[0],
        "loss_prevention": result[1],
        "loss_prevention_toggle": result[2],
        "performance_based_allocation": result[3],
        "max_price_spread": float(result[4]) if result[4] is not None else 0.0300,
        "paper_trade": bool(result[5]) if result[5] is not None else False,
        "prob_adj": float(result[6]) if result[6] is not None else 5.00,
        "position_size": result[7],
        "position_type": result[8],
        "multiplier": float(result[9]) if result[9] is not None else 1.00,
        "min_probability": float(result[10]) if result[10] is not None else None,
        "max_probability": float(result[11]) if result[11] is not None else None,
        "min_differential": float(result[12]) if result[12] else 0.25,
        "max_differential": float(result[13]) if result[13] is not None else None,
        "min_time": result[14],
        "max_time": result[15],
        "allow_re_entry": result[16],
        "spike_alert_enabled": result[17],
        "spike_alert_momentum_threshold": result[18],
        "spike_alert_cooldown_threshold": result[19],
        "spike_alert_cooldown_minutes": result[20],
        "current_probability": result[21],
        "min_ttc_seconds": result[22],
        "momentum_spike_enabled": result[23],
        "momentum_spike_threshold": result[24],
        "verification_period_enabled": result[25],
        "verification_period_seconds": result[26],
        "min_volume": result[27],
        "momentum_scalp_entry_threshold": float(result[28]) if result[28] is not None else None,
        "momentum_scalp_trailing_stop_amount": float(result[29]) if result[29] is not None else 0.10,
        "momentum_scalp_profit_target": float(result[30]) if result[30] is not None else 0.99,
        "min_ask": float(result[31]) if result[31] is not None else 0.0000,
        "max_ask": float(result[32]) if result[32] is not None else 0.9800,
        "max_profit": float(result[33]) if result[33] is not None else 0.9900,
        "min_ask_range": float(result[34]) if result[34] is not None else None,
        "stop_loss_price": float(result[35]) if result[35] is not None else 0.0,
        "min_cooldown_timer": int(result[36]) if result[36] is not None else 300,
        "max_cooldown_timer": int(result[37]) if result[37] is not None else 3300,
        "regime_monitor_enabled": bool(result[38]) if result[38] is not None else False,
        "regime_window": (result[39] if result[39] is not None else "30d"),
        "time_in_force": (result[40] if result[40] is not None else "fill_or_kill"),
        "order_type": (result[41] if result[41] is not None else "market"),
        "symbol_wide_loss_prevention": bool(result[42]) if result[42] is not None else False,
        "symbol_wide_cooldown_duration": int(result[43]) if result[43] is not None else 4,
        "symbol_wide_cooldown_start_time": result[44],
        "flip_sell_prob": bool(result[45]) if result[45] is not None else False,
        "flip_sell_floor": bool(result[46]) if result[46] is not None else False,
        "flip_sell_prob_mult": result[47],
        "flip_sell_floor_mult": result[48],
    }


def _code_fallback_strategy_defaults() -> Dict[str, Any]:
    """Last-resort defaults when tenant and system.strategy_list_default both miss the strategy."""
    return {
        "win_streak_threshold": 22,
        "loss_prevention": "none",
        "loss_prevention_toggle": True,
        "performance_based_allocation": False,
        "max_price_spread": 0.0300,
        "paper_trade": False,
        "prob_adj": 5.00,
        "position_size": 1,
        "position_type": "percent",
        "multiplier": 1.00,
        "min_probability": 25,
        "max_probability": None,
        "min_differential": 0.25,
        "max_differential": None,
        "min_time": 0,
        "max_time": 0,
        "allow_re_entry": False,
        "spike_alert_enabled": False,
        "spike_alert_momentum_threshold": 80,
        "spike_alert_cooldown_threshold": 60,
        "spike_alert_cooldown_minutes": 30,
        "current_probability": None,
        "min_ttc_seconds": 0,
        "momentum_spike_enabled": False,
        "momentum_spike_threshold": 70,
        "verification_period_enabled": False,
        "verification_period_seconds": 60,
        "min_volume": 0,
        "momentum_scalp_entry_threshold": None,
        "momentum_scalp_trailing_stop_amount": 0.10,
        "momentum_scalp_profit_target": 0.99,
        "min_ask": 0.0000,
        "max_ask": 0.9800,
        "max_profit": 0.9900,
        "min_ask_range": None,
        "stop_loss_price": 0.0,
        "min_cooldown_timer": 300,
        "max_cooldown_timer": 3300,
        "regime_monitor_enabled": False,
        "regime_window": "30d",
        "time_in_force": "fill_or_kill",
        "order_type": "market",
        "symbol_wide_loss_prevention": False,
        "symbol_wide_cooldown_duration": 4,
        "symbol_wide_cooldown_start_time": None,
        "flip_sell_prob": False,
        "flip_sell_floor": False,
        "flip_sell_prob_mult": None,
        "flip_sell_floor_mult": None,
    }


def _fetch_strategy_defaults_row(cursor, table_ident, strategy_name):
    """
    Return one row of strategy defaults or None.
    Raises psycopg2.ProgrammingError if the table lacks expected columns.
    """
    sel = sql.SQL(
        """
        SELECT
            win_streak_threshold, loss_prevention, loss_prevention_toggle,
            performance_based_allocation, max_price_spread, paper_trade, prob_adj,
            position_size, position_type, multiplier,
            min_probability, max_probability, min_differential, max_differential,
            min_time, max_time, allow_re_entry,
            spike_alert_enabled, spike_alert_momentum_threshold,
            spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
            current_probability, min_ttc_seconds, momentum_spike_enabled,
            momentum_spike_threshold, verification_period_enabled,
            verification_period_seconds, min_volume,
            momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount,
            momentum_scalp_profit_target, min_ask, max_ask, max_profit,
            min_ask_range,
            stop_loss_price,
            min_cooldown_timer, max_cooldown_timer,
            regime_monitor_enabled, regime_window,
            time_in_force, order_type,
            symbol_wide_loss_prevention, symbol_wide_cooldown_duration, symbol_wide_cooldown_start_time,
            flip_sell_prob, flip_sell_floor, flip_sell_prob_mult, flip_sell_floor_mult
        FROM {}
        WHERE name = %s
        """
    ).format(table_ident)
    cursor.execute(sel, (strategy_name,))
    result = cursor.fetchone()
    if result:
        return result
    sel_lo = sql.SQL(
        """
        SELECT
            win_streak_threshold, loss_prevention, loss_prevention_toggle,
            performance_based_allocation, max_price_spread, paper_trade, prob_adj,
            position_size, position_type, multiplier,
            min_probability, max_probability, min_differential, max_differential,
            min_time, max_time, allow_re_entry,
            spike_alert_enabled, spike_alert_momentum_threshold,
            spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
            current_probability, min_ttc_seconds, momentum_spike_enabled,
            momentum_spike_threshold, verification_period_enabled,
            verification_period_seconds, min_volume,
            momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount,
            momentum_scalp_profit_target, min_ask, max_ask, max_profit,
            min_ask_range,
            stop_loss_price,
            min_cooldown_timer, max_cooldown_timer,
            regime_monitor_enabled, regime_window,
            time_in_force, order_type,
            symbol_wide_loss_prevention, symbol_wide_cooldown_duration, symbol_wide_cooldown_start_time,
            flip_sell_prob, flip_sell_floor, flip_sell_prob_mult, flip_sell_floor_mult
        FROM {}
        WHERE LOWER(name) = LOWER(%s)
        """
    ).format(table_ident)
    cursor.execute(sel_lo, (strategy_name,))
    return cursor.fetchone()


def get_strategy_default_settings(strategy_name, user_number="0001"):
    """
    Load per-strategy defaults from the tenant ``strategy_list_<slot>`` row.

    If that table is missing columns (name-only stub) or has no matching row, read from
    ``system.strategy_list_default`` (canonical mirror of slot 0001). Only then use
    built-in code fallbacks.
    """
    slot = _norm_slot(user_number)
    tenant_ident = sql_ident_qualified_table(strategy_list_fqn(slot))
    row = None

    conn = monitor_manager.get_database_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                try:
                    row = _fetch_strategy_defaults_row(cursor, tenant_ident, strategy_name)
                except psycopg2.ProgrammingError as pe:
                    _logger.debug(
                        "strategy defaults: tenant strategy_list not usable for slot %s: %s",
                        slot,
                        pe,
                    )
        except Exception as e:
            _logger.warning("strategy defaults: tenant read error: %s", e)
            row = None
        finally:
            conn.close()

    if row is None:
        sys_ident = sql.SQL("{}.{}").format(
            sql.Identifier("system"),
            sql.Identifier("strategy_list_default"),
        )
        sys_conn = get_system_postgresql_connection()
        if sys_conn:
            try:
                with sys_conn.cursor() as cursor:
                    try:
                        row = _fetch_strategy_defaults_row(cursor, sys_ident, strategy_name)
                    except psycopg2.ProgrammingError as pe:
                        _logger.debug("strategy defaults: system.strategy_list_default unreadable: %s", pe)
                        row = None
            except Exception as e:
                _logger.warning("strategy defaults: system read error: %s", e)
                row = None
            finally:
                sys_conn.close()

    if row:
        _logger.debug("Loaded strategy defaults for '%s' (tenant or system)", strategy_name)
        return _strategy_defaults_tuple_to_dict(row)

    _logger.debug("No DB row for strategy '%s'; using code fallback", strategy_name)
    return _code_fallback_strategy_defaults()

def _format_hour_label(hour_index: int) -> str:
    """Return time label matching contract_hour formatting."""
    if hour_index == 24:
        return "12am"
    if hour_index == 12:
        return "12pm"
    if hour_index > 12:
        return f"{hour_index - 12}pm"
    return f"{hour_index}am"


def initialize_monitor_performance_table(
    cursor,
    user_number: str,
    monitor_id: int,
    symbol: Optional[str],
    window_days: int = 84,
) -> None:
    """Create and seed the monitor_cycle_performance table for a new monitor."""
    u = _norm_slot(user_number)
    table_name = f"monitor_cycle_performance_{u}_{monitor_id}"
    table_identifier = sql.SQL("{}.{}").format(
        sql.Identifier(f"users_{u}"),
        sql.Identifier(table_name),
    )
    index_name = f"{table_name}_winrate_idx"

    cursor.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {} (
                weekly_cycle            SMALLINT PRIMARY KEY,
                day_name                TEXT,
                contract_hour           TEXT,
                trade_count             INT      NOT NULL DEFAULT 0,
                win_count               INT      NOT NULL DEFAULT 0,
                win_rate_pct            NUMERIC(5,2),
                avg_collateral_exposure INT,
                median_exposure         INT,
                max_exposure            INT,
                max_pct_exposure        NUMERIC(10,2) NOT NULL DEFAULT 0,
                performance_modifier    NUMERIC(10,2) NOT NULL DEFAULT 0,
                window_start            TIMESTAMPTZ,
                window_end              TIMESTAMPTZ,
                last_updated            TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        ).format(table_identifier)
    )

    cursor.execute(
        sql.SQL(
            "CREATE INDEX IF NOT EXISTS {} ON {} (win_rate_pct DESC NULLS LAST)"
        ).format(
            sql.Identifier(index_name),
            table_identifier
        )
    )

    cursor.execute(
        sql.SQL("SELECT COUNT(*) FROM {}").format(table_identifier)
    )
    existing_count = cursor.fetchone()[0] or 0
    if existing_count >= 168:
        return

    symbol_label = (symbol or "UNKNOWN").upper()
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=window_days)
    last_updated = window_end

    insert_sql = sql.SQL(
        """
        INSERT INTO {} (
            weekly_cycle,
            day_name,
            contract_hour,
            trade_count,
            win_count,
            win_rate_pct,
            avg_collateral_exposure,
            median_exposure,
            max_exposure,
            max_pct_exposure,
            performance_modifier,
            window_start,
            window_end,
            last_updated
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (weekly_cycle) DO NOTHING
        """
    ).format(table_identifier)

    day_names = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]

    for weekly_cycle in range(1, 169):
        day_index = (weekly_cycle - 1) // 24
        day_name = day_names[day_index]
        hour_index = ((weekly_cycle - 1) % 24) + 1
        hour_label = _format_hour_label(hour_index)
        contract_hour = f"{symbol_label} {hour_label}"

        cursor.execute(
            insert_sql,
            (
                weekly_cycle,
                day_name,
                contract_hour,
                0,
                0,
                0,
                0,
                0,
                0,
                0.25,
                1.00,
                window_start,
                window_end,
                last_updated,
            ),
        )

@app.route('/api/monitor/create', methods=['POST'])
def create_monitor():
    """Create a new monitor - business logic handled here"""
    try:
        data = request.get_json()
        
        # Extract parameters from request body
        symbol = data.get("symbol")
        strategy = data.get("strategy")
        bankroll_allotment_pct = data.get("bankroll_allotment_pct", 10)
        # Prefer strategy defaults unless explicitly overridden by request.
        position_size = data.get("position_size")
        multiplier = data.get("multiplier")
        user_id = data.get("user_id", "user_0001")
        raw_market = data.get("market", "hourly")
        market = "15m" if (raw_market and str(raw_market).strip().lower() == "15m") else "hourly"
        
        if not symbol or not strategy:
            return jsonify({"status": "error", "message": "Missing symbol or strategy parameter"}), 400
        
        # Extract user number from user_id (e.g., user_0001 -> 0001, user_2 -> 0002)
        user_number = _norm_slot(user_id.replace("user_", ""))

        # Get strategy default settings
        strategy_defaults = get_strategy_default_settings(strategy, user_number)
        if not strategy_defaults:
            _logger.warning("Monitor create: strategy_defaults empty for '%s'", strategy)
            strategy_defaults = _code_fallback_strategy_defaults()
        _logger.debug("Monitor create: using strategy defaults for '%s'", strategy)
        _logger.debug("Monitor create: min_time=%s max_time=%s min_probability=%s", strategy_defaults.get('min_time'), strategy_defaults.get('max_time'), strategy_defaults.get('min_probability'))
        _logger.debug("Monitor create: max_probability=%s min_differential=%s max_differential=%s", strategy_defaults.get('max_probability'), strategy_defaults.get('min_differential'), strategy_defaults.get('max_differential'))
        _logger.debug("Monitor create: spike_alert_enabled=%s momentum_spike_enabled=%s", strategy_defaults.get('spike_alert_enabled'), strategy_defaults.get('momentum_spike_enabled'))
        
        conn = monitor_manager.get_database_connection()
        if not conn:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500
        
        with conn.cursor() as cursor:
            # Get current bankroll to calculate allotment_total (paper vs live for this slot)
            ab_ident = sql_ident_qualified_table(account_balance_table_for_user(user_number))
            ml_ident = sql_ident_qualified_table(monitor_list_fqn(user_number))
            cursor.execute(
                sql.SQL(
                    """
                    SELECT bankroll_current, portfolio
                    FROM {}
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).format(ab_ident)
            )

            balance_result = cursor.fetchone()
            bankroll_value = balance_result[0] if balance_result and balance_result[0] else 0
            portfolio_value = balance_result[1] if balance_result and balance_result[1] else 0
            
            # Use bankroll_current if available, otherwise portfolio (both in cents)
            total_bankroll_cents = bankroll_value if bankroll_value > 0 else portfolio_value
            
            # Calculate bankroll_allotment_total
            bankroll_allotment_total = int((bankroll_allotment_pct / 100) * total_bankroll_cents)
            
            # Determine final position settings: use request values if provided, otherwise use strategy defaults
            final_position_size = position_size if position_size is not None else strategy_defaults.get('position_size', 1)
            final_position_type = data.get("position_type") if data.get("position_type") is not None else strategy_defaults.get('position_type', 'percent')
            final_multiplier = multiplier if multiplier is not None else strategy_defaults.get('multiplier', 1.0)
            
            # Calculate total_position based on final position settings
            multiplier_value = float(final_multiplier or 0)
            if multiplier_value == 0:
                total_position = 1
            elif final_position_type == 'percent':
                # For percent: round((position_size * allotment_dollars / 100) * multiplier)
                allotment_dollars = bankroll_allotment_total / 100
                total_position = int(round((final_position_size * allotment_dollars / 100) * multiplier_value))
            else:
                # For contracts: position_size * multiplier
                total_position = int(final_position_size * multiplier_value)
            
            # Let PostgreSQL handle the ID automatically with SERIAL
            cursor.execute(
                sql.SQL(
                    """
                INSERT INTO {}
                (name, symbol, market, strategy, default_strategy, auto_trade, auto_trade_status, status, bankroll_allotment_pct, bankroll_allotment_total, position_size, position_type, multiplier, total_position, trades, win_loss, ret_pct, pnl, dashboard_order, created,
                 win_streak_threshold, loss_prevention, loss_prevention_toggle, performance_based_allocation, max_price_spread, paper_trade, prob_adj,
                 min_probability, max_probability, min_differential, max_differential, min_time, max_time, allow_re_entry, spike_alert_enabled, spike_alert_momentum_threshold, spike_alert_cooldown_threshold, spike_alert_cooldown_minutes, current_probability, min_ttc_seconds, momentum_spike_enabled, momentum_spike_threshold, verification_period_enabled, verification_period_seconds, min_volume,
                 momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount, momentum_scalp_profit_target, min_ask, max_ask, max_profit, min_ask_range, stop_loss_price,
                 min_cooldown_timer, max_cooldown_timer,
                 regime_monitor_enabled, regime_window,
                 time_in_force, order_type,
                 symbol_wide_loss_prevention, symbol_wide_cooldown_duration, symbol_wide_cooldown_start_time,
                 flip_sell_prob, flip_sell_floor, flip_sell_prob_mult, flip_sell_floor_mult)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(),
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """
                ).format(ml_ident),
                (
                f"mon_{user_number}_temp",  # Temporary name
                symbol,
                market,  # market: hourly or 15m
                strategy,
                False,  # default_strategy (NOT NULL boolean; some tenant clones lack table default)
                False,  # auto_trade defaults to False
                'off',  # auto_trade_status defaults to 'off'
                'active',  # status defaults to 'active'
                bankroll_allotment_pct / 100,  # Convert to decimal
                bankroll_allotment_total,
                final_position_size,
                final_position_type,
                final_multiplier,
                total_position,
                0,  # trades defaults to 0
                0,  # win_loss defaults to 0
                0,  # ret_pct defaults to 0
                0,  # pnl defaults to 0
                999,  # dashboard_order defaults to 999 (end of list)
                # Strategy defaults (from strategy_list)
                strategy_defaults.get('win_streak_threshold', 22),
                (
                    "new"
                    if strategy_defaults.get('loss_prevention_toggle', True)
                    else "off"
                ),
                strategy_defaults.get('loss_prevention_toggle', True),
                strategy_defaults.get('performance_based_allocation', False),
                strategy_defaults.get('max_price_spread', 0.0300),
                bool(strategy_defaults.get('paper_trade', False)),
                strategy_defaults.get('prob_adj', 5.00),
                # Strategy default auto trade settings (from strategy_list)
                # Use values directly from strategy_defaults - they should all be present if strategy was found
                # Convert to appropriate types and use None if not present
                float(strategy_defaults.get('min_probability')) if strategy_defaults.get('min_probability') is not None else None,
                float(strategy_defaults.get('max_probability')) if strategy_defaults.get('max_probability') is not None else None,
                float(strategy_defaults.get('min_differential')) if strategy_defaults.get('min_differential') is not None else 0.25,
                float(strategy_defaults.get('max_differential')) if strategy_defaults.get('max_differential') is not None else None,
                int(strategy_defaults.get('min_time')) if strategy_defaults.get('min_time') is not None else None,
                int(strategy_defaults.get('max_time')) if strategy_defaults.get('max_time') is not None else None,
                strategy_defaults.get('allow_re_entry', False),
                strategy_defaults.get('spike_alert_enabled', False),
                strategy_defaults.get('spike_alert_momentum_threshold'),
                strategy_defaults.get('spike_alert_cooldown_threshold'),
                strategy_defaults.get('spike_alert_cooldown_minutes'),
                strategy_defaults.get('current_probability'),
                strategy_defaults.get('min_ttc_seconds'),
                strategy_defaults.get('momentum_spike_enabled', False),
                strategy_defaults.get('momentum_spike_threshold'),
                strategy_defaults.get('verification_period_enabled', False),
                strategy_defaults.get('verification_period_seconds'),
                strategy_defaults.get('min_volume'),
                # Momentum scalp settings
                strategy_defaults.get('momentum_scalp_entry_threshold'),
                strategy_defaults.get('momentum_scalp_trailing_stop_amount', 0.10),
                strategy_defaults.get('momentum_scalp_profit_target', 0.99),
                strategy_defaults.get('min_ask', 0.0000),
                strategy_defaults.get('max_ask', 0.9800),
                strategy_defaults.get('max_profit', 0.9900),
                float(strategy_defaults.get('min_ask_range')) if strategy_defaults.get('min_ask_range') is not None else None,
                float(strategy_defaults.get('stop_loss_price', 0.0) or 0.0),
                int(strategy_defaults.get('min_cooldown_timer', 300)),
                int(strategy_defaults.get('max_cooldown_timer', 3300)),
                strategy_defaults.get('regime_monitor_enabled', False),
                strategy_defaults.get('regime_window') or '30d',
                strategy_defaults.get('time_in_force') or 'fill_or_kill',
                strategy_defaults.get('order_type') or 'market',
                strategy_defaults.get('symbol_wide_loss_prevention', False),
                int(strategy_defaults.get('symbol_wide_cooldown_duration', 4)),
                None,  # symbol_wide_cooldown_start_time: always NULL on new monitor
                strategy_defaults.get('flip_sell_prob', False),
                strategy_defaults.get('flip_sell_floor', False),
                strategy_defaults.get('flip_sell_prob_mult'),
                strategy_defaults.get('flip_sell_floor_mult'),
                ),
            )

            # Get the generated ID
            monitor_id = cursor.fetchone()[0]
            
            # Generate the proper monitor name based on the ID
            monitor_name = f"mon_{user_number}_{monitor_id}"
            
            # Update the name with the correct ID
            cursor.execute(
                sql.SQL(
                    """
                UPDATE {}
                SET name = %s
                WHERE id = %s
            """
                ).format(ml_ident),
                (monitor_name, monitor_id),
            )

            initialize_monitor_performance_table(cursor, user_number, monitor_id, symbol)
            
        conn.commit()
        conn.close()
        
        monitor_manager.log_event("CREATE", f"Monitor created monitor_id={monitor_id} name={monitor_name}")
        
        # Spawn monitor processes for the new monitor
        monitor_data = {
            'user_number': user_number,
            'monitor_id': str(monitor_id),
            'name': monitor_name
        }
        spawn_ok = monitor_manager.spawn_monitor_processes(monitor_data)
        
        if not spawn_ok:
            # Surface a soft failure so callers know processes did not start
            monitor_manager.log_event(
                "ERROR",
                f"Monitor {monitor_name} created but failed to spawn processes; supervisor config/update returned error"
            )
            status_code = 207  # Multi-Status / partial success
            message = (
                f"Monitor {monitor_name} created, but failed to start auto-entry/active-trade supervisors. "
                "A MASTER_RESTART or manual investigation of monitor_manager logs may be required."
            )
        else:
            status_code = 200
            message = f"Monitor {monitor_name} created successfully"
        
        monitor_manager._notify_frontend_monitor_list_updated("Monitor created")
        return jsonify({
            "status": "ok" if spawn_ok else "partial",
            "message": message,
            "monitor_name": monitor_name,
            "monitor_id": monitor_id
        }), status_code
        
    except Exception as e:
        monitor_manager.log_event("ERROR", f"Error creating monitor: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "service": "monitor_manager",
        "version": "1.0.0",
        "capabilities": [
            "bankroll_updates", 
            "position_calculation", 
            "monitor_allotments", 
            "frontend_sync", 
            "monitor_creation", 
            "monitor_statistics_update",
            "trade_status_handling",
            "periodic_statistics_update",
            "individual_monitor_statistics",
            "all_monitor_statistics"
        ]
    })

@app.route('/api/monitor/<int:monitor_id>/statistics', methods=['GET'])
def get_monitor_statistics(monitor_id):
    """Get statistics for a specific monitor"""
    try:
        _logger.debug("Getting statistics for monitor %s", monitor_id)
        
        # Use monitor_manager's built-in method
        result = monitor_manager.get_monitor_statistics(monitor_id)
        
        if result.get('status') == 'success':
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 404
        
    except Exception as e:
        _logger.error("Error getting monitor statistics: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/monitors/statistics', methods=['GET'])
def get_all_monitor_statistics():
    """Get statistics for all monitors"""
    try:
        _logger.debug("Getting statistics for all monitors")
        
        # Use monitor_manager's built-in method
        result = monitor_manager.get_all_monitor_statistics()
        
        if result.get('status') == 'success':
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 500
        
    except Exception as e:
        _logger.error("Error getting all monitor statistics: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500

# === FUTURE ENDPOINTS (Foundation) ===

@app.route('/api/monitor_settings_update', methods=['POST'])
def monitor_settings_update():
    """Future: Handle monitor settings updates"""
    # TODO: Implement comprehensive settings management
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

@app.route('/api/toggle-auto-trade', methods=['POST'])
def toggle_auto_trade():
    """Toggle auto_trade boolean value for a specific monitor"""
    try:
        data = request.get_json()
        monitor_id = data.get("monitor_id")
        auto_trade = data.get("auto_trade")
        user_id = data.get("user_id", "user_0001")
        
        if not monitor_id or auto_trade is None:
            return jsonify({"status": "error", "message": "Missing monitor_id or auto_trade parameter"})
        
        # Extract user number and monitor ID from monitor_id (e.g., MON_0001_10001 -> user_0001, 10001)
        if monitor_id.startswith("MON_") and "_" in monitor_id:
            parts = monitor_id.split("_")
            if len(parts) >= 3:
                user_number = _norm_slot(parts[1])
                db_monitor_id = parts[2]
            else:
                return jsonify({"status": "error", "message": "Invalid monitor ID format"})
        else:
            return jsonify({"status": "error", "message": "Invalid monitor ID format"})
        
        conn = monitor_manager.get_database_connection()
        ml_ident = sql_ident_qualified_table(monitor_list_fqn(user_number))
        with conn.cursor() as cursor:
            # Update ONLY auto_trade boolean - do NOT change auto_trade_status
            cursor.execute(
                sql.SQL(
                    """
                UPDATE {}
                SET auto_trade = %s
                WHERE id = %s
            """
                ).format(ml_ident),
                (auto_trade, db_monitor_id),
            )
            
            if cursor.rowcount == 0:
                return jsonify({"status": "error", "message": "Monitor not found"})
            
        conn.commit()
        conn.close()
        
        monitor_manager._notify_frontend_monitor_list_updated("Auto trade toggled")
        return jsonify({"status": "ok", "message": f"Auto trade {'enabled' if auto_trade else 'disabled'} for monitor {monitor_id}"})
        
    except Exception as e:
        _logger.error("Error toggling auto trade: %s", e)
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/trade_state_update', methods=['POST'])
def trade_state_update():
    """Future: Handle trade state updates"""
    # TODO: Implement trade state management
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

@app.route('/api/sync_all_states', methods=['POST'])
def sync_all_states():
    """Future: Synchronize all monitor states"""
    # TODO: Implement comprehensive state synchronization
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

@app.route('/api/trade_status_update', methods=['POST'])
def trade_status_update():
    """Handle trade status updates and update monitor statistics if needed"""
    try:
        data = request.get_json()
        trade_id = data.get('trade_id')
        status = data.get('status')
        monitor = data.get('monitor')
        bulk_update = data.get('bulk_update', False)
        ticker = data.get('ticker')
        
        if not status:
            return jsonify({'success': False, 'error': 'Missing status parameter'}), 400
        
        if not bulk_update and not trade_id:
            return jsonify({'success': False, 'error': 'Missing trade_id parameter for individual trade updates'}), 400
        
        if not monitor:
            return jsonify({'success': False, 'error': 'Missing monitor parameter'}), 400
        
        if bulk_update:
            _logger.debug("Bulk trade status update: ticker %s status %s monitor %s", ticker, status, monitor)
        else:
            _logger.debug("Trade status update: ID %s status %s monitor %s", trade_id, status, monitor)
        
        # Use monitor_manager's built-in method
        result = monitor_manager.handle_trade_status_update(trade_id, status, monitor, bulk_update, ticker)
        
        if result.get('status') in ['success', 'skipped']:
            return jsonify({'success': True, 'message': result.get('message')})
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 500
        
    except Exception as e:
        _logger.error("Error handling trade status update: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/regime/reconcile', methods=['POST'])
def regime_reconcile():
    """Trigger immediate regime reconciliation after monitor setting changes."""
    try:
        data = request.get_json(silent=True) or {}
        user_number = str(data.get('user_number', '0001'))
        full_sweep = bool(data.get('full_sweep', False))
        monitor_id = data.get('monitor_id')
        force_immediate = bool(data.get('force_immediate', False))

        if full_sweep or monitor_id is None:
            result = monitor_manager.reconcile_regime_full_sweep(user_number=user_number, force_immediate=force_immediate)
        else:
            result = monitor_manager.reconcile_regime_for_monitor(int(monitor_id), user_number=user_number, force_immediate=force_immediate)

        if result.get("status") == "success":
            return jsonify({"success": True, **result})
        return jsonify({"success": False, **result}), 400
    except Exception as e:
        _logger.error("Error reconciling regime settings: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500

class MonitorStatusWatcher:
    """Background thread to watch for monitor status changes"""
    
    def __init__(self, monitor_manager_instance):
        self.monitor_manager = monitor_manager_instance
        self.running = False
        self.thread = None
        self.last_status = {}  # Cache of last known status for each monitor
        
    def start(self):
        """Start the status watcher thread"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._watch_loop, daemon=True)
            self.thread.start()
            _logger.debug("Monitor status watcher started")
    
    def stop(self):
        """Stop the status watcher thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        _logger.debug("Monitor status watcher stopped")
    
    def _watch_loop(self):
        """Main watching loop"""
        while self.running:
            try:
                self._check_for_status_changes()
                time.sleep(10)  # Check every 10 seconds
            except Exception as e:
                _logger.error("Error in status watcher: %s", e)
                time.sleep(30)  # Wait longer on error
    
    def _check_for_status_changes(self):
        """Check for monitor status changes in the database"""
        try:
            conn = self.monitor_manager.get_database_connection()
            with conn.cursor() as cursor:
                ml = _mm_monitor_list_qualified()
                cursor.execute(
                    sql.SQL("SELECT id, status FROM {} ORDER BY id").format(ml)
                )
                
                current_status = {}
                for row in cursor.fetchall():
                    monitor_id = row[0]
                    status = row[1]
                    current_status[monitor_id] = status
                
                conn.close()
                
                # Check for changes
                for monitor_id, status in current_status.items():
                    if monitor_id not in self.last_status or self.last_status[monitor_id] != status:
                        _logger.debug("Status change detected: Monitor %s changed from %s to %s", monitor_id, self.last_status.get(monitor_id, 'unknown'), status)
                        self._handle_status_change(monitor_id, status)
                        self.last_status[monitor_id] = status
                
                # Check for removed monitors
                for monitor_id in list(self.last_status.keys()):
                    if monitor_id not in current_status:
                        _logger.info("Monitor removed from database monitor_id=%s", monitor_id)
                        del self.last_status[monitor_id]
                        
        except Exception as e:
            _logger.error("Error checking status changes: %s", e)
    
    def _handle_status_change(self, monitor_id, new_status):
        """Handle a monitor status change"""
        try:
            _logger.debug("Status change detected: Monitor %s changed to %s", monitor_id, new_status)
            
            # Use monitor_manager's built-in sync method
            success = self.monitor_manager.sync_monitor_processes()
            
            if success:
                _logger.info("Monitor process sync completed successfully for monitor_id=%s", monitor_id)
            else:
                _logger.warning("Monitor process sync failed for monitor_id=%s", monitor_id)
                
        except Exception as e:
            _logger.error("Error handling status change for monitor %s: %s", monitor_id, e)

# Single process-global instance (startup init + Redis subscriber + Flask routes share this).
# Initialize the status watcher
status_watcher = MonitorStatusWatcher(monitor_manager)

def start_status_watcher():
    """Start the monitor status watcher when the Flask app starts"""
    status_watcher.start()

# Start the status watcher immediately
start_status_watcher()

# Start the daily cleanup scheduler
monitor_manager.start_daily_cleanup_scheduler()

# Temporary safety net: periodically validate/recalculate total_position for all active monitors.
# Long term this will be replaced by the Redis-backed position sizing pipeline.
monitor_manager.start_total_position_refresher(interval_seconds=30)


def start_monitor_manager_redis_subscriber() -> None:
    """trade_manager → monitor_manager trade events via Redis (rec_io:mm:trade_events)."""
    from backend.core.trading_redis_comms import channel_monitor_manager, redis_client_optional, use_trading_redis_comms

    if not use_trading_redis_comms():
        return

    def loop():
        backoff = 3.0
        while True:
            try:
                r = redis_client_optional()
                if not r:
                    time.sleep(backoff)
                    continue
                pubsub = r.pubsub()
                ch = channel_monitor_manager()
                pubsub.subscribe(ch)
                _logger.info("monitor_manager subscribed to Redis %s", ch)
                backoff = 3.0
                for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    raw = msg.get("data")
                    if raw is None:
                        continue
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    try:
                        if data.get("type") == "bankroll_updated":
                            monitor_manager.handle_bankroll_update(
                                bool(data.get("bankroll_stepped_down", False))
                            )
                            continue
                        monitor_manager.handle_trade_status_update(
                            data.get("trade_id"),
                            data.get("status"),
                            data.get("monitor"),
                            bool(data.get("bulk_update", False)),
                            data.get("ticker"),
                        )
                    except Exception as e:
                        _logger.warning("Redis trade_status handling: %s", e)
            except Exception as e:
                _logger.warning("monitor_manager Redis subscriber reconnect: %s", e)
                time.sleep(backoff)
                backoff = min(backoff * 1.3, 60.0)

    threading.Thread(target=loop, daemon=True, name="monitor-manager-redis").start()


start_monitor_manager_redis_subscriber()


def _handle_auto_entry_settings_stream(decoded: Dict[str, Any], msg_id: str, raw_fields: Dict[str, str]) -> bool:
    """Redis stream consumer: apply unified auto trade settings to monitor_list."""
    cid = ""
    try:
        from backend.core.auto_entry_settings_store import (
            apply_auto_entry_settings,
            trigger_regime_reconcile_after_auto_entry_save,
        )
        from backend.core.trading_redis_comms import (
            mm_monitor_settings_ack_key,
            redis_client_optional,
        )

        inner = decoded.get("payload") or {}
        if not isinstance(inner, dict):
            return True
        cid = str(decoded.get("correlation_id") or inner.get("correlation_id") or "")
        body = inner.get("body") or {}
        mid = str(inner.get("monitor_id") or body.get("monitor_id") or "")
        from backend.core.tenant_context import get_api_tenant_context, worker_tenant_context_cached
        from backend.trading_mode import _norm_slot

        un_raw = inner.get("user_number") or body.get("user_number")
        if un_raw is not None and str(un_raw).strip():
            try:
                tenant_user_no = _norm_slot(str(un_raw))
            except ValueError:
                tenant_user_no = worker_tenant_context_cached().user_no
        else:
            tenant_user_no = worker_tenant_context_cached().user_no
        tenant_ctx = get_api_tenant_context(tenant_user_no)

        conn = monitor_manager.get_database_connection()
        try:
            with conn.cursor() as cursor:
                result = apply_auto_entry_settings(cursor, mid, body, tenant_context=tenant_ctx)
            if result.get("status") == "ok":
                conn.commit()
                trigger_regime_reconcile_after_auto_entry_save(
                    mid,
                    user_number=tenant_user_no,
                    source="set_auto_entry_settings_redis",
                )
                monitor_manager._notify_frontend_monitor_list_updated(
                    "Auto trade settings updated (Redis)"
                )
            else:
                conn.rollback()
        finally:
            conn.close()

        r = redis_client_optional()
        if r and cid:
            r.set(mm_monitor_settings_ack_key(cid), json.dumps(result, default=str), ex=90)
        return True
    except Exception as e:
        _logger.warning("auto_entry_settings stream handler: %s", e)
        try:
            from backend.core.trading_redis_comms import mm_monitor_settings_ack_key, redis_client_optional

            r = redis_client_optional()
            if r and cid:
                r.set(
                    mm_monitor_settings_ack_key(cid),
                    json.dumps({"status": "error", "message": str(e)}, default=str),
                    ex=90,
                )
        except Exception:
            pass
        return True


def start_monitor_manager_auto_entry_settings_consumer() -> None:
    from backend.core.trading_redis_comms import (
        default_consumer_name,
        start_consumer_daemon,
        stream_mm_monitor_settings,
        use_trading_redis_comms,
    )

    if not use_trading_redis_comms():
        return
    stream = stream_mm_monitor_settings()
    group = "mm_monitor_settings"
    consumer = default_consumer_name("mm-settings")
    start_consumer_daemon(stream, group, consumer, _handle_auto_entry_settings_stream)
    _logger.info(
        "monitor_manager stream consumer started: %s group=%s",
        stream,
        group,
    )


start_monitor_manager_auto_entry_settings_consumer()


def _heartbeat_loop():
    while True:
        time.sleep(HEARTBEAT_INTERVAL_SEC)
        _logger.info("heartbeat")


if __name__ == "__main__":
    _logger.debug("Starting Core Monitor Management System")
    _hb = threading.Thread(target=_heartbeat_loop, daemon=True)
    _hb.start()
    # Perform startup cleanup (move inactive monitor logs to archive)
    # DISABLED: Too aggressive - moves logs to archive too quickly
    # monitor_manager.perform_startup_cleanup()
    monitor_port = get_port("monitor_manager")
    app.run(host='0.0.0.0', port=monitor_port, debug=False)
