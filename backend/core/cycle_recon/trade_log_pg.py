"""Load strategy trades from tenant PostgreSQL (users_NNNN.trades_NNNN ∪ archives)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.config.database import get_postgresql_connection
from backend.core.cycle_recon.time_util import (
    combine_trade_log_close_utc,
    combine_trade_log_open_utc,
)
from backend.core.cycle_recon.trade_log import StrategyTradeRef, _norm_side
from backend.util.trade_log_archivist import union_trades_with_archives_select_columns

_TRADE_COLS = (
    "id",
    "date",
    "time",
    "closed_at",
    "created_at",
    "updated_at",
    "ticker",
    "symbol",
    "side",
    "monitor",
    "trade_strategy",
    "market",
    "contract",
    "strike",
    "buy_price",
    "sell_price",
    "position",
    "status",
    "pnl",
    "market_result",
    "paper_trade",
)


def _slot(user_no: str) -> str:
    s = str(user_no or "").strip()
    if s.startswith("users_"):
        s = s[6:]
    if not s.isdigit():
        raise ValueError(f"invalid user_no: {user_no!r}")
    return f"{int(s):04d}"


def _row_dict(colnames: Sequence[str], row: Sequence[Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for i, c in enumerate(colnames):
        v = row[i] if i < len(row) else None
        if isinstance(v, datetime):
            out[c] = v.isoformat()
        elif isinstance(v, date) and not isinstance(v, datetime):
            out[c] = v.isoformat()
        else:
            out[c] = v
    return out


def _fingerprint(rows: List[Dict[str, Any]], slot: str) -> str:
    payload = {
        "slot": slot,
        "ids": [str(r.get("id")) for r in rows],
        "tickers": sorted({str(r.get("ticker") or "") for r in rows}),
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def select_strategy_trades_pg(
    user_no: str,
    *,
    trade_ids: Optional[Sequence[str]] = None,
    monitors: Optional[Sequence[str]] = None,
    tickers: Optional[Sequence[str]] = None,
    symbols: Optional[Sequence[str]] = None,
    min_date_et: Optional[str] = None,
    max_date_et: Optional[str] = None,
    strategies: Optional[Sequence[str]] = None,
    limit: int = 5000,
) -> List[StrategyTradeRef]:
    """
    Query tenant trade log (live ∪ archive) and map rows to StrategyTradeRef.

    Date filters use Eastern calendar ``date`` text (YYYY-MM-DD), same as trade history.
    """
    slot = _slot(user_no)
    id_set = {str(x).strip() for x in (trade_ids or []) if str(x).strip()} or None
    mon_set = {str(x).strip() for x in (monitors or []) if str(x).strip()} or None
    tick_set = {str(x).strip() for x in (tickers or []) if str(x).strip()} or None
    sym_set = {str(x).strip().upper() for x in (symbols or []) if str(x).strip()} or None
    strat_set = {str(x).strip() for x in (strategies or []) if str(x).strip()} or None

    conn = get_postgresql_connection(tenant_user_no=slot)
    try:
        cur = conn.cursor()
        union_sql, _ = union_trades_with_archives_select_columns(cur, slot, _TRADE_COLS)
        where: List[str] = ["ticker IS NOT NULL", "BTRIM(ticker::text) <> ''"]
        params: List[Any] = []
        if id_set is not None:
            where.append("id::text = ANY(%s)")
            params.append(list(id_set))
        if mon_set is not None:
            where.append("LOWER(monitor::text) = ANY(%s)")
            params.append([m.lower() for m in mon_set])
        if tick_set is not None:
            where.append("ticker = ANY(%s)")
            params.append(list(tick_set))
        if sym_set is not None:
            where.append("UPPER(symbol::text) = ANY(%s)")
            params.append(list(sym_set))
        if strat_set is not None:
            where.append("trade_strategy = ANY(%s)")
            params.append(list(strat_set))
        if min_date_et:
            where.append("date >= %s")
            params.append(str(min_date_et).strip()[:10])
        if max_date_et:
            where.append("date <= %s")
            params.append(str(max_date_et).strip()[:10])

        sql = (
            f"SELECT {_quoted_cols(_TRADE_COLS)} FROM ( {union_sql} ) AS u "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY date DESC NULLS LAST, id DESC "
            f"LIMIT %s"
        )
        params.append(int(limit))
        cur.execute(sql, params)
        raw_rows = cur.fetchall()
        colnames = [d[0] for d in cur.description]
    finally:
        conn.close()

    rows = [_row_dict(colnames, r) for r in raw_rows]
    digest = _fingerprint(rows, slot)
    namespace = f"pg:users_{slot}"
    out: List[StrategyTradeRef] = []
    for r in rows:
        tid = str(r.get("id") or "").strip()
        ticker = str(r.get("ticker") or "").strip()
        if not tid or not ticker:
            continue
        entry = combine_trade_log_open_utc(
            str(r.get("date") or ""),
            str(r.get("time") or ""),
            str(r.get("created_at") or "") or None,
        )
        close = combine_trade_log_close_utc(
            str(r.get("date") or ""),
            str(r.get("closed_at") or "") or None,
            str(r.get("updated_at") or "") or None,
        )
        out.append(
            StrategyTradeRef(
                source_path=f"postgresql:users_{slot}.trades_{slot}",
                source_sha256=digest,
                source_namespace=namespace,
                trade_id=tid,
                ticker=ticker,
                monitor=str(r.get("monitor") or "").strip() or None,
                side=_norm_side(r.get("side")),
                date=str(r.get("date") or "") or None,
                entry_utc=entry,
                close_utc=close,
                row=r,
            )
        )
    return out


def _quoted_cols(cols: Sequence[str]) -> str:
    return ", ".join(f'"{c}"' for c in cols)


def list_distinct_tickers_pg(
    user_no: str,
    *,
    min_date_et: Optional[str] = None,
    max_date_et: Optional[str] = None,
    symbols: Optional[Sequence[str]] = None,
    monitors: Optional[Sequence[str]] = None,
    limit: int = 5000,
) -> List[str]:
    """Distinct market tickers in the tenant trade log for a symbol/date window."""
    slot = _slot(user_no)
    sym_set = {str(x).strip().upper() for x in (symbols or []) if str(x).strip()} or None
    mon_set = {str(x).strip() for x in (monitors or []) if str(x).strip()} or None
    conn = get_postgresql_connection(tenant_user_no=slot)
    try:
        cur = conn.cursor()
        union_sql, _ = union_trades_with_archives_select_columns(
            cur, slot, ("ticker", "symbol", "date", "monitor")
        )
        where = ["ticker IS NOT NULL", "BTRIM(ticker::text) <> ''"]
        params: List[Any] = []
        if min_date_et:
            where.append("date >= %s")
            params.append(str(min_date_et).strip()[:10])
        if max_date_et:
            where.append("date <= %s")
            params.append(str(max_date_et).strip()[:10])
        if sym_set is not None:
            where.append("UPPER(symbol::text) = ANY(%s)")
            params.append(list(sym_set))
        if mon_set is not None:
            where.append("LOWER(monitor::text) = ANY(%s)")
            params.append([m.lower() for m in mon_set])
        cur.execute(
            f"""
            SELECT ticker, COUNT(*)::int AS n
            FROM ( {union_sql} ) AS u
            WHERE {' AND '.join(where)}
            GROUP BY ticker
            ORDER BY n DESC, ticker
            LIMIT %s
            """,
            params + [int(limit)],
        )
        return [str(r[0]).strip() for r in cur.fetchall() if r[0]]
    finally:
        conn.close()


def trade_catalog_pg(
    user_no: str,
    *,
    min_date_et: Optional[str] = None,
    max_date_et: Optional[str] = None,
    symbols: Optional[Sequence[str]] = None,
    limit_tickers: int = 500,
) -> Dict[str, Any]:
    """
    Distinct symbols + tickers (with counts) from the tenant trade log for UI pickers.
    """
    slot = _slot(user_no)
    sym_set = {str(x).strip().upper() for x in (symbols or []) if str(x).strip()} or None
    conn = get_postgresql_connection(tenant_user_no=slot)
    try:
        cur = conn.cursor()
        union_sql, _ = union_trades_with_archives_select_columns(
            cur, slot, ("id", "date", "ticker", "symbol", "trade_strategy", "monitor")
        )
        where = ["ticker IS NOT NULL", "BTRIM(ticker::text) <> ''"]
        params: List[Any] = []
        if min_date_et:
            where.append("date >= %s")
            params.append(str(min_date_et).strip()[:10])
        if max_date_et:
            where.append("date <= %s")
            params.append(str(max_date_et).strip()[:10])
        if sym_set is not None:
            where.append("UPPER(symbol::text) = ANY(%s)")
            params.append(list(sym_set))
        wsql = " AND ".join(where)

        cur.execute(
            f"""
            SELECT COALESCE(UPPER(symbol::text), '') AS symbol, COUNT(*)::int AS n
            FROM ( {union_sql} ) AS u
            WHERE {wsql}
            GROUP BY 1
            ORDER BY n DESC, symbol
            """,
            params,
        )
        symbol_rows = [{"symbol": r[0] or "", "trade_count": int(r[1])} for r in cur.fetchall()]

        cur.execute(
            f"""
            SELECT ticker, COALESCE(UPPER(symbol::text), '') AS symbol,
                   COUNT(*)::int AS n,
                   MIN(date) AS min_date, MAX(date) AS max_date
            FROM ( {union_sql} ) AS u
            WHERE {wsql}
            GROUP BY ticker, symbol
            ORDER BY n DESC, ticker
            LIMIT %s
            """,
            params + [int(limit_tickers)],
        )
        ticker_rows = [
            {
                "ticker": r[0],
                "symbol": r[1],
                "trade_count": int(r[2]),
                "min_date": r[3],
                "max_date": r[4],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()

    return {
        "user_no": slot,
        "source": f"pg:users_{slot}",
        "min_date_et": min_date_et,
        "max_date_et": max_date_et,
        "symbols": symbol_rows,
        "tickers": ticker_rows,
    }


def find_trade_refs_pg(
    user_no: str, trade_ids: Sequence[str]
) -> Tuple[List[StrategyTradeRef], List[str]]:
    wanted = [str(x).strip() for x in trade_ids if str(x).strip()]
    found = select_strategy_trades_pg(user_no, trade_ids=wanted)
    have = {t.trade_id for t in found}
    missing = [w for w in wanted if w not in have]
    return found, missing
