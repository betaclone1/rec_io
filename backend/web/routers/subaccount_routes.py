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
