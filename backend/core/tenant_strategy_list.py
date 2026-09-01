"""
Per-tenant strategy picker data (dashboard / trade history dropdowns).

Uses an **explicit** tenant slot on :func:`get_postgresql_connection` so the connection
always rewrites ``users.*`` SQL to ``users_<slot>``, independent of ContextVar timing.
Reads ``system.strategy_list_default`` via :func:`get_system_postgresql_connection` so
catalog reads are not subject to tenant RLS on ``users_*`` tables.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple

import psycopg2

from backend.core.config.database import (
    get_postgresql_connection,
    get_system_postgresql_connection,
)

logger = logging.getLogger(__name__)

_SLOT_RE = re.compile(r"^\d{4}$")

# Last-resort picker labels if DB seed and system mirror both fail.
FALLBACK_STRATEGY_NAMES: Tuple[str, ...] = (
    "Hourly HTC",
    "Reverse HTC",
    "Momentum Scalp",
    "Momentum Breakout",
    "Momentum Contain",
    "Rising Devil",
    "Expiration Scalp",
    "High Water Scalp",
    "High Water Test 1",
    "Test Strategy",
    "Daily HTC",
    "Scalp Strategy",
)


def normalize_strategy_slot(raw: str) -> str:
    s = str(raw or "").strip().zfill(4)
    if not _SLOT_RE.match(s):
        raise ValueError(f"invalid tenant slot for strategy list: {raw!r}")
    return s


def _system_default_strategy_names() -> List[str]:
    conn = get_system_postgresql_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
                )
                """
            )
            if not cur.fetchone()[0]:
                return []
            cur.execute(
                """
                SELECT name FROM system.strategy_list_default
                WHERE name IS NOT NULL AND BTRIM(name::text) <> ''
                ORDER BY id
                """
            )
            return [str(r[0]) for r in cur.fetchall() if r[0]]
    except Exception as e:
        logger.warning("tenant_strategy_list: read system.strategy_list_default: %s", e)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _system_strategy_list_default_table_exists_on_cursor(cursor) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
        )
        """
    )
    return bool(cursor.fetchone()[0])


def _tenant_strategy_list_has_full_defaults_columns(cursor, tenant_schema: str, table: str) -> bool:
    """True when the tenant table has monitor-default columns (not the old name-only stub)."""
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = 'win_streak_threshold'
        )
        """,
        (tenant_schema, table),
    )
    return bool(cursor.fetchone()[0])


