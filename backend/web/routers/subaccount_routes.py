"""Subaccount PATCH/POST mutations on main_app (PostgreSQL + db_change fanout)."""

import logging
import uuid

from fastapi import APIRouter, Request
from psycopg2 import sql

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.core.time_eastern import now_est
from backend.trading_mode import (
    account_balance_table_for_user,
    is_paper_trading,
    sql_ident_qualified_table,
    subaccounts_table_for_user,
    transfers_table_for_user,
)
from backend.web.main_realtime import broadcast_db_change

_log = logging.getLogger("main_app")

subaccount_router = APIRouter()

_CASH_NAMES = frozenset({"CASH", "PRIMARY"})
_MTB_NAME = "Master Trading Bankroll"


def _latest_account_cash_cents(cursor, account_balance_table: str) -> int | None:
    ab_ident = sql_ident_qualified_table(account_balance_table)
    cursor.execute(
        sql.SQL("SELECT balance FROM {} ORDER BY id DESC LIMIT 1").format(ab_ident),
    )
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


def _cash_balance_cents_live(user_no: str) -> int | None:
    """Kalshi subaccount #0 (CASH wallet cash), not total portfolio."""
    from backend.bookkeeper.kalshi_portfolio_balance import (
        fetch_portfolio_balance_detail,
        fetch_subaccount_balances_cents_map,
    )

    balances = fetch_subaccount_balances_cents_map(user_no)
    if balances is not None and 0 in balances:
        return int(balances[0])
    detail = fetch_portfolio_balance_detail(user_no)
    if detail is not None:
        return int(detail["balance_cents"])
    return None


def _from_transfer_balance_cents(
    cursor,
    *,
    user_no: str,
    from_name: str,
    paper: bool,
    subaccounts_ident,
    account_balance_table: str,
) -> tuple[int | None, str | None]:
    if from_name in _CASH_NAMES:
        if paper:
            cash = _latest_account_cash_cents(cursor, account_balance_table)
            if cash is None:
                return None, "Unable to read CASH balance"
            return cash, None
        cash = _cash_balance_cents_live(user_no)
        if cash is None:
            return None, "Unable to read CASH (Kalshi #0) balance"
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


def _insert_manual_transfer_row(
    cursor,
    *,
    xfer_ident,
    transfer_timestamp_est: str,
    from_name: str,
    to_name: str,
    amount_cents: int,
) -> None:
    insert_xfer = sql.SQL(
        """
        INSERT INTO {} (timestamp, type, "from", "to", amount, initiated)
        VALUES (%s, %s, %s, %s, %s, %s)
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
        if not from_name or not to_name:
            return {"ok": False, "error": "from and to required"}
        if from_name == "External" or to_name == "External":
            return {"ok": False, "error": "External transfers not supported yet"}
        if from_name == to_name:
            return {"ok": False, "error": "from and to must differ"}
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
        try:
            with conn.cursor() as cursor:
                from_balance, bal_err = _from_transfer_balance_cents(
                    cursor,
                    user_no=slot,
                    from_name=from_name,
                    paper=paper,
                    subaccounts_ident=sa_ident,
                    account_balance_table=ab_fqn,
                )
                if bal_err:
                    return {"ok": False, "error": bal_err}
                if from_balance < amount_cents:
                    return {"ok": False, "error": f"insufficient balance in {from_name}"}
                if not _subaccount_row_exists(cursor, sa_ident, to_name):
                    return {"ok": False, "error": f"subaccount not found: {to_name}"}
        finally:
            conn.close()

        if not paper:
            from backend.bookkeeper.kalshi_subaccount_transfer import (
                apply_subaccount_transfer,
                subaccount_name_to_number,
            )

            try:
                from_num = subaccount_name_to_number(from_name)
                to_num = subaccount_name_to_number(to_name)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

            if cash_to_mtb:
                conn = get_postgresql_connection()
                try:
                    with conn.cursor() as cursor:
                        bump_mtb_base_value_for_cash_funding(cursor, sa_tbl, amount_cents)
                        conn.commit()
                finally:
                    conn.close()

            try:
                apply_subaccount_transfer(
                    slot,
                    from_num,
                    to_num,
                    amount_cents,
                    str(uuid.uuid4()),
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
                _log.warning("Kalshi subaccount transfer failed: %s", exc)
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
