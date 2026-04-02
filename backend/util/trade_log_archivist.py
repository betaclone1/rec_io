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

# Master trade log is singular today; archive tables are per user_number (e.g. 0001).
MASTER_TRADES_TABLE = "trades_0001"
MASTER_TRADES_SCHEMA = "users"


def archive_table_live(user_number: str) -> str:
    return f"trades_archive_live_{user_number}"


def archive_table_paper(user_number: str) -> str:
    return f"trades_archive_paper_{user_number}"


def canonical_monitor_key(user_number: str, monitor_id: str) -> str:
    """Match trade_manager MONITOR_KEY_PATTERN storage: mon_<user>_<id> (lowercase mon_)."""
    return f"mon_{user_number}_{monitor_id}"


def fetch_trades_0001_column_names(cursor) -> List[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (MASTER_TRADES_SCHEMA, MASTER_TRADES_TABLE),
    )
    return [r[0] for r in cursor.fetchall()]


def _compose_insert_from_master(
    archive_schema: str,
    archive_table: str,
    columns: Sequence[str],
    *,
    paper_rows: bool,
) -> sql.Composed:
    """INSERT ... SELECT from users.trades_0001 for one paper/live split."""
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
        src=sql.Identifier(MASTER_TRADES_SCHEMA, MASTER_TRADES_TABLE),
    )


def _compose_delete_master() -> sql.Composed:
    return sql.SQL(
        """
        DELETE FROM {src} AS t
        WHERE LOWER(TRIM(t.monitor)) = LOWER(%s)
        """
    ).format(src=sql.Identifier(MASTER_TRADES_SCHEMA, MASTER_TRADES_TABLE))


def _sql_where_archivable_not_active_inactive_monitor(mon_list_rel: str, user_number: str) -> str:
    """
    SQL predicate on alias `t` (users.trades_0001): rows to move to archive.
    Archives when: no monitor text, malformed mon_* key, user prefix != user_number,
    no row in monitor_list for that id, or list status is not active/inactive (incl. NULL).

    mon_list_rel must be a safe qualified name e.g. users.monitor_list_0001; user_number
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
    if user_number != "0001":
        raise NotImplementedError(
            f"trade_log_archivist: only users.trades_0001 is wired; got user_number={user_number!r}"
        )

    live_tbl = archive_table_live(user_number)
    paper_tbl = archive_table_paper(user_number)
    mon_list_rel = f"{MASTER_TRADES_SCHEMA}.monitor_list_{user_number}"
    pred = _sql_where_archivable_not_active_inactive_monitor(mon_list_rel, user_number)

    columns = fetch_trades_0001_column_names(cursor)
    if not columns:
        raise RuntimeError("users.trades_0001 has no columns (missing table?)")

    col_list = ", ".join([f'"{c.replace(chr(34), "")}"' for c in columns])

    if dry_run:
        cursor.execute(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE COALESCE(t.paper_trade, FALSE)),
              COUNT(*) FILTER (WHERE NOT COALESCE(t.paper_trade, FALSE))
            FROM {MASTER_TRADES_SCHEMA}.{MASTER_TRADES_TABLE} AS t
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
FROM {MASTER_TRADES_SCHEMA}.{MASTER_TRADES_TABLE} AS t
WHERE {pred}
  AND COALESCE(t.paper_trade, FALSE) = TRUE
"""
    ins_live = f"""
INSERT INTO archive.{live_tbl} ({col_list}, archived_at)
SELECT {col_list}, NOW()
FROM {MASTER_TRADES_SCHEMA}.{MASTER_TRADES_TABLE} AS t
WHERE {pred}
  AND COALESCE(t.paper_trade, FALSE) = FALSE
"""
    cursor.execute(ins_paper)
    paper_moved = cursor.rowcount
    cursor.execute(ins_live)
    live_moved = cursor.rowcount

    del_sql = f"""
DELETE FROM {MASTER_TRADES_SCHEMA}.{MASTER_TRADES_TABLE} AS t
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
    Copy trades for mon_<user_number>_<monitor_id> from users.trades_0001 into archive
    (live vs paper), then delete from master. Uses the caller's transaction.

    Returns counts and monitor_key. On dry_run, only returns estimated rows (no writes).
    """
    if user_number != "0001":
        raise NotImplementedError(
            f"trade_log_archivist: only users.trades_0001 is wired; got user_number={user_number!r}"
        )

    mk = canonical_monitor_key(user_number, str(monitor_id).strip())
    live_tbl = archive_table_live(user_number)
    paper_tbl = archive_table_paper(user_number)

    columns = fetch_trades_0001_column_names(cursor)
    if not columns:
        raise RuntimeError("users.trades_0001 has no columns (missing table?)")

    if dry_run:
        cursor.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE COALESCE(paper_trade, FALSE)),
              COUNT(*) FILTER (WHERE NOT COALESCE(paper_trade, FALSE))
            FROM users.trades_0001
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

    ins_paper = _compose_insert_from_master("archive", paper_tbl, columns, paper_rows=True)
    cursor.execute(ins_paper, (mk, True))
    paper_moved = cursor.rowcount

    ins_live = _compose_insert_from_master("archive", live_tbl, columns, paper_rows=False)
    cursor.execute(ins_live, (mk, False))
    live_moved = cursor.rowcount

    del_q = _compose_delete_master()
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
    Same column order as users.trades_0001 plus archived_at.

    Returns (sql_string, ()) — params empty; safe identifiers are embedded only from user_number.
    """
    if user_number != "0001":
        raise NotImplementedError("union_trades_with_archives_select: only trades_0001 master wired")

    cols = fetch_trades_0001_column_names(cursor)
    if not cols:
        raise RuntimeError("users.trades_0001 column list empty")

    quoted = ", ".join(f'"{c.replace(chr(34), "")}"' for c in cols)
    live_arch = archive_table_live(user_number)
    paper_arch = archive_table_paper(user_number)

    q = f"""
SELECT {quoted}, NULL::timestamptz AS archived_at
FROM {MASTER_TRADES_SCHEMA}.{MASTER_TRADES_TABLE}
UNION ALL
SELECT {quoted}, archived_at
FROM archive.{live_arch}
UNION ALL
SELECT {quoted}, archived_at
FROM archive.{paper_arch}
""".strip()
    return q, ()


def union_trades_subquery_alias(cursor, user_number: str = "0001", alias: str = "u") -> Tuple[str, Tuple]:
    """Wrap union_trades_with_archives_select as subquery: ( {union} ) AS alias """
    inner, params = union_trades_with_archives_select(cursor, user_number=user_number)
    return f"( {inner} ) AS {alias}", params
