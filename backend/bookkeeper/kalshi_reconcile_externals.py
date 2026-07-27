"""
Match Kalshi external deposits/withdrawals to existing QBO bank↔Kalshi moves.

Bank ACH lines are categorized in QBO as Transfers/Deposits to/from Kalshi Trading
Account (often a few days after Kalshi marks them applied). Until that QBO line
exists, the wallet gap must not be dumped into Trading Income.

``adjusted_gap = raw_gap + unmirrored_signed_dollars``

where ``unmirrored_signed_dollars`` is the sum of unmatched applied external
transfer amounts (deposits positive into Kalshi, withdrawals negative).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2 import sql

from backend.core.config.database import get_postgresql_connection
from backend.trading_mode import sql_ident_qualified_table, transfers_table_for_user

_ET = ZoneInfo("America/New_York")

# How far bank categorization may lag Kalshi ``applied``.
DEFAULT_MATCH_WINDOW_DAYS = 14
# Only recent externals can still sit in the live QBO↔Kalshi gap; older
# unmatched DB rows (duplicates / pre-reset history) must not adjust today's books.
DEFAULT_LOOKBACK_DAYS = 21


@dataclass(frozen=True)
class ExternalTransferRow:
    id: int
    txn_date: date
    amount_cents: int  # deposit > 0, withdrawal < 0
    status: str
    from_name: str
    to_name: str

    @property
    def amount_dollars(self) -> float:
        return round(self.amount_cents / 100.0, 2)


@dataclass(frozen=True)
class QboKalshiBankMove:
    entity: str  # Transfer | Deposit
    qbo_id: str
    txn_date: date
    amount_dollars: float  # always > 0
    direction: str  # "into_kalshi" | "out_of_kalshi"
    note: str
    other_account: str


@dataclass
class ExternalMatchResult:
    matched: list[tuple[ExternalTransferRow, QboKalshiBankMove]]
    unmatched: list[ExternalTransferRow]
    unmirrored_signed_dollars: float
    qbo_moves: list[QboKalshiBankMove]


def adjusted_reconcile_gap(raw_gap: float, unmirrored_signed_dollars: float) -> float:
    """
    Strip unmirrored Kalshi↔bank cash from the wallet gap before Trading Income.

    Unmirrored deposit (+D into Kalshi): raw gap falls by D → add D back.
    Unmirrored withdrawal (−W): raw gap rises by W → add (−W) i.e. subtract W.
    """
    return round(float(raw_gap) + float(unmirrored_signed_dollars), 2)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(_ET).date()
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def list_applied_external_transfers(
    user_no: str,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    as_of: date | None = None,
) -> list[ExternalTransferRow]:
    """Applied Kalshi external deposits/withdrawals in the lookback window (ET)."""
    end = as_of or datetime.now(_ET).date()
    start = end - timedelta(days=max(1, int(lookback_days)))
    conn = get_postgresql_connection(tenant_user_no=str(user_no).zfill(4))
    if not conn:
        raise RuntimeError(f"PostgreSQL unavailable for transfers lookup (user {user_no})")
    out: list[ExternalTransferRow] = []
    try:
        t_ident = sql_ident_qualified_table(
            transfers_table_for_user(user_no, force_live=True)
        )
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT id, timestamp, amount, status, "from", "to"
                    FROM {}
                    WHERE type = 'external'
                      AND LOWER(TRIM(COALESCE(status, ''))) = 'applied'
                      AND amount IS NOT NULL
                      AND amount <> 0
                      AND timestamp::date >= %s
                      AND timestamp::date <= %s
                    ORDER BY timestamp ASC, id ASC
                    """
                ).format(t_ident),
                (start, end),
            )
            for row in cur.fetchall():
                tid, ts, amount, status, fr, to = row
                d = _as_date(ts)
                if d is None:
                    continue
                out.append(
                    ExternalTransferRow(
                        id=int(tid),
                        txn_date=d,
                        amount_cents=int(amount),
                        status=str(status or ""),
                        from_name=str(fr or ""),
                        to_name=str(to or ""),
                    )
                )
    finally:
        conn.close()
    return out


def _ref_id(ref: Any) -> str | None:
    if not isinstance(ref, dict):
        return None
    v = ref.get("value")
    return str(v) if v is not None else None


def _ref_name(ref: Any) -> str:
    if not isinstance(ref, dict):
        return ""
    return str(ref.get("name") or "")


