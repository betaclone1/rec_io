#!/usr/bin/env python3
"""
One-time / prod-sync backfill for users.trades_* (live + paper, not trades_simulated_*):

1. market — NULL rows only; same rules as backend/trade_manager._resolve_trade_market_for_insert
   (monitor_list.market when monitor_key resolves; else strategy/ticker infer hourly vs 15m).

2. win_loss_confirmed — closed rows only, NULL confirmation only; uses persisted
   symbol_expiration, else symbol_close, with strike/side/win_loss (same counterfactual
   rules as trade_manager._compute_win_loss_confirmed / _apply_win_loss_confirmed_for_trade_ids).

Run from repo root (after deploy; uses prod credentials from your env):

  PYTHONPATH=$(pwd) .venv/bin/python scripts/db/backfill_trades_market_and_win_loss_confirmed.py
  PYTHONPATH=$(pwd) .venv/bin/python scripts/db/backfill_trades_market_and_win_loss_confirmed.py --dry-run
  PYTHONPATH=$(pwd) .venv/bin/python scripts/db/backfill_trades_market_and_win_loss_confirmed.py --limit 5000

Optional: restrict tables (default: all users.trades_<digits>):

  PYTHONPATH=$(pwd) .venv/bin/python scripts/db/backfill_trades_market_and_win_loss_confirmed.py --tables users.trades_0001

Keep in sync with backend/trade_manager.py (helpers inlined to avoid importing trade_manager).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any, Optional, Sequence, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, PROJECT_ROOT)

from psycopg2 import sql

from backend.core.config.database import get_postgresql_connection

MONITOR_KEY_PATTERN = re.compile(r"^mon_(\d+?)_(\d+)$", re.IGNORECASE)
_TRADES_TABLE_RE = re.compile(r"^trades_(\d{4})$")


def _tenant_schema_for_trades_table(table_name: str) -> str:
    m = _TRADES_TABLE_RE.match(table_name)
    if not m:
        raise ValueError(f"expected trades_NNNN table name, got {table_name!r}")
    return f"users_{m.group(1)}"


def _parse_trades_table_fq(fq: str) -> Tuple[str, str]:
    """Return (schema, table_name) for users_NNNN.trades_NNNN; accepts legacy users.trades_NNNN."""
    fq = fq.strip()
    if "." not in fq:
        t = fq
        return _tenant_schema_for_trades_table(t), t
    sch, t = fq.split(".", 1)
    if re.fullmatch(r"users_\d{4}", sch):
        return sch, t
    if sch == "users":
        return _tenant_schema_for_trades_table(t), t
    raise ValueError(
        f"expected schema users_NNNN or legacy users.*, got {fq!r}"
    )


def _get_market_for_monitor_key(pg_conn, monitor_key: Optional[str]) -> str:
    if not monitor_key or not pg_conn:
        return "hourly"
    try:
        match = MONITOR_KEY_PATTERN.match(str(monitor_key))
        if not match:
            return "hourly"
        user_number = match.group(1)
        monitor_id = match.group(2)
        with pg_conn.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "SELECT COALESCE(market, 'hourly') FROM {}.{} WHERE id = %s"
                ).format(
                    sql.Identifier(f"users_{user_number}"),
                    sql.Identifier(f"monitor_list_{user_number}"),
                ),
                (monitor_id,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                m = str(row[0]).strip().lower()
                return m if m in ("hourly", "15m") else "hourly"
        return "hourly"
    except Exception:
        return "hourly"


def _resolve_trade_market_for_insert(
    pg_conn,
    monitor_key: Optional[str],
    trade_strategy: Optional[str],
    ticker: Optional[str],
) -> str:
    if monitor_key and pg_conn:
        return _get_market_for_monitor_key(pg_conn, monitor_key)
    ts = (trade_strategy or "").lower()
    tk = (ticker or "").upper()
    if "15m" in ts or "15M" in tk:
        return "15m"
    return "hourly"


def _hypothetical_win_loss_at_expiration(strike, side, symbol_expiration) -> Optional[str]:
    if symbol_expiration is None or strike is None or side is None:
        return None
    try:
        strike_clean = str(strike).replace("$", "").replace(",", "")
        strike_float = float(strike_clean)
        sym_exp = float(symbol_expiration)
    except (ValueError, TypeError):
        return None
    side_u = str(side).strip().upper()
    if side_u in ("Y", "YES"):
        return "W" if sym_exp >= strike_float else "L"
    if side_u in ("N", "NO"):
        return "W" if sym_exp <= strike_float else "L"
    return None


def _normalize_win_loss_for_confirm(actual) -> Optional[str]:
    if actual is None:
        return None
    a = str(actual).strip().upper()
    if not a:
        return None
    if a in ("D", "DRAW", "TIE", "PUSH"):
        return None
    if a[0] == "W":
        return "W"
    if a[0] == "L":
        return "L"
    if a in ("1", "TRUE", "YES"):
        return "W"
    if a in ("0", "FALSE", "NO"):
        return "L"
    return None


def _compute_win_loss_confirmed(strike, side, symbol_expiration, win_loss_actual) -> Optional[bool]:
    hypo = _hypothetical_win_loss_at_expiration(strike, side, symbol_expiration)
    act = _normalize_win_loss_for_confirm(win_loss_actual)
    if hypo is None or act is None:
        return None
    return hypo == act


def _eff_symbol_exp(sym_exp: Any, sym_close: Any) -> Optional[float]:
    eff = sym_exp
    if eff is None and sym_close is not None:
        try:
            eff = float(sym_close)
        except (TypeError, ValueError):
            eff = None
    if eff is None:
        return None
    try:
        return float(eff)
    except (TypeError, ValueError):
        return None


def _list_trades_tables(cur) -> list[Tuple[str, str]]:
    cur.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema ~ '^users_[0-9]{4}$'
          AND table_name ~ '^trades_[0-9]{4}$'
        ORDER BY table_schema, table_name
        """
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def _table_has_columns(cur, schema: str, table: str, cols: Sequence[str]) -> Tuple[bool, list[str]]:
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    present = {r[0] for r in cur.fetchall()}
    ok = all(c in present for c in cols)
    missing = [c for c in cols if c not in present]
    return ok, missing


