"""
Paper trading: YES/NO collateral netting per Kalshi market ticker (FIFO pairing).

Open-position ``positions`` / ``exposure`` in account_balance_paper use netted premium:
only unpaired YES/NO legs count toward collateral after pairing opposite legs on the same
``ticker``. This matches bracket-style offsetting on the same contract.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any, List, Optional, Sequence, Tuple

_LOG = logging.getLogger(__name__)


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "y")

# (trade_id, ticker, side, buy_price, position)
PaperCollateralRow = Tuple[Any, Any, Any, Any, Any]


def normalize_paper_trade_side(side: Any) -> Optional[str]:
    s = str(side or "").strip().upper()
    if s in ("Y", "YES"):
        return "yes"
    if s in ("N", "NO"):
        return "no"
    return None


def lot_premium_cents(qty: int, buy_price: float) -> int:
    return int(round(float(buy_price) * int(qty) * 100.0))


def netted_open_premium_cents_from_rows(rows: Sequence[PaperCollateralRow]) -> int:
    """
    Aggregate open-premium cents with FIFO pairing of YES vs NO lots per ticker.

    ``rows`` must be ordered by trade id ascending for deterministic pairing (oldest first).
    """
    by_ticker: dict[str, List[Tuple[int, str, int, float]]] = defaultdict(list)
    orphan_premium = 0

    for rid, ticker, side, bp, pos in rows:
        ns = normalize_paper_trade_side(side)
        try:
            q = int(pos)
            p = float(bp)
        except (TypeError, ValueError):
            continue
        if q <= 0 or p <= 0 or p >= 1:
            continue
        if ns is None:
            orphan_premium += lot_premium_cents(q, p)
            continue

        t = str(ticker or "").strip() or f"__missing_ticker:{rid}__"
        try:
            iid = int(rid)
        except (TypeError, ValueError):
            iid = 0
        by_ticker[t].append((iid, ns, q, p))

    total = orphan_premium

    for _t, lst in by_ticker.items():
        lst.sort(key=lambda x: x[0])
        yes = [[q, p] for _, ns, q, p in lst if ns == "yes"]
        no = [[q, p] for _, ns, q, p in lst if ns == "no"]
        i, j = 0, 0
        while i < len(yes) and j < len(no):
            if yes[i][0] <= 0:
                i += 1
                continue
            if no[j][0] <= 0:
                j += 1
                continue
            m = min(yes[i][0], no[j][0])
            yes[i][0] -= m
            no[j][0] -= m
        for bucket in (yes, no):
            for q, p in bucket:
                if q > 0:
                    total += lot_premium_cents(q, p)
    return max(0, int(total))


def _paper_equity_baseline_cents() -> Optional[int]:
    from backend.balance_snapshot import read_last_paper_portfolio_total_cents, read_paper_primary_total_cents

    return read_last_paper_portfolio_total_cents() or read_paper_primary_total_cents()


def fetch_open_paper_collateral_rows() -> List[PaperCollateralRow]:
    from backend.core.config.database import get_postgresql_connection
    from backend.core.tenant_context import resolved_tenant_user_no_for_app

    slot = resolved_tenant_user_no_for_app()
    conn = get_postgresql_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, ticker, side, buy_price, "position"
                FROM users.trades_{slot}
                WHERE paper_trade IS TRUE
                  AND status IN ('open', 'closing')
                  AND buy_price IS NOT NULL
                  AND "position" IS NOT NULL
                ORDER BY id ASC
                """
            )
            return list(cur.fetchall() or [])
    finally:
        conn.close()


def paper_open_passes_collateral_cap(
    *,
    ticker: Optional[str],
    side: Any,
    buy_price: float,
    position: int,
    open_fee_dollars: float,
) -> Tuple[bool, str]:
    """
    Returns (allowed, reason). If allowed is False, do not insert the paper trade.

    Uses the same identity as sync_paper_balance_feed_after_open:
    ``positions_new <= portfolio_equity - open_fee`` (all in cents), where ``positions``
    is netted FIFO collateral across open paper rows plus this hypothetical open.

    Set ``REC_SKIP_PAPER_COLLATERAL_CAP=1`` only for local recovery when open-premium vs
    portfolio snapshot is temporarily inconsistent (every paper open would otherwise 400).
    """
    if _truthy_env("REC_SKIP_PAPER_COLLATERAL_CAP"):
        _LOG.warning(
            "REC_SKIP_PAPER_COLLATERAL_CAP: bypassing paper collateral cap (dev/recovery only)"
        )
        return True, ""
    try:
        pos_i = int(position)
        bp = float(buy_price)
    except (TypeError, ValueError):
        return False, "invalid position or buy_price"

    if pos_i <= 0 or bp <= 0 or bp >= 1:
        return False, "position or buy_price out of range for paper open"

    if normalize_paper_trade_side(side) is None:
        return False, "side must be Y/N for paper collateral check"

    equity = _paper_equity_baseline_cents()
    if equity is None:
        return False, "no paper portfolio baseline (seed paper bankroll first)"

    fee_cents = int(round(float(open_fee_dollars or 0.0) * 100.0))
    cap = int(equity) - max(0, fee_cents)
    if cap < 0:
        return False, f"open fee exceeds paper equity (equity={equity}c fee={fee_cents}c)"

    rows = fetch_open_paper_collateral_rows()
    hyp_id = 0
    for r in rows or []:
        if not r:
            continue
        try:
            hyp_id = max(hyp_id, int(r[0]))
        except (TypeError, ValueError):
            continue
    hyp_id += 1
    rows_with_hyp = list(rows) + [(hyp_id, ticker, side, bp, pos_i)]
    pos_new = netted_open_premium_cents_from_rows(rows_with_hyp)

    if pos_new <= cap:
        return True, ""
    return (
        False,
        f"net_collateral_after_open={pos_new}c exceeds cap={cap}c "
        f"(portfolio_equity={equity}c open_fee={fee_cents}c)",
    )
