#!/usr/bin/env python3
"""
UNIFIED SUPERVISOR CONFIGURATION GENERATOR
Generate supervisor configuration with unified configuration system.
Uses absolute paths and proper environment variables.
"""

import sys
import os
import re
from pathlib import Path
from typing import Optional

# Add project root to Python path (script lives in scripts/config/)
current_dir = Path(__file__).parent
project_root = current_dir.parent.parent
sys.path.insert(0, str(project_root))

from backend.core.unified_config import unified_config
from backend.core.config.database import get_database_config
from backend.core.path_manager import PathManager
from backend.core.host_detector import HostDetector
from backend.core.exchange_credentials import fetch_kalshi_enabled_map_for_user_nos
from backend.core.tenant_provision import ensure_tenant_schemas_for_active_users
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def global_core_service_specs():
    """
    Global autostart supervisor programs (name + script fragment).
    Shared with system_monitor service discovery — keep in sync with _generate_supervisor_content.
    """
    return [
        {"name": "main_app", "script": "main.py"},
        {"name": "read_api", "script": "read_api.py"},
        {"name": "redis_switchboard", "script": "redis_switchboard.py"},
        {"name": "cfbenchmarks_price_watchdog", "script": "cfbenchmarks_price_watchdog.py"},
        {
            "name": "market_watchdog_ws_kalshi",
            "script": "market_watchdog_ws.py --exchange kalshi --market all",
        },
        {"name": "system_monitor", "script": "system_monitor.py"},
        {"name": "cascading_failure_detector", "script": "cascading_failure_detector.py"},
    ]


