"""
Move rows from users.trades_0001 into archive.trades_archive_{live|paper}_<user_number> when:

- POST /api/monitor/archive: all trades for that monitor key (archive_trades_for_monitor).
- Sweep: monitor missing from monitor_list, wrong mon_<user>_* prefix, or list status not
  active/inactive (archive_trades_not_in_active_or_inactive_monitor).

Backfill script uses the sweep for bulk cleanup.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from psycopg2 import sql

def tenant_trades_schema(user_number: str) -> str:
    """PostgreSQL schema for tenant user_number (e.g. users_0001)."""
    return f"users_{user_number}"


def master_trades_table(user_number: str) -> str:
    """Master trades table name for user_number (e.g. trades_0001)."""
    return f"trades_{user_number}"


# Default single-tenant names (tests / legacy imports).
MASTER_TRADES_TABLE = "trades_0001"
MASTER_TRADES_SCHEMA = "users_0001"


def archive_table_live(user_number: str) -> str:
    return f"trades_archive_live_{user_number}"


def archive_table_paper(user_number: str) -> str:
    return f"trades_archive_paper_{user_number}"


def canonical_monitor_key(user_number: str, monitor_id: str) -> str:
    """Match trade_manager MONITOR_KEY_PATTERN storage: mon_<user>_<id> (lowercase mon_)."""
    return f"mon_{user_number}_{monitor_id}"


def fetch_master_trades_column_names(cursor, user_number: str) -> List[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (tenant_trades_schema(user_number), master_trades_table(user_number)),
    )
    return [r[0] for r in cursor.fetchall()]


def _information_schema_table_exists(cursor, schema: str, table: str) -> bool:
    """True if ``schema.table`` exists (for optional archive UNION branches)."""
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        )
        """,
        (schema, table),
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def _compose_insert_from_master(
    archive_schema: str,
    archive_table: str,
    columns: Sequence[str],
    user_number: str,
    *,
    paper_rows: bool,
) -> sql.Composed:
    """INSERT ... SELECT from users_<n>.trades_<n> for one paper/live split."""
    ins_cols = sql.SQL(", ").join([sql.Identifier(c) for c in columns] + [sql.Identifier("archived_at")])
    sel_cols = sql.SQL(", ").join([sql.Identifier("t", c) for c in columns])
    dest = sql.Identifier(archive_schema, archive_table)
    return sql.SQL(
        """
        INSERT INTO {dest} ({ins_cols})
        SELECT {sel_cols}, NOW()
        FROM {src} AS t
        WHERE LOWER(TRIM(t.monitor)) = LOWER(%s)
          AND COALESCE(t.paper_trade, FALSE) = %s
        """
    ).format(
        dest=dest,
        ins_cols=ins_cols,
        sel_cols=sel_cols,
        src=sql.Identifier(
            tenant_trades_schema(user_number), master_trades_table(user_number)
        ),
    )


def _compose_delete_master(user_number: str) -> sql.Composed:
    return sql.SQL(
        """
        DELETE FROM {src} AS t
        WHERE LOWER(TRIM(t.monitor)) = LOWER(%s)
        """
    ).format(
        src=sql.Identifier(
            tenant_trades_schema(user_number), master_trades_table(user_number)
        )
    )


def _sql_where_archivable_not_active_inactive_monitor(mon_list_rel: str, user_number: str) -> str:
    """
    SQL predicate on alias `t` (users.trades_0001): rows to move to archive.
    Archives when: no monitor text, malformed mon_* key, user prefix != user_number,
    no row in monitor_list for that id, or list status is not active/inactive (incl. NULL).

    mon_list_rel must be a safe qualified name e.g. users_0001.monitor_list_0001; user_number
    exactly four digits (caller validates).
    """
    return f"""
(
  t.monitor IS NULL OR BTRIM(t.monitor) = ''
  OR regexp_match(LOWER(BTRIM(t.monitor)), '^mon_([0-9]+)_([0-9]+)$') IS NULL
  OR (regexp_match(LOWER(BTRIM(t.monitor)), '^mon_([0-9]+)_([0-9]+)$'))[1] IS DISTINCT FROM '{user_number}'
  OR NOT EXISTS (
    SELECT 1 FROM {mon_list_rel} ml
    WHERE ml.id::text = (regexp_match(LOWER(BTRIM(t.monitor)), '^mon_([0-9]+)_([0-9]+)$'))[2]
  )
  OR EXISTS (
    SELECT 1 FROM {mon_list_rel} ml
    WHERE ml.id::text = (regexp_match(LOWER(BTRIM(t.monitor)), '^mon_([0-9]+)_([0-9]+)$'))[2]
      AND (
        ml.status IS NULL
        OR UPPER(TRIM(ml.status)) NOT IN ('ACTIVE', 'INACTIVE')
      )
  )
)
"""


