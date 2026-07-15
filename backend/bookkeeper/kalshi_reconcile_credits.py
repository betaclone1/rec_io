"""
Kalshi credit history helpers for bookkeeper daily reconcile journal entries.

Interest and incentive credits for the txn date are pulled from
``users_<slot>.credits_history_<slot>`` and split out of Trading Income onto
Interest Income / Kalshi Incentives Income.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from psycopg2 import sql

from backend.core.config.database import get_postgresql_connection
from backend.trading_mode import credits_history_table_for_user, sql_ident_qualified_table

# Kalshi credit_history ``type`` values we map to QBO income accounts.
CREDIT_TYPE_INTEREST = "interest"
CREDIT_TYPE_INCENTIVE = "incentive"


def sum_credits_cents_for_txn_date(user_no: str, txn_date: str | date) -> dict[str, int]:
    """
    Sum ``amount_cents`` by type for credits whose America/New_York calendar date
    equals ``txn_date``.

    Returns ``{"interest": int, "incentive": int}`` (missing types → 0).
    Does not invent rows; empty table / no matches → zeros.
    """
    if isinstance(txn_date, date) and not isinstance(txn_date, datetime):
        day = txn_date
    else:
        day = date.fromisoformat(str(txn_date)[:10])

    out = {CREDIT_TYPE_INTEREST: 0, CREDIT_TYPE_INCENTIVE: 0}
    conn = get_postgresql_connection(tenant_user_no=str(user_no).zfill(4))
    if not conn:
        raise RuntimeError(f"PostgreSQL unavailable for credits lookup (user {user_no})")
    try:
        t_ident = sql_ident_qualified_table(credits_history_table_for_user(user_no))
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT type, COALESCE(SUM(amount_cents), 0)::bigint
                    FROM {}
                    WHERE (created_at AT TIME ZONE 'America/New_York')::date = %s
                      AND type IN (%s, %s)
                      AND amount_cents IS NOT NULL
                      AND amount_cents > 0
                    GROUP BY type
                    """
                ).format(t_ident),
                (day, CREDIT_TYPE_INTEREST, CREDIT_TYPE_INCENTIVE),
            )
            for typ, cents in cur.fetchall():
                key = str(typ or "").strip().lower()
                if key in out:
                    out[key] = int(cents)
    finally:
        conn.close()
    return out


def build_kalshi_reconcile_je_lines(
    *,
    gap: float,
    interest_dollars: float,
    incentive_dollars: float,
    kalshi_account_id: str,
    trading_income_account_id: str,
    interest_income_account_id: str | None = None,
    incentives_income_account_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Build balanced JE lines for Kalshi vs QBO reconcile.

    ``gap`` = QBO Kalshi CurrentBalance − Kalshi total portfolio (dollars).
    Positive gap → QB high (credit Kalshi asset); negative → Kalshi high (debit asset).

    Interest / incentive amounts (dollars, ≥ 0) are always **credited** to their
    income accounts when > 0. Trading Income absorbs the residual so the entry balances:

        asset_delta = -gap
        trading     = asset_delta - interest - incentive

    If ``trading`` > 0 → Credit Trading Income; if ``trading`` < 0 → Debit Trading Income.
    """
    gap_r = round(float(gap), 2)
    interest = round(max(0.0, float(interest_dollars)), 2)
    incentive = round(max(0.0, float(incentive_dollars)), 2)

    if interest > 0 and not interest_income_account_id:
        raise ValueError("interest credits require interest_income_account_id")
    if incentive > 0 and not incentives_income_account_id:
        raise ValueError("incentive credits require incentives_income_account_id")

    asset_delta = round(-gap_r, 2)
    trading = round(asset_delta - interest - incentive, 2)

    lines: list[dict[str, Any]] = []

    if asset_delta > 0:
        lines.append(
            {
                "posting_type": "Debit",
                "account_id": str(kalshi_account_id),
                "amount": asset_delta,
                "label": "Kalshi Trading Account",
            }
        )
    elif asset_delta < 0:
        lines.append(
            {
                "posting_type": "Credit",
                "account_id": str(kalshi_account_id),
                "amount": round(-asset_delta, 2),
                "label": "Kalshi Trading Account",
            }
        )

    if interest > 0:
        lines.append(
            {
                "posting_type": "Credit",
                "account_id": str(interest_income_account_id),
                "amount": interest,
                "label": "Interest Income",
            }
        )
    if incentive > 0:
        lines.append(
            {
                "posting_type": "Credit",
                "account_id": str(incentives_income_account_id),
                "amount": incentive,
                "label": "Kalshi Incentives Income",
            }
        )

    if trading > 0:
        lines.append(
            {
                "posting_type": "Credit",
                "account_id": str(trading_income_account_id),
                "amount": trading,
                "label": "Trading Income",
            }
        )
    elif trading < 0:
        lines.append(
            {
                "posting_type": "Debit",
                "account_id": str(trading_income_account_id),
                "amount": round(-trading, 2),
                "label": "Trading Income",
            }
        )

    debit_sum = round(
        sum(L["amount"] for L in lines if L["posting_type"] == "Debit"), 2
    )
    credit_sum = round(
        sum(L["amount"] for L in lines if L["posting_type"] == "Credit"), 2
    )
    if not lines:
        return []
    if debit_sum != credit_sum:
        raise ValueError(
            f"Internal JE imbalance: debits={debit_sum:.2f} credits={credit_sum:.2f} "
            f"(gap={gap_r:.2f} interest={interest:.2f} incentive={incentive:.2f})"
        )
    return lines
