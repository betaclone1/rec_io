"""
Provision missing PostgreSQL tenant schemas ``users_NNNN`` by cloning structure from the
default template schema (``REC_DEFAULT_USER_SCHEMA``, usually ``users_0001``).

Used before supervisor regen so each active ``system.master_users`` row has a real schema
before per-user programs query ``users_<n>.monitor_list_<n>``, etc.

Does not clone ``monitor_cycle_performance_<user>_<monitor>`` tables; those are created
per monitor (see ``monitor_manager`` / ``trade_manager``).
"""

from __future__ import annotations

import logging
import re
import time
from typing import List, Optional, Sequence, Tuple

from psycopg2 import sql as psql

from backend.core.config.database import get_database_config, get_system_postgresql_connection
from backend.core.tenant_context import default_pg_schema_for_init

_LOG = logging.getLogger(__name__)

_SCHEMA_RE = re.compile(r"^users_(\d{4})$")
_USER_NO_RAW_RE = re.compile(r"^\d{1,4}$")
_LEGACY_USER_ID_RE = re.compile(r"(?:user_)?(\d{4})", re.IGNORECASE)
# Point-in-time snapshot tables (often moved to schema ``archive``); must not be cloned per-tenant.
_DATED_TENANT_ARCHIVE_TBL = re.compile(
    r"^(trades|transfers)_\d{4}_archive_\d{8}$",
    re.IGNORECASE,
)
_TENANT_PROVISION_LOCK_A = 672804213
_TENANT_PROVISION_LOCK_B = 1103
_TENANT_PROVISION_RETRIES = 3
_TENANT_PROVISION_RETRY_SLEEP_SEC = 0.2


def normalize_master_user_no_slot(user_no_raw, user_id_raw) -> Optional[str]:
    """Match supervisor generator: 4-digit slot from ``user_no`` or legacy ``user_id``."""
    s = str(user_no_raw or "").strip()
    if s and _USER_NO_RAW_RE.fullmatch(s):
        return s.zfill(4)
    uid = str(user_id_raw or "").strip()
    m = _LEGACY_USER_ID_RE.fullmatch(uid)
    return m.group(1) if m else None


def _template_user_no(template_schema: str) -> str:
    m = _SCHEMA_RE.match(template_schema)
    if not m:
        raise ValueError(f"invalid template schema {template_schema!r} (expected users_NNNN)")
    return m.group(1)


def _remap_tenant_identifier(name: str, src_no: str, tgt_no: str) -> str:
    if src_no == tgt_no:
        return name
    s, u = f"_{src_no}", f"_{tgt_no}"
    out = name.replace(f"{s}_", f"{u}_")
    if out.endswith(s):
        out = out[: -len(s)] + u
    return out


def _should_clone_table(table_name: str, src_no: str) -> bool:
    s = f"_{src_no}"
    return table_name.endswith(s) or f"{s}_" in table_name


def _excluded_from_tenant_schema_clone(table_name: str) -> bool:
    """Runtime per-monitor tables; empty until populated for that user's monitors."""
    return table_name.startswith("monitor_cycle_performance_")


def _is_dated_tenant_snapshot_archive_table(table_name: str) -> bool:
    """True for e.g. ``trades_0001_archive_20260503`` (any case); lives in ``archive`` on prod."""
    return bool(_DATED_TENANT_ARCHIVE_TBL.match(table_name))


