"""
Centralized Database Configuration
Provides environment variable-based configuration for PostgreSQL connections.

Single pattern: use DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT. If unset,
falls back to REC_DB_HOST, REC_DB_NAME, REC_DB_USER, REC_DB_PASS, REC_DB_PORT
so .env or deploy can use either convention. Scripts should use
get_postgresql_connection() / get_system_postgresql_connection() or get_database_config(); do not use POSTGRES_*
or hardcoded credentials.

**Schema evolution:** Add or change tables/columns only via intentional pairs under
``scripts/migrations/`` and ``scripts/db/run_migration.py``. Do not extend
``init_database()`` with new ``ALTER`` / ``ADD COLUMN`` for production-shaped
objects; that path is legacy greenfield bootstrap only (see ``docs/TENANT_INIT_AND_MIGRATIONS.md``).

**Capacity:** Many supervisor programs each hold DB sessions. If Postgres returns
``too many clients``, raise ``max_connections`` (e.g. 200+ for local multi-tenant dev) and tune
``REC_MONITOR_MANAGER_PG_POOL_MAX`` / ``REC_MARKET_WATCHDOG_DB_POOL_MAX`` rather than relying only on connect retries.
"""

import logging
import os
import re
import time
from typing import Optional

import psycopg2
import psycopg2.pool

from backend.core.db_schema_contract import enforce_on_raw_connection
from backend.core.time_eastern import merge_psycopg2_connect_kwargs

_logger = logging.getLogger(__name__)

# Burst startup (supervisor) can exceed Postgres max_connections briefly; retry instead of
# logging full tracebacks that include server severity prefixes.
_PG_CONNECT_MAX_ATTEMPTS = int(os.environ.get("REC_PG_CONNECT_MAX_ATTEMPTS", "18"))
_PG_CONNECT_BASE_SLEEP_SEC = float(os.environ.get("REC_PG_CONNECT_BASE_SLEEP_SEC", "0.04"))
_PG_CONNECT_MAX_SLEEP_SEC = float(os.environ.get("REC_PG_CONNECT_MAX_SLEEP_SEC", "0.75"))
_PG_LOG_SEVERITY_PREFIX = re.compile(r"(?i)\b(?:FATAL|ERROR):\s*")


def _pg_connect_error_for_log(exc: BaseException) -> str:
    """Single-line message for logs without Postgres severity tokens (avoids noisy FATAL/ERROR lines)."""
    raw = str(exc).strip()
    if not raw:
        return "connection error"
    msg = _PG_LOG_SEVERITY_PREFIX.sub("", raw)
    msg = " ".join(msg.split())
    return msg[:480] if msg else "connection error"


def _is_transient_operational_connect_error(exc: BaseException) -> bool:
    if not isinstance(exc, psycopg2.OperationalError):
        return False
    m = str(exc).lower()
    return (
        "too many clients" in m
        or "connection refused" in m
        or "could not connect to server" in m
        or "server closed the connection unexpectedly" in m
    )


def _sleep_between_pg_connect_retries(attempt_index: int) -> None:
    delay = min(
        _PG_CONNECT_MAX_SLEEP_SEC,
        _PG_CONNECT_BASE_SLEEP_SEC * (2 ** min(attempt_index, 10)),
    )
    time.sleep(delay)

# Shared schemas for global daemons (no users_NNNN). Order: app shared data first, then public, catalog.
_SYSTEM_SEARCH_PATH = (
    "live_data, system, historical_data, backtest, testing, archive, public, pg_catalog"
)


def _apply_system_search_path(conn) -> None:
    cur = conn.cursor()
    try:
        cur.execute(f"SET search_path TO {_SYSTEM_SEARCH_PATH}")
    finally:
        cur.close()


class SystemThreadedConnectionPool(psycopg2.pool.ThreadedConnectionPool):
    """
    Raw psycopg2 pool with system ``search_path`` only (no :class:`TenantConnection`, no ``users.`` rewrite).

    Use from global processes that must **not** bind to a tenant (e.g. market_watchdog_ws → ``live_data`` only).
    """

    def __init__(self, minconn: int, maxconn: int, **connect_kwargs):
        super().__init__(minconn, maxconn, **merge_psycopg2_connect_kwargs(connect_kwargs))

    def _connect(self, key=None):
        conn = psycopg2.connect(*self._args, **self._kwargs)
        _apply_system_search_path(conn)
        enforce_on_raw_connection(conn)
        if key is not None:
            self._used[key] = conn
            self._rused[id(conn)] = key
        else:
            self._pool.append(conn)
        return conn


def get_database_config():
    """Get database configuration from environment variables. Prefer DB_*; fall back to REC_DB_*.
    ``REC_DB_PASSWORD`` is also accepted (same as ``load_unified_config.sh`` / :mod:`unified_config` export).

    In production (REC_ENVIRONMENT=production), a non-empty password is required; no default.

    Includes ``options`` so PostgreSQL session ``TimeZone`` is America/New_York (naive TIMESTAMP
    columns and naive datetime adapters match project conventions)."""
    pw = (
        os.getenv("DB_PASSWORD")
        or os.getenv("REC_DB_PASS")
        or os.getenv("REC_DB_PASSWORD")
    )
    if os.getenv("REC_ENVIRONMENT") == "production" and not (pw and str(pw).strip()):
        raise ValueError(
            "DB_PASSWORD, REC_DB_PASS, or REC_DB_PASSWORD required in production"
        )
    base = {
        'host': os.getenv('DB_HOST') or os.getenv('REC_DB_HOST') or 'localhost',
        'database': os.getenv('DB_NAME') or os.getenv('REC_DB_NAME') or 'rec_io_db',
        'user': os.getenv('DB_USER') or os.getenv('REC_DB_USER') or 'rec_io_user',
        'password': pw or 'rec_io_password',
        'port': int(os.getenv('DB_PORT') or os.getenv('REC_DB_PORT') or '5432'),
    }
    return merge_psycopg2_connect_kwargs(base)


def get_system_postgresql_connection():
    """
    Raw PostgreSQL connection for **global** services (market ingest, live_data writers, LISTEN/NOTIFY helpers).

    Does **not** wrap :class:`~backend.core.tenant_context.TenantConnection` and does **not** rewrite ``users.``.
    Session ``search_path`` is limited to shared schemas (see ``_SYSTEM_SEARCH_PATH``).

    Do **not** use this to read or write ``users_NNNN`` tenant tables; use :func:`get_postgresql_connection` with
    request tenant, ``tenant_user_no``, or a worker ``REC_USER_SCHEMA`` instead.

    Retries on transient ``OperationalError`` (e.g. connection limit during supervisor startup).
    Logs use :func:`_pg_connect_error_for_log` (no server ``FATAL``/``ERROR`` severity tokens).
    """
    cfg = get_database_config()
    for attempt in range(_PG_CONNECT_MAX_ATTEMPTS):
        try:
            conn = psycopg2.connect(**cfg)
            _apply_system_search_path(conn)
            enforce_on_raw_connection(conn)
            return conn
        except psycopg2.OperationalError as e:
            if _is_transient_operational_connect_error(e) and attempt + 1 < _PG_CONNECT_MAX_ATTEMPTS:
                _sleep_between_pg_connect_retries(attempt)
                continue
            _logger.warning(
                "PostgreSQL (system) connect failed after %s attempt(s): %s",
                attempt + 1,
                _pg_connect_error_for_log(e),
            )
            return None
        except Exception as e:
            _logger.warning(
                "PostgreSQL (system) connect failed: %s", _pg_connect_error_for_log(e)
            )
            return None
    return None


def get_postgresql_connection(tenant_user_no: Optional[str] = None):
    """Get a connection to the PostgreSQL database using environment configuration.

    Wraps the connection so SQL strings containing ``users.`` are rewritten to the
    tenant schema: from ``tenant_user_no`` when provided (HTTP/API), else from
    the bound web session slot, else (workers/scripts only) ``REC_USER_SCHEMA`` /
    single-user default. See :mod:`backend.core.tenant_context`.

    When ``REC_STRICT_SESSION_TENANT_FOR_DB`` is set (main_app, read_api), a connection
    is refused if neither ``tenant_user_no`` nor a valid web session tenant is available
    (no silent default user).

    For processes that must not bind to any tenant (writes to ``live_data`` / ``system`` only),
    use :func:`get_system_postgresql_connection` instead.

    Retries transient ``OperationalError`` on the initial ``psycopg2.connect`` (same as
    :func:`get_system_postgresql_connection`). Failure logs avoid Postgres ``FATAL``/``ERROR`` tokens.
    """
    from backend.core.tenant_context import (
        TenantConnection,
        effective_tenant_context_for_sql_rewrite,
        get_api_tenant_context,
        strict_session_tenant_for_db_enabled,
    )
    from backend.web.tenant_asgi import get_web_api_user_no

    config = get_database_config()
    conn = None

    for attempt in range(_PG_CONNECT_MAX_ATTEMPTS):
        try:
            conn = psycopg2.connect(**config)
            enforce_on_raw_connection(conn)
            if tenant_user_no:
                ctx = get_api_tenant_context(tenant_user_no)
            else:
                rt = get_web_api_user_no()
                if rt:
                    ctx = get_api_tenant_context(rt)
                elif strict_session_tenant_for_db_enabled():
                    conn.close()
                    conn = None
                    raise RuntimeError(
                        "tenant PostgreSQL connection refused: no session tenant "
                        "(REC_STRICT_SESSION_TENANT_FOR_DB is enabled; authenticate or pass tenant_user_no)"
                    )
                else:
                    ctx = effective_tenant_context_for_sql_rewrite()
            return TenantConnection(conn, ctx)
        except RuntimeError:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            raise
        except psycopg2.OperationalError as e:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
            if _is_transient_operational_connect_error(e) and attempt + 1 < _PG_CONNECT_MAX_ATTEMPTS:
                _sleep_between_pg_connect_retries(attempt)
                continue
            _logger.warning(
                "PostgreSQL (tenant) connect failed after %s attempt(s): %s",
                attempt + 1,
                _pg_connect_error_for_log(e),
            )
            return None
        except Exception as e:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            _logger.warning(
                "PostgreSQL (tenant) connect failed: %s", _pg_connect_error_for_log(e)
            )
            return None

    return None


def get_postgresql_tenant_connection(tenant_user_no: str):
    """API helper: qualify ``users.`` SQL to ``users_<tenant_user_no>`` (validated)."""
    return get_postgresql_connection(tenant_user_no=tenant_user_no)

def test_database_connection():
    """Test the database connection and return status."""
    try:
        conn = get_postgresql_connection()
        if conn:
            conn.close()
            return True, "Database connection successful"
        else:
            return False, "Database connection failed"
    except Exception as e:
        return False, f"Database connection error: {e}"

