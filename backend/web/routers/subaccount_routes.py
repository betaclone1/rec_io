"""Subaccount PATCH/POST mutations on main_app (PostgreSQL + db_change fanout)."""

import logging
import threading

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
    Manual internal transfer between subaccounts (e.g. Cash Transfer ↔ Master Trading Bankroll).
    Body: { "from": "...", "to": "...", "amount": 100 } (amount in dollars).
    Inserts into transfers (live or paper), updates subaccounts. If Master Trading Bankroll is the
    from or to side, appends an account_balance row with bankroll_current and master_trading_bankroll
    set to the new MTB balance and notifies monitor_manager to refresh monitor allocations (live and paper).
    In live mode, kalshi_account_sync sync_balance runs only when MTB is not involved (rare); CT↔MTB
    reshuffles local slices only and does not change Kalshi totals.
    """
    try:
        payload = await request.json()
        from_name = payload.get("from")
        to_name = payload.get("to")
        amount_dollars = payload.get("amount")
        if not from_name or not to_name:
            return {"ok": False, "error": "from and to required"}
        if from_name == "PRIMARY" or to_name == "PRIMARY":
            return {"ok": False, "error": "PRIMARY cannot be from or to"}
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

        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                sa_ident = sql_ident_qualified_table(
                    subaccounts_table_for_user(resolved_tenant_user_no_for_app())
                )
                cursor.execute(
                    sql.SQL("SELECT balance FROM {} WHERE subaccount = %s").format(sa_ident),
                    (from_name,),
                )
                row = cursor.fetchone()
                if not row:
                    return {"ok": False, "error": f"subaccount not found: {from_name}"}
                from_balance = int(row[0]) if row[0] is not None else 0
                if from_balance < amount_cents:
                    return {"ok": False, "error": f"insufficient balance in {from_name}"}
                cursor.execute(
                    sql.SQL("SELECT 1 FROM {} WHERE subaccount = %s").format(sa_ident),
                    (to_name,),
                )
                if not cursor.fetchone():
                    return {"ok": False, "error": f"subaccount not found: {to_name}"}

                xfer_ident = sql_ident_qualified_table(
                    transfers_table_for_user(resolved_tenant_user_no_for_app())
                )
                insert_xfer = sql.SQL(
                    """
                    INSERT INTO {} (timestamp, type, "from", "to", amount, initiated)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """
                ).format(xfer_ident)
                cursor.execute(
                    insert_xfer,
                    (transfer_timestamp_est, "internal", from_name, to_name, amount_cents, "manual"),
                )
                cursor.execute(
                    sql.SQL("UPDATE {} SET balance = balance - %s WHERE subaccount = %s").format(sa_ident),
                    (amount_cents, from_name),
                )
                cursor.execute(
                    sql.SQL("UPDATE {} SET balance = balance + %s WHERE subaccount = %s").format(sa_ident),
                    (amount_cents, to_name),
                )
                conn.commit()
        finally:
            conn.close()

        await broadcast_db_change("subaccounts", {"source": "initiate_transfer"})
        if is_paper_trading():
            await broadcast_db_change("transfers_paper", {"source": "initiate_transfer"})
        else:
            await broadcast_db_change("transfers", {"source": "initiate_transfer"})

        mtb_affected = from_name == "Master Trading Bankroll" or to_name == "Master Trading Bankroll"
        if mtb_affected:
            try:
                from backend.balance_snapshot import (
                    insert_account_balance_snapshot_after_mtb_subaccount_internal_transfer,
                )

                slot = resolved_tenant_user_no_for_app()
                ab_tbl = account_balance_table_for_user(slot)
                sa_tbl = subaccounts_table_for_user(slot)
                notify_name = "account_balance_paper" if is_paper_trading() else "account_balance"
                insert_account_balance_snapshot_after_mtb_subaccount_internal_transfer(
                    account_balance_table=ab_tbl,
                    subaccounts_table=sa_tbl,
                    notify_db_name=notify_name,
                )
            except Exception as e:
                _log.warning("initiate-transfer: MTB account_balance snapshot failed: %s", e)

        if not is_paper_trading() and not mtb_affected:

            def _run_sync():
                try:
                    from backend.kalshi_account_sync_ws import sync_balance

                    sync_balance()
                except Exception as e:
                    _log.warning("initiate-transfer: sync_balance failed: %s", e)

            threading.Thread(target=_run_sync, daemon=True).start()

        return {"ok": True}
    except Exception as e:
        _log.warning("Error initiating transfer: %s", e)
        return {"ok": False, "error": str(e)}