def _validate_user_number(user_number: str) -> None:
    if len(user_number) != 4 or not user_number.isdigit():
        raise ValueError(f"user_number must be four digits, got {user_number!r}")


def archive_trades_not_in_active_or_inactive_monitor(
    cursor,
    user_number: str,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Move every trades_0001 row whose monitor is not represented as active or inactive in
    users.monitor_list_<user_number>: missing/invalid monitor key, id absent from list,
    status not in (active, inactive), or mon_<otheruser>_* prefix.

    Same archive tables and paper/live split as archive_trades_for_monitor.
    """
    _validate_user_number(user_number)

    live_tbl = archive_table_live(user_number)
    paper_tbl = archive_table_paper(user_number)
    ts = tenant_trades_schema(user_number)
    mon_list_rel = f"{ts}.monitor_list_{user_number}"
    pred = _sql_where_archivable_not_active_inactive_monitor(mon_list_rel, user_number)

    columns = fetch_master_trades_column_names(cursor, user_number)
    if not columns:
        raise RuntimeError(
            f"{ts}.{master_trades_table(user_number)} has no columns (missing table?)"
        )

    col_list = ", ".join([f'"{c.replace(chr(34), "")}"' for c in columns])

    mt = master_trades_table(user_number)
    if dry_run:
        cursor.execute(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE COALESCE(t.paper_trade, FALSE)),
              COUNT(*) FILTER (WHERE NOT COALESCE(t.paper_trade, FALSE))
            FROM {ts}.{mt} AS t
            WHERE {pred}
            """
        )
        paper_n, live_n = cursor.fetchone()
        return {
            "paper_rows": int(paper_n or 0),
            "live_rows": int(live_n or 0),
            "dry_run": True,
        }

    ins_paper = f"""
INSERT INTO archive.{paper_tbl} ({col_list}, archived_at)
SELECT {col_list}, NOW()
FROM {ts}.{mt} AS t
WHERE {pred}
  AND COALESCE(t.paper_trade, FALSE) = TRUE
"""
    ins_live = f"""
INSERT INTO archive.{live_tbl} ({col_list}, archived_at)
SELECT {col_list}, NOW()
FROM {ts}.{mt} AS t
WHERE {pred}
  AND COALESCE(t.paper_trade, FALSE) = FALSE
"""
    cursor.execute(ins_paper)
    paper_moved = cursor.rowcount
    cursor.execute(ins_live)
    live_moved = cursor.rowcount

    del_sql = f"""
DELETE FROM {ts}.{mt} AS t
WHERE {pred}
"""
    cursor.execute(del_sql)
    deleted = cursor.rowcount

    _sync_sequence(cursor, "archive", live_tbl)
    _sync_sequence(cursor, "archive", paper_tbl)

    return {
        "paper_moved": paper_moved,
        "live_moved": live_moved,
        "deleted_from_master": deleted,
        "dry_run": False,
    }


def _sync_sequence(cursor, schema: str, table: str) -> None:
    """Advance archive table id sequence after bulk copy; use regclass param for sequence."""
    for part in (schema, table):
        if not part or not all(c.isalnum() or c == "_" for c in part):
            raise ValueError(f"invalid schema/table for _sync_sequence: {part!r}")
    seq_fq = f"{schema}.{table}_id_seq"
    tbl_q = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    cursor.execute(
        sql.SQL(
            "SELECT setval(%s::regclass, (SELECT COALESCE(MAX(id), 1) FROM {}), true)"
        ).format(tbl_q),
        (seq_fq,),
    )


