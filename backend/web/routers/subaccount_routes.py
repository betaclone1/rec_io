"""Subaccount PATCH/POST mutations on main_app (PostgreSQL + db_change fanout)."""

import logging
import re
import uuid

from fastapi import APIRouter, Request
from psycopg2 import sql

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.core.time_eastern import now_est
from backend.trading_mode import (
    account_balance_table_for_user,
    is_paper_trading,
    paper_subaccounts_fqn,
    sql_ident_qualified_table,
    subaccount_balance_table_fqn,
    subaccounts_table_for_user,
    transfers_table_for_user,
)
from backend.web.main_realtime import broadcast_db_change

_log = logging.getLogger("main_app")

subaccount_router = APIRouter()

_CASH_NAMES = frozenset({"CASH", "PRIMARY"})
_MTB_NAME = "Master Trading Bankroll"
_RESERVED_LABELS = frozenset({"CASH", "PRIMARY", "Master Trading Bankroll"})
_LABEL_RE = re.compile(r"^[\w][\w \-./()]{0,62}$", re.UNICODE)


def _normalize_subaccount_label(raw: object) -> str | None:
    if raw is None:
        return None
    name = str(raw).strip()
    if not name:
        return None
    if not _LABEL_RE.match(name):
        return None
    return name


def _label_taken(cursor, sa_ident, name: str, *, exclude_id: int | None = None) -> bool:
    if exclude_id is None:
        cursor.execute(
            sql.SQL("SELECT 1 FROM {} WHERE subaccount = %s LIMIT 1").format(sa_ident),
            (name,),
        )
    else:
        cursor.execute(
            sql.SQL(
                "SELECT 1 FROM {} WHERE subaccount = %s AND id <> %s LIMIT 1"
            ).format(sa_ident),
            (name, int(exclude_id)),
        )
    return cursor.fetchone() is not None


def _upsert_subaccount_row(
    cursor,
    sa_ident,
    *,
    table_fqn: str,
    sa_id: int,
    label: str,
    in_mtb: bool = True,
) -> None:
    cursor.execute(
        sql.SQL(
            """
            INSERT INTO {} (
                id, subaccount, balance,
                exchange_0_balance, exchange_1_balance, exchange_2_balance, exchange_3_balance,
                automatic_transfers, in_mtb
            ) VALUES (%s, %s, 0, 0, 0, 0, 0, FALSE, %s)
            ON CONFLICT (id) DO UPDATE SET subaccount = EXCLUDED.subaccount
            """
        ).format(sa_ident),
        (int(sa_id), label, bool(in_mtb) and int(sa_id) != 0),
    )
    cursor.execute(
        sql.SQL(
            "SELECT setval("
            "pg_get_serial_sequence(%s, 'id'), "
            "GREATEST((SELECT MAX(id) FROM {}), 1), "
            "true)"
        ).format(sa_ident),
        (table_fqn,),
    )


def _latest_account_cash_cents(cursor, account_balance_table: str) -> int | None:
    ab_ident = sql_ident_qualified_table(account_balance_table)
    cursor.execute(
        sql.SQL("SELECT balance FROM {} ORDER BY id DESC LIMIT 1").format(ab_ident),
    )
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


def _paper_transfer_balance_cents(
    cursor,
    *,
    from_name: str,
    subaccounts_ident,
    account_balance_table: str,
) -> tuple[int | None, str | None]:
    """Paper-mode source balance. Live mode reads Kalshi instead."""
    if from_name in _CASH_NAMES:
        cash = _latest_account_cash_cents(cursor, account_balance_table)
        if cash is None:
            return None, "Unable to read CASH balance"
        return cash, None
    cursor.execute(
        sql.SQL("SELECT balance FROM {} WHERE subaccount = %s").format(subaccounts_ident),
        (from_name,),
    )
    row = cursor.fetchone()
    if not row:
        return None, f"subaccount not found: {from_name}"
    return int(row[0]) if row[0] is not None else 0, None


def _subaccount_row_exists(cursor, subaccounts_ident, name: str) -> bool:
    cursor.execute(
        sql.SQL("SELECT 1 FROM {} WHERE subaccount = %s").format(subaccounts_ident),
        (name,),
    )
    return cursor.fetchone() is not None