def init_database():
    """Greenfield bootstrap for the default tenant schema and shared schemas.

    Historical ``CREATE TABLE IF NOT EXISTS`` / ``ADD COLUMN IF NOT EXISTS`` blocks
    remain for backward-compatible one-shot installs. **New schema work** must ship as
    reversible migrations in ``scripts/migrations/`` and be applied with
    ``scripts/db/run_migration.py`` — not as new DDL added here. Ongoing environments
    should rely on migrations + ``system.schema_migrations``, not on re-running this
    function to evolve the catalog.
    """
    try:
        conn = get_postgresql_connection()
        if not conn:
            print("❌ Cannot initialize database - connection failed")
            return False, "Database connection failed"
        
        cursor = conn.cursor()
        from backend.core.tenant_context import TenantContext, default_pg_schema_for_init

        TS = default_pg_schema_for_init()
        _init_slot = TenantContext.from_schema(TS).user_no

        def _us(sql: str) -> str:
            # Template DDL uses legacy ``*_0001`` suffixes; align with init schema (e.g. users_0002 → trades_0002).
            sql = sql.replace("_0001", f"_{_init_slot}")
            return (
                sql.replace("SCHEMA users ", f"SCHEMA {TS} ")
                .replace("SCHEMA users\n", f"SCHEMA {TS}\n")
                .replace("IN SCHEMA users ", f"IN SCHEMA {TS} ")
                .replace("IN SCHEMA users\n", f"IN SCHEMA {TS}\n")
                .replace("ON SCHEMA users ", f"ON SCHEMA {TS} ")
                .replace("ON SCHEMA users\n", f"ON SCHEMA {TS}\n")
                .replace("table_schema = 'users'", f"table_schema = '{TS}'")
                .replace("c.table_schema = 'users'", f"c.table_schema = '{TS}'")
                .replace("n.nspname = 'users'", f"n.nspname = '{TS}'")
                .replace("schemaname = 'users'", f"schemaname = '{TS}'")
                .replace("users.", f"{TS}.")
            )

        
        # Create schemas if they don't exist
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {TS};")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS live_data;")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS system;")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS testing;")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS backtest;")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS archive;")

        # Redis switchboard pilot: minimal testing table for DB -> NOTIFY -> Redis -> WS.
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS testing.redis_basic_test (
                id SERIAL PRIMARY KEY,
                test_value_1 NUMERIC,
                test_value_2 NUMERIC,
                test_value_3 NUMERIC,
                test_value_4 NUMERIC,
                test_value_5 NUMERIC,
                test_value_6 NUMERIC,
                test_value_7 NUMERIC,
                test_value_8 NUMERIC,
                test_value_9 NUMERIC,
                test_value_10 NUMERIC,
                test_value_11 NUMERIC,
                test_value_12 NUMERIC,
                test_value_13 NUMERIC,
                test_value_14 NUMERIC,
                test_value_15 NUMERIC,
                test_value_16 NUMERIC,
                test_value_17 NUMERIC,
                test_value_18 NUMERIC,
                test_value_19 NUMERIC,
                test_value_20 NUMERIC
            );
        """))
        
        # Create core tables
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS users.trades_0001 (
                id SERIAL PRIMARY KEY,
                status VARCHAR(50) DEFAULT 'pending',
                date DATE,
                time TIME,
                symbol VARCHAR(50),
                exchange VARCHAR(50),
                trade_strategy VARCHAR(100),
                market VARCHAR(10) DEFAULT 'hourly',
                contract VARCHAR(255),
                strike VARCHAR(50),
                side VARCHAR(10),
                prob DECIMAL(10,4),
                diff VARCHAR(50),
                buy_price NUMERIC(12,6),
                position NUMERIC(12,2),
                initial_price NUMERIC(10,4),
                slippage NUMERIC(10,4),
                initial_count INTEGER,
                initial_proj_price NUMERIC(10,8),
                initial_proj_fees NUMERIC(10,4),
                sell_price NUMERIC(12,6),
                closed_at TIMESTAMP,
                fees DECIMAL(10,4),
                pnl NUMERIC(12,6),
                symbol_open NUMERIC(18,5),
                symbol_close NUMERIC(18,5),
                symbol_expiration NUMERIC(18,5),
                win_loss_confirmed BOOLEAN,
                momentum INTEGER,
                volatility_percentile NUMERIC(5,1),
                win_loss VARCHAR(10),
                ticker VARCHAR(100),
                ticket_id VARCHAR(100) UNIQUE,
                market_id VARCHAR(100),
                momentum_percentile DECIMAL(10,4),
                entry_method VARCHAR(50),
                close_method VARCHAR(50),
                bankroll DECIMAL(12,2),
                master_trading_bankroll INTEGER,
                mtb_base_value INTEGER,
                monitor VARCHAR(50),
                hour_idx INTEGER,
                weekly_cycle NUMERIC(5,1),
                order_id TEXT,
                order_id_open TEXT,
                order_id_close TEXT,
                time_in_force TEXT,
                order_type TEXT,
                high_price DECIMAL(10,4),
                low_price DECIMAL(10,4),
                loss_prevention BOOLEAN DEFAULT FALSE,
                loss_prevention_state VARCHAR(64),
                multiplier DECIMAL(10,2),
                price_spread DECIMAL(6,4),
                yes_ask_min_15m NUMERIC(18,4),
                yes_ask_max_15m NUMERIC(18,4),
                no_ask_min_15m NUMERIC(18,4),
                no_ask_max_15m NUMERIC(18,4),
                yes_ask_range_15m NUMERIC(18,4),
                no_ask_range_15m NUMERIC(18,4),
                paper_trade BOOLEAN DEFAULT FALSE,
                cooldown_timer INTEGER,
                monitor_confirmed BOOLEAN DEFAULT NULL,
                cycle_win_loss TEXT,
                cycle_pnl REAL,
                cycle_ret_pct REAL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                test_filter BOOLEAN DEFAULT FALSE,
                notes TEXT,
                ret_pct REAL,
                ret_pct_base REAL,
                roi_pct REAL,
                momentum_5s_avg NUMERIC,
                volatility NUMERIC(10,4),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                ats_updated TIMESTAMPTZ
            );
        """))

        # Simulated trades table: same column set as trades_0001, but buy_price, position, fees, bankroll, price_spread (and sell_price) are nullable by design—the simulated path inserts NULL for those. See MASTER_DB_SCHEMA_REFERENCE.
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS users.trades_simulated_0001 (
                id SERIAL PRIMARY KEY,
                status TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                symbol TEXT,
                exchange TEXT DEFAULT 'kalshi',
                trade_strategy TEXT DEFAULT 'Hourly HTC',
                market VARCHAR(10) DEFAULT 'hourly',
                contract TEXT NOT NULL,
                strike TEXT NOT NULL,
                side TEXT NOT NULL,
                prob REAL,
                diff TEXT,
                buy_price NUMERIC(12,6),
                position NUMERIC(12,2),
                initial_proj_price NUMERIC(10,8),
                initial_proj_fees NUMERIC(10,4),
                sell_price NUMERIC(12,6),
                closed_at TEXT,
                fees REAL,
                pnl NUMERIC(12,6),
                symbol_open NUMERIC(18,5),
                symbol_close NUMERIC(18,5),
                momentum INTEGER,
                volatility_percentile NUMERIC(5,1),
                volatility NUMERIC(10,4),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                win_loss TEXT,
                ticker TEXT,
                ticket_id TEXT,
                market_id TEXT,
                momentum_percentile REAL,
                entry_method TEXT DEFAULT 'manual',
                close_method TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                test_filter BOOLEAN DEFAULT FALSE,
                notes TEXT,
                monitor TEXT,
                bankroll REAL,
                master_trading_bankroll INTEGER,
                mtb_base_value INTEGER,
                ret_pct REAL,
                ret_pct_base REAL,
                roi_pct REAL,
                momentum_5s_avg NUMERIC(10,4),
                order_id TEXT,
                order_id_open TEXT,
                order_id_close TEXT,
                time_in_force TEXT,
                order_type TEXT,
                high_price NUMERIC(10,4),
                low_price NUMERIC(10,4),
                hour_idx SMALLINT,
                weekly_cycle NUMERIC(5,1),
                loss_prevention BOOLEAN DEFAULT FALSE,
                multiplier NUMERIC(10,2),
                price_spread NUMERIC(6,4),
                yes_ask_min_15m NUMERIC(18,4),
                yes_ask_max_15m NUMERIC(18,4),
                no_ask_min_15m NUMERIC(18,4),
                no_ask_max_15m NUMERIC(18,4),
                yes_ask_range_15m NUMERIC(18,4),
                no_ask_range_15m NUMERIC(18,4),
                paper_trade BOOLEAN DEFAULT FALSE,
                cooldown_timer INTEGER,
                monitor_confirmed BOOLEAN DEFAULT NULL,
                cycle_win_loss TEXT,
                cycle_pnl REAL,
                cycle_ret_pct REAL,
                ats_updated TIMESTAMPTZ
            );
        """))

        # Ensure new columns exist for legacy databases
        cursor.execute(_us("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'loss_prevention'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN loss_prevention BOOLEAN DEFAULT FALSE;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'loss_prevention_state'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN loss_prevention_state VARCHAR(64);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'multiplier'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN multiplier DECIMAL(10,2);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'price_spread'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN price_spread DECIMAL(6,4);
                END IF;

                -- weekly_cycle: migrate INTEGER to NUMERIC(5,1) for 15m-window record-keeping (hourly=.4, 15m :00/.15/.30/.45 = .0/.1/.2/.3)
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns c
                    WHERE c.table_schema = 'users' AND c.table_name = 'trades_0001' AND c.column_name = 'weekly_cycle'
                      AND c.data_type IN ('integer', 'smallint', 'bigint')
                ) THEN
                    ALTER TABLE users.trades_0001 ALTER COLUMN weekly_cycle TYPE NUMERIC(5,1) USING weekly_cycle::numeric(5,1);
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001')
                  AND EXISTS (
                    SELECT 1 FROM information_schema.columns c
                    WHERE c.table_schema = 'users' AND c.table_name = 'trades_simulated_0001' AND c.column_name = 'weekly_cycle'
                      AND c.data_type IN ('integer', 'smallint', 'bigint')
                ) THEN
                    ALTER TABLE users.trades_simulated_0001 ALTER COLUMN weekly_cycle TYPE NUMERIC(5,1) USING weekly_cycle::numeric(5,1);
                END IF;

                -- symbol_open / symbol_close: NUMERIC(18,5) for low-priced spots (SOL/XRP); legacy was REAL or DECIMAL(10,4)
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns c
                    WHERE c.table_schema = 'users' AND c.table_name = 'trades_0001' AND c.column_name = 'symbol_open'
                      AND (
                           c.data_type IN ('double precision', 'real')
                        OR (c.data_type = 'numeric' AND (
                             COALESCE(c.numeric_precision, 0) < 18 OR COALESCE(c.numeric_scale, 0) < 5
                           ))
                      )
                ) THEN
                    ALTER TABLE users.trades_0001
                      ALTER COLUMN symbol_open TYPE NUMERIC(18,5) USING symbol_open::numeric,
                      ALTER COLUMN symbol_close TYPE NUMERIC(18,5) USING symbol_close::numeric;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns c
                    WHERE c.table_schema = 'users' AND c.table_name = 'trades_simulated_0001' AND c.column_name = 'symbol_open'
                      AND (
                           c.data_type IN ('double precision', 'real')
                        OR (c.data_type = 'numeric' AND (
                             COALESCE(c.numeric_precision, 0) < 18 OR COALESCE(c.numeric_scale, 0) < 5
                           ))
                      )
                ) THEN
                    ALTER TABLE users.trades_simulated_0001
                      ALTER COLUMN symbol_open TYPE NUMERIC(18,5) USING symbol_open::numeric,
                      ALTER COLUMN symbol_close TYPE NUMERIC(18,5) USING symbol_close::numeric;
                END IF;

                -- Live record-keeping: end-of-cycle spot and counterfactual W/L confirmation (not on trades_simulated_0001)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'symbol_expiration'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN symbol_expiration NUMERIC(18,5);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'win_loss_confirmed'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN win_loss_confirmed BOOLEAN;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'market_result'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN market_result TEXT;
                END IF;

                -- Kalshi cadence: hourly vs 15m (not venue; see `exchange`)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'market'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN market VARCHAR(10) DEFAULT 'hourly';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_simulated_0001'
                      AND column_name = 'market'
                ) THEN
                    ALTER TABLE users.trades_simulated_0001 ADD COLUMN market VARCHAR(10) DEFAULT 'hourly';
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_0001' AND column_name = 'ats_updated'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN ats_updated TIMESTAMPTZ;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001' AND column_name = 'ats_updated'
                ) THEN
                    ALTER TABLE users.trades_simulated_0001 ADD COLUMN ats_updated TIMESTAMPTZ;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_0001' AND column_name = 'initial_price'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN initial_price NUMERIC(10,4);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_0001' AND column_name = 'slippage'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN slippage NUMERIC(10,4);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_0001' AND column_name = 'initial_count'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN initial_count INTEGER;
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns c
                    WHERE c.table_schema = 'users'
                      AND c.table_name = 'trades_0001'
                      AND c.column_name = 'buy_price'
                      AND (
                           c.data_type <> 'numeric'
                        OR COALESCE(c.numeric_precision, 0) < 12
                        OR COALESCE(c.numeric_scale, 0) < 6
                      )
                ) THEN
                    ALTER TABLE users.trades_0001
                      ALTER COLUMN buy_price TYPE NUMERIC(12,6) USING ROUND(buy_price::numeric, 6);
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns c
                    WHERE c.table_schema = 'users'
                      AND c.table_name = 'trades_0001'
                      AND c.column_name = 'sell_price'
                      AND (
                           c.data_type <> 'numeric'
                        OR COALESCE(c.numeric_precision, 0) < 12
                        OR COALESCE(c.numeric_scale, 0) < 6
                      )
                ) THEN
                    ALTER TABLE users.trades_0001
                      ALTER COLUMN sell_price TYPE NUMERIC(12,6) USING ROUND(sell_price::numeric, 6);
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001'
                ) AND EXISTS (
                    SELECT 1
                    FROM information_schema.columns c
                    WHERE c.table_schema = 'users'
                      AND c.table_name = 'trades_simulated_0001'
                      AND c.column_name = 'buy_price'
                      AND (
                           c.data_type <> 'numeric'
                        OR COALESCE(c.numeric_precision, 0) < 12
                        OR COALESCE(c.numeric_scale, 0) < 6
                      )
                ) THEN
                    ALTER TABLE users.trades_simulated_0001
                      ALTER COLUMN buy_price TYPE NUMERIC(12,6) USING ROUND(buy_price::numeric, 6);
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001'
                ) AND EXISTS (
                    SELECT 1
                    FROM information_schema.columns c
                    WHERE c.table_schema = 'users'
                      AND c.table_name = 'trades_simulated_0001'
                      AND c.column_name = 'sell_price'
                      AND (
                           c.data_type <> 'numeric'
                        OR COALESCE(c.numeric_precision, 0) < 12
                        OR COALESCE(c.numeric_scale, 0) < 6
                      )
                ) THEN
                    ALTER TABLE users.trades_simulated_0001
                      ALTER COLUMN sell_price TYPE NUMERIC(12,6) USING ROUND(sell_price::numeric, 6);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_0001' AND column_name = 'initial_proj_price'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN initial_proj_price NUMERIC(10,8);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_0001' AND column_name = 'initial_proj_fees'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN initial_proj_fees NUMERIC(10,4);
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001' AND column_name = 'initial_proj_price'
                ) THEN
                    ALTER TABLE users.trades_simulated_0001 ADD COLUMN initial_proj_price NUMERIC(10,8);
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001' AND column_name = 'initial_proj_fees'
                ) THEN
                    ALTER TABLE users.trades_simulated_0001 ADD COLUMN initial_proj_fees NUMERIC(10,4);
                END IF;

                -- Strike-table final-window ask snapshot at trade insert (migration 20260330_2200_trades_strike_final_quarter_asks)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'yes_ask_min_15m'
                ) THEN
                    ALTER TABLE users.trades_0001
                      ADD COLUMN yes_ask_min_15m NUMERIC(18,4),
                      ADD COLUMN yes_ask_max_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_min_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_max_15m NUMERIC(18,4),
                      ADD COLUMN yes_ask_range_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_range_15m NUMERIC(18,4);
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_simulated_0001'
                      AND column_name = 'yes_ask_min_15m'
                ) THEN
                    ALTER TABLE users.trades_simulated_0001
                      ADD COLUMN yes_ask_min_15m NUMERIC(18,4),
                      ADD COLUMN yes_ask_max_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_min_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_max_15m NUMERIC(18,4),
                      ADD COLUMN yes_ask_range_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_range_15m NUMERIC(18,4);
                END IF;

                -- Ensure trades_simulated_0001.id has a sequence default so INSERT ... RETURNING id returns a value
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001') THEN
                    CREATE SEQUENCE IF NOT EXISTS users.trades_simulated_0001_id_seq;
                    ALTER TABLE users.trades_simulated_0001 ALTER COLUMN id SET DEFAULT nextval('users.trades_simulated_0001_id_seq'::regclass);
                    PERFORM setval('users.trades_simulated_0001_id_seq', (SELECT COALESCE(MAX(id), 0) + 1 FROM users.trades_simulated_0001 WHERE id IS NOT NULL));
                    -- Add primary key if missing (enables row delete in TablePlus and other GUIs)
                    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON c.conrelid = t.oid JOIN pg_namespace n ON t.relnamespace = n.oid WHERE n.nspname = 'users' AND t.relname = 'trades_simulated_0001' AND c.contype = 'p') THEN
                        ALTER TABLE users.trades_simulated_0001 ADD PRIMARY KEY (id);
                    END IF;
                    -- Simulated trades insert NULL for buy_price, position (and fees, bankroll, price_spread): ensure columns are nullable
                    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001' AND column_name = 'buy_price' AND is_nullable = 'NO') THEN
                        ALTER TABLE users.trades_simulated_0001 ALTER COLUMN buy_price DROP NOT NULL;
                    END IF;
                    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001' AND column_name = 'position' AND is_nullable = 'NO') THEN
                        ALTER TABLE users.trades_simulated_0001 ALTER COLUMN position DROP NOT NULL;
                    END IF;
                END IF;

                -- Migrate from volatility to volatility_percentile
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'volatility'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'volatility_percentile'
                ) THEN
                    ALTER TABLE users.trades_0001 DROP COLUMN volatility;
                    ALTER TABLE users.trades_0001 ADD COLUMN volatility_percentile NUMERIC(5,1);
                END IF;

                -- Ensure volatility_percentile exists (for new databases)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'volatility_percentile'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN volatility_percentile NUMERIC(5,1);
                END IF;

                -- Add paper_trade column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'paper_trade'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE;
                END IF;

                -- Add cooldown_timer column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'cooldown_timer'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN cooldown_timer INTEGER;
                END IF;

                -- Add monitor_confirmed column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'monitor_confirmed'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN monitor_confirmed BOOLEAN DEFAULT NULL;
                END IF;

                -- Add cycle_win_loss column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'cycle_win_loss'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN cycle_win_loss TEXT;
                END IF;

                -- Add cycle_pnl column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'cycle_pnl'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN cycle_pnl REAL;
                END IF;

                -- Add cycle_ret_pct column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'cycle_ret_pct'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN cycle_ret_pct REAL;
                END IF;

                -- Add created_at column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'created_at'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
                END IF;

                -- Add updated_at column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'updated_at'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
                END IF;

                -- Add test_filter column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'test_filter'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN test_filter BOOLEAN DEFAULT FALSE;
                END IF;

                -- Add notes column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'notes'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN notes TEXT;
                END IF;

                -- Add ret_pct column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'ret_pct'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN ret_pct REAL;
                END IF;

                -- Add momentum_5s_avg column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'momentum_5s_avg'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN momentum_5s_avg NUMERIC;
                END IF;

                -- Add volatility (raw), movement, movement_percentile - same format as momentum / momentum_percentile
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'volatility'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN volatility NUMERIC(10,4);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'movement'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN movement NUMERIC(10,4);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'movement_percentile'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN movement_percentile NUMERIC(5,1);
                END IF;

                -- Add order_id column if it doesn't exist (legacy, before order_id_open/order_id_close)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'order_id'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN order_id TEXT;
                END IF;
            END
            $$;
        """))
        
        # Legacy generic table kept for backwards compatibility with older tooling.
        # Unified ATS pool tables are ``users.active_trades_15m_<slot>`` and ``users.active_trades_hourly_<slot>`` (per tenant).
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS users.active_trades_0001 (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                side VARCHAR(10) NOT NULL,
                quantity DECIMAL(20,8),
                entry_price DECIMAL(20,8),
                current_price DECIMAL(20,8),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20)
            );
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS users.trade_preferences_0001 (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                symbol VARCHAR(20),
                risk_level VARCHAR(20),
                trade_strategy VARCHAR(100),
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS users.account_history_0001 (
                id SERIAL PRIMARY KEY,
                entry_type VARCHAR(20) NOT NULL,
                amount INTEGER NOT NULL,
                fee INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE,
                status VARCHAR(50),
                returned_amount INTEGER DEFAULT 0,
                deposit_type VARCHAR(50),
                immediate_amount INTEGER,
                immediate_status VARCHAR(50),
                synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                master_trading_bankroll INTEGER,
                mtb_base_value INTEGER,
                CONSTRAINT account_history_0001_created_type_amount_key UNIQUE (created_at, entry_type, amount)
            );
        """))
        # Ensure account_history_0001 columns and constraint exist (for tables created manually)
        cursor.execute(_us("""
            DO $$
            DECLARE
                col TEXT;
                cols_add TEXT[] := ARRAY[
                    'entry_type', 'amount', 'fee', 'created_at', 'updated_at', 'status',
                    'returned_amount', 'deposit_type', 'immediate_amount', 'immediate_status',
                    'synced_at', 'kalshi_id', 'vendor', 'rail', 'master_trading_bankroll', 'mtb_base_value'
                ];
                col_defs TEXT[] := ARRAY[
                    'VARCHAR(20) NOT NULL', 'INTEGER NOT NULL', 'INTEGER DEFAULT 0', 'TIMESTAMP WITH TIME ZONE NOT NULL',
                    'TIMESTAMP WITH TIME ZONE', 'VARCHAR(50)', 'INTEGER DEFAULT 0', 'VARCHAR(50)', 'INTEGER', 'VARCHAR(50)',
                    'TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP', 'VARCHAR(64)', 'VARCHAR(100)', 'VARCHAR(100)',
                    'INTEGER', 'INTEGER'
                ];
                i INT;
            BEGIN
                FOR i IN 1..array_length(cols_add, 1) LOOP
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users' AND table_name = 'account_history_0001' AND column_name = cols_add[i]
                    ) THEN
                        EXECUTE format('ALTER TABLE users.account_history_0001 ADD COLUMN %I ' || col_defs[i], cols_add[i]);
                    END IF;
                END LOOP;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'account_history_0001_created_type_amount_key') THEN
                    ALTER TABLE users.account_history_0001 ADD CONSTRAINT account_history_0001_created_type_amount_key UNIQUE (created_at, entry_type, amount);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'users' AND tablename = 'account_history_0001' AND indexname = 'account_history_0001_kalshi_id_key'
                ) THEN
                    CREATE UNIQUE INDEX account_history_0001_kalshi_id_key ON users.account_history_0001 (kalshi_id) WHERE kalshi_id IS NOT NULL;
                END IF;
            EXCEPTION WHEN OTHERS THEN
                NULL;
            END $$;
        """))

        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.strike_pipeline_health (
                exchange VARCHAR(20) NOT NULL,
                market VARCHAR(20) NOT NULL,
                symbol VARCHAR(10) NOT NULL,
                pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
                pipeline_health_reason TEXT,
                pipeline_health_checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 900,
                ws_transport_ok_at TIMESTAMP WITH TIME ZONE,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                PRIMARY KEY (exchange, market, symbol)
            );
        """))
        cursor.execute(_us("""
            CREATE INDEX IF NOT EXISTS strike_pipeline_health_checked_idx
            ON live_data.strike_pipeline_health USING btree (pipeline_health_checked_at DESC);
        """))
        cursor.execute(_us("""
            CREATE INDEX IF NOT EXISTS strike_pipeline_health_transport_idx
            ON live_data.strike_pipeline_health USING btree (ws_transport_ok_at DESC NULLS LAST);
        """))
        # Add status and external_transfer_id to transfers_0001 if table exists
        cursor.execute(_us("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'transfers_0001') THEN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'transfers_0001' AND column_name = 'status') THEN
                        ALTER TABLE users.transfers_0001 ADD COLUMN status VARCHAR(50);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'transfers_0001' AND column_name = 'external_transfer_id') THEN
                        ALTER TABLE users.transfers_0001 ADD COLUMN external_transfer_id INTEGER;
                    END IF;
                END IF;
            END $$;
        """))
        # Kalshi v1 account UUID for sync (system.master_users; migration 20260421_1400).
        # exchange_credentials: same as migration 20260410_2100 — existing DBs created before this
        # column was added get it here (CREATE TABLE IF NOT EXISTS does not alter old tables).
        cursor.execute(_us("""
            DO $$
            BEGIN
                IF to_regclass('system.master_users') IS NOT NULL THEN
                    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS kalshi_user_id VARCHAR(64);
                    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS exchange_credentials JSONB
                        NOT NULL DEFAULT '{"kalshi": false, "polymarket": false}'::jsonb;
                    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITHOUT TIME ZONE;
                    -- Self-reg uses status pending_email_verification (28 chars); migration 20260420_1000 widens to 64.
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'system' AND table_name = 'master_users'
                          AND column_name = 'status'
                          AND data_type = 'character varying'
                          AND character_maximum_length IS NOT NULL
                          AND character_maximum_length < 64
                    ) THEN
                        ALTER TABLE system.master_users ALTER COLUMN status TYPE VARCHAR(64);
                    END IF;
                END IF;
            END $$;
        """))

        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS users.system_settings_0001 (
                id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                drawdown_trading_halt BOOLEAN NOT NULL DEFAULT TRUE,
                drawdown_reset_threshold_pct NUMERIC(5, 2) NOT NULL DEFAULT 50.00
                    CHECK (drawdown_reset_threshold_pct > 0 AND drawdown_reset_threshold_pct < 100),
                trading_halt_active BOOLEAN NOT NULL DEFAULT FALSE,
                drawdown_halt_monitor_snapshot JSONB,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))
        cursor.execute(_us("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'system_settings_0001'
                      AND column_name = 'trading_halt_active'
                ) THEN
                    ALTER TABLE users.system_settings_0001
                        ADD COLUMN trading_halt_active BOOLEAN NOT NULL DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'system_settings_0001'
                      AND column_name = 'drawdown_halt_monitor_snapshot'
                ) THEN
                    ALTER TABLE users.system_settings_0001
                        ADD COLUMN drawdown_halt_monitor_snapshot JSONB;
                END IF;
            END $$;
        """))
        cursor.execute(_us("""
            INSERT INTO users.system_settings_0001 (id, drawdown_trading_halt, drawdown_reset_threshold_pct)
            VALUES (1, TRUE, 50.00)
            ON CONFLICT (id) DO NOTHING;
        """))

        # Create sequence for 5-digit IDs starting with 10001
        cursor.execute(_us("""
            CREATE SEQUENCE IF NOT EXISTS users.monitor_list_0001_id_seq
            START WITH 10001
            INCREMENT BY 1
            MINVALUE 10001
            MAXVALUE 99999
            CYCLE;
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS users.monitor_list_0001 (
                id INTEGER PRIMARY KEY DEFAULT nextval('users.monitor_list_0001_id_seq'),
                name VARCHAR(255) NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                market TEXT DEFAULT 'hourly',
                strategy VARCHAR(100),
                auto_trade BOOLEAN DEFAULT FALSE,
                auto_trade_status VARCHAR(20) DEFAULT 'inactive',
                trades INTEGER DEFAULT 0,
                win_loss DECIMAL(5,1) DEFAULT 0.0,
                ret_pct DECIMAL(5,1) DEFAULT 0.0,
                pnl DECIMAL(10,2) DEFAULT 0.00,
                bankroll_allotment DECIMAL(5,1) DEFAULT 0.0,
                status VARCHAR(20) DEFAULT 'active',
                dashboard_order INTEGER DEFAULT 0,
                win_streak INTEGER DEFAULT 0,
                win_streak_threshold INTEGER DEFAULT 22,
                loss_prevention VARCHAR(50) DEFAULT 'none',
                loss_prevention_toggle BOOLEAN DEFAULT TRUE,
                last_processed_cycle VARCHAR(100),
                current_contract TEXT,
                current_weekly_cycle SMALLINT,
                current_performance_modifier NUMERIC(10,2) DEFAULT 1.00,
                current_max_pct_exposure NUMERIC(10,2) DEFAULT 0.25,
                performance_based_allocation BOOLEAN NOT NULL DEFAULT FALSE,
                max_price_spread NUMERIC(6,4) DEFAULT 0.0300,
                paper_trade BOOLEAN DEFAULT FALSE,
                test_filter BOOLEAN DEFAULT FALSE,
                prob_adj NUMERIC(5,2) DEFAULT 5.00,
                simulated_trade_loss_prevention BOOLEAN DEFAULT FALSE,
                simulated_trade_cooldown_duration INTEGER DEFAULT 4,
                simulated_trade_cooldown_start_time TIMESTAMPTZ,
                original_simulated_trade_cooldown_start_time TIMESTAMPTZ,
                simulated_trade_cooldown_loss_count INTEGER NOT NULL DEFAULT 0,
                live_trade_cooldown_start_time TIMESTAMPTZ,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        # New naming convention tables
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_btc (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,2),
                one_minute_avg DECIMAL(10,2),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1)
            );
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_eth (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,2),
                one_minute_avg DECIMAL(10,2),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1)
            );
        """))

        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_sol (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,6),
                one_minute_avg DECIMAL(10,6),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                momentum_percentile DECIMAL(5,1),
                momentum_5s_avg DECIMAL(5,1),
                momentum_30s_avg DECIMAL(5,1),
                volatility DECIMAL(10,6),
                volatility_percentile DECIMAL(5,1),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1)
            );
        """))

        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_xrp (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,6),
                one_minute_avg DECIMAL(10,6),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                momentum_percentile DECIMAL(5,1),
                momentum_5s_avg DECIMAL(5,1),
                momentum_30s_avg DECIMAL(5,1),
                volatility DECIMAL(10,6),
                volatility_percentile DECIMAL(5,1),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1)
            );
        """))
        
        # Ensure movement columns exist on live_price_log tables
        cursor.execute(_us("""
            DO $$
            DECLARE
                t text;
                c text;
                ty text;
                tbl regclass;
            BEGIN
                FOREACH t IN ARRAY ARRAY['live_price_log_1s_btc','live_price_log_1s_eth','live_price_log_1s_sol','live_price_log_1s_xrp'] LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = t) THEN
                        FOREACH c IN ARRAY ARRAY['move_1m','move_2m','move_3m','move_4m','move_15m','move_30m','movement','movement_percentile'] LOOP
                            IF c = 'movement_percentile' THEN ty := 'DECIMAL(5,1)'; ELSE ty := 'DECIMAL(10,4)'; END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = c) THEN
                                EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN %I ' || ty, t, c);
                            END IF;
                        END LOOP;
                    END IF;
                END LOOP;
            END $$;
        """))

        # Watchdog insert_tick requires momentum/volatility percentile columns (same as BTC/ETH).
        cursor.execute(_us("""
            DO $$
            DECLARE
                t text;
            BEGIN
                FOREACH t IN ARRAY ARRAY['live_price_log_1s_btc','live_price_log_1s_eth','live_price_log_1s_sol','live_price_log_1s_xrp'] LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = t) THEN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'momentum_percentile') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN momentum_percentile DECIMAL(5,1)', t);
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'momentum_5s_avg') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN momentum_5s_avg DECIMAL(5,1)', t);
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'momentum_30s_avg') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN momentum_30s_avg DECIMAL(5,1)', t);
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'volatility') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN volatility DECIMAL(10,6)', t);
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'volatility_percentile') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN volatility_percentile DECIMAL(5,1)', t);
                        END IF;
                    END IF;
                END LOOP;
            END $$;
        """))
        
        # Add volatility and movement columns to hourly strike tables (btc, eth)
        cursor.execute(_us("""
            DO $$
            DECLARE
                t text;
                r record;
            BEGIN
                FOREACH t IN ARRAY ARRAY['strike_table_hourly'] LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = t) THEN
                        FOR r IN (SELECT unnest(ARRAY['volatility','volatility_percentile','movement','movement_percentile']) AS col,
                                         unnest(ARRAY['NUMERIC(10,6)','NUMERIC(5,1)','NUMERIC(10,4)','NUMERIC(5,1)']) AS typ) LOOP
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = r.col) THEN
                                EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN %I ' || r.typ, t, r.col);
                            END IF;
                        END LOOP;
                    END IF;
                END LOOP;
            END $$;
        """))
        
        # Add market column (TEXT: 'hourly' or '15m') to all market_kalshi_* and strike_table_* tables
        cursor.execute(_us("""
            DO $$
            DECLARE
                r record;
                tbl text;
                def text;
            BEGIN
                FOR r IN (
                    SELECT unnest(ARRAY['market_kalshi_hourly']) AS t, 'hourly' AS d
                    UNION ALL SELECT 'market_kalshi_15m', '15m'
                    UNION ALL SELECT 'strike_table_hourly', 'hourly'
                    UNION ALL SELECT 'strike_table_15m', '15m'
                ) LOOP
                    tbl := r.t;
                    def := r.d;
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = tbl)
                       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = tbl AND column_name = 'market') THEN
                        EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN market TEXT DEFAULT %L', tbl, def);
                    END IF;
                END LOOP;
            END $$;
        """))
        
        # Rename momentum_value -> movement_value in all analytics movement profile tables
        cursor.execute(_us("""
            DO $$
            DECLARE
                r record;
            BEGIN
                FOR r IN (SELECT table_name FROM information_schema.tables
                          WHERE table_schema = 'analytics' AND table_name LIKE '%_movement_profile%') LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_schema = 'analytics' AND table_name = r.table_name AND column_name = 'momentum_value') THEN
                        EXECUTE format('ALTER TABLE analytics.%I RENAME COLUMN momentum_value TO movement_value', r.table_name);
                    END IF;
                END LOOP;
            END $$;
        """))
        
        # live_symbol_status: one row per symbol; columns mirror live_price_log_1s_* (latest tick per symbol)
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.live_symbol_status (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20),
                "timestamp" TEXT,
                price DECIMAL(10,2),
                one_minute_avg DECIMAL(10,2),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                momentum_percentile DECIMAL(5,1),
                momentum_5s_avg DECIMAL(5,1),
                volatility DECIMAL(10,6),
                volatility_percentile DECIMAL(5,1),
                momentum_30s_avg DECIMAL(5,1),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1),
                prev_day_avg_momentum_percentile DECIMAL(5,1),
                prev_day_avg_volatility_percentile DECIMAL(5,1),
                prev_day_avg_movement_percentile DECIMAL(5,1),
                daily_update TEXT
            );
        """))

        # Trigger-driven live_symbol_status sync depends on a deterministic uniqueness guarantee per symbol.
        cursor.execute(_us("""
            CREATE UNIQUE INDEX IF NOT EXISTS live_symbol_status_symbol_uniq_all
            ON live_data.live_symbol_status USING btree (symbol);
        """))
        # Trigger-driven sync from live_price_log_1s_* into live_symbol_status (BTC/ETH/SOL/XRP).
        cursor.execute(_us("""
            CREATE OR REPLACE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                sym text := TG_ARGV[0];
            BEGIN
                INSERT INTO live_data.live_symbol_status (
                    symbol, "timestamp", price, one_minute_avg, momentum,
                    delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m,
                    momentum_percentile, momentum_5s_avg, volatility, volatility_percentile, momentum_30s_avg,
                    move_1m, move_2m, move_3m, move_4m, move_15m, move_30m, movement, movement_percentile
                )
                VALUES (
                    sym, NEW.timestamp, NEW.price, NEW.one_minute_avg, NEW.momentum,
                    NEW.delta_1m, NEW.delta_2m, NEW.delta_3m, NEW.delta_4m, NEW.delta_15m, NEW.delta_30m,
                    NEW.momentum_percentile, NEW.momentum_5s_avg, NEW.volatility, NEW.volatility_percentile, NEW.momentum_30s_avg,
                    NEW.move_1m, NEW.move_2m, NEW.move_3m, NEW.move_4m, NEW.move_15m, NEW.move_30m, NEW.movement, NEW.movement_percentile
                )
                ON CONFLICT (symbol) DO UPDATE SET
                    "timestamp" = EXCLUDED."timestamp",
                    price = EXCLUDED.price,
                    one_minute_avg = EXCLUDED.one_minute_avg,
                    momentum = EXCLUDED.momentum,
                    delta_1m = EXCLUDED.delta_1m,
                    delta_2m = EXCLUDED.delta_2m,
                    delta_3m = EXCLUDED.delta_3m,
                    delta_4m = EXCLUDED.delta_4m,
                    delta_15m = EXCLUDED.delta_15m,
                    delta_30m = EXCLUDED.delta_30m,
                    momentum_percentile = EXCLUDED.momentum_percentile,
                    momentum_5s_avg = EXCLUDED.momentum_5s_avg,
                    volatility = EXCLUDED.volatility,
                    volatility_percentile = EXCLUDED.volatility_percentile,
                    momentum_30s_avg = EXCLUDED.momentum_30s_avg,
                    move_1m = EXCLUDED.move_1m,
                    move_2m = EXCLUDED.move_2m,
                    move_3m = EXCLUDED.move_3m,
                    move_4m = EXCLUDED.move_4m,
                    move_15m = EXCLUDED.move_15m,
                    move_30m = EXCLUDED.move_30m,
                    movement = EXCLUDED.movement,
                    movement_percentile = EXCLUDED.movement_percentile;
                RETURN NEW;
            END;
            $$;
        """))
        cursor.execute(_us("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_price_log_1s_btc') THEN
                    DROP TRIGGER IF EXISTS sync_live_symbol_status_btc_from_price_log ON live_data.live_price_log_1s_btc;
                    CREATE TRIGGER sync_live_symbol_status_btc_from_price_log
                    AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_btc
                    FOR EACH ROW EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log('BTC');
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_price_log_1s_eth') THEN
                    DROP TRIGGER IF EXISTS sync_live_symbol_status_eth_from_price_log ON live_data.live_price_log_1s_eth;
                    CREATE TRIGGER sync_live_symbol_status_eth_from_price_log
                    AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_eth
                    FOR EACH ROW EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log('ETH');
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_price_log_1s_sol') THEN
                    DROP TRIGGER IF EXISTS sync_live_symbol_status_sol_from_price_log ON live_data.live_price_log_1s_sol;
                    CREATE TRIGGER sync_live_symbol_status_sol_from_price_log
                    AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_sol
                    FOR EACH ROW EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log('SOL');
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_price_log_1s_xrp') THEN
                    DROP TRIGGER IF EXISTS sync_live_symbol_status_xrp_from_price_log ON live_data.live_price_log_1s_xrp;
                    CREATE TRIGGER sync_live_symbol_status_xrp_from_price_log
                    AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_xrp
                    FOR EACH ROW EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log('XRP');
                END IF;
            END $$;
        """))
        cursor.execute(_us("""
            DO $$
            DECLARE
                col text;
                ty text;
                cols text[] := ARRAY['timestamp','price','one_minute_avg','momentum','delta_1m','delta_2m','delta_3m','delta_4m','delta_15m','delta_30m','momentum_percentile','momentum_5s_avg','volatility','volatility_percentile','momentum_30s_avg','move_1m','move_2m','move_3m','move_4m','move_15m','move_30m','movement','movement_percentile','prev_day_avg_momentum_percentile','prev_day_avg_volatility_percentile','prev_day_avg_movement_percentile','daily_update'];
                types text[] := ARRAY['TEXT','DECIMAL(10,2)','DECIMAL(10,2)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(5,1)','DECIMAL(5,1)','DECIMAL(10,6)','DECIMAL(5,1)','DECIMAL(5,1)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(5,1)','DECIMAL(5,1)','DECIMAL(5,1)','DECIMAL(5,1)','TEXT'];
                i int;
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status') THEN
                    FOR i IN 1..array_length(cols, 1) LOOP
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status' AND column_name = cols[i]) THEN
                            EXECUTE format('ALTER TABLE live_data.live_symbol_status ADD COLUMN %I ' || types[i], cols[i]);
                        END IF;
                    END LOOP;
                END IF;
            END $$;
        """))
        # Migrate daily_update from timestamptz to TEXT (same format as timestamp column)
        cursor.execute(_us("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status' AND column_name = 'daily_update')
                   AND (SELECT data_type FROM information_schema.columns
                        WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status' AND column_name = 'daily_update') = 'timestamp with time zone' THEN
                    ALTER TABLE live_data.live_symbol_status
                    ALTER COLUMN daily_update TYPE TEXT USING to_char(daily_update AT TIME ZONE 'America/New_York', 'YYYY-MM-DD"T"HH24:MI:SS');
                END IF;
            END $$;
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.btc_price_change (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.eth_price_change (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        # New naming convention for price change tables
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_btc (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_eth (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))

        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_sol (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))

        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_xrp (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        # Unified hourly strike table (BTC+ETH rows); same column types as strike_table_15m / migration 20260331_1530.
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS live_data.strike_table_hourly (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
                symbol VARCHAR(10) NOT NULL,
                exchange VARCHAR(20) NOT NULL DEFAULT 'kalshi',
                market TEXT DEFAULT 'hourly',
                current_price NUMERIC(18,5),
                ttc_hourly INTEGER,
                ttc_15m INTEGER,
                event_ticker VARCHAR(50),
                market_title TEXT,
                strike_tier INTEGER,
                market_status VARCHAR(20),
                strike NUMERIC(18,5),
                buffer NUMERIC(18,5),
                buffer_pct NUMERIC(12,6),
                probability_hourly DECIMAL(5,2),
                probability_15m DECIMAL(5,2),
                yes_ask_dollars TEXT,
                no_ask_dollars TEXT,
                yes_bid_dollars TEXT,
                no_bid_dollars TEXT,
                yes_price_spread NUMERIC(6,4),
                no_price_spread NUMERIC(6,4),
                yes_diff DECIMAL(5,2),
                no_diff DECIMAL(5,2),
                volume_fp TEXT,
                open_interest_fp TEXT,
                ticker VARCHAR(50),
                active_side VARCHAR(10),
                momentum_weighted_score DECIMAL(5,3),
                momentum_percentile DECIMAL(5,1),
                volatility NUMERIC(10,6),
                volatility_percentile NUMERIC(5,1),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                yes_ask_min_15m NUMERIC(18,4),
                yes_ask_max_15m NUMERIC(18,4),
                no_ask_min_15m NUMERIC(18,4),
                no_ask_max_15m NUMERIC(18,4),
                yes_ask_range_15m NUMERIC(18,4),
                no_ask_range_15m NUMERIC(18,4),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            );
        """))

        # Backward-compatible column changes for existing hourly strike tables:
        # - Rename ttc_seconds -> ttc_hourly, probability -> probability_hourly.
        # - Add ttc_15m and probability_15m for simulated 15m cycles (initially NULL).
        cursor.execute(_us("""
            DO $$
            DECLARE
                tbl TEXT;
            BEGIN
                FOR tbl IN SELECT unnest(ARRAY[
                    'strike_table_hourly'
                ]) LOOP
                    -- Rename ttc_seconds to ttc_hourly if old column exists and new one does not
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'ttc_seconds'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'ttc_hourly'
                    ) THEN
                        EXECUTE format('ALTER TABLE live_data.%I RENAME COLUMN ttc_seconds TO ttc_hourly;', tbl);
                    END IF;

                    -- Rename probability to probability_hourly if old column exists and new one does not
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'probability'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'probability_hourly'
                    ) THEN
                        EXECUTE format('ALTER TABLE live_data.%I RENAME COLUMN probability TO probability_hourly;', tbl);
                    END IF;

                    -- Add 15m TTC/probability columns for simulated cycles if missing
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'ttc_15m'
                    ) THEN
                        EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN ttc_15m INTEGER;', tbl);
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'probability_15m'
                    ) THEN
                        EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN probability_15m DECIMAL(5,2);', tbl);
                    END IF;
                END LOOP;
            END
            $$;
        """))

        # Final-quarter (15m window) YES/NO ask extrema in dollars — matches migration
        # 20260328_2115_strike_table_final_quarter_ask_tracking.
        cursor.execute(_us("""
            DO $$
            DECLARE
              t TEXT;
              tables TEXT[] := ARRAY[
                'strike_table_15m',
                'strike_table_hourly'
              ];
            BEGIN
              FOREACH t IN ARRAY tables LOOP
                IF EXISTS (
                  SELECT 1 FROM information_schema.tables
                  WHERE table_schema = 'live_data' AND table_name = t
                ) THEN
                  EXECUTE format(
                    'ALTER TABLE live_data.%I
                       ADD COLUMN IF NOT EXISTS yes_ask_min_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS yes_ask_max_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS no_ask_min_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS no_ask_max_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS yes_ask_range_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS no_ask_range_15m NUMERIC(18,4);',
                    t
                  );
                END IF;
              END LOOP;
            END
            $$;
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS system.health_status (
                id SERIAL PRIMARY KEY,
                service_name VARCHAR(100),
                status VARCHAR(50),
                last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                details JSONB
            );
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS system.installation_access_log (
                id SERIAL PRIMARY KEY,
                installer_user_id VARCHAR(100) NOT NULL,
                installer_name VARCHAR(200),
                installer_email VARCHAR(200),
                installer_ip_address INET,
                connection_start TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                connection_end TIMESTAMP WITH TIME ZONE,
                schemas_accessed TEXT[],
                tables_cloned INTEGER,
                total_rows_cloned BIGINT,
                clone_duration_seconds INTEGER,
                status VARCHAR(50) DEFAULT 'in_progress',
                error_message TEXT,
                user_agent TEXT,
                installation_package_version VARCHAR(50),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))

        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS system.version_control (
                id SERIAL PRIMARY KEY,
                version VARCHAR(32) NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        cursor.execute(_us("""
            INSERT INTO system.version_control (version, updated_at)
            SELECT '3.0.1', NOW()
            WHERE NOT EXISTS (SELECT 1 FROM system.version_control);
        """))
        
        # Create historical_data schema and tables
        cursor.execute("CREATE SCHEMA IF NOT EXISTS historical_data;")
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS historical_data.strike_table_master (
                id BIGINT GENERATED ALWAYS AS IDENTITY,
                symbol VARCHAR(10) NOT NULL,
                exchange VARCHAR(20) NOT NULL,
                market TEXT DEFAULT '15m',
                market_ticker VARCHAR(64) NOT NULL,
                current_price NUMERIC(18,5),
                ttc_hourly INTEGER,
                ttc_15m INTEGER,
                event_ticker VARCHAR(50),
                market_title TEXT,
                strike_tier INTEGER,
                market_status VARCHAR(20),
                strike NUMERIC(18,5),
                buffer NUMERIC(18,5),
                buffer_pct NUMERIC(12,6),
                probability_hourly DECIMAL(5,2),
                probability_15m DECIMAL(5,2),
                yes_prob_hourly DECIMAL(5,2),
                no_prob_hourly DECIMAL(5,2),
                yes_prob_15m DECIMAL(5,2),
                no_prob_15m DECIMAL(5,2),
                yes_ask_dollars TEXT,
                no_ask_dollars TEXT,
                yes_bid_dollars TEXT,
                no_bid_dollars TEXT,
                yes_price_spread NUMERIC(6,4),
                no_price_spread NUMERIC(6,4),
                yes_diff DECIMAL(5,2),
                no_diff DECIMAL(5,2),
                volume_fp TEXT,
                open_interest_fp TEXT,
                ticker VARCHAR(50),
                active_side VARCHAR(10),
                momentum_weighted_score DECIMAL(5,3),
                momentum_percentile DECIMAL(5,1),
                volatility NUMERIC(10,6),
                volatility_percentile NUMERIC(5,1),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                yes_ask_min_15m NUMERIC(18,4),
                yes_ask_max_15m NUMERIC(18,4),
                no_ask_min_15m NUMERIC(18,4),
                no_ask_max_15m NUMERIC(18,4),
                yes_ask_range_15m NUMERIC(18,4),
                no_ask_range_15m NUMERIC(18,4),
                "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (timezone('America/New_York', now())),
                market_result TEXT,
                snapshot_wall_second BIGINT,
                snapshot_generation_seq BIGINT,
                PRIMARY KEY (id, "timestamp")
            ) PARTITION BY RANGE ("timestamp");
        """))
        cursor.execute(_us("""
            ALTER TABLE historical_data.strike_table_master
                ADD COLUMN IF NOT EXISTS snapshot_wall_second BIGINT,
                ADD COLUMN IF NOT EXISTS snapshot_generation_seq BIGINT;
        """))
        cursor.execute(_us("""
            CREATE INDEX IF NOT EXISTS strike_table_master_market_ts_idx
                ON historical_data.strike_table_master (market_ticker, "timestamp" DESC);
        """))
        cursor.execute(_us("""
            CREATE INDEX IF NOT EXISTS strike_table_master_symbol_market_ts_idx
                ON historical_data.strike_table_master (symbol, market, "timestamp" DESC);
        """))
        cursor.execute(_us("""
            DO $$
            DECLARE
                start_naive TIMESTAMP;
                end_naive TIMESTAMP;
                part_name TEXT;
                i INTEGER;
            BEGIN
                FOR i IN 0..2 LOOP
                    start_naive := (date_trunc('month', timezone('America/New_York', now())) + (i || ' months')::interval)::timestamp;
                    end_naive := (date_trunc('month', timezone('America/New_York', now())) + ((i + 1) || ' months')::interval)::timestamp;
                    part_name := format('strike_table_master_%s', to_char(start_naive, 'YYYYMM'));
                    EXECUTE format(
                        'CREATE TABLE IF NOT EXISTS historical_data.%I PARTITION OF historical_data.strike_table_master FOR VALUES FROM (%L) TO (%L)',
                        part_name, start_naive, end_naive
                    );
                END LOOP;
            END $$;
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS historical_data.btc_price_history (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                open DECIMAL(15,2),
                high DECIMAL(15,2),
                low DECIMAL(15,2),
                close DECIMAL(15,2),
                volume DECIMAL(20,8),
                momentum DECIMAL(10,4),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))
        
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS historical_data.eth_price_history (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                open DECIMAL(15,2),
                high DECIMAL(15,2),
                low DECIMAL(15,2),
                close DECIMAL(15,2),
                volume DECIMAL(20,8),
                momentum DECIMAL(10,4),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))
        
        # Ensure loss_prevention_toggle column exists for monitor_list_0001
        cursor.execute(_us("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'loss_prevention_toggle'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN loss_prevention_toggle BOOLEAN DEFAULT TRUE;
                    UPDATE users.monitor_list_0001 SET loss_prevention_toggle = TRUE WHERE loss_prevention_toggle IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'max_price_spread'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN max_price_spread NUMERIC(6,4) DEFAULT 0.0300;
                    UPDATE users.monitor_list_0001 SET max_price_spread = 0.0300 WHERE max_price_spread IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'paper_trade'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE;
                    UPDATE users.monitor_list_0001 SET paper_trade = FALSE WHERE paper_trade IS NULL;
                END IF;

                -- Regime Monitor settings columns (optional feature toggle + window)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'regime_monitor_enabled'
                ) THEN
                    ALTER TABLE users.monitor_list_0001
                    ADD COLUMN regime_monitor_enabled BOOLEAN DEFAULT FALSE;
                    UPDATE users.monitor_list_0001
                    SET regime_monitor_enabled = FALSE
                    WHERE regime_monitor_enabled IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'regime_window'
                ) THEN
                    ALTER TABLE users.monitor_list_0001
                    ADD COLUMN regime_window TEXT DEFAULT '30d';
                    UPDATE users.monitor_list_0001
                    SET regime_window = '30d'
                    WHERE regime_window IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'prob_adj'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN prob_adj NUMERIC(5,2) DEFAULT 5.00;
                    UPDATE users.monitor_list_0001 SET prob_adj = 5.00 WHERE prob_adj IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'min_cooldown_timer'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN min_cooldown_timer INTEGER DEFAULT 300;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'max_cooldown_timer'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN max_cooldown_timer INTEGER DEFAULT 3300;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'min_ask_range'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN min_ask_range NUMERIC(18,4);
                END IF;
            END
            $$;
        """))
        
        # Add market column to all monitor_list tables (hourly vs 15m); backfill existing rows to 'hourly'
        cursor.execute(_us("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'users' 
            AND table_name LIKE 'monitor_list_%'
            ORDER BY table_name
        """))
        monitor_list_tables_market = [row[0] for row in cursor.fetchall()]
        for table_name in monitor_list_tables_market:
            cursor.execute(_us(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'market'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN market TEXT DEFAULT %L', '{table_name}', 'hourly');
                        EXECUTE format('UPDATE users.%I SET market = %L WHERE market IS NULL', '{table_name}', 'hourly');
                    END IF;
                END
                $$;
            """))

        # Kalshi execution defaults on monitor_list (time_in_force + limit|market policy); trades snapshot via migration.
        cursor.execute(_us("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'users' 
            AND table_name LIKE 'monitor_list_%'
            ORDER BY table_name
        """))
        for (ml_tn,) in cursor.fetchall():
            cursor.execute(_us(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{ml_tn}'
                          AND column_name = 'time_in_force'
                    ) THEN
                        EXECUTE format(
                            'ALTER TABLE users.%I ADD COLUMN time_in_force TEXT NOT NULL DEFAULT %L',
                            '{ml_tn}', 'fill_or_kill'
                        );
                        EXECUTE format(
                            'ALTER TABLE users.%I ADD CONSTRAINT %I CHECK (time_in_force IN (%L, %L, %L))',
                            '{ml_tn}', '{ml_tn}_time_in_force_chk',
                            'fill_or_kill', 'immediate_or_cancel', 'good_till_canceled'
                        );
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{ml_tn}'
                          AND column_name = 'order_type'
                    ) THEN
                        EXECUTE format(
                            'ALTER TABLE users.%I ADD COLUMN order_type TEXT NOT NULL DEFAULT %L',
                            '{ml_tn}', 'market'
                        );
                        EXECUTE format(
                            'ALTER TABLE users.%I ADD CONSTRAINT %I CHECK (order_type IN (%L, %L))',
                            '{ml_tn}', '{ml_tn}_order_type_policy_chk',
                            'limit', 'market'
                        );
                    END IF;
                END
                $$;
            """))
        for tr_sim in ("trades_0001", "trades_simulated_0001"):
            cursor.execute(_us(f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'users' AND table_name = '{tr_sim}'
                    ) THEN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'users' AND table_name = '{tr_sim}'
                              AND column_name = 'time_in_force'
                        ) THEN
                            ALTER TABLE users.{tr_sim} ADD COLUMN time_in_force TEXT;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'users' AND table_name = '{tr_sim}'
                              AND column_name = 'order_type'
                        ) THEN
                            ALTER TABLE users.{tr_sim} ADD COLUMN order_type TEXT;
                        END IF;
                    END IF;
                END
                $$;
            """))

        # Archive live/paper trade tables must include every column the master trades table lists for
        # union_trades_with_archives_select(); otherwise GET /trades and dashboard PnL unions error.
        _arch_trades_tbl = re.compile(r"^trades_archive_(?:live|paper)_\d{4}$")
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'archive'
              AND (
                table_name LIKE 'trades_archive_live_' || '%'
                OR table_name LIKE 'trades_archive_paper_' || '%'
              )
            ORDER BY table_name
            """
        )
        for (arch_tn,) in cursor.fetchall():
            if not arch_tn or not _arch_trades_tbl.match(arch_tn):
                continue
            cursor.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'archive'
                          AND table_name = '{arch_tn}'
                          AND column_name = 'time_in_force'
                    ) THEN
                        ALTER TABLE archive.{arch_tn} ADD COLUMN time_in_force TEXT;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'archive'
                          AND table_name = '{arch_tn}'
                          AND column_name = 'order_type'
                    ) THEN
                        ALTER TABLE archive.{arch_tn} ADD COLUMN order_type TEXT;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'archive'
                          AND table_name = '{arch_tn}'
                          AND column_name = 'loss_prevention_state'
                    ) THEN
                        ALTER TABLE archive.{arch_tn} ADD COLUMN loss_prevention_state VARCHAR(64);
                    END IF;
                END
                $$;
                """
            )

        # Create strategy_list_0001 table with all default settings columns (matching monitor_list structure)
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS users.strategy_list_0001 (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated TIMESTAMP,
                -- Strategy default settings (matching monitor_list columns, excluding monitor-specific ones)
                win_streak_threshold INTEGER DEFAULT 22,
                loss_prevention VARCHAR(50) DEFAULT 'none',
                loss_prevention_toggle BOOLEAN DEFAULT TRUE,
                performance_based_allocation BOOLEAN NOT NULL DEFAULT FALSE,
                max_price_spread NUMERIC(6,4) DEFAULT 0.0300,
                paper_trade BOOLEAN DEFAULT FALSE,
                prob_adj NUMERIC(5,2) DEFAULT 5.00,
                -- Position sizing defaults
                position_size INTEGER DEFAULT 1,
                position_type VARCHAR(20) DEFAULT 'percent',
                multiplier NUMERIC(3,2) DEFAULT 1.00,
                -- Auto entry settings
                min_probability NUMERIC(5,2),
                max_probability NUMERIC(5,2),
                min_differential NUMERIC(5,2) DEFAULT 0.25,
                max_differential NUMERIC(5,2),
                min_time INTEGER,
                max_time INTEGER,
                allow_re_entry BOOLEAN DEFAULT FALSE,
                spike_alert_enabled BOOLEAN DEFAULT FALSE,
                spike_alert_momentum_threshold INTEGER,
                spike_alert_cooldown_threshold INTEGER,
                spike_alert_cooldown_minutes INTEGER,
                current_probability INTEGER,
                min_ttc_seconds INTEGER,
                momentum_spike_enabled BOOLEAN DEFAULT FALSE,
                momentum_spike_threshold INTEGER,
                verification_period_enabled BOOLEAN DEFAULT FALSE,
                verification_period_seconds INTEGER,
                min_volume INTEGER,
                momentum_scalp_entry_threshold NUMERIC(5,2),
                momentum_scalp_trailing_stop_amount NUMERIC(5,2) DEFAULT 0.10,
                momentum_scalp_profit_target NUMERIC(5,2) DEFAULT 0.99,
                min_ask NUMERIC(6,4) DEFAULT 0.0000,
                max_ask NUMERIC(6,4) DEFAULT 0.9800,
                max_profit NUMERIC(6,4) DEFAULT 0.9900,
                stop_loss_price NUMERIC(6,4) DEFAULT 0.0000,
                min_ask_range NUMERIC(18,4),
                min_cooldown_timer INTEGER DEFAULT 300,
                max_cooldown_timer INTEGER DEFAULT 3300,
                regime_monitor_enabled BOOLEAN DEFAULT FALSE,
                regime_window TEXT DEFAULT '30d',
                time_in_force TEXT NOT NULL DEFAULT 'fill_or_kill',
                order_type TEXT NOT NULL DEFAULT 'market',
                simulated_trade_loss_prevention BOOLEAN DEFAULT FALSE,
                simulated_trade_cooldown_duration INTEGER DEFAULT 4,
                simulated_trade_cooldown_start_time TIMESTAMPTZ,
                original_simulated_trade_cooldown_start_time TIMESTAMPTZ,
                simulated_trade_cooldown_loss_count INTEGER NOT NULL DEFAULT 0,
                live_trade_cooldown_start_time TIMESTAMPTZ,
                flip_sell_prob BOOLEAN NOT NULL DEFAULT FALSE,
                flip_sell_floor BOOLEAN NOT NULL DEFAULT FALSE,
                flip_sell_prob_mult VARCHAR(32),
                flip_sell_floor_mult VARCHAR(32),
                CONSTRAINT strategy_list_0001_time_in_force_chk CHECK (time_in_force IN ('fill_or_kill', 'immediate_or_cancel', 'good_till_canceled')),
                CONSTRAINT strategy_list_0001_order_type_chk CHECK (order_type IN ('limit', 'market'))
            );
        """))
        
        # Add any missing columns to strategy_list_0001 (for existing tables)
        cursor.execute(_us("""
            DO $$
            BEGIN
                -- Add columns that might not exist in older versions
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'updated'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN updated TIMESTAMP;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'win_streak_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN win_streak_threshold INTEGER DEFAULT 22;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'loss_prevention'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN loss_prevention VARCHAR(50) DEFAULT 'none';
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'loss_prevention_toggle'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN loss_prevention_toggle BOOLEAN DEFAULT TRUE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'performance_based_allocation'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN performance_based_allocation BOOLEAN NOT NULL DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_price_spread'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_price_spread NUMERIC(6,4) DEFAULT 0.0300;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'paper_trade'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'prob_adj'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN prob_adj NUMERIC(5,2) DEFAULT 5.00;
                END IF;
                
                -- Auto entry settings columns
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_probability'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_probability NUMERIC(5,2);
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_probability'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_probability NUMERIC(5,2);
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_differential'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_differential NUMERIC(5,2) DEFAULT 0.25;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_differential'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_differential NUMERIC(5,2);
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_time'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_time INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_time'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_time INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'allow_re_entry'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN allow_re_entry BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'spike_alert_enabled'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN spike_alert_enabled BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'spike_alert_momentum_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN spike_alert_momentum_threshold INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'spike_alert_cooldown_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN spike_alert_cooldown_threshold INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'spike_alert_cooldown_minutes'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN spike_alert_cooldown_minutes INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'current_probability'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN current_probability INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_ttc_seconds'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_ttc_seconds INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_spike_enabled'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_spike_enabled BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_spike_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_spike_threshold INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'verification_period_enabled'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN verification_period_enabled BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'verification_period_seconds'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN verification_period_seconds INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_volume'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_volume INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_scalp_entry_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_scalp_entry_threshold NUMERIC(5,2);
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_scalp_trailing_stop_amount'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_scalp_trailing_stop_amount NUMERIC(5,2) DEFAULT 0.10;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_scalp_profit_target'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_scalp_profit_target NUMERIC(5,2) DEFAULT 0.99;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_ask'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_ask NUMERIC(6,4) DEFAULT 0.0000;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_ask'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_ask NUMERIC(6,4) DEFAULT 0.9800;
                END IF;
                
                -- Position sizing defaults
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'position_size'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN position_size INTEGER DEFAULT 1;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'position_type'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN position_type VARCHAR(20) DEFAULT 'percent';
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'multiplier'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN multiplier NUMERIC(3,2) DEFAULT 1.00;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_profit'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_profit NUMERIC(6,4) DEFAULT 0.9900;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'stop_loss_price'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN stop_loss_price NUMERIC(6,4) DEFAULT 0.0000;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_ask_range'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_ask_range NUMERIC(18,4);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_cooldown_timer'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_cooldown_timer INTEGER DEFAULT 300;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_cooldown_timer'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_cooldown_timer INTEGER DEFAULT 3300;
                END IF;
            END
            $$;
        """))

        # system.master_users: canonical table (migration 20260410_1015_users_master_users_to_system); not in users schema
        cursor.execute(_us("""
            CREATE TABLE IF NOT EXISTS system.master_users (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                phone VARCHAR(50),
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                system_version VARCHAR(50),
                status VARCHAR(64) DEFAULT 'active',
                notes TEXT,
                password_hash VARCHAR(255),
                kalshi_user_id VARCHAR(64),
                exchange_credentials JSONB NOT NULL DEFAULT '{"kalshi": false, "polymarket": false}'::jsonb
            );
        """))
        cursor.execute(_us("""
            CREATE OR REPLACE VIEW system.active_master_users AS
            SELECT user_id, name, email, last_updated
            FROM system.master_users
            WHERE status = 'active';
        """))
        cursor.execute(_us("""
            CREATE OR REPLACE VIEW system.recent_master_registrations AS
            SELECT user_id, name, email, registration_date
            FROM system.master_users
            WHERE registration_date > NOW() - INTERVAL '30 days';
        """))
        cursor.execute(_us("""
            CREATE OR REPLACE VIEW system.master_users_summary AS
            SELECT
                COUNT(*)::bigint AS total_users,
                COUNT(*) FILTER (WHERE status = 'active')::bigint AS active_users,
                COUNT(*) FILTER (WHERE registration_date > NOW() - INTERVAL '30 days')::bigint AS recent_registrations
            FROM system.master_users;
        """))
        # system.strategy_list_default mirror (migrations 20260409_2200, 20260409_2300)
        cursor.execute(_us("""
            DO $$
            BEGIN
                IF to_regclass('users.strategy_list_0001') IS NOT NULL
                   AND to_regclass('system.strategy_list_default') IS NULL THEN
                    EXECUTE 'CREATE TABLE system.strategy_list_default (LIKE users.strategy_list_0001 INCLUDING ALL)';
                    EXECUTE 'INSERT INTO system.strategy_list_default SELECT * FROM users.strategy_list_0001';
                END IF;
            END
            $$;
        """))
        cursor.execute(_us("""
            DO $$
            DECLARE
                seq text;
                has_id boolean;
            BEGIN
                IF to_regclass('system.master_users') IS NOT NULL THEN
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'system'
                          AND table_name = 'master_users'
                          AND column_name = 'id'
                    ) INTO has_id;
                    IF has_id THEN
                        seq := pg_get_serial_sequence('system.master_users', 'id');
                        IF seq IS NOT NULL THEN
                            EXECUTE format(
                                'SELECT setval(%L, (SELECT COALESCE(MAX(id), 1) FROM system.master_users), true)',
                                seq
                            );
                        END IF;
                    END IF;
                END IF;
                IF to_regclass('system.strategy_list_default') IS NOT NULL THEN
                    seq := pg_get_serial_sequence('system.strategy_list_default', 'id');
                    IF seq IS NOT NULL THEN
                        EXECUTE format(
                            'SELECT setval(%L, (SELECT COALESCE(MAX(id), 1) FROM system.strategy_list_default), true)',
                            seq
                        );
                    END IF;
                END IF;
            END
            $$;
        """))
        
        # Add columns to every monitor_list_* table in the init tenant schema and, when it differs,
        # the legacy ``users`` schema. ``_us()`` rewrites DDL to ``TS`` only; tables that still live
        # under ``users`` were previously skipped, so symbol_wide (and other) columns never appeared.
        _ml_migrate_schemas = sorted({TS, "users"})
        for _ml_schema in _ml_migrate_schemas:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name LIKE 'monitor_list_%%'
                ORDER BY table_name
                """,
                (_ml_schema,),
            )
            _monitor_list_tables = [row[0] for row in cursor.fetchall()]
            for _ml_table in _monitor_list_tables:
                cursor.execute(
                    f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'paper_trade'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE', '{_ml_schema}', '{_ml_table}');
                        EXECUTE format('UPDATE %I.%I SET paper_trade = FALSE WHERE paper_trade IS NULL', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'test_filter'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN test_filter BOOLEAN DEFAULT FALSE', '{_ml_schema}', '{_ml_table}');
                        EXECUTE format('UPDATE %I.%I SET test_filter = FALSE WHERE test_filter IS NULL', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'regime_monitor_enabled'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN regime_monitor_enabled BOOLEAN DEFAULT FALSE', '{_ml_schema}', '{_ml_table}');
                        EXECUTE format('UPDATE %I.%I SET regime_monitor_enabled = FALSE WHERE regime_monitor_enabled IS NULL', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'regime_window'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN regime_window TEXT DEFAULT %L', '{_ml_schema}', '{_ml_table}', '30d');
                        EXECUTE format('UPDATE %I.%I SET regime_window = %L WHERE regime_window IS NULL', '{_ml_schema}', '{_ml_table}', '30d');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'prob_adj'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN prob_adj NUMERIC(5,2) DEFAULT 5.00', '{_ml_schema}', '{_ml_table}');
                        EXECUTE format('UPDATE %I.%I SET prob_adj = 5.00 WHERE prob_adj IS NULL', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'stop_loss_price'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN stop_loss_price NUMERIC(6,4) DEFAULT 0.0000', '{_ml_schema}', '{_ml_table}');
                        EXECUTE format('UPDATE %I.%I SET stop_loss_price = 0.0000 WHERE stop_loss_price IS NULL', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'flip_sell_prob'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN flip_sell_prob BOOLEAN NOT NULL DEFAULT FALSE', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'flip_sell_floor'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN flip_sell_floor BOOLEAN NOT NULL DEFAULT FALSE', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'flip_sell_prob_mult'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN flip_sell_prob_mult VARCHAR(32)', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'flip_sell_floor_mult'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN flip_sell_floor_mult VARCHAR(32)', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'symbol_wide_loss_prevention'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'simulated_trade_loss_prevention'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN symbol_wide_loss_prevention TO simulated_trade_loss_prevention', '{_ml_schema}', '{_ml_table}');
                        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN symbol_wide_cooldown_duration TO simulated_trade_cooldown_duration', '{_ml_schema}', '{_ml_table}');
                        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN symbol_wide_cooldown_start_time TO simulated_trade_cooldown_start_time', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'simulated_trade_loss_prevention'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_trade_loss_prevention BOOLEAN DEFAULT FALSE', '{_ml_schema}', '{_ml_table}');
                        EXECUTE format('UPDATE %I.%I SET simulated_trade_loss_prevention = FALSE WHERE simulated_trade_loss_prevention IS NULL', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'simulated_trade_cooldown_duration'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_duration INTEGER DEFAULT 4', '{_ml_schema}', '{_ml_table}');
                        EXECUTE format('UPDATE %I.%I SET simulated_trade_cooldown_duration = 4 WHERE simulated_trade_cooldown_duration IS NULL', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'simulated_trade_cooldown_start_time'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_start_time TIMESTAMPTZ', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'original_simulated_trade_cooldown_start_time'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN original_simulated_trade_cooldown_start_time TIMESTAMPTZ', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'simulated_trade_cooldown_loss_count'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_loss_count INTEGER NOT NULL DEFAULT 0', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_ml_schema}'
                          AND table_name = '{_ml_table}'
                          AND column_name = 'live_trade_cooldown_start_time'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN live_trade_cooldown_start_time TIMESTAMPTZ', '{_ml_schema}', '{_ml_table}');
                    END IF;

                    EXECUTE format(
                        'UPDATE %I.%I SET loss_prevention = %L WHERE loss_prevention IS NOT NULL AND lower(trim(loss_prevention::text)) = %L',
                        '{_ml_schema}', '{_ml_table}', 'win_streak_one_contract', 'one_contract'
                    );
                END
                $$;
                """
                )
                if _ml_table.startswith("monitor_list_"):
                    _ledger_slot = _ml_table.replace("monitor_list_", "", 1)
                    cursor.execute(
                        _us(
                            f"""
                        CREATE TABLE IF NOT EXISTS users.sim_trade_lp_cycle_ledger_{_ledger_slot} (
                            monitor_id INTEGER NOT NULL,
                            cycle_date DATE NOT NULL,
                            weekly_cycle NUMERIC(10, 1) NOT NULL,
                            applied_units INTEGER NOT NULL DEFAULT 0,
                            PRIMARY KEY (monitor_id, cycle_date, weekly_cycle)
                        );
                        """
                        )
                    )

        # strategy_list_* + system.strategy_list_default: keep auto-trade / UAT columns aligned with monitor_list_*.
        _sl_targets: list[tuple[str, str]] = []
        for _sl_schema in _ml_migrate_schemas:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name LIKE 'strategy_list_%%'
                ORDER BY table_name
                """,
                (_sl_schema,),
            )
            _sl_targets.extend((_sl_schema, row[0]) for row in cursor.fetchall())
        cursor.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
            LIMIT 1
            """
        )
        if cursor.fetchone():
            _sl_targets.append(("system", "strategy_list_default"))

        for _sl_schema, _sl_table in _sl_targets:
            cursor.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'regime_monitor_enabled'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN regime_monitor_enabled BOOLEAN DEFAULT FALSE', '{_sl_schema}', '{_sl_table}');
                        EXECUTE format('UPDATE %I.%I SET regime_monitor_enabled = FALSE WHERE regime_monitor_enabled IS NULL', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'regime_window'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN regime_window TEXT DEFAULT %L', '{_sl_schema}', '{_sl_table}', '30d');
                        EXECUTE format('UPDATE %I.%I SET regime_window = %L WHERE regime_window IS NULL', '{_sl_schema}', '{_sl_table}', '30d');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'time_in_force'
                    ) THEN
                        EXECUTE format(
                            'ALTER TABLE %I.%I ADD COLUMN time_in_force TEXT NOT NULL DEFAULT %L',
                            '{_sl_schema}', '{_sl_table}', 'fill_or_kill'
                        );
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'order_type'
                    ) THEN
                        EXECUTE format(
                            'ALTER TABLE %I.%I ADD COLUMN order_type TEXT NOT NULL DEFAULT %L',
                            '{_sl_schema}', '{_sl_table}', 'market'
                        );
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint c
                        JOIN pg_class t ON c.conrelid = t.oid
                        JOIN pg_namespace n ON t.relnamespace = n.oid
                        WHERE n.nspname = '{_sl_schema}'
                          AND t.relname = '{_sl_table}'
                          AND c.conname = '{_sl_table}_time_in_force_chk'
                    ) THEN
                        EXECUTE format(
                            'ALTER TABLE %I.%I ADD CONSTRAINT %I CHECK (time_in_force IN (%L, %L, %L))',
                            '{_sl_schema}', '{_sl_table}', '{_sl_table}_time_in_force_chk',
                            'fill_or_kill', 'immediate_or_cancel', 'good_till_canceled'
                        );
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint c
                        JOIN pg_class t ON c.conrelid = t.oid
                        JOIN pg_namespace n ON t.relnamespace = n.oid
                        WHERE n.nspname = '{_sl_schema}'
                          AND t.relname = '{_sl_table}'
                          AND c.conname = '{_sl_table}_order_type_policy_chk'
                    ) THEN
                        EXECUTE format(
                            'ALTER TABLE %I.%I ADD CONSTRAINT %I CHECK (order_type IN (%L, %L))',
                            '{_sl_schema}', '{_sl_table}', '{_sl_table}_order_type_policy_chk',
                            'limit', 'market'
                        );
                    END IF;

                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'symbol_wide_loss_prevention'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'simulated_trade_loss_prevention'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN symbol_wide_loss_prevention TO simulated_trade_loss_prevention', '{_sl_schema}', '{_sl_table}');
                        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN symbol_wide_cooldown_duration TO simulated_trade_cooldown_duration', '{_sl_schema}', '{_sl_table}');
                        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN symbol_wide_cooldown_start_time TO simulated_trade_cooldown_start_time', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'simulated_trade_loss_prevention'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_trade_loss_prevention BOOLEAN DEFAULT FALSE', '{_sl_schema}', '{_sl_table}');
                        EXECUTE format('UPDATE %I.%I SET simulated_trade_loss_prevention = FALSE WHERE simulated_trade_loss_prevention IS NULL', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'simulated_trade_cooldown_duration'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_duration INTEGER DEFAULT 4', '{_sl_schema}', '{_sl_table}');
                        EXECUTE format('UPDATE %I.%I SET simulated_trade_cooldown_duration = 4 WHERE simulated_trade_cooldown_duration IS NULL', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'simulated_trade_cooldown_start_time'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_start_time TIMESTAMPTZ', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'original_simulated_trade_cooldown_start_time'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN original_simulated_trade_cooldown_start_time TIMESTAMPTZ', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'simulated_trade_cooldown_loss_count'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_loss_count INTEGER NOT NULL DEFAULT 0', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'live_trade_cooldown_start_time'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN live_trade_cooldown_start_time TIMESTAMPTZ', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'flip_sell_prob'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN flip_sell_prob BOOLEAN NOT NULL DEFAULT FALSE', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'flip_sell_floor'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN flip_sell_floor BOOLEAN NOT NULL DEFAULT FALSE', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'flip_sell_prob_mult'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN flip_sell_prob_mult VARCHAR(32)', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = '{_sl_schema}'
                          AND table_name = '{_sl_table}'
                          AND column_name = 'flip_sell_floor_mult'
                    ) THEN
                        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN flip_sell_floor_mult VARCHAR(32)', '{_sl_schema}', '{_sl_table}');
                    END IF;

                    EXECUTE format(
                        'UPDATE %I.%I SET loss_prevention = %L WHERE loss_prevention IS NOT NULL AND lower(trim(loss_prevention::text)) = %L',
                        '{_sl_schema}', '{_sl_table}', 'win_streak_one_contract', 'one_contract'
                    );
                END
                $$;
                """
            )

        # -------------------------------------------------------------------------
        # Symbol-wide loss prevention: partial index on trades_* for startup scan
        # (MAX closed_at GROUP BY symbol for qualifying losses).
        #
        # ROLLBACK (reverse migration): for each users.trades_<slot> run:
        #   DROP INDEX IF EXISTS users.idx_trades_<slot>_sw_lp_startup;
        # -------------------------------------------------------------------------
        cursor.execute(_us("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'users'
              AND table_name ~ '^trades_[0-9]{{4}}$'
            ORDER BY table_name
        """))
        trades_tenant_tables = [row[0] for row in cursor.fetchall()]
        for _tn in trades_tenant_tables:
            _suffix = _tn.replace("trades_", "", 1)
            _idx = f"idx_trades_{_suffix}_sw_lp_startup"
            cursor.execute(
                _us(
                    f"""
                    CREATE INDEX IF NOT EXISTS {_idx}
                    ON users.{_tn} (symbol, closed_at DESC)
                    WHERE status = 'closed'
                      AND win_loss = 'L'
                      AND (paper_trade IS NOT TRUE)
                      AND (test_filter IS NOT TRUE)
                    """
                )
            )
            cursor.execute(
                _us(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'users' AND table_name = '{_tn}'
                              AND column_name = 'loss_prevention_state'
                        ) THEN
                            EXECUTE format(
                                'ALTER TABLE %I.%I ADD COLUMN loss_prevention_state VARCHAR(64)',
                                'users', '{_tn}'
                            );
                        END IF;
                    END
                    $$;
                    """
                )
            )

        # Grant privileges
        cursor.execute(_us("GRANT ALL PRIVILEGES ON SCHEMA users TO rec_io_user;"))
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA live_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA system TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA historical_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA backtest TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA archive TO rec_io_user;")
        cursor.execute(_us("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA users TO rec_io_user;"))
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA live_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA system TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA historical_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA backtest TO rec_io_user;")
        cursor.execute(_us("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA users TO rec_io_user;"))
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA live_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA system TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA historical_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA backtest TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA archive TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA archive TO rec_io_user;")

        # Row-level tenant gate on users_* (see migration 20260411_1500_rec_tenant_rls_session_guc).
        try:
            cursor.execute(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_proc p
                  JOIN pg_namespace n ON p.pronamespace = n.oid
                  WHERE n.nspname = 'rec'
                    AND p.proname = 'ensure_tenant_rls_for_schema'
                )
                """
            )
            if cursor.fetchone()[0]:
                cursor.execute("SELECT rec.ensure_tenant_rls_for_schema(%s)", (TS,))
        except Exception as rls_exc:
            print(f"⚠️ rec.ensure_tenant_rls_for_schema skipped (run migrations if needed): {rls_exc}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Database initialized successfully")
        print(
            "Note: ongoing schema changes belong in scripts/migrations/*.up.sql "
            "and scripts/db/run_migration.py up <id>, not init_database()."
        )
        return True, "Database initialized successfully"
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return False, f"Database initialization error: {e}"