class SupervisorConfigGenerator:
    """Generate supervisor config with unified configuration"""
    
    def __init__(self):
        """Initialize the supervisor config generator"""
        self.config = unified_config
        self.path_manager = PathManager(unified_config)
        self.host_detector = HostDetector(unified_config.project_root)
        
        logger.info("SupervisorConfigGenerator initialized")
    
    def generate_config(self) -> bool:
        """Generate complete supervisor configuration"""
        try:
            logger.info("Generating unified supervisor configuration...")
            
            # Validate configuration
            if not self.config.validate_config():
                logger.error("Configuration validation failed")
                return False
            
            # Get configuration values
            project_root = self.config.project_root
            python_executable = self.config.get('runtime.python_executable', sys.executable)
            system_host = self.config.get('runtime.system_host', 'localhost')
            
            # Get port assignments from MASTER_PORT_MANIFEST
            ports = self._get_port_assignments()
            
            # Generate supervisor configuration content
            supervisor_config = self._generate_supervisor_content(
                project_root, python_executable, system_host, ports
            )
            
            # Write supervisor configuration file
            supervisor_config_path = self.path_manager.get_supervisor_config_path()
            self.path_manager.ensure_file_directory_exists(supervisor_config_path)
            
            with open(supervisor_config_path, 'w') as f:
                f.write(supervisor_config)
            
            logger.info(f"Generated supervisor configuration: {supervisor_config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error generating supervisor configuration: {e}")
            return False
    
    def _discover_trading_user_nos(self) -> list:
        """
        Active rows in ``system.master_users`` → 4-digit slots.

        Prefer canonical ``user_no`` column (matches login tenant / ``users_NNNN``). Fall back to
        parsing ``user_id`` only when it looks like ``0002`` or ``user_0002`` (legacy).
        """
        nos = []
        master_rows_exist = False
        try:
            import psycopg2

            conn = psycopg2.connect(**get_database_config())
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM system.master_users")
                master_rows_exist = (cur.fetchone() or (0,))[0] > 0
                cur.execute(
                    """
                    SELECT user_no, user_id FROM system.master_users
                    WHERE COALESCE(NULLIF(TRIM(LOWER(status)), ''), 'active') = 'active'
                    ORDER BY user_no NULLS LAST, user_id
                    """
                )
                for row in cur.fetchall() or []:
                    u_no_col, uid = row[0], row[1] if len(row) > 1 else None
                    slot = None
                    un = str(u_no_col or "").strip()
                    if un:
                        if un.isdigit():
                            slot = un.zfill(4) if len(un) <= 4 else None
                        else:
                            m = re.fullmatch(r"(?:user_)?(\d{4})", un, flags=re.IGNORECASE)
                            if m:
                                slot = m.group(1)
                    if not slot and uid is not None:
                        raw = str(uid or "").strip()
                        m = re.fullmatch(r"(?:user_)?(\d{4})", raw, flags=re.IGNORECASE)
                        if m:
                            slot = m.group(1)
                    if slot and re.fullmatch(r"\d{4}", slot):
                        nos.append(slot)
            conn.close()
        except Exception as e:
            logger.warning("Could not read system.master_users (%s)", e)
            master_rows_exist = False

        if nos:
            return sorted(set(nos))
        # Table exists and has rows but none are trading-active: do not resurrect a slot from env.
        if master_rows_exist:
            return []
        p = (os.environ.get("REC_POOL_USER_NUMBER") or os.environ.get("REC_USER_NO") or "").strip()
        if p.isdigit():
            return sorted(set([p.zfill(4) if len(p) <= 4 else p[:4]]))
        return []

    @staticmethod
    def _scoped_port(
        ports: dict,
        base_key: str,
        user_no: str,
        default_port: int,
        *,
        ref_slot: str,
    ) -> int:
        """Prefer ``{base_key}_{user_no}`` from manifest; else offset from manifest ref slot."""
        sk = f"{base_key}_{user_no}"
        if sk in ports:
            return ports[sk]
        ref_key = f"{base_key}_{ref_slot}"
        base = ports.get(ref_key, default_port)
        try:
            delta = int(user_no) - int(ref_slot)
        except ValueError:
            delta = 0
        return base + delta * 10

    def _get_active_monitors_for_user(
        self, user_no: str, *, log_monitor_counts: bool = True
    ) -> list:
        """Monitors for AES/ATS and logging; one tenant schema ``users_<user_no>``."""
        monitors = []
        try:
            import psycopg2

            conn = psycopg2.connect(**get_database_config())
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, name, status,
                           LOWER(TRIM(COALESCE(NULLIF(TRIM(market), ''), 'hourly'))) AS market_norm
                    FROM users_{user_no}.monitor_list_{user_no}
                    WHERE status = 'active'
                    ORDER BY id
                    """
                )
                for row in cur.fetchall():
                    monitor_id = row[0]
                    name = row[1]
                    status = row[2]
                    market_raw = row[3] if len(row) > 3 else "hourly"
                    market_norm = (market_raw or "hourly").strip().lower()
                    if market_norm not in ("hourly", "15m"):
                        market_norm = "hourly"
                    if name.startswith("mon_"):
                        parts = name.split("_")
                        if len(parts) >= 3:
                            parsed_user = parts[1]
                            parsed_mon = parts[2]
                        else:
                            parsed_user = user_no
                            parsed_mon = str(monitor_id)
                    else:
                        parsed_user = user_no
                        parsed_mon = str(monitor_id)
                    monitors.append(
                        {
                            "id": parsed_mon,
                            "name": name,
                            "status": status,
                            "user_number": parsed_user,
                            "monitor_id": parsed_mon,
                            "market": market_norm,
                        }
                    )
            conn.close()
            if log_monitor_counts:
                logger.info("Found %s active monitors for user %s", len(monitors), user_no)
        except Exception as e:
            logger.error("Error getting monitors for %s: %s", user_no, e)
        return monitors

    def _get_active_monitors(self) -> list:
        """All active monitors across trading-user slots (e.g. system_monitor service discovery)."""
        combined: list = []
        for slot in self._discover_trading_user_nos():
            combined.extend(
                self._get_active_monitors_for_user(slot, log_monitor_counts=False)
            )
        return combined

    def _get_port_assignments(self) -> dict:
        """Get port assignments from MASTER_PORT_MANIFEST"""
        try:
            # Try to load from MASTER_PORT_MANIFEST
            manifest_path = self.path_manager.get_config_file_path("MASTER_PORT_MANIFEST")
            
            if self.path_manager.path_exists(manifest_path):
                import json
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)

                # Normalize legacy unsuffixed user-scoped service keys so every user-level/live-data
                # process has an explicit slot suffix in the manifest (e.g. trade_executor_0001).
                manifest_changed = self._normalize_user_scoped_manifest_keys(manifest)
                if manifest_changed:
                    temp_path = manifest_path + ".tmp"
                    with open(temp_path, "w") as f:
                        json.dump(manifest, f, indent=2)
                    os.replace(temp_path, manifest_path)
                    logger.info(
                        "Normalized MASTER_PORT_MANIFEST user-scoped keys to suffixed names: %s",
                        manifest_path,
                    )
                
                ports = {}
                
                # Extract ports from core_services
                for service_name, service_config in manifest.get("core_services", {}).items():
                    ports[service_name] = service_config.get("port", 3000)
                
                # Extract ports from watchdog_services
                for service_name, service_config in manifest.get("watchdog_services", {}).items():
                    ports[service_name] = service_config.get("port", 8000)
                
                logger.info(f"Loaded port assignments from MASTER_PORT_MANIFEST: {ports}")
                return ports
            
            # Fallback to default ports
            default_ports = {
                "main_app": 3000,
                "trade_manager_0001": 4000,
                "trade_executor_0001": 8001,
                "active_trade_supervisor": 6000,
                "auto_entry_supervisor": 8002,
                "cfbenchmarks_price_watchdog": 8008,
                "symbol_price_watchdog_spx": 8017,
                "symbol_price_watchdog_ndx": 8019,
                "kalshi_account_sync_0001": 8004,
                "market_watchdog_ws_kalshi": 8005,
                "strike_table_generator_ws_hourly": 8014,
                "strike_table_generator_ws_15m": 8036,
                "auto_entry_supervisor_15m": 8033,
                "active_trade_supervisor_15m": 8034,
                "auto_entry_supervisor_0001": 8033,
                "active_trade_supervisor_0001": 8034,
                "auto_entry_supervisor_hourly": 8037,
                "active_trade_supervisor_hourly": 8038,
                "system_monitor": 8006,
                "monitor_manager_0001": 8012,
                "kalshi_lifecycle_consumer_0001": 8040,
                "cascading_failure_detector": 8007
            }
            
            logger.info(f"Using default port assignments: {default_ports}")
            return default_ports
            
        except Exception as e:
            logger.error(f"Error getting port assignments: {e}")
            return {}

    def _normalize_user_scoped_manifest_keys(self, manifest: dict) -> bool:
        """
        Ensure services that require tenant suffixes are stored as ``<service>_<user_no>``.

        Legacy manifests may contain unsuffixed keys (e.g. ``trade_executor``). Those keys
        are migrated to the current pool user slot and removed.
        """
        if not isinstance(manifest, dict):
            return False

        scoped_bases = (
            "trade_manager",
            "trade_executor",
            "kalshi_account_sync",
            "monitor_manager",
            "auto_entry_supervisor",
            "active_trade_supervisor",
            "kalshi_lifecycle_consumer",
        )
        trading_users = self._discover_trading_user_nos()
        if trading_users:
            pool_user_no = sorted(trading_users)[0]
        else:
            p = (
                os.environ.get("REC_POOL_USER_NUMBER")
                or os.environ.get("REC_USER_NO")
                or "0001"
            ).strip()
            pool_user_no = p.zfill(4) if p.isdigit() and len(p) <= 4 else "0001"

        changed = False
        for section in ("core_services", "watchdog_services"):
            services = manifest.get(section)
            if not isinstance(services, dict):
                continue
            for base in scoped_bases:
                if base not in services:
                    continue
                suffixed = f"{base}_{pool_user_no}"
                if suffixed not in services:
                    services[suffixed] = services[base]
                del services[base]
                changed = True
                logger.warning(
                    "MASTER_PORT_MANIFEST: migrated legacy key '%s' -> '%s' in %s",
                    base,
                    suffixed,
                    section,
                )
        return changed
    
    def _generate_supervisor_content(self, project_root: str, python_executable: str, 
                                   system_host: str, ports: dict) -> str:
        """Generate supervisor configuration content"""
        
        # Use layered unified DB settings (config.local + env overrides), not process-only env
        # from backend.core.config.database.get_database_config() — bare regenerations default DB_HOST to localhost.
        udb = self.config.get_database_config() or {}
        db_name = udb.get("name") or udb.get("database") or "rec_io_db"
        try:
            db_port = int(udb.get("port", 5432))
        except (TypeError, ValueError):
            db_port = 5432
        db_config = {
            "host": udb.get("host", "localhost"),
            "database": db_name,
            "name": db_name,
            "user": udb.get("user", "rec_io_user"),
            "password": udb.get("password", "rec_io_password"),
            "port": db_port,
            "sslmode": udb.get("sslmode", "disable"),
        }
        log_dir = self.path_manager.get_log_directory()
        trading_users = self._discover_trading_user_nos()
        if trading_users:
            pool_for_global = sorted(trading_users)[0]
        else:
            p = (
                os.environ.get("REC_POOL_USER_NUMBER")
                or os.environ.get("REC_USER_NO")
                or "0001"
            ).strip()
            pool_for_global = p.zfill(4) if p.isdigit() and len(p) <= 4 else "0001"
        default_schema = (os.environ.get("REC_DEFAULT_USER_SCHEMA") or "").strip() or f"users_{pool_for_global}"
        if not (os.environ.get("REC_DEFAULT_USER_SCHEMA") or "").strip():
            os.environ["REC_DEFAULT_USER_SCHEMA"] = default_schema
        if not ensure_tenant_schemas_for_active_users(trading_users, logger=logger):
            raise RuntimeError(
                "ensure_tenant_schemas_for_active_users failed; fix PostgreSQL / tenant template "
                "before regenerating supervisord (see log above)."
            )
        monitors_by_user = {u: self._get_active_monitors_for_user(u) for u in trading_users}

        env_global = self._create_environment_variables(
            db_config,
            system_host,
            pool_for_global,
            rec_single_user_mode="1",
            rec_default_user_schema=default_schema,
        )

        services = []
        services.append(
            {
                "name": "main_app",
                "script": "main.py",
                "port": ports.get("main_app", 3000),
                "environment": env_global,
                "autostart": True,
            }
        )
        services.append(
            {
                "name": "read_api",
                "script": "read_api.py",
                "port": ports.get("read_api", 3050),
                "environment": env_global,
                "autostart": True,
            }
        )
        services.append(
            {
                "name": "redis_switchboard",
                "script": "redis_switchboard.py",
                "port": ports.get("redis_switchboard", 3010),
                "environment": env_global,
                "autostart": True,
            }
        )
        # Crypto spot: single Kalshi cfbenchmarks_value feed (replaces 4× Coinbase symbol_price_watchdog).
        cfb_env = (
            env_global
            + ',CFBENCHMARKS_PUBLISH_MODE="live_state"'
            + ',CFBENCHMARKS_INDEX_IDS="BRTI,ETHUSD_RTI,SOLUSD_RTI,XRPUSD_RTI,DOGEUSD_RTI"'
            + ',CFBENCHMARKS_RING_PG="1"'
        )
        services.append(
            {
                "name": "cfbenchmarks_price_watchdog",
                "script": "cfbenchmarks_price_watchdog.py",
                "port": ports.get("cfbenchmarks_price_watchdog", 8008),
                "environment": cfb_env,
                "autostart": True,
            }
        )
        services.append(
            {
                "name": "market_watchdog_ws_kalshi",
                "script": "market_watchdog_ws.py --exchange kalshi --market all",
                "port": ports.get("market_watchdog_ws_kalshi", 8005),
                "environment": env_global,
                "autostart": True,
            }
        )
        services.append(
            {
                "name": "system_monitor",
                "script": "system_monitor.py",
                "port": ports.get("system_monitor", 8006),
                "environment": env_global,
                "autostart": True,
            }
        )
        services.append(
            {
                "name": "cascading_failure_detector",
                "script": "cascading_failure_detector.py",
                "port": ports.get("cascading_failure_detector", 8007),
                "environment": env_global,
                "autostart": True,
            }
        )
        services.append(
            {
                "name": "strike_snapshot_publisher",
                "script": "strike_snapshot_publisher.py",
                "port": ports.get("strike_snapshot_publisher", 8062),
                "environment": env_global,
                "autostart": True,
            }
        )
        # db_writer_agent removed: script not in tree; hot path uses Redis live_state + optional spool.

        pr = Path(project_root)
        kalshi_by_user = fetch_kalshi_enabled_map_for_user_nos(list(trading_users))
        for user_no in trading_users:
            umon = monitors_by_user[user_no]
            prod_pem = (
                pr
                / "backend"
                / "data"
                / "users"
                / f"user_{user_no}"
                / "credentials"
                / "kalshi-credentials"
                / "prod"
                / "kalshi.pem"
            )
            prod_env = prod_pem.parent / ".env"
            has_live = prod_pem.is_file() and prod_env.is_file()
            kalshi_exchange = kalshi_by_user.get(user_no)
            # Signed Kalshi API only when key material exists AND master_users does not set kalshi false.
            # None from DB = unknown / legacy row → do not block (same as prior file-only behavior).
            kalshi_auth_ok = has_live and (kalshi_exchange is not False)

            env_u = self._create_environment_variables(
                db_config,
                system_host,
                user_no,
                rec_user_schema=f"users_{user_no}",
                rec_single_user_mode="0",
                rec_paper_only_user="1" if not kalshi_auth_ok else None,
            )

            tm = f"trade_manager_{user_no}"
            te = f"trade_executor_{user_no}"
            kas = f"kalshi_account_sync_{user_no}"
            mm = f"monitor_manager_{user_no}"

            services.append(
                {
                    "name": tm,
                    "script": "trade_manager.py",
                    "port": self._scoped_port(ports, "trade_manager", user_no, 4000, ref_slot=pool_for_global),
                    "environment": env_u,
                    "autostart": True,
                }
            )
            services.append(
                {
                    "name": te,
                    "script": "trade_executor.py",
                    "port": self._scoped_port(ports, "trade_executor", user_no, 8001, ref_slot=pool_for_global),
                    "environment": env_u,
                    # Paper mode still routes fills through trade_executor (Redis streams); always start with trade_manager.
                    "autostart": True,
                }
            )
            services.append(
                {
                    "name": kas,
                    "script": "kalshi_account_sync_ws.py",
                    "port": self._scoped_port(ports, "kalshi_account_sync", user_no, 8004, ref_slot=pool_for_global),
                    "environment": env_u,
                    # Always start: without live Kalshi, ``REC_PAPER_ONLY_USER`` / DB flag triggers
                    # ``block_forever_if_kalshi_authenticated_api_disallowed`` (dormant, low CPU).
                    "autostart": True,
                }
            )
            services.append(
                {
                    "name": mm,
                    "script": "monitor_manager.py",
                    "port": self._scoped_port(ports, "monitor_manager", user_no, 8012, ref_slot=pool_for_global),
                    "environment": env_u,
                    "autostart": True,
                }
            )
            services.append(
                {
                    "name": f"kalshi_lifecycle_consumer_{user_no}",
                    "script": "kalshi_lifecycle_trade_consumer.py",
                    "port": self._scoped_port(ports, "kalshi_lifecycle_consumer", user_no, 8040, ref_slot=pool_for_global),
                    "environment": env_u,
                    "autostart": True,
                }
            )

            has_15m = any(m.get("market", "hourly") == "15m" for m in umon)
            has_hourly = any(m.get("market", "hourly") != "15m" for m in umon)
            if has_15m or has_hourly:
                # One AES/ATS pair per trading user; name must match user_no (not monitor-derived pool id)
                # so REC_POOL_USER_NUMBER and program name stay aligned with trade_manager_<user_no>.
                aes_name = f"auto_entry_supervisor_{user_no}"
                ats_name = f"active_trade_supervisor_{user_no}"
                services.append(
                    {
                        "name": aes_name,
                        "script": "auto_entry_supervisor.py unified",
                        "port": self._scoped_port(ports, "auto_entry_supervisor", user_no, 8033, ref_slot=pool_for_global),
                        "environment": env_u,
                        "autostart": True,
                    }
                )
                services.append(
                    {
                        "name": ats_name,
                        "script": "active_trade_supervisor.py unified",
                        "port": self._scoped_port(ports, "active_trade_supervisor", user_no, 8034, ref_slot=pool_for_global),
                        "environment": env_u,
                        "autostart": True,
                    }
                )

        services.append(
            {
                "name": "strike_table_generator_ws_hourly",
                "script": "strike_table_generator_ws.py --exchange kalshi --market hourly",
                "port": ports.get("strike_table_generator_ws_hourly", 8014),
                "environment": env_global,
                "autostart": True,
            }
        )
        services.append(
            {
                "name": "strike_table_generator_ws_15m",
                "script": "strike_table_generator_ws.py --exchange kalshi --market 15m",
                "port": ports.get("strike_table_generator_ws_15m", 8036),
                "environment": env_global,
                "autostart": True,
            }
        )
        # Supervisord main log: durable path under logs/ with rotation (critical for incident review)
        supervisord_log = os.path.join(log_dir, "supervisord.log")
        
        # Generate supervisor configuration
        config_content = f"""[supervisord]