def _subaccount_kalshi_number_for_label(cursor, subaccounts_ident, name: str) -> int | None:
    """
    Resolve display label → Kalshi subaccount number.

    ``id`` is the Kalshi number; ``subaccount`` is display-only (may be renamed).
    """
    if name in _CASH_NAMES:
        return 0
    cursor.execute(
        sql.SQL("SELECT id FROM {} WHERE subaccount = %s").format(subaccounts_ident),
        (name,),
    )
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


def _insert_manual_transfer_row(
    cursor,
    *,
    xfer_ident,
    transfer_timestamp_est: str,
    from_name: str,
    to_name: str,
    amount_cents: int,
    status: str | None = "applied",
) -> None:
    insert_xfer = sql.SQL(
        """
        INSERT INTO {} (timestamp, type, "from", "to", amount, initiated, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
    ).format(xfer_ident)
    cursor.execute(
        insert_xfer,
        (
            transfer_timestamp_est,
            "internal",
            from_name,
            to_name,
            amount_cents,
            "manual",
            status,
        ),
    )


def _apply_paper_subaccount_balance_deltas(
    cursor,
    sa_ident,
    *,
    subaccounts_table: str,
    from_name: str,
    to_name: str,
    amount_cents: int,
) -> int:
    """
    Adjust paper subaccount balances for a manual internal transfer.
    Returns hero cash delta in cents (negative when CASH funds MTB).
    """
    cash_delta = 0
    if from_name not in _CASH_NAMES:
        cursor.execute(
            sql.SQL("UPDATE {} SET balance = balance - %s WHERE subaccount = %s").format(sa_ident),
            (amount_cents, from_name),
        )
    elif to_name == _MTB_NAME:
        for cash_name in ("CASH", "PRIMARY"):
            cursor.execute(
                sql.SQL(
                    "UPDATE {} SET balance = balance - %s WHERE subaccount = %s"
                ).format(sa_ident),
                (amount_cents, cash_name),
            )
        cash_delta = -int(amount_cents)

    if to_name not in _CASH_NAMES:
        cursor.execute(
            sql.SQL("UPDATE {} SET balance = balance + %s WHERE subaccount = %s").format(sa_ident),
            (amount_cents, to_name),
        )
    elif from_name == _MTB_NAME:
        for cash_name in ("CASH", "PRIMARY"):
            cursor.execute(
                sql.SQL(
                    "UPDATE {} SET balance = balance + %s WHERE subaccount = %s"
                ).format(sa_ident),
                (amount_cents, cash_name),
            )
        cash_delta = int(amount_cents)

    if to_name == _MTB_NAME or from_name == _MTB_NAME:
        from backend.balance_snapshot import refresh_mtb_realized_pnl_from_balance

        refresh_mtb_realized_pnl_from_balance(cursor, subaccounts_table)
    return cash_delta


@subaccount_router.patch("/api/subaccounts/automatic-transfers")
async def update_subaccount_automatic_transfers(request: Request):
    """Set automatic_transfers for a subaccount by name. Body: { \"subaccount\": \"Master Trading Bankroll\", \"automatic_transfers\": true }."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        automatic = payload.get("automatic_transfers")
        if subaccount_name is None or automatic is None:
            return {"ok": False, "error": "subaccount and automatic_transfers required"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(resolved_tenant_user_no_for_app())
            )
            cursor.execute(
                sql.SQL("UPDATE {} SET automatic_transfers = %s WHERE subaccount = %s").format(sa_ident),
                (bool(automatic), subaccount_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _log.warning("Error updating subaccount automatic_transfers: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.patch("/api/subaccounts/transfer-settings")
async def update_subaccount_transfer_settings(request: Request):
    """Set target_pnl__pct and/or transfer_amt for a subaccount. Body: { \"subaccount\": \"Master Trading Bankroll\", \"target_pnl__pct\": 0.115, \"transfer_amt\": 0.10 } (fractions)."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        target_pct = payload.get("target_pnl__pct")
        transfer_amt = payload.get("transfer_amt")
        if subaccount_name is None:
            return {"ok": False, "error": "subaccount required"}
        if target_pct is None and transfer_amt is None:
            return {"ok": False, "error": "at least one of target_pnl__pct or transfer_amt required"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(resolved_tenant_user_no_for_app())
            )
            if target_pct is not None and transfer_amt is not None:
                cursor.execute(
                    sql.SQL(
                        "UPDATE {} SET target_pnl__pct = %s, transfer_amt = %s WHERE subaccount = %s"
                    ).format(sa_ident),
                    (float(target_pct), float(transfer_amt), subaccount_name),
                )
            elif target_pct is not None:
                cursor.execute(
                    sql.SQL("UPDATE {} SET target_pnl__pct = %s WHERE subaccount = %s").format(sa_ident),
                    (float(target_pct), subaccount_name),
                )
            else:
                cursor.execute(
                    sql.SQL("UPDATE {} SET transfer_amt = %s WHERE subaccount = %s").format(sa_ident),
                    (float(transfer_amt), subaccount_name),
                )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _log.warning("Error updating subaccount transfer settings: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.patch("/api/subaccounts/drawdown-halt")
async def update_subaccount_drawdown_halt(request: Request):
    """Set drawdown_trading_halt for a subaccount by name. Body: { \"subaccount\": \"Master Trading Bankroll\", \"drawdown_trading_halt\": true }."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        halt_on = payload.get("drawdown_trading_halt")
        if subaccount_name is None or halt_on is None:
            return {"ok": False, "error": "subaccount and drawdown_trading_halt required"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(resolved_tenant_user_no_for_app())
            )
            cursor.execute(
                sql.SQL(
                    "UPDATE {} SET drawdown_trading_halt = %s WHERE subaccount = %s"
                ).format(sa_ident),
                (bool(halt_on), subaccount_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _log.warning("Error updating subaccount drawdown_trading_halt: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.patch("/api/subaccounts/drawdown-settings")
async def update_subaccount_drawdown_settings(request: Request):
    """Set drawdown_reset_threshold_pct for a subaccount. Body: { \"subaccount\": \"…\", \"drawdown_reset_threshold_pct\": 50 } (percent, exclusive 0–100)."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        pct = payload.get("drawdown_reset_threshold_pct")
        if subaccount_name is None:
            return {"ok": False, "error": "subaccount required"}
        if pct is None:
            return {"ok": False, "error": "drawdown_reset_threshold_pct required"}
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            return {"ok": False, "error": "drawdown_reset_threshold_pct must be a number"}
        if not (0 < pct_f < 100):
            return {"ok": False, "error": "drawdown_reset_threshold_pct must be between 0 and 100 exclusive"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(resolved_tenant_user_no_for_app())
            )
            cursor.execute(
                sql.SQL(
                    "UPDATE {} SET drawdown_reset_threshold_pct = %s WHERE subaccount = %s"
                ).format(sa_ident),
                (pct_f, subaccount_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _log.warning("Error updating subaccount drawdown settings: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.patch("/api/subaccounts/base-value")
async def update_subaccount_base_value(request: Request):
    """Set base_value (cents) for a subaccount. Body: { \"subaccount\": \"Master Trading Bankroll\", \"base_value\": 84329 } (base_value in cents)."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        base_value = payload.get("base_value")
        if subaccount_name is None:
            return {"ok": False, "error": "subaccount required"}
        if base_value is None:
            return {"ok": False, "error": "base_value required"}
        try:
            base_value_int = int(base_value)
        except (TypeError, ValueError):
            return {"ok": False, "error": "base_value must be an integer (cents)"}
        if base_value_int < 0:
            return {"ok": False, "error": "base_value must be non-negative"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(resolved_tenant_user_no_for_app())
            )
            cursor.execute(
                sql.SQL("UPDATE {} SET base_value = %s WHERE subaccount = %s").format(sa_ident),
                (base_value_int, subaccount_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _log.warning("Error updating subaccount base_value: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.patch("/api/subaccounts/mtb-membership")
async def update_subaccount_mtb_membership(request: Request):
    """
    Set whether a subaccount counts toward live MTB.

    Body: ``{ "subaccount_id": 4, "in_mtb": true }``.
    CASH (#0) cannot be in MTB.
    """
    try:
        payload = await request.json()
        try:
            sa_id = int(payload.get("subaccount_id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "subaccount_id required"}
        if sa_id == 0:
            return {"ok": False, "error": "CASH (subaccount 0) cannot be in MTB"}
        if "in_mtb" not in payload:
            return {"ok": False, "error": "in_mtb required"}
        in_mtb = bool(payload.get("in_mtb"))
        user_no = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                sa_ident = sql_ident_qualified_table(
                    subaccounts_table_for_user(user_no)
                )
                cursor.execute(
                    sql.SQL("UPDATE {} SET in_mtb = %s WHERE id = %s").format(sa_ident),
                    (in_mtb, sa_id),
                )
                if cursor.rowcount == 0:
                    return {"ok": False, "error": "subaccount not found"}
                conn.commit()
            try:
                broadcast_db_change("subaccounts")
            except Exception:
                pass
            return {"ok": True, "subaccount_id": sa_id, "in_mtb": in_mtb}
        finally:
            conn.close()
    except Exception as e:
        _log.warning("Error updating subaccount in_mtb: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.patch("/api/subaccounts/mtb-weight")
async def update_subaccount_mtb_weight(request: Request):
    """
    Set percent-of-MTB-Base weight for a trading subaccount.

    Body: ``{ "subaccount_id": 4, "mtb_weight_pct": 20 }`` or ``null`` to clear.
    """
    try:
        payload = await request.json()
        try:
            sa_id = int(payload.get("subaccount_id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "subaccount_id required"}
        if "mtb_weight_pct" not in payload:
            return {"ok": False, "error": "mtb_weight_pct required (number or null)"}
        raw = payload.get("mtb_weight_pct")
        weight: float | None
        if raw is None or raw == "":
            weight = None
        else:
            try:
                weight = float(raw)
            except (TypeError, ValueError):
                return {"ok": False, "error": "mtb_weight_pct must be a number or null"}
            if not (0 <= weight <= 100):
                return {"ok": False, "error": "mtb_weight_pct must be between 0 and 100"}
        user_no = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                sa_ident = sql_ident_qualified_table(
                    subaccounts_table_for_user(user_no)
                )
                cursor.execute(
                    sql.SQL(
                        "UPDATE {} SET mtb_weight_pct = %s WHERE id = %s"
                    ).format(sa_ident),
                    (weight, sa_id),
                )
                if cursor.rowcount == 0:
                    return {"ok": False, "error": "subaccount not found"}
                conn.commit()
            try:
                broadcast_db_change("subaccounts")
            except Exception:
                pass
            return {"ok": True, "subaccount_id": sa_id, "mtb_weight_pct": weight}
        finally:
            conn.close()
    except Exception as e:
        _log.warning("Error updating subaccount mtb_weight_pct: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.get("/api/portfolio/mtb-base")
async def get_portfolio_mtb_base():
    """Return portfolio MTB Base Value in cents from system_settings."""
    try:
        user_no = str(resolved_tenant_user_no_for_app()).zfill(4)
        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                ss_ident = sql_ident_qualified_table(
                    f"users_{user_no}.system_settings_{user_no}"
                )
                cursor.execute(
                    sql.SQL(
                        "SELECT mtb_base_value_cents FROM {} WHERE id = 1"
                    ).format(ss_ident)
                )
                row = cursor.fetchone()
            cents = int(row[0]) if row and row[0] is not None else None
            return {"ok": True, "mtb_base_value_cents": cents}
        finally:
            conn.close()
    except Exception as e:
        _log.warning("Error reading mtb_base_value_cents: %s", e)
        return {"ok": False, "error": str(e), "mtb_base_value_cents": None}


@subaccount_router.patch("/api/portfolio/mtb-base")
async def update_portfolio_mtb_base(request: Request):
    """
    Set portfolio MTB Base Value.

    Body: ``{ "mtb_base_value_cents": 1000000 }`` or ``null`` to clear.
    """
    try:
        payload = await request.json()
        if "mtb_base_value_cents" not in payload:
            return {"ok": False, "error": "mtb_base_value_cents required (integer or null)"}
        raw = payload.get("mtb_base_value_cents")
        cents: int | None
        if raw is None or raw == "":
            cents = None
        else:
            try:
                cents = int(raw)
            except (TypeError, ValueError):
                return {"ok": False, "error": "mtb_base_value_cents must be an integer or null"}
            if cents < 0:
                return {"ok": False, "error": "mtb_base_value_cents must be non-negative"}
        user_no = str(resolved_tenant_user_no_for_app()).zfill(4)
        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                ss_ident = sql_ident_qualified_table(
                    f"users_{user_no}.system_settings_{user_no}"
                )
                cursor.execute(
                    sql.SQL(
                        "UPDATE {} SET mtb_base_value_cents = %s, updated_at = NOW() WHERE id = 1"
                    ).format(ss_ident),
                    (cents,),
                )
                if cursor.rowcount == 0:
                    return {"ok": False, "error": "system_settings row missing"}
                conn.commit()
            try:
                broadcast_db_change("subaccounts")
            except Exception:
                pass
            return {"ok": True, "mtb_base_value_cents": cents}
        finally:
            conn.close()
    except Exception as e:
        _log.warning("Error updating mtb_base_value_cents: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.patch("/api/subaccounts/rename")
async def rename_subaccount(request: Request):
    """
    Rename internal display label on ``subaccounts_*`` (and paper twin when live).

    Body: ``{ "subaccount_id": 4, "name": "BTC Tail" }``.
    Kalshi number (``id``) is unchanged. CASH (#0) cannot be renamed.
    """
    try:
        payload = await request.json()
        try:
            sa_id = int(payload.get("subaccount_id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "subaccount_id required"}
        if sa_id == 0:
            return {"ok": False, "error": "CASH (subaccount 0) label cannot be renamed"}
        new_name = _normalize_subaccount_label(payload.get("name"))
        if not new_name:
            return {"ok": False, "error": "invalid name"}
        if new_name in _RESERVED_LABELS:
            return {"ok": False, "error": f"reserved name: {new_name}"}

        user_no = resolved_tenant_user_no_for_app()
        paper = is_paper_trading()
        live_fqn = subaccounts_table_for_user(user_no, force_live=True)
        paper_fqn = paper_subaccounts_fqn(user_no)
        active_fqn = paper_fqn if paper else live_fqn

        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                active_ident = sql_ident_qualified_table(active_fqn)
                cursor.execute(
                    sql.SQL("SELECT subaccount FROM {} WHERE id = %s").format(active_ident),
                    (sa_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return {"ok": False, "error": "subaccount not found"}
                old_name = str(row[0])
                if old_name == new_name:
                    return {"ok": True, "subaccount_id": sa_id, "name": new_name, "unchanged": True}
                if _label_taken(cursor, active_ident, new_name, exclude_id=sa_id):
                    return {"ok": False, "error": f"name already in use: {new_name}"}
                cursor.execute(
                    sql.SQL("UPDATE {} SET subaccount = %s WHERE id = %s").format(active_ident),
                    (new_name, sa_id),
                )
                if not paper:
                    paper_ident = sql_ident_qualified_table(paper_fqn)
                    cursor.execute(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                        """,
                        (paper_fqn.split(".", 1)[0], paper_fqn.split(".", 1)[1]),
                    )
                    if cursor.fetchone():
                        if not _label_taken(cursor, paper_ident, new_name, exclude_id=sa_id):
                            cursor.execute(
                                sql.SQL(
                                    "UPDATE {} SET subaccount = %s WHERE id = %s"
                                ).format(paper_ident),
                                (new_name, sa_id),
                            )
                conn.commit()
            try:
                broadcast_db_change("subaccounts")
            except Exception:
                pass
            return {
                "ok": True,
                "subaccount_id": sa_id,
                "name": new_name,
                "previous_name": old_name,
            }
        finally:
            conn.close()
    except Exception as e:
        _log.warning("Error renaming subaccount: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.post("/api/subaccounts/create")
async def create_subaccount(request: Request):
    """
    Create a new Kalshi subaccount on exchange indexes 0–3 and insert DB rows.

    Body: ``{ "name": "BTC Tail" }``.
    Live: ``POST /portfolio/subaccounts`` per shard, then live + paper twin rows.
    Paper: allocate next id locally on paper (and live twin for id parity) only.
    """
    try:
        payload = await request.json()
        name = _normalize_subaccount_label(payload.get("name"))
        if not name:
            return {"ok": False, "error": "invalid name"}
        if name in _RESERVED_LABELS:
            return {"ok": False, "error": f"reserved name: {name}"}

        user_no = resolved_tenant_user_no_for_app()
        paper = is_paper_trading()
        live_fqn = subaccounts_table_for_user(user_no, force_live=True)
        paper_fqn = paper_subaccounts_fqn(user_no)

        shards_created: list[int] = []
        shards_failed: dict = {}
        sa_id: int | None = None

        if paper:
            conn = get_postgresql_connection()
            try:
                with conn.cursor() as cursor:
                    paper_ident = sql_ident_qualified_table(paper_fqn)
                    live_ident = sql_ident_qualified_table(live_fqn)
                    if _label_taken(cursor, paper_ident, name) or _label_taken(
                        cursor, live_ident, name
                    ):
                        return {"ok": False, "error": f"name already in use: {name}"}
                    cursor.execute(
                        sql.SQL("SELECT COALESCE(MAX(id), 0) FROM {}").format(paper_ident)
                    )
                    max_paper = int(cursor.fetchone()[0] or 0)
                    cursor.execute(
                        sql.SQL("SELECT COALESCE(MAX(id), 0) FROM {}").format(live_ident)
                    )
                    max_live = int(cursor.fetchone()[0] or 0)
                    sa_id = max(max_paper, max_live) + 1
                    if sa_id < 1:
                        sa_id = 1
                    _upsert_subaccount_row(
                        cursor, paper_ident, table_fqn=paper_fqn, sa_id=sa_id, label=name
                    )
                    _upsert_subaccount_row(
                        cursor, live_ident, table_fqn=live_fqn, sa_id=sa_id, label=name
                    )
                    conn.commit()
            finally:
                conn.close()
        else:
            from backend.bookkeeper.kalshi_subaccount_transfer import (
                create_kalshi_subaccount_on_shards,
            )

            try:
                created = create_kalshi_subaccount_on_shards(str(user_no).zfill(4))
            except Exception as exc:
                _log.warning("Kalshi create subaccount failed: %s", exc)
                return {"ok": False, "error": str(exc)}
            sa_id = int(created["subaccount_number"])
            shards_created = list(created.get("shards_created") or [])
            shards_failed = dict(created.get("shards_failed") or {})

            conn = get_postgresql_connection()
            try:
                with conn.cursor() as cursor:
                    live_ident = sql_ident_qualified_table(live_fqn)
                    paper_ident = sql_ident_qualified_table(paper_fqn)
                    if _label_taken(cursor, live_ident, name, exclude_id=sa_id):
                        return {
                            "ok": False,
                            "error": (
                                f"Kalshi created subaccount {sa_id}, but name "
                                f"{name!r} is already used locally"
                            ),
                            "subaccount_id": sa_id,
                            "shards_created": shards_created,
                            "shards_failed": shards_failed,
                        }
                    _upsert_subaccount_row(
                        cursor, live_ident, table_fqn=live_fqn, sa_id=sa_id, label=name
                    )
                    cursor.execute(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                        """,
                        (paper_fqn.split(".", 1)[0], paper_fqn.split(".", 1)[1]),
                    )
                    if cursor.fetchone():
                        if not _label_taken(cursor, paper_ident, name, exclude_id=sa_id):
                            _upsert_subaccount_row(
                                cursor,
                                paper_ident,
                                table_fqn=paper_fqn,
                                sa_id=sa_id,
                                label=name,
                            )
                    from backend.balance_snapshot import ensure_subaccount_balance_table

                    ensure_subaccount_balance_table(
                        cursor, subaccount_balance_table_fqn(user_no, sa_id)
                    )
                    conn.commit()
            finally:
                conn.close()

        try:
            broadcast_db_change("subaccounts")
        except Exception:
            pass
        return {
            "ok": True,
            "subaccount_id": sa_id,
            "name": name,
            "paper": paper,
            "shards_created": shards_created,
            "shards_failed": shards_failed,
        }
    except Exception as e:
        _log.warning("Error creating subaccount: %s", e)
        return {"ok": False, "error": str(e)}


@subaccount_router.post("/api/subaccounts/initiate-transfer")
async def initiate_transfer(request: Request):
    """
    Manual internal transfer between subaccounts (including CASH / Kalshi #0).

    CASH→MTB (live): bump MTB base_value first, Kalshi transfer, full balance repoll
    (automatic rake suppressed for that poll). Other live transfers: Kalshi transfer then
    full repoll. Paper: local subaccount updates + hero snapshot (no automatic rake).
    """
    try:
        payload = await request.json()
        from_name = payload.get("from")
        to_name = payload.get("to")
        amount_dollars = payload.get("amount")
        try:
            from_exchange_index = int(payload.get("from_exchange_index", 0))
            to_exchange_index = int(payload.get("to_exchange_index", 0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "from_exchange_index and to_exchange_index must be integers"}
        if from_exchange_index < 0 or to_exchange_index < 0:
            return {"ok": False, "error": "exchange indexes must be >= 0"}
        if not from_name or not to_name:
            return {"ok": False, "error": "from and to required"}
        if from_name == "External" or to_name == "External":
            return {"ok": False, "error": "External transfers not supported yet"}
        try:
            amount_val = float(amount_dollars)
        except (TypeError, ValueError):
            return {"ok": False, "error": "amount must be a number"}
        if amount_val <= 0:
            return {"ok": False, "error": "amount must be positive"}
        amount_cents = int(round(amount_val * 100))

        transfer_timestamp_est = now_est().strftime("%Y-%m-%d %H:%M:%S")
        slot = resolved_tenant_user_no_for_app()
        paper = is_paper_trading()
        if from_name == to_name and (
            paper or from_exchange_index == to_exchange_index
        ):
            return {"ok": False, "error": "from and to addresses must differ"}
        sa_tbl = subaccounts_table_for_user(slot)
        sa_ident = sql_ident_qualified_table(sa_tbl)
        ab_fqn = account_balance_table_for_user(slot)

        from backend.balance_snapshot import (
            bump_mtb_base_value_for_cash_funding,
            is_cash_to_mtb_funding_transfer,
            refresh_paper_snapshot_after_manual_internal_transfer,
            revert_mtb_base_value_cash_funding_bump,
        )

        cash_to_mtb = is_cash_to_mtb_funding_transfer(from_name, to_name)

        conn = get_postgresql_connection()
        from_num = to_num = None
        from_balance = None
        try:
            with conn.cursor() as cursor:
                if paper:
                    from_balance, bal_err = _paper_transfer_balance_cents(
                        cursor,
                        from_name=from_name,
                        subaccounts_ident=sa_ident,
                        account_balance_table=ab_fqn,
                    )
                    if bal_err:
                        return {"ok": False, "error": bal_err}
                if not _subaccount_row_exists(cursor, sa_ident, to_name):
                    return {"ok": False, "error": f"subaccount not found: {to_name}"}
                if not paper:
                    from_num = _subaccount_kalshi_number_for_label(cursor, sa_ident, from_name)
                    to_num = _subaccount_kalshi_number_for_label(cursor, sa_ident, to_name)
                    if from_num is None:
                        return {"ok": False, "error": f"subaccount not found: {from_name}"}
                    if to_num is None:
                        return {"ok": False, "error": f"subaccount not found: {to_name}"}
        finally:
            conn.close()

        if not paper:
            # Kalshi is the only authority on what is transferable right now, and it
            # holds sub-cent amounts the polled copy cannot represent.
            from backend.bookkeeper.kalshi_portfolio_balance import (
                fetch_subaccount_transferable_cents,
            )

            from_balance = fetch_subaccount_transferable_cents(
                slot,
                from_num,
                exchange_index=from_exchange_index,
            )
            if from_balance is None:
                return {
                    "ok": False,
                    "error": (
                        f"Unable to read Kalshi balance for {from_name} "
                        f"(#{from_num}, exchange {from_exchange_index})"
                    ),
                }
        if from_balance <= 0:
            return {
                "ok": False,
                "error": (
                    f"no balance available in {from_name} "
                    f"(exchange {from_exchange_index})"
                ),
            }
        if amount_cents > from_balance:
            _log.info(
                "initiate-transfer (%s,%s) → (%s,%s): requested %sc exceeds available %sc; "
                "sending full balance",
                from_exchange_index,
                from_name,
                to_exchange_index,
                to_name,
                amount_cents,
                from_balance,
            )
            amount_cents = int(from_balance)

        if not paper:
            from backend.bookkeeper.kalshi_subaccount_transfer import (
                transfer_kalshi_address,
            )

            if cash_to_mtb:
                conn = get_postgresql_connection()
                try:
                    with conn.cursor() as cursor:
                        bump_mtb_base_value_for_cash_funding(cursor, sa_tbl, amount_cents)
                        conn.commit()
                finally:
                    conn.close()

            try:
                transfer_kalshi_address(
                    slot,
                    from_exchange=from_exchange_index,
                    from_subaccount=from_num,
                    to_exchange=to_exchange_index,
                    to_subaccount=to_num,
                    amount_cents=amount_cents,
                    client_transfer_id=str(uuid.uuid4()),
                    wait_for_iat_credit=True,
                )
            except Exception as exc:
                if cash_to_mtb:
                    conn = get_postgresql_connection()
                    try:
                        with conn.cursor() as cursor:
                            revert_mtb_base_value_cash_funding_bump(cursor, sa_tbl, amount_cents)
                            conn.commit()
                    except Exception as revert_exc:
                        _log.warning(
                            "initiate-transfer: revert MTB base_value after Kalshi failure failed: %s",
                            revert_exc,
                        )
                    finally:
                        conn.close()
                _log.warning("Kalshi address transfer failed: %s", exc)
                return {"ok": False, "error": f"Kalshi transfer failed: {exc}"}

            conn = get_postgresql_connection()
            try:
                with conn.cursor() as cursor:
                    xfer_ident = sql_ident_qualified_table(transfers_table_for_user(slot))
                    _insert_manual_transfer_row(
                        cursor,
                        xfer_ident=xfer_ident,
                        transfer_timestamp_est=transfer_timestamp_est,
                        from_name=from_name,
                        to_name=to_name,
                        amount_cents=amount_cents,
                    )
                    conn.commit()
            finally:
                conn.close()

            try:
                from backend.kalshi_account_sync_ws import sync_balance

                sync_balance(full=True, skip_automatic_mtb_rake=cash_to_mtb)
            except Exception as exc:
                _log.warning("initiate-transfer: sync_balance after Kalshi transfer failed: %s", exc)
        else:
            conn = get_postgresql_connection()
            try:
                with conn.cursor() as cursor:
                    if cash_to_mtb:
                        bump_mtb_base_value_for_cash_funding(cursor, sa_tbl, amount_cents)

                    xfer_ident = sql_ident_qualified_table(transfers_table_for_user(slot))
                    _insert_manual_transfer_row(
                        cursor,
                        xfer_ident=xfer_ident,
                        transfer_timestamp_est=transfer_timestamp_est,
                        from_name=from_name,
                        to_name=to_name,
                        amount_cents=amount_cents,
                    )
                    cash_delta = _apply_paper_subaccount_balance_deltas(
                        cursor,
                        sa_ident,
                        subaccounts_table=sa_tbl,
                        from_name=from_name,
                        to_name=to_name,
                        amount_cents=amount_cents,
                    )
                    refresh_paper_snapshot_after_manual_internal_transfer(
                        cursor,
                        user_no=slot,
                        cash_delta_cents=cash_delta,
                    )
                    conn.commit()
            finally:
                conn.close()

        await broadcast_db_change("subaccounts", {"source": "initiate_transfer"})
        if paper:
            await broadcast_db_change("transfers_paper", {"source": "initiate_transfer"})
            await broadcast_db_change("account_balance_paper", {"source": "initiate_transfer"})
        else:
            await broadcast_db_change("transfers", {"source": "initiate_transfer"})

        return {"ok": True}
    except Exception as e:
        _log.warning("Error initiating transfer: %s", e)
        return {"ok": False, "error": str(e)}