def _list_base_tables(cur, schema: str) -> List[str]:
    cur.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind = 'r'
        ORDER BY c.relname
        """,
        (schema,),
    )
    return [r[0] for r in cur.fetchall()]


def _schema_exists(cur, schema: str) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)",
        (schema,),
    )
    return bool(cur.fetchone()[0])


def _reattach_serial_defaults(
    cur,
    template_schema: str,
    template_table: str,
    target_schema: str,
    target_table: str,
    app_role: str,
) -> None:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (template_schema, template_table),
    )
    for (col,) in cur.fetchall():
        cur.execute(
            "SELECT pg_get_serial_sequence(%s, %s)",
            (f"{template_schema}.{template_table}", col),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            continue
        seq_name = f"{target_table}_{col}_seq"
        cur.execute(
            psql.SQL("CREATE SEQUENCE IF NOT EXISTS {}.{}").format(
                psql.Identifier(target_schema), psql.Identifier(seq_name)
            )
        )
        qual = f"{target_schema}.{seq_name}"
        cur.execute(
            psql.SQL(
                "ALTER TABLE {}.{} ALTER COLUMN {} SET DEFAULT nextval(%s::regclass)"
            ).format(
                psql.Identifier(target_schema),
                psql.Identifier(target_table),
                psql.Identifier(col),
            ),
            (qual,),
        )
        cur.execute(
            psql.SQL("ALTER SEQUENCE {}.{} OWNED BY {}.{}.{}").format(
                psql.Identifier(target_schema),
                psql.Identifier(seq_name),
                psql.Identifier(target_schema),
                psql.Identifier(target_table),
                psql.Identifier(col),
            )
        )
        cur.execute(
            psql.SQL("GRANT ALL PRIVILEGES ON SEQUENCE {}.{} TO {}").format(
                psql.Identifier(target_schema),
                psql.Identifier(seq_name),
                psql.Identifier(app_role),
            )
        )


def _grant_schema_usage(cur, target_schema: str, app_role: str) -> None:
    cur.execute(
        psql.SQL("GRANT ALL ON SCHEMA {} TO {}").format(
            psql.Identifier(target_schema), psql.Identifier(app_role)
        )
    )
    cur.execute(
        psql.SQL("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} TO {}").format(
            psql.Identifier(target_schema), psql.Identifier(app_role)
        )
    )
    cur.execute(
        psql.SQL("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
            psql.Identifier(target_schema), psql.Identifier(app_role)
        )
    )


def _minimal_subaccount_seed(cur, target_schema: str, dst_tbl: str) -> None:
    """CASH + MTB + undefined_2 rows so balance_snapshot UPDATEs never no-op on new tenants."""
    cur.execute(
        psql.SQL(
            """
            INSERT INTO {t_s}.{t_tbl} (subaccount, balance, automatic_transfers)
            SELECT v.sa, 0, FALSE
            FROM (VALUES ('CASH'), ('Master Trading Bankroll'), ('undefined_2')) AS v(sa)
            WHERE NOT EXISTS (
                SELECT 1 FROM {t_s}.{t_tbl} x WHERE x.subaccount = v.sa
            )
            """
        ).format(
            t_s=psql.Identifier(target_schema),
            t_tbl=psql.Identifier(dst_tbl),
        )
    )


def _copy_subaccount_rows_from_template(
    cur,
    *,
    template_schema: str,
    src_tbl: str,
    target_schema: str,
    dst_tbl: str,
    is_paper: bool,
) -> None:
    """Copy subaccount definitions from template without INSERT...SELECT (RLS uses one GUC per schema)."""
    cur.execute(
        "SELECT set_config('rec.tenant_pg_schema', %s, false)",
        (template_schema,),
    )
    cur.execute(
        psql.SQL(
            """
            SELECT subaccount, base_value, target_pnl__pct, transfer_amt, automatic_transfers
            FROM {s_s}.{s_tbl}
            """
        ).format(
            s_s=psql.Identifier(template_schema),
            s_tbl=psql.Identifier(src_tbl),
        )
    )
    rows = cur.fetchall() or []
    cur.execute(
        "SELECT set_config('rec.tenant_pg_schema', %s, false)",
        (target_schema,),
    )
    for subaccount, base_value, target_pnl__pct, transfer_amt, automatic_transfers in rows:
        auto = False if is_paper else bool(automatic_transfers or False)
        cur.execute(
            psql.SQL(
                """
                INSERT INTO {t_s}.{t_tbl} (
                    subaccount, balance, base_value, realized_pnl, realized_pnl_pct,
                    target_pnl__pct, transfer_amt, automatic_transfers
                ) VALUES (%s, 0, %s, NULL, NULL, %s, %s, %s)
                """
            ).format(
                t_s=psql.Identifier(target_schema),
                t_tbl=psql.Identifier(dst_tbl),
            ),
            (
                subaccount,
                base_value,
                target_pnl__pct,
                transfer_amt,
                auto,
            ),
        )


def _seed_subaccounts_from_template(
    cur,
    *,
    template_schema: str,
    source_no: str,
    target_schema: str,
    target_no: str,
) -> None:
    """
    Clone creates empty ``subaccounts_*`` / ``subaccounts_paper_*`` tables. Copy row definitions
    (names + settings, zero balances) from the template so the account UI and subaccounts_update work.
    Idempotent: fills empty tables from the template; always ensures PRIMARY / MTB / Cash Transfer
    exist (partially-filled clones from older tooling left some tenants without MTB rows).
    """
    specs = (
        (f"subaccounts_{target_no}", f"subaccounts_{source_no}", False),
        (f"subaccounts_paper_{target_no}", f"subaccounts_paper_{source_no}", True),
    )
    for dst_tbl, src_tbl, is_paper in specs:
        cur.execute(
            "SELECT set_config('rec.tenant_pg_schema', %s, false)",
            (target_schema,),
        )
        cur.execute(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = %s AND table_name = %s
            )
            """,
            (target_schema, dst_tbl),
        )
        if not cur.fetchone()[0]:
            continue
        cur.execute(
            psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                psql.Identifier(target_schema), psql.Identifier(dst_tbl)
            )
        )
        row_count = (cur.fetchone() or (0,))[0]
        cur.execute(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = %s AND table_name = %s
            )
            """,
            (template_schema, src_tbl),
        )
        if not cur.fetchone()[0]:
            _minimal_subaccount_seed(cur, target_schema, dst_tbl)
            _LOG.info("Minimal subaccount seed for %s.%s (no template table)", target_schema, dst_tbl)
            continue
        cur.execute(
            "SELECT set_config('rec.tenant_pg_schema', %s, false)",
            (template_schema,),
        )
        cur.execute(
            psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                psql.Identifier(template_schema), psql.Identifier(src_tbl)
            )
        )
        tpl_count = (cur.fetchone() or (0,))[0]
        if row_count == 0:
            if tpl_count == 0:
                _minimal_subaccount_seed(cur, target_schema, dst_tbl)
                _LOG.info("Minimal subaccount seed for %s.%s (template empty)", target_schema, dst_tbl)
            elif is_paper:
                _copy_subaccount_rows_from_template(
                    cur,
                    template_schema=template_schema,
                    src_tbl=src_tbl,
                    target_schema=target_schema,
                    dst_tbl=dst_tbl,
                    is_paper=True,
                )
                _LOG.info(
                    "Seeded %s.%s from %s.%s",
                    target_schema,
                    dst_tbl,
                    template_schema,
                    src_tbl,
                )
            else:
                _copy_subaccount_rows_from_template(
                    cur,
                    template_schema=template_schema,
                    src_tbl=src_tbl,
                    target_schema=target_schema,
                    dst_tbl=dst_tbl,
                    is_paper=False,
                )
                _LOG.info(
                    "Seeded %s.%s from %s.%s",
                    target_schema,
                    dst_tbl,
                    template_schema,
                    src_tbl,
                )
        cur.execute(
            "SELECT set_config('rec.tenant_pg_schema', %s, false)",
            (target_schema,),
        )
        _minimal_subaccount_seed(cur, target_schema, dst_tbl)


def _align_paper_cash_with_account_balance(
    cur, target_schema: str, target_no: str
) -> None:
    """If paper history exists but CASH was just seeded at 0, match CASH to latest portfolio."""
    cur.execute(
        "SELECT set_config('rec.tenant_pg_schema', %s, false)",
        (target_schema,),
    )
    ab_tbl = f"account_balance_paper_{target_no}"
    sa_tbl = f"subaccounts_paper_{target_no}"
    cur.execute(
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.tables
          WHERE table_schema = %s AND table_name = %s
        )
        """,
        (target_schema, ab_tbl),
    )
    if not cur.fetchone()[0]:
        return
    cur.execute(
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.tables
          WHERE table_schema = %s AND table_name = %s
        )
        """,
        (target_schema, sa_tbl),
    )
    if not cur.fetchone()[0]:
        return
    cur.execute(
        psql.SQL(
            "SELECT portfolio FROM {}.{} ORDER BY id DESC LIMIT 1"
        ).format(
            psql.Identifier(target_schema),
            psql.Identifier(ab_tbl),
        )
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return
    pv = int(row[0])
    cur.execute(
        psql.SQL(
            "UPDATE {}.{} SET balance = %s WHERE subaccount = 'CASH'"
        ).format(
            psql.Identifier(target_schema),
            psql.Identifier(sa_tbl),
        ),
        (pv,),
    )


def _ensure_tenant_rls(cur, target_schema: str) -> None:
    cur.execute(
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
    if cur.fetchone()[0]:
        cur.execute("SELECT rec.ensure_tenant_rls_for_schema(%s)", (target_schema,))


def provision_tenant_schema_clone(
    cur,
    target_user_no: str,
    *,
    template_schema: Optional[str] = None,
    app_role: Optional[str] = None,
) -> bool:
    """
    Create ``users_<target_user_no>`` and clone matching base tables from ``template_schema``.
    Skips ``monitor_cycle_performance_*`` (created when monitors are added).
    Idempotent: skips tables that already exist in the target schema.

    Returns True if any new object was created (schema, table, or sequence).
    """
    if not target_user_no or not re.fullmatch(r"^\d{4}$", target_user_no):
        raise ValueError(f"invalid target_user_no: {target_user_no!r}")

    tpl = (template_schema or default_pg_schema_for_init()).strip()
    src_no = _template_user_no(tpl)
    tgt_schema = f"users_{target_user_no}"
    role = app_role or get_database_config().get("user") or "rec_io_user"

    if tpl == tgt_schema:
        return False

    if not _schema_exists(cur, tpl):
        raise RuntimeError(f"template schema {tpl!r} does not exist; cannot provision {tgt_schema}")

    created = False
    if not _schema_exists(cur, tgt_schema):
        cur.execute(psql.SQL("CREATE SCHEMA {}").format(psql.Identifier(tgt_schema)))
        created = True

    _grant_schema_usage(cur, tgt_schema, role)

    tables = [
        t
        for t in _list_base_tables(cur, tpl)
        if _should_clone_table(t, src_no)
        and not _excluded_from_tenant_schema_clone(t)
        and not _is_dated_tenant_snapshot_archive_table(t)
    ]
    for old_name in tables:
        new_name = _remap_tenant_identifier(old_name, src_no, target_user_no)
        cur.execute(
            """
            SELECT EXISTS (
              SELECT 1 FROM pg_tables WHERE schemaname = %s AND tablename = %s
            )
            """,
            (tgt_schema, new_name),
        )
        if cur.fetchone()[0]:
            continue
        cur.execute(
            psql.SQL(
                "CREATE TABLE {}.{} (LIKE {}.{} "
                "INCLUDING CONSTRAINTS INCLUDING INDEXES INCLUDING STORAGE INCLUDING COMMENTS "
                "EXCLUDING DEFAULTS EXCLUDING GENERATED EXCLUDING IDENTITY)"
            ).format(
                psql.Identifier(tgt_schema),
                psql.Identifier(new_name),
                psql.Identifier(tpl),
                psql.Identifier(old_name),
            )
        )
        _reattach_serial_defaults(cur, tpl, old_name, tgt_schema, new_name, role)
        created = True

    _grant_schema_usage(cur, tgt_schema, role)
    try:
        _ensure_tenant_rls(cur, tgt_schema)
    except Exception as exc:
        _LOG.warning(
            "rec.ensure_tenant_rls_for_schema skipped for %s (run migrations if needed): %s",
            tgt_schema,
            exc,
        )
    _seed_subaccounts_from_template(
        cur,
        template_schema=tpl,
        source_no=src_no,
        target_schema=tgt_schema,
        target_no=target_user_no,
    )
    _align_paper_cash_with_account_balance(cur, tgt_schema, target_user_no)
    return created


def fetch_active_master_user_nos(cur) -> List[str]:
    cur.execute(
        """
        SELECT TRIM(user_no::text), TRIM(user_id::text)
        FROM system.master_users
        WHERE COALESCE(NULLIF(TRIM(LOWER(status)), ''), 'active') = 'active'
        ORDER BY LPAD(TRIM(user_no::text), 4, '0'), TRIM(user_id::text)
        """
    )
    rows: Sequence[Tuple[str, str]] = cur.fetchall() or []
    out: List[str] = []
    for user_no_raw, user_id_raw in rows:
        n = normalize_master_user_no_slot(user_no_raw, user_id_raw)
        if n:
            out.append(n)
    return sorted(set(out))


def ensure_tenant_schemas_for_active_users(
    user_nos: Sequence[str],
    *,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """
    For each 4-digit user number, ensure ``users_<n>`` exists and matches the template layout.

    Returns False if provisioning hit a fatal error (caller may abort supervisor regen).
    On missing DB connection, logs a warning and returns True (non-fatal).
    """
    log = logger or _LOG
    conn = get_system_postgresql_connection()
    if not conn:
        log.warning("Skipping tenant schema ensure: no system PostgreSQL connection")
        return True

    tpl = default_pg_schema_for_init().strip()
    app_role = get_database_config().get("user") or "rec_io_user"

    try:
        # get_system_postgresql_connection runs SET search_path (implicit transaction).
        # Use autocommit for DDL so psycopg2 does not reject set_session mid-transaction.
        conn.commit()
        conn.autocommit = True

        with conn.cursor() as cur:
            # Serialize tenant schema provisioning across concurrent supervisor generations
            # (e.g. multiple monitor_manager syncs) to avoid catalog-write races.
            cur.execute(
                "SELECT pg_advisory_lock(%s, %s)",
                (_TENANT_PROVISION_LOCK_A, _TENANT_PROVISION_LOCK_B),
            )
            if not _schema_exists(cur, tpl):
                log.error(
                    "Tenant provision skipped: template schema %s is missing",
                    tpl,
                )
                return False

        for user_no in sorted(set(user_nos)):
            if not re.fullmatch(r"^\d{4}$", str(user_no).strip()):
                log.warning("Skipping invalid user_no %r for tenant provision", user_no)
                continue
            n = str(user_no).strip()
            tgt = f"users_{n}"
            for attempt in range(1, _TENANT_PROVISION_RETRIES + 1):
                try:
                    with conn.cursor() as cur:
                        if provision_tenant_schema_clone(
                            cur, n, template_schema=tpl, app_role=app_role
                        ):
                            log.info("Provisioned tenant schema from %s → %s", tpl, tgt)
                    break
                except Exception as exc:
                    msg = str(exc).lower()
                    if (
                        "tuple concurrently updated" in msg
                        and attempt < _TENANT_PROVISION_RETRIES
                    ):
                        log.warning(
                            "Retrying tenant schema %s after catalog concurrency race "
                            "(attempt %s/%s): %s",
                            tgt,
                            attempt,
                            _TENANT_PROVISION_RETRIES,
                            exc,
                        )
                        time.sleep(_TENANT_PROVISION_RETRY_SLEEP_SEC)
                        continue
                    log.error("Failed to provision tenant schema %s: %s", tgt, exc)
                    return False
        return True
    except Exception as exc:
        log.error("Tenant schema ensure failed: %s", exc)
        return False
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (_TENANT_PROVISION_LOCK_A, _TENANT_PROVISION_LOCK_B),
                )
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