nodaemon=true
logfile={supervisord_log}
logfile_maxbytes=50MB
logfile_backups=10
pidfile=/tmp/supervisord.pid
stdout_logfile_maxbytes=0
stderr_logfile_maxbytes=0

[supervisorctl]
serverurl=unix:///tmp/supervisord.sock

[unix_http_server]
file=/tmp/supervisord.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface


"""
        
        # Long settlement polling can run many minutes; allow graceful stop before SIGKILL.
        PROGRAM_EXTRA_DIRECTIVES = {
            s["name"]: ["stopwaitsecs=120"]
            for s in services
            if s["name"].startswith("trade_manager_")
        }
        # Critical assets get higher log retention (see docs/CRITICAL_ASSET_LOGGING.md)
        CRITICAL_LOG_SERVICES = {"system_monitor", "cascading_failure_detector"}
        CRITICAL_STDOUT_MAX, CRITICAL_STDOUT_BACKUPS = "20MB", 10
        CRITICAL_STDERR_MAX, CRITICAL_STDERR_BACKUPS = "10MB", 10
        DEFAULT_STDOUT_MAX, DEFAULT_STDOUT_BACKUPS = "10MB", 5
        DEFAULT_STDERR_MAX, DEFAULT_STDERR_BACKUPS = "5MB", 5
        
        # Generate program sections
        for service in services:
            service_name = service["name"]
            script_path = service["script"]
            port = service["port"]
            env_vars = service["environment"]
            autostart_s = "true" if service.get("autostart", True) else "false"

            stdout_log = os.path.join(log_dir, f"{service_name}.out.log")
            stderr_log = os.path.join(log_dir, f"{service_name}.err.log")
            if service_name in CRITICAL_LOG_SERVICES:
                stderr_max, stderr_backups = CRITICAL_STDERR_MAX, CRITICAL_STDERR_BACKUPS
                stdout_max, stdout_backups = CRITICAL_STDOUT_MAX, CRITICAL_STDOUT_BACKUPS
            else:
                stderr_max, stderr_backups = DEFAULT_STDERR_MAX, DEFAULT_STDERR_BACKUPS
                stdout_max, stdout_backups = DEFAULT_STDOUT_MAX, DEFAULT_STDOUT_BACKUPS

            run_cmd = f'{python_executable} {project_root}/backend/{script_path}'
            extra_lines = "\n".join(PROGRAM_EXTRA_DIRECTIVES.get(service_name, []))
            extra_block = f"{extra_lines}\n" if extra_lines else ""
            # Create program section
            config_content += f"""[program:{service_name}]