def load_strategy_picker_for_slot(user_slot: str) -> Dict[str, Any]:
    """
    Return ``strategies`` and ``default_strategy_names`` for the given four-digit slot.

    Ensures ``strategy_list_<slot>`` exists under ``users_<slot>``. Prefer
    ``CREATE ... (LIKE system.strategy_list_default INCLUDING ALL)`` plus a full row copy
    from ``system.strategy_list_default`` so new monitors inherit real defaults. Falls back
    to the legacy name-only table only when the system mirror is missing. If the tenant
    table still yields nothing (e.g. RLS), uses system names or :data:`FALLBACK_STRATEGY_NAMES`.
    """
    slot = normalize_strategy_slot(user_slot)
    tenant_schema = f"users_{slot}"
    table = f"strategy_list_{slot}"
    qualified_legacy = f"users.{table}"

    conn = get_postgresql_connection(tenant_user_no=slot)
    if not conn:
        names = _system_default_strategy_names() or list(FALLBACK_STRATEGY_NAMES)
        logger.warning(
            "tenant_strategy_list: no tenant DB connection; slot=%s static/system count=%s",
            slot,
            len(names),
        )
        return {
            "strategies": names,
            "default_strategy_names": list(names),
        }

    strategies: List[str] = []
    default_strategy_names: List[str] = []
    outcome = "tenant_table"

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                (tenant_schema, table),
            )
            table_present = bool(cursor.fetchone()[0])
            if table_present and not _tenant_strategy_list_has_full_defaults_columns(
                cursor, tenant_schema, table
            ):
                logger.info(
                    "tenant_strategy_list: dropping stub strategy_list for slot=%s (incomplete columns)",
                    slot,
                )
                cursor.execute(f"DROP TABLE IF EXISTS {qualified_legacy} CASCADE")
                table_present = False

            if not table_present:
                if _system_strategy_list_default_table_exists_on_cursor(cursor):
                    try:
                        cursor.execute(
                            f"CREATE TABLE {qualified_legacy} (LIKE system.strategy_list_default INCLUDING ALL)"
                        )
                        cursor.execute(
                            f"""
                            INSERT INTO {qualified_legacy}
                            SELECT * FROM system.strategy_list_default
                            ON CONFLICT (name) DO NOTHING
                            """
                        )
                    except psycopg2.Error as e:
                        logger.warning(
                            "tenant_strategy_list: full strategy_list create/seed failed slot=%s: %s",
                            slot,
                            e,
                        )
                        cursor.execute(f"DROP TABLE IF EXISTS {qualified_legacy} CASCADE")
                        cursor.execute(
                            f"""
                            CREATE TABLE IF NOT EXISTS {qualified_legacy} (
                                id SERIAL PRIMARY KEY,
                                name VARCHAR(100) NOT NULL UNIQUE,
                                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                else:
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {qualified_legacy} (
                            id SERIAL PRIMARY KEY,
                            name VARCHAR(100) NOT NULL UNIQUE,
                            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

            cursor.execute(f"SELECT COUNT(*) FROM {qualified_legacy}")
            count = int(cursor.fetchone()[0] or 0)

            if count == 0 and _system_strategy_list_default_table_exists_on_cursor(cursor):
                try:
                    cursor.execute(
                        f"""
                        INSERT INTO {qualified_legacy}
                        SELECT * FROM system.strategy_list_default
                        ON CONFLICT (name) DO NOTHING
                        """
                    )
                except psycopg2.Error as e:
                    logger.debug("tenant_strategy_list: refill from system skipped slot=%s: %s", slot, e)
                cursor.execute(f"SELECT COUNT(*) FROM {qualified_legacy}")
                count = int(cursor.fetchone()[0] or 0)

            if count == 0:
                sys_names = _system_default_strategy_names()
                for nm in sys_names:
                    try:
                        cursor.execute(
                            f"""
                            INSERT INTO {qualified_legacy} (name) VALUES (%s)
                            ON CONFLICT (name) DO NOTHING
                            """,
                            (nm,),
                        )
                    except psycopg2.Error:
                        break
                cursor.execute(f"SELECT COUNT(*) FROM {qualified_legacy}")
                count = int(cursor.fetchone()[0] or 0)

            if count == 0:
                for nm in FALLBACK_STRATEGY_NAMES:
                    try:
                        cursor.execute(
                            f"""
                            INSERT INTO {qualified_legacy} (name) VALUES (%s)
                            ON CONFLICT (name) DO NOTHING
                            """,
                            (nm,),
                        )
                    except psycopg2.Error:
                        break

            try:
                cursor.execute(
                    f"""
                    SELECT name, "default"
                    FROM {qualified_legacy}
                    ORDER BY id
                    """
                )
                rows = cursor.fetchall()
                strategies = [str(r[0]) for r in rows if r[0]]
                default_strategy_names = [
                    str(r[0]) for r in rows if r[0] and r[1]
                ]
            except psycopg2.ProgrammingError:
                cursor.execute(
                    f"""
                    SELECT name FROM {qualified_legacy} ORDER BY id
                    """
                )
                rows = cursor.fetchall()
                strategies = [str(r[0]) for r in rows if r[0]]
                default_strategy_names = list(strategies)

            strategies = [s for s in strategies if s.strip()]
            default_strategy_names = [s for s in default_strategy_names if s.strip()]

            if not strategies:
                sys_names = _system_default_strategy_names()
                if sys_names:
                    strategies = sys_names
                    default_strategy_names = list(sys_names)
                    outcome = "system_mirror_rls_or_empty_tenant"
                else:
                    strategies = list(FALLBACK_STRATEGY_NAMES)
                    default_strategy_names = list(FALLBACK_STRATEGY_NAMES)
                    outcome = "static_fallback"

        conn.commit()
    except Exception as e:
        logger.warning("tenant_strategy_list: slot=%s error: %s", slot, e)
        try:
            conn.rollback()
        except Exception:
            pass
        names = _system_default_strategy_names() or list(FALLBACK_STRATEGY_NAMES)
        strategies = names
        default_strategy_names = list(names)
        outcome = "error_recovery"
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if outcome != "tenant_table":
        logger.info(
            "tenant_strategy_list: slot=%s outcome=%s strategies=%s",
            slot,
            outcome,
            len(strategies),
        )

    return {
        "strategies": strategies,
        "default_strategy_names": default_strategy_names,
    }
