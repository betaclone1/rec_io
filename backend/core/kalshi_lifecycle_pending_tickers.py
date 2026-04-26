"""
Read-only, cross-tenant queries for Kalshi lifecycle WebSocket subscription planning.

``market_watchdog_ws`` runs under :func:`backend.core.config.database.get_system_postgresql_connection`
(no tenant rewrite). It must not assume a single ``users_0001`` schema: we discover
``(users_NNNN, trades_NNNN)`` pairs from ``information_schema`` and ``UNION ALL`` qualified selects.

This module performs **SELECT only** (no DML). Trade row updates remain in
:mod:`backend.core.kalshi_lifecycle_trade_outcome` via per-tenant consumers.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from psycopg2 import sql

logger = logging.getLogger(__name__)


def _trades_table_pairs(cursor) -> List[Tuple[str, str]]:
    cursor.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema ~ '^users_[0-9]{4}$'
          AND table_name ~ '^trades_[0-9]{4}$'
          AND replace(table_schema, 'users_', '') = replace(table_name, 'trades_', '')
        ORDER BY table_schema, table_name
        """
    )
    return [(str(a), str(b)) for a, b in cursor.fetchall() or ()]


def _pending_fragment(schema: str, table: str) -> sql.Composable:
    return sql.SQL(
        """
        SELECT ticker, symbol, id FROM {}.{}
        WHERE LOWER(TRIM(COALESCE(exchange, ''))) = %s
          AND ticker IS NOT NULL AND TRIM(ticker::text) != ''
          AND status IN ('open', 'closing', 'expired', 'closed')
          AND (
            (status IN ('open', 'closing') AND market_result IS NULL)
            OR (status = 'expired')
            OR (status = 'closed' AND market_result IS NULL)
          )
        """
    ).format(sql.Identifier(schema), sql.Identifier(table))


def fetch_lifecycle_pending_meta_all_tenants(conn, exchange_key: str) -> Dict[str, Tuple[str, str]]:
    """
    Map ``ticker -> (symbol, '')`` for rows that still need ``market_result``, across all tenant trade tables.
    """
    ex = str(exchange_key).strip().lower()
    out: Dict[str, Tuple[str, str]] = {}
    try:
        with conn.cursor() as cur:
            pairs = _trades_table_pairs(cur)
            if not pairs:
                return out
            parts: List[sql.Composable] = [_pending_fragment(s, t) for s, t in pairs]
            inner = sql.SQL(" UNION ALL ").join(parts)
            query = sql.SQL(
                """
                SELECT DISTINCT ON (ticker) ticker, symbol FROM ({}) AS _u
                ORDER BY ticker, id DESC
                """
            ).format(inner)
            params = tuple([ex] * len(pairs))
            cur.execute(query, params)
            for row in cur.fetchall() or ():
                tkr, sym = row[0], row[1]
                if not tkr:
                    continue
                ts = str(tkr).strip()
                su = str(sym or "").strip().upper()
                out[ts] = (su, "")
    except Exception:
        logger.exception("fetch_lifecycle_pending_meta_all_tenants failed")
    return out


def distinct_open_trade_tickers_for_symbol_all_tenants(conn, symbol_upper: str) -> set:
    """Distinct Kalshi tickers with ``pending``/``open`` rows for ``symbol`` across all tenant ``trades_*`` tables."""
    sym = str(symbol_upper or "").strip().upper()
    tickers = set()
    if not sym:
        return tickers
    try:
        with conn.cursor() as cur:
            pairs = _trades_table_pairs(cur)
            for schema, table in pairs:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT DISTINCT ticker FROM {}.{}
                        WHERE status IN ('pending', 'open')
                          AND UPPER(TRIM(COALESCE(symbol::text, ''))) = %s
                          AND ticker IS NOT NULL AND TRIM(ticker::text) <> ''
                        """
                    ).format(sql.Identifier(schema), sql.Identifier(table)),
                    (sym,),
                )
                for (t,) in cur.fetchall() or ():
                    if t:
                        tickers.add(t)
    except Exception:
        logger.exception("distinct_open_trade_tickers_for_symbol_all_tenants failed symbol=%s", sym)
    return tickers


def ticker_still_needs_market_result_any_tenant(conn, market_ticker: str, exchange_key: str) -> bool:
    mt = str(market_ticker).strip()
    ex = str(exchange_key).strip().lower()
    if not mt:
        return False
    try:
        with conn.cursor() as cur:
            pairs = _trades_table_pairs(cur)
            for schema, table in pairs:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT 1 FROM {}.{}
                        WHERE ticker = %s
                          AND LOWER(TRIM(COALESCE(exchange, ''))) = %s
                          AND status IN ('open', 'closing', 'expired', 'closed')
                          AND (
                            (status IN ('open', 'closing') AND market_result IS NULL)
                            OR (status = 'expired')
                            OR (status = 'closed' AND market_result IS NULL)
                          )
                        LIMIT 1
                        """
                    ).format(sql.Identifier(schema), sql.Identifier(table)),
                    (mt, ex),
                )
                if cur.fetchone():
                    return True
    except Exception:
        logger.exception("ticker_still_needs_market_result_any_tenant failed ticker=%s", mt)
        return True
    return False
