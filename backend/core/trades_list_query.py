"""
PostgreSQL trade list (master + archive union) for HTTP handlers.

Used by read_api GET /trades. main_app forwards same-origin GET /trades to read_api.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import HTTPException

from backend.util.trade_log_archivist import (
    fetch_master_trades_column_names,
    union_trades_with_archives_select_columns,
)

_ISO_DATE_PARAM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TRADES_PAGE_SIZE_MAX = 500

# Columns returned by GET /trades (trade history table + client filters). Omit heavy / unused fields.
TRADES_LIST_HTTP_COLUMNS: Tuple[str, ...] = (
    "id",
    "status",
    "date",
    "time",
    "symbol",
    "trade_strategy",
    "contract",
    "strike",
    "side",
    "prob",
    "diff",
    "buy_price",
    "sell_price",
    "position",
    "fees",
    "pnl",
    "ret_pct",
    "closed_at",
    "symbol_open",
    "symbol_close",
    "momentum_percentile",
    "win_loss",
    "close_method",
    "win_loss_confirmed",
    "paper_trade",
    "test_filter",
    "monitor",
    "ticker",
)


def normalize_trades_date_query_param(
    label: str, value: Optional[str]
) -> Optional[str]:
    if value is None or value == "":
        return None
    s = value.strip()
    if not _ISO_DATE_PARAM_RE.match(s):
        raise HTTPException(
            status_code=400, detail=f"Invalid {label}; expected YYYY-MM-DD"
        )
    return s


def trades_dicts_from_rows(
    rows: List[tuple], columns: List[str]
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    norm_cols = [c.lower() if isinstance(c, str) else c for c in columns]
    for row in rows:
        trade_dict = dict(zip(norm_cols, row))
        if "date" in trade_dict and "time" in trade_dict:
            trade_dict["timestamp"] = f"{trade_dict['date']} {trade_dict['time']}"
        if "buy_price" in trade_dict:
            trade_dict["price"] = trade_dict["buy_price"]
        result.append(trade_dict)
    return result


def execute_trades_list_query(
    cursor: Any,
    *,
    slot: str,
    status: Optional[str] = None,
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
    page_size: Optional[int] = None,
    before_id: Optional[int] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Run tenant trade list query. Caller owns connection/cursor lifecycle.

    Returns a list (full result) or a dict with keys trades, has_more, next_before_id.
    """
    min_d = normalize_trades_date_query_param("min_date", min_date)
    max_d = normalize_trades_date_query_param("max_date", max_date)
    if min_d and max_d and min_d > max_d:
        raise HTTPException(status_code=400, detail="min_date must be <= max_date")
    if before_id is not None and page_size is None:
        raise HTTPException(
            status_code=400, detail="before_id requires page_size"
        )

    paginate = page_size is not None
    fetch_limit = (page_size + 1) if paginate else None

    if not fetch_master_trades_column_names(cursor, slot):
        return (
            []
            if not paginate
            else {"trades": [], "has_more": False, "next_before_id": None}
        )

    union_sql, _ = union_trades_with_archives_select_columns(
        cursor, slot, TRADES_LIST_HTTP_COLUMNS
    )
    where_parts: List[str] = []
    params: List[Any] = []
    if status:
        where_parts.append("status = %s")
        params.append(status)
    if min_d:
        where_parts.append("date >= %s")
        params.append(min_d)
    if max_d:
        where_parts.append("date <= %s")
        params.append(max_d)
    if before_id is not None:
        where_parts.append("id < %s")
        params.append(before_id)
    where_sql = ""
    if where_parts:
        where_sql = " WHERE " + " AND ".join(where_parts)
    limit_sql = ""
    exec_params: Tuple[Any, ...] = tuple(params)
    if fetch_limit is not None:
        limit_sql = " LIMIT %s"
        exec_params = tuple(params) + (fetch_limit,)
    cursor.execute(
        f"""
        SELECT * FROM ({union_sql}) AS all_trades
        {where_sql}
        ORDER BY id DESC
        {limit_sql}
        """,
        exec_params,
    )

    trades = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]

    if paginate:
        ps = int(page_size) if page_size is not None else 0
        has_more = len(trades) > ps
        if has_more:
            trades = trades[:ps]
        payload = trades_dicts_from_rows(trades, columns)
        next_before: Optional[int] = None
        if has_more and payload:
            next_before = min(
                int(t["id"]) for t in payload if t.get("id") is not None
            )
        return {
            "trades": payload,
            "has_more": has_more,
            "next_before_id": next_before,
        }

    return trades_dicts_from_rows(trades, columns)