command={run_cmd}
directory={project_root}
autostart={autostart_s}
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
{extra_block}stderr_logfile={stderr_log}
stderr_logfile_maxbytes={stderr_max}
stderr_logfile_backups={stderr_backups}
stdout_logfile={stdout_log}
stdout_logfile_maxbytes={stdout_max}
stdout_logfile_backups={stdout_backups}
environment={env_vars}

"""
        
        return config_content
    
    def _create_environment_variables(
        self,
        db_config: dict,
        system_host: str,
        rec_pool_user: str,
        *,
        rec_user_schema: Optional[str] = None,
        rec_single_user_mode: Optional[str] = None,
        rec_paper_only_user: Optional[str] = None,
        rec_default_user_schema: Optional[str] = None,
    ) -> str:
        """Create environment variables string for supervisor (optional tenant / paper flags)."""
        try:
            env_vars = [
                f'PATH="{self.config.get("runtime.venv_path", "")}/bin"',
                f'PYTHONPATH="{self.config.project_root}"',
                'PYTHONGC=1',
                'PYTHONDNSCACHE=1',
                'PYTHONDONTWRITEBYTECODE=1',
                f'TRADING_SYSTEM_HOST="{system_host}"',
                f'REC_SYSTEM_HOST="{system_host}"',
                f'REC_POOL_USER_NUMBER="{rec_pool_user}"',
                f'REC_PROJECT_ROOT="{self.config.project_root}"',
                f'REC_ENVIRONMENT="{self.config.get("system.environment", "development")}"',
                f'DB_HOST="{db_config.get("host", "localhost")}"',
                f'DB_NAME="{db_config.get("database", db_config.get("name", "rec_io_db"))}"',
                f'DB_USER="{db_config.get("user", "rec_io_user")}"',
                f'DB_PASSWORD="{db_config.get("password", "")}"',
                f'DB_PORT="{db_config.get("port", 5432)}"',
                f'POSTGRES_HOST="{db_config.get("host", "localhost")}"',
                f'POSTGRES_DB="{db_config.get("database", db_config.get("name", "rec_io_db"))}"',
                f'POSTGRES_USER="{db_config.get("user", "rec_io_user")}"',
                f'POSTGRES_PASSWORD="{db_config.get("password", "")}"',
                f'POSTGRES_PORT="{db_config.get("port", 5432)}"',
                f'REC_DB_HOST="{db_config.get("host", "localhost")}"',
                f'REC_DB_NAME="{db_config.get("database", db_config.get("name", "rec_io_db"))}"',
                f'REC_DB_USER="{db_config.get("user", "rec_io_user")}"',
                f'REC_DB_PASS="{db_config.get("password", "")}"',
                f'REC_DB_PORT="{db_config.get("port", 5432)}"',
                f'REC_DB_SSLMODE="{db_config.get("sslmode", "disable")}"'
            ]

            # Trading-plane Redis (pub/sub preferences, streams): supervisord does not inherit shell env.
            # Propagate from the environment used when running this generator (or CI/deploy secrets).
            _trading_redis_keys = (
                "USE_TRADING_REDIS_COMMS",
                "REDIS_URL",
                "REDIS_HOST",
                "REDIS_PORT",
                "REDIS_PASSWORD",
                "REDIS_CHANNEL_TRADING_PREFERENCES",
                "REDIS_CHANNEL_ATS_TM_NOTIFICATIONS",
                "REDIS_CHANNEL_ATS_ENROLL_REQUEST",
                "REDIS_CHANNEL_DB_CHANGES",
                "REDIS_CHANNEL_TM_POSITIONS_UPDATED",
                "REDIS_CHANNEL_KALSHI_LIFECYCLE_TRADES",
            )
            for key in _trading_redis_keys:
                val = os.getenv(key)
                if val is None or str(val).strip() == "":
                    continue
                esc = str(val).replace("\\", "\\\\").replace('"', '\\"')
                env_vars.append(f'{key}="{esc}"')

            # Alerts / registration email (Gmail SMTP): propagate non-secret vars only.
            # Do NOT embed REC_ALERTS_SMTP_PASSWORD here — it would land in supervisord.conf on disk.
            # Use REC_ALERTS_SMTP_PASSWORD_FILE (path) or rely on backend/data/secrets/rec_alerts_smtp_password.txt
            # next to the repo (see docs/REC_ALERTS_SMTP_SECRETS.md).
            _rec_alerts_smtp_keys = (
                "REC_ALERTS_SMTP_HOST",
                "REC_ALERTS_SMTP_PORT",
                "REC_ALERTS_SMTP_USER",
                "REC_ALERTS_SMTP_FROM",
                "REC_ALERTS_SMTP_PASSWORD_FILE",
            )
            for key in _rec_alerts_smtp_keys:
                val = os.getenv(key)
                if val is None or str(val).strip() == "":
                    continue
                esc = str(val).replace("\\", "\\\\").replace('"', '\\"')
                env_vars.append(f'{key}="{esc}"')

            # Intuit / QuickBooks OAuth (main_app): supervisord does not inherit shell env.
            # Prefer env at generation time; else read gitignored one-line files (same pattern as alerts).
            def _intuit_oauth_secret_from_file(rel_name: str) -> str:
                p = Path(self.config.project_root) / "backend" / "data" / "secrets" / rel_name
                try:
                    if p.is_file():
                        return p.read_text().strip()
                except OSError:
                    pass
                return ""

            _intuit_keys = (
                "REC_INTUIT_OAUTH_STATE_SECRET",
                "REC_INTUIT_OAUTH_ADMIN_SECRET",
                "REC_INTUIT_OAUTH_REDIRECT_URI",
            )
            for key in _intuit_keys:
                val = os.getenv(key)
                if val is None or str(val).strip() == "":
                    if key == "REC_INTUIT_OAUTH_STATE_SECRET":
                        val = _intuit_oauth_secret_from_file("rec_intuit_oauth_state_secret.txt")
                    elif key == "REC_INTUIT_OAUTH_ADMIN_SECRET":
                        val = _intuit_oauth_secret_from_file("rec_intuit_oauth_admin_secret.txt")
                if val is None or str(val).strip() == "":
                    continue
                esc = str(val).replace("\\", "\\\\").replace('"', '\\"')
                env_vars.append(f'{key}="{esc}"')

            # Redis-first defaults for supervised services:
            # - Enable trading Redis comms unless explicitly overridden.
            # - If REDIS_URL is absent, provide localhost host/port defaults.
            if not any(x.startswith("USE_TRADING_REDIS_COMMS=") for x in env_vars):
                env_vars.append('USE_TRADING_REDIS_COMMS="1"')

            has_redis_url = any(x.startswith("REDIS_URL=") for x in env_vars)
            has_redis_host = any(x.startswith("REDIS_HOST=") for x in env_vars)
            has_redis_port = any(x.startswith("REDIS_PORT=") for x in env_vars)
            if not has_redis_url and not has_redis_host:
                env_vars.append('REDIS_HOST="localhost"')
            if not has_redis_url and not has_redis_port:
                env_vars.append('REDIS_PORT="6379"')

            # Strike-table historical archive: disabled to cap PG growth.
            # Set REC_STRIKE_TABLE_ARCHIVE="1" to re-enable.
            if not any(x.startswith("REC_STRIKE_TABLE_ARCHIVE=") for x in env_vars):
                env_vars.append('REC_STRIKE_TABLE_ARCHIVE="0"')

            # HTTP fallback should be opt-in during Redis cutover.
            if not any(x.startswith("ATS_HTTP_FALLBACK_ENABLED=") for x in env_vars):
                env_vars.append('ATS_HTTP_FALLBACK_ENABLED="0"')

            # Pipeline-health trade gate defaults:
            # keep fail-closed behavior enabled in supervised environments unless explicitly overridden.
            if not any(x.startswith("STRIKE_PIPELINE_HEALTH_STRICT_MODE=") for x in env_vars):
                env_vars.append('STRIKE_PIPELINE_HEALTH_STRICT_MODE="1"')
            if not any(x.startswith("STRIKE_PIPELINE_FRESHNESS_STRICT=") for x in env_vars):
                env_vars.append('STRIKE_PIPELINE_FRESHNESS_STRICT="1"')
            if not any(x.startswith("PIPELINE_HEALTH_WRITER_DEAD_SEC=") for x in env_vars):
                env_vars.append('PIPELINE_HEALTH_WRITER_DEAD_SEC="900"')
            if not any(x.startswith("PIPELINE_CATASTROPHIC_TRANSPORT_SEC=") for x in env_vars):
                env_vars.append('PIPELINE_CATASTROPHIC_TRANSPORT_SEC="600"')

            # Phase 1 live_state cache (config.local.json "live_state" or shell env at generate time).
            _live_state_cfg = self.config.get("live_state") or {}
            if not isinstance(_live_state_cfg, dict):
                _live_state_cfg = {}
            for _ls_key in (
                "LIVE_STATE_CACHE_ENABLED",
                "LIVE_STATE_USE_TICK_BUFFER",
                "LIVE_STATE_SPOOL_ENABLED",
                "LIVE_STATE_DUAL_WRITE_PG",
                "PROBABILITY_LOOKUP_RAM",
                "DB_WRITER_ENABLED",
                "DB_WRITER_FLUSH_INTERVAL_SEC",
                "DB_WRITER_MAX_EVENTS_PER_FLUSH",
                "DB_WRITER_SPOOL_READ_CHUNK",
                "MARKET_WATCHDOG_WS_ORDERBOOK_PG",
                "TRADE_MONITOR_ORDERBOOK_PG_FALLBACK",
                "LIVE_STATE_REDIS_KEY_PREFIX",
                "LIVE_STATE_UPDATED_CHANNEL",
                "LIVE_STATE_SPOOL_STREAM",
            ):
                if any(x.startswith(f"{_ls_key}=") for x in env_vars):
                    continue
                _ls_val = os.getenv(_ls_key)
                if _ls_val is None or str(_ls_val).strip() == "":
                    _ls_val = _live_state_cfg.get(_ls_key)
                if _ls_val is None or str(_ls_val).strip() == "":
                    continue
                esc = str(_ls_val).replace("\\", "\\\\").replace('"', '\\"')
                env_vars.append(f'{_ls_key}="{esc}"')
            # HF orderbook hot path (market_watchdog + switchboard + AES tradeflow wake).
            for _hf_key, _hf_default in (
                ("MARKET_WATCHDOG_HOT_TICKER_FLUSH", "1"),
                ("ORDERBOOK_PREBUILD_WS_PAYLOAD", "1"),
                ("TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC", "0.05"),
            ):
                if any(x.startswith(f"{_hf_key}=") for x in env_vars):
                    continue
                _hf_val = os.getenv(_hf_key, _hf_default)
                if _hf_val is None or str(_hf_val).strip() == "":
                    continue
                esc = str(_hf_val).replace("\\", "\\\\").replace('"', '\\"')
                env_vars.append(f'{_hf_key}="{esc}"')
            for _hf_opt in (
                "MARKET_WATCHDOG_HOT_ORDERBOOK_TICKERS",
                "MARKET_WATCHDOG_PUBLISH_COALESCE_MS",
            ):
                if any(x.startswith(f"{_hf_opt}=") for x in env_vars):
                    continue
                _hf_val = os.getenv(_hf_opt)
                if _hf_val is None or str(_hf_val).strip() == "":
                    continue
                esc = str(_hf_val).replace("\\", "\\\\").replace('"', '\\"')
                env_vars.append(f'{_hf_opt}="{esc}"')
            # v3.7+ hot path defaults ON in backend/core/live_state_config.py (no env required).
            # Still propagate explicit overrides from shell or config.local.json "live_state".

            # Shared strike ladder snapshots (Redis): AES/ATS read same payload per wall second when publisher runs.
            if not any(x.startswith("REC_STRIKE_SNAPSHOT_READ=") for x in env_vars):
                env_vars.append('REC_STRIKE_SNAPSHOT_READ="1"')
            if not any(x.startswith("REC_STRIKE_SNAPSHOT_MAX_AGE_SEC=") for x in env_vars):
                env_vars.append('REC_STRIKE_SNAPSHOT_MAX_AGE_SEC="3"')
            # Historical strike archive: default publisher-only (same ladder as Redis); see historical_strike_table_archive.
            if not any(x.startswith("REC_STRIKE_TABLE_ARCHIVE_SOURCE=") for x in env_vars):
                env_vars.append('REC_STRIKE_TABLE_ARCHIVE_SOURCE="publisher"')

            if rec_user_schema:
                esc_s = str(rec_user_schema).replace("\\", "\\\\").replace('"', '\\"')
                env_vars.append(f'REC_USER_SCHEMA="{esc_s}"')
                env_vars.append(f'REC_USER_NO="{rec_pool_user}"')
            if rec_single_user_mode is not None:
                env_vars.append(f'REC_SINGLE_USER_MODE="{rec_single_user_mode}"')
            if rec_paper_only_user is not None:
                env_vars.append(f'REC_PAPER_ONLY_USER="{rec_paper_only_user}"')
            if rec_default_user_schema:
                esc_ds = str(rec_default_user_schema).replace("\\", "\\\\").replace('"', '\\"')
                env_vars.append(f'REC_DEFAULT_USER_SCHEMA="{esc_ds}"')

            return ','.join(env_vars)
            
        except Exception as e:
            logger.error(f"Error creating environment variables: {e}")
            return f'PATH="{self.config.get("runtime.venv_path", "")}/bin",PYTHONPATH="{self.config.project_root}",PYTHONGC=1,PYTHONDNSCACHE=1'
    
    def validate_generated_config(self) -> bool:
        """Validate the generated supervisor configuration"""
        try:
            supervisor_config_path = self.path_manager.get_supervisor_config_path()
            
            if not self.path_manager.path_exists(supervisor_config_path):
                logger.error("Supervisor configuration file does not exist")
                return False
            
            # Check if file is readable
            with open(supervisor_config_path, 'r') as f:
                content = f.read()
            
            # Basic validation checks
            required_sections = [
                "[supervisord]",
                "[supervisorctl]",
                "[unix_http_server]",
                "[program:main_app]"
            ]
            
            for section in required_sections:
                if section not in content:
                    logger.error(f"Missing required section in supervisor config: {section}")
                    return False
            
            logger.info("Supervisor configuration validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Error validating supervisor configuration: {e}")
            return False
    
    def get_config_summary(self) -> dict:
        """Get summary of the generated configuration"""
        try:
            supervisor_config_path = self.path_manager.get_supervisor_config_path()
            
            summary = {
                "supervisor_config_path": supervisor_config_path,
                "config_exists": self.path_manager.path_exists(supervisor_config_path),
                "project_root": self.config.project_root,
                "system_host": self.config.get('runtime.system_host'),
                "python_executable": self.config.get('runtime.python_executable'),
                "log_directory": self.path_manager.get_log_directory(),
                "database_config": self.config.get_database_config(),
                "validation_passed": self.validate_generated_config()
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting config summary: {e}")
            return {"error": str(e)}

def main():
    """Main function to generate supervisor configuration"""
    try:
        logger.info("Starting unified supervisor configuration generation...")
        
        # Initialize generator
        generator = SupervisorConfigGenerator()
        
        # Generate configuration
        success = generator.generate_config()
        
        if success:
            # Validate generated configuration
            if generator.validate_generated_config():
                logger.info("✅ Supervisor configuration generated and validated successfully")
                
                # Print summary
                summary = generator.get_config_summary()
                logger.info("Configuration Summary:")
                for key, value in summary.items():
                    logger.info(f"  {key}: {value}")
                
                return 0
            else:
                logger.error("❌ Supervisor configuration validation failed")
                return 1
        else:
            logger.error("❌ Failed to generate supervisor configuration")
            return 1
            
    except Exception as e:
        logger.error(f"❌ Error in main function: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