def list_qbo_kalshi_bank_moves(
    cfg: Any,
    access_token: str,
    kalshi_account_id: str,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    as_of: date | None = None,
) -> list[QboKalshiBankMove]:
    """
    QBO Transfers and Deposits that move cash into/out of Kalshi Trading Account.

    Does not create QBO rows — bank categorization already posts these.
    """
    from backend.bookkeeper.quickbooks import run_report_query

    end = as_of or datetime.now(_ET).date()
    start = end - timedelta(days=max(1, int(lookback_days)))
    kid = str(kalshi_account_id)
    moves: list[QboKalshiBankMove] = []

    tbody = run_report_query(
        cfg, access_token, "select * from Transfer maxresults 1000"
    )
    transfers = (tbody.get("QueryResponse") or {}).get("Transfer") or []
    if isinstance(transfers, dict):
        transfers = [transfers]
    for t in transfers:
        if not isinstance(t, dict):
            continue
        td = _as_date(t.get("TxnDate"))
        if td is None or td < start or td > end:
            continue
        fr = t.get("FromAccountRef") or {}
        to = t.get("ToAccountRef") or {}
        fr_id, to_id = _ref_id(fr), _ref_id(to)
        try:
            amt = abs(round(float(t.get("Amount") or 0), 2))
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        if fr_id == kid and to_id != kid:
            moves.append(
                QboKalshiBankMove(
                    entity="Transfer",
                    qbo_id=str(t.get("Id")),
                    txn_date=td,
                    amount_dollars=amt,
                    direction="out_of_kalshi",
                    note=str(t.get("PrivateNote") or ""),
                    other_account=_ref_name(to),
                )
            )
        elif to_id == kid and fr_id != kid:
            moves.append(
                QboKalshiBankMove(
                    entity="Transfer",
                    qbo_id=str(t.get("Id")),
                    txn_date=td,
                    amount_dollars=amt,
                    direction="into_kalshi",
                    note=str(t.get("PrivateNote") or ""),
                    other_account=_ref_name(fr),
                )
            )

    dbody = run_report_query(
        cfg, access_token, "select * from Deposit maxresults 1000"
    )
    deposits = (dbody.get("QueryResponse") or {}).get("Deposit") or []
    if isinstance(deposits, dict):
        deposits = [deposits]
    for dep in deposits:
        if not isinstance(dep, dict):
            continue
        td = _as_date(dep.get("TxnDate"))
        if td is None or td < start or td > end:
            continue
        deposit_to = _ref_id(dep.get("DepositToAccountRef"))
        note = str(dep.get("PrivateNote") or "")
        lines = dep.get("Line") or []
        if isinstance(lines, dict):
            lines = [lines]
        for ln in lines:
            if not isinstance(ln, dict):
                continue
            detail = ln.get("DepositLineDetail") or {}
            line_acct = _ref_id(detail.get("AccountRef"))
            try:
                amt = abs(round(float(ln.get("Amount") or 0), 2))
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            # Money deposited into bank from Kalshi asset line → out of Kalshi.
            if deposit_to != kid and line_acct == kid:
                moves.append(
                    QboKalshiBankMove(
                        entity="Deposit",
                        qbo_id=str(dep.get("Id")),
                        txn_date=td,
                        amount_dollars=amt,
                        direction="out_of_kalshi",
                        note=note,
                        other_account=_ref_name(dep.get("DepositToAccountRef")),
                    )
                )
            # Deposit into Kalshi (rare; Kalshi as DepositTo) from another account.
            elif deposit_to == kid and line_acct != kid:
                moves.append(
                    QboKalshiBankMove(
                        entity="Deposit",
                        qbo_id=str(dep.get("Id")),
                        txn_date=td,
                        amount_dollars=amt,
                        direction="into_kalshi",
                        note=note,
                        other_account=_ref_name(detail.get("AccountRef")),
                    )
                )

    moves.sort(key=lambda m: (m.txn_date, m.entity, m.qbo_id))
    return moves


def match_externals_to_qbo(
    externals: list[ExternalTransferRow],
    qbo_moves: list[QboKalshiBankMove],
    *,
    match_window_days: int = DEFAULT_MATCH_WINDOW_DAYS,
) -> ExternalMatchResult:
    """
    Greedy 1:1 match by absolute dollars and direction within ``match_window_days``.

    Deposit (amount > 0) ↔ QBO into_kalshi.
    Withdrawal (amount < 0) ↔ QBO out_of_kalshi.
    """
    window = max(0, int(match_window_days))
    unused = list(qbo_moves)
    matched: list[tuple[ExternalTransferRow, QboKalshiBankMove]] = []
    unmatched: list[ExternalTransferRow] = []

    for ext in externals:
        want_dir = "into_kalshi" if ext.amount_cents > 0 else "out_of_kalshi"
        want_amt = round(abs(ext.amount_cents) / 100.0, 2)
        best_i: int | None = None
        best_delta: int | None = None
        for i, mv in enumerate(unused):
            if mv.direction != want_dir:
                continue
            if abs(mv.amount_dollars - want_amt) > 0.009:
                continue
            delta = abs((mv.txn_date - ext.txn_date).days)
            if delta > window:
                continue
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_i = i
        if best_i is None:
            unmatched.append(ext)
            continue
        mv = unused.pop(best_i)
        matched.append((ext, mv))

    unmirrored = round(sum(e.amount_dollars for e in unmatched), 2)
    return ExternalMatchResult(
        matched=matched,
        unmatched=unmatched,
        unmirrored_signed_dollars=unmirrored,
        qbo_moves=qbo_moves,
    )


def compute_external_gap_adjustment(
    user_no: str,
    cfg: Any,
    access_token: str,
    kalshi_account_id: str,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    match_window_days: int = DEFAULT_MATCH_WINDOW_DAYS,
    as_of: date | None = None,
) -> ExternalMatchResult:
    """Load DB externals + QBO moves and return match / unmirrored totals."""
    externals = list_applied_external_transfers(
        user_no, lookback_days=lookback_days, as_of=as_of
    )
    moves = list_qbo_kalshi_bank_moves(
        cfg,
        access_token,
        kalshi_account_id,
        lookback_days=lookback_days,
        as_of=as_of,
    )
    return match_externals_to_qbo(
        externals, moves, match_window_days=match_window_days
    )