def backfill_market(
    pg_conn, schema: str, table_name: str, *, dry_run: bool, limit: Optional[int]
) -> int:
    q = sql.SQL(
        """
        SELECT id, monitor, trade_strategy, ticker
        FROM {}.{}
        WHERE market IS NULL
        ORDER BY id
        """
    ).format(sql.Identifier(schema), sql.Identifier(table_name))
    if limit is not None:
        q = sql.SQL("{} LIMIT %s").format(q)
    with pg_conn.cursor() as cur:
        cur.execute(q, (limit,) if limit is not None else ())
        rows = cur.fetchall()
    updated = 0
    for tid, monitor, strategy, ticker in rows:
        m = _resolve_trade_market_for_insert(pg_conn, monitor, strategy, ticker)
        if dry_run:
            print(f"  [dry-run] {schema}.{table_name} id={tid} market <- {m!r}")
            updated += 1
            continue
        with pg_conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "UPDATE {}.{} SET market = %s WHERE id = %s AND market IS NULL"
                ).format(sql.Identifier(schema), sql.Identifier(table_name)),
                (m, tid),
            )
            updated += cur.rowcount
    return updated


def backfill_win_loss_confirmed(
    pg_conn, schema: str, table_name: str, *, dry_run: bool, limit: Optional[int]
) -> int:
    q = sql.SQL(
        """
        SELECT id, strike, side, symbol_expiration, symbol_close, win_loss
        FROM {}.{}
        WHERE status = 'closed'
          AND win_loss IS NOT NULL
          AND win_loss_confirmed IS NULL
        ORDER BY id
        """
    ).format(sql.Identifier(schema), sql.Identifier(table_name))
    if limit is not None:
        q = sql.SQL("{} LIMIT %s").format(q)
    with pg_conn.cursor() as cur:
        cur.execute(q, (limit,) if limit is not None else ())
        rows = cur.fetchall()
    updated = 0
    for tid, strike, side, sym_exp, sym_close, win_loss in rows:
        eff = _eff_symbol_exp(sym_exp, sym_close)
        wlc = _compute_win_loss_confirmed(strike, side, eff, win_loss)
        if wlc is None:
            continue
        if dry_run:
            print(f"  [dry-run] {schema}.{table_name} id={tid} win_loss_confirmed <- {wlc}")
            updated += 1
            continue
        with pg_conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    UPDATE {}.{}
                    SET win_loss_confirmed = %s
                    WHERE id = %s AND status = 'closed' AND win_loss_confirmed IS NULL
                    """
                ).format(sql.Identifier(schema), sql.Identifier(table_name)),
                (wlc, tid),
            )
            updated += cur.rowcount
    return updated


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Print actions only; no commits")
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max rows per phase per table (default: no limit)",
    )
    ap.add_argument(
        "--tables",
        type=str,
        default="",
        help="Comma-separated full names (e.g. users_0001.trades_0001 or legacy users.trades_0001). "
        "Default: all users_NNNN.trades_NNNN",
    )
    args = ap.parse_args()

    tables: list[Tuple[str, str]] = []
    if args.tables.strip():
        for raw in args.tables.split(","):
            fq = raw.strip()
            if not fq:
                continue
            try:
                tables.append(_parse_trades_table_fq(fq))
            except ValueError as e:
                print(e, file=sys.stderr)
                return 2
    if not tables:
        c0 = get_postgresql_connection()
        if not c0:
            print("No database connection", file=sys.stderr)
            return 1
        try:
            with c0.cursor() as cur:
                tables = _list_trades_tables(cur)
        finally:
            c0.close()

    pg = get_postgresql_connection()
    if not pg:
        print("No database connection", file=sys.stderr)
        return 1
    try:
        total_m = total_w = 0
        for sch, tname in tables:
            with pg.cursor() as cur:
                ok, missing = _table_has_columns(
                    cur, sch, tname, ("market", "win_loss_confirmed")
                )
            if not ok:
                print(f"Skip {sch}.{tname}: missing columns {missing}")
                continue
            print(f"=== {sch}.{tname} ===")
            m = backfill_market(
                pg, sch, tname, dry_run=args.dry_run, limit=args.limit
            )
            w = backfill_win_loss_confirmed(
                pg, sch, tname, dry_run=args.dry_run, limit=args.limit
            )
            total_m += m
            total_w += w
            print(f"  market rows updated: {m}; win_loss_confirmed rows updated: {w}")
        if args.dry_run:
            print(f"[dry-run] Totals: market={total_m}, win_loss_confirmed={total_w} (no DB writes)")
        else:
            pg.commit()
            print(f"Done. Totals: market={total_m}, win_loss_confirmed={total_w}")
    except Exception as e:
        if pg and not args.dry_run:
            pg.rollback()
        raise
    finally:
        pg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
