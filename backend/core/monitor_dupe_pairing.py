"""Cross-monitor dupe pairing: cap open size by peer monitor exposure on same ticker+side."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple


def normalize_monitor_dupe_pairing(raw: Any, *, self_monitor_id: Optional[int] = None) -> List[int]:
    """Return sorted unique positive monitor ids; exclude self."""
    out: List[int] = []
    seen: set[int] = set()
    items: Iterable[Any]
    if raw is None:
        items = ()
    elif isinstance(raw, (list, tuple, set)):
        items = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s or s in ("{}", "[]"):
            items = ()
        else:
            items = [p.strip() for p in s.strip("{}[]").split(",") if p.strip()]
    else:
        items = (raw,)

    for item in items:
        try:
            mid = int(item)
        except (TypeError, ValueError):
            continue
        if mid <= 0 or mid in seen:
            continue
        if self_monitor_id is not None and mid == int(self_monitor_id):
            continue
        seen.add(mid)
        out.append(mid)
    out.sort()
    return out


def monitor_keys_for_dupe_pairs(user_slot: str, paired_ids: Sequence[int]) -> List[str]:
    slot = str(user_slot or "").strip()
    keys: List[str] = []
    for mid in paired_ids:
        keys.append(f"mon_{slot}_{int(mid)}")
    return keys


def _side_sql_bucket_param(side_bucket: str) -> Tuple[str, ...]:
    if side_bucket == "yes":
        return ("Y", "y", "yes", "YES")
    if side_bucket == "no":
        return ("N", "n", "no", "NO")
    return tuple()


def sum_paired_open_contracts(
    cursor,
    *,
    trades_table: str,
    monitor_keys: Sequence[str],
    ticker: str,
    side_bucket: str,
    paper_trade: bool,
) -> int:
    """Sum in-flight contract size on paired monitors for the same ticker+side."""
    if not monitor_keys or not ticker or not side_bucket:
        return 0
    side_vals = _side_sql_bucket_param(side_bucket)
    if not side_vals:
        return 0
    cursor.execute(
        f"""
        SELECT COALESCE(SUM(GREATEST(COALESCE(position, 0), 0)), 0)
        FROM {trades_table}
        WHERE monitor = ANY(%s)
          AND ticker = %s
          AND side = ANY(%s)
          AND status IN ('open', 'pending', 'partial')
          AND paper_trade IS {"TRUE" if paper_trade else "NOT TRUE"}
        """,
        (list(monitor_keys), str(ticker).strip(), list(side_vals)),
    )
    row = cursor.fetchone()
    if not row or row[0] is None:
        return 0
    try:
        return max(0, int(float(row[0])))
    except (TypeError, ValueError):
        return 0


def apply_monitor_dupe_pairing_position_cap(
    data: dict,
    *,
    cursor,
    monitor_list_table: str,
    trades_table: str,
    user_slot: str,
    monitor_id: int,
    normalize_side_fn,
    log_fn=None,
) -> Tuple[bool, Optional[str]]:
    """
    Mutate ``data['position']`` / ``count_fp`` when paired monitors hold same ticker+side.

    Returns (allowed, detail). ``allowed=False`` when no contracts remain after cap.
    """
    ticker = str(data.get("ticker") or "").strip()
    side_bucket = normalize_side_fn(data.get("side"))
    if not ticker or not side_bucket:
        return True, None

    try:
        requested = int(float(data.get("position")))
    except (TypeError, ValueError):
        return True, None
    if requested <= 0:
        return True, None

    cursor.execute(
        f"SELECT monitor_dupe_pairing FROM {monitor_list_table} WHERE id = %s",
        (int(monitor_id),),
    )
    row = cursor.fetchone()
    paired = normalize_monitor_dupe_pairing(
        row[0] if row else None,
        self_monitor_id=int(monitor_id),
    )
    if not paired:
        return True, None

    from backend.trading_mode import effective_paper_trade

    paper = effective_paper_trade(data.get("paper_trade", False))
    peer_keys = monitor_keys_for_dupe_pairs(user_slot, paired)
    paired_open = sum_paired_open_contracts(
        cursor,
        trades_table=trades_table,
        monitor_keys=peer_keys,
        ticker=ticker,
        side_bucket=side_bucket,
        paper_trade=paper,
    )
    remaining = requested - paired_open
    if remaining <= 0:
        detail = (
            f"monitor_dupe_pairing_blocked requested={requested} "
            f"paired_open={paired_open} peers={paired} ticker={ticker} side={side_bucket}"
        )
        if log_fn:
            log_fn(detail)
        return False, detail

    if remaining < requested:
        data["position"] = int(remaining)
        data["count_fp"] = f"{float(remaining):.2f}"
        detail = (
            f"monitor_dupe_pairing_capped requested={requested} "
            f"paired_open={paired_open} allowed={remaining} peers={paired} "
            f"ticker={ticker} side={side_bucket}"
        )
        if log_fn:
            log_fn(detail)
        return True, detail

    return True, None