def archive_trades_for_monitor(
    cursor,
    user_number: str,
    monitor_id: str,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Copy trades for mon_<user_number>_<monitor_id> from users_<n>.trades_<n> into archive
    (live vs paper), then delete from master. Uses the caller's transaction.

    Returns counts and monitor_key. On dry_run, only returns estimated rows (no writes).
    """
    _validate_user_number(user_number)

    mk = canonical_monitor_key(user_number, str(monitor_id).strip())
    live_tbl = archive_table_live(user_number)
    paper_tbl = archive_table_paper(user_number)
    ts = tenant_trades_schema(user_number)
    mt = master_trades_table(user_number)

    columns = fetch_master_trades_column_names(cursor, user_number)
    if not columns:
        raise RuntimeError(f"{ts}.{mt} has no columns (missing table?)")

    if dry_run:
        cursor.execute(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE COALESCE(paper_trade, FALSE)),
              COUNT(*) FILTER (WHERE NOT COALESCE(paper_trade, FALSE))
            FROM {ts}.{mt}
            WHERE LOWER(TRIM(monitor)) = LOWER(%s)
            """,
            (mk,),
        )
        paper_n, live_n = cursor.fetchone()
        return {
            "monitor_key": mk,
            "paper_rows": int(paper_n or 0),
            "live_rows": int(live_n or 0),
            "dry_run": True,
        }

    ins_paper = _compose_insert_from_master(
        "archive", paper_tbl, columns, user_number, paper_rows=True
    )
    cursor.execute(ins_paper, (mk, True))
    paper_moved = cursor.rowcount

    ins_live = _compose_insert_from_master(
        "archive", live_tbl, columns, user_number, paper_rows=False
    )
    cursor.execute(ins_live, (mk, False))
    live_moved = cursor.rowcount

    del_q = _compose_delete_master(user_number)
    cursor.execute(del_q, (mk,))
    deleted = cursor.rowcount

    _sync_sequence(cursor, "archive", live_tbl)
    _sync_sequence(cursor, "archive", paper_tbl)

    return {
        "monitor_key": mk,
        "paper_moved": paper_moved,
        "live_moved": live_moved,
        "deleted_from_master": deleted,
        "dry_run": False,
    }


def union_trades_with_archives_select(
    cursor,
    user_number: str = "0001",
) -> Tuple[str, Tuple]:
    """
    Build SQL text for (live master ∪ archive live ∪ archive paper) with trailing archived_at.
    Same column order as users_<n>.trades_<n> plus archived_at.

    Returns (sql_string, ()) — params empty; safe identifiers are embedded only from user_number.
    """
    _validate_user_number(user_number)
    ts = tenant_trades_schema(user_number)
    mt = master_trades_table(user_number)

    cols = fetch_master_trades_column_names(cursor, user_number)
    if not cols:
        raise RuntimeError(f"{ts}.{mt} column list empty")

    quoted = ", ".join(f'"{c.replace(chr(34), "")}"' for c in cols)
    live_arch = archive_table_live(user_number)
    paper_arch = archive_table_paper(user_number)

    parts = [
        f"SELECT {quoted}, NULL::timestamptz AS archived_at\nFROM {ts}.{mt}"
    ]
    if _information_schema_table_exists(cursor, "archive", live_arch):
        parts.append(
            f"SELECT {quoted}, archived_at\nFROM archive.{live_arch}"
        )
    if _information_schema_table_exists(cursor, "archive", paper_arch):
        parts.append(
            f"SELECT {quoted}, archived_at\nFROM archive.{paper_arch}"
        )
    q = "\nUNION ALL\n".join(parts)
    return q, ()


def union_trades_with_archives_select_columns(
    cursor,
    user_number: str,
    columns: Sequence[str],
) -> Tuple[str, Tuple]:
    """
    Same as ``union_trades_with_archives_select`` but each branch selects only ``columns``
    (must be a subset of master column names). Used by HTTP trade list to avoid ``SELECT *``.
    """
    _validate_user_number(user_number)
    ts = tenant_trades_schema(user_number)
    mt = master_trades_table(user_number)

    master_cols = fetch_master_trades_column_names(cursor, user_number)
    if not master_cols:
        raise RuntimeError(f"{ts}.{mt} column list empty")
    allowed = set(master_cols)
    ordered: List[str] = []
    for c in columns:
        if c in allowed and c not in ordered:
            ordered.append(c)
    if not ordered:
        raise RuntimeError("union_trades_with_archives_select_columns: no valid columns")

    quoted = ", ".join(f'"{c.replace(chr(34), "")}"' for c in ordered)
    live_arch = archive_table_live(user_number)
    paper_arch = archive_table_paper(user_number)

    parts = [
        f"SELECT {quoted}, NULL::timestamptz AS archived_at\nFROM {ts}.{mt}"
    ]
    if _information_schema_table_exists(cursor, "archive", live_arch):
        parts.append(f"SELECT {quoted}, archived_at\nFROM archive.{live_arch}")
    if _information_schema_table_exists(cursor, "archive", paper_arch):
        parts.append(f"SELECT {quoted}, archived_at\nFROM archive.{paper_arch}")
    q = "\nUNION ALL\n".join(parts)
    return q, ()


def union_trades_subquery_alias(cursor, user_number: str = "0001", alias: str = "u") -> Tuple[str, Tuple]:
    """Wrap union_trades_with_archives_select as subquery: ( {union} ) AS alias """
    inner, params = union_trades_with_archives_select(cursor, user_number=user_number)
    return f"( {inner} ) AS {alias}", params
