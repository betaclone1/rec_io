#!/usr/bin/env python3
"""
One-time backfill: ``users.trades_<slot>``.symbol_expiration from historical_data.*_price_history,
then win_loss_confirmed using the same strike/side/spot rules as backend/trade_manager.py (inlined here).

Cycle end time (US Eastern wall time, naive — matches price_history.timestamp):
- Hourly contract (e.g. "BTC 2pm"): window [2pm, 3pm) → spot at end → 3:00:00 same day.
- 15m contract (e.g. "BTC 2:15pm"): resolution at that clock time → 2:15:00 same day.

Price: uses the 1m bar's `close` at the cycle end minute, or the latest bar within
+/- 2 minutes if that exact timestamp is missing (sparse data / DST edges).

Symbols: any historical_data.{symbol_lower}_price_history that exists (typically btc, eth).
Skips rows with no history table, no parseable contract/date, or no matching bar.

Paper and live: both get symbol_expiration and win_loss_confirmed when computable.

Run from repo root (venv required):
  PYTHONPATH=$(pwd) .venv/bin/python scripts/db/backfill_trades_symbol_expiration_from_history.py
  PYTHONPATH=$(pwd) .venv/bin/python scripts/db/backfill_trades_symbol_expiration_from_history.py --dry-run
  PYTHONPATH=$(pwd) .venv/bin/python scripts/db/backfill_trades_symbol_expiration_from_history.py --force
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_legacy_sql import legacy_users_trades
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no

# Keep in sync with backend/trade_manager.py (avoid importing trade_manager: pulls requests, etc.)
CONTRACT_HOUR_PATTERN = re.compile(r".*\s([0-9]{1,2})(am|pm)$", re.IGNORECASE)
CONTRACT_15M_FULL_PATTERN = re.compile(r".*\s([0-9]{1,2}):([0-9]{2})\s*(am|pm)", re.IGNORECASE)
CONTRACT_15M_HOUR_PATTERN = re.compile(r".*\s([0-9]{1,2}):[0-9]{2}\s*(am|pm)", re.IGNORECASE)
_HIGH_PRECISION = frozenset({"SOL", "XRP"})


def _sym_norm(symbol: Optional[str]) -> str:
    return str(symbol or "").strip().upper()


def normalize_trade_spot_price(symbol: Optional[str], value):
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        try:
            d = Decimal(str(float(value)))
        except Exception:
            return None
    step = Decimal("0.00001") if _sym_norm(symbol) in _HIGH_PRECISION else Decimal("0.01")
    return d.quantize(step, rounding=ROUND_HALF_UP)


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


def _parse_date(date_val) -> date | None:
    if date_val is None:
        return None
    if hasattr(date_val, "year"):
        if isinstance(date_val, datetime):
            return date_val.date()
        return date_val
    try:
        return datetime.strptime(str(date_val).strip()[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _wall_hour_start_12h(hour_raw: int, mer: str) -> int:
    mer = (mer or "").lower()
    h = int(hour_raw)
    if mer == "am":
        return 0 if h == 12 else h
    return 12 if h == 12 else h + 12


def _hourly_cycle_end(contract: str, d: date) -> datetime | None:
    """End of hourly Kalshi window: label is start of hour; end is +1 hour."""
    s = (contract or "").strip()
    if CONTRACT_15M_HOUR_PATTERN.search(s):
        return None
    m = CONTRACT_HOUR_PATTERN.match(s)
    if not m:
        return None
    hour_raw = int(m.group(1))
    mer = m.group(2)
    h0 = _wall_hour_start_12h(hour_raw, mer)
    start = datetime.combine(d, time(h0, 0, 0))
    return start + timedelta(hours=1)


def _quarter_hour_cycle_end(contract: str, d: date) -> datetime | None:
    """15m: contract time is resolution (end of window)."""
    s = (contract or "").strip()
    match = CONTRACT_15M_FULL_PATTERN.search(s)
    if not match:
        return None
    hour_raw = int(match.group(1))
    minutes = int(match.group(2))
    mer = match.group(3)
    h = _wall_hour_start_12h(hour_raw, mer)
    return datetime.combine(d, time(h, minutes, 0))


def _resolve_cycle_end_naive(date_val, contract: str, market: str) -> datetime | None:
    d = _parse_date(date_val)
    if d is None:
        return None
    mk = (market or "hourly").strip().lower()
    if mk not in ("hourly", "15m"):
        mk = "hourly"
    s = (contract or "").strip()
    has_15m_token = CONTRACT_15M_FULL_PATTERN.search(s) is not None
    if has_15m_token or mk == "15m":
        end = _quarter_hour_cycle_end(contract, d)
        if end is not None:
            return end
        if mk == "15m":
            return None
    return _hourly_cycle_end(contract, d)


def _infer_market(trade_strategy, ticker, market_col) -> str:
    m = (market_col or "").strip().lower() if market_col is not None else ""
    if m in ("hourly", "15m"):
        return m
    ts = (trade_strategy or "").lower()
    tk = (ticker or "").upper()
    if "15m" in ts or "15M" in tk:
        return "15m"
    return "hourly"


def _historical_table_for_symbol(cur, symbol: str) -> str | None:
    if not symbol:
        return None
    name = f"{str(symbol).strip().lower()}_price_history"
    cur.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'historical_data' AND table_name = %s
        """,
        (name,),
    )
    if cur.fetchone():
        return f"historical_data.{name}"
    return None


def _fetch_close_near(cur, table_sql: str, target: datetime):
    """Prefer exact timestamp; else closest bar within +/- 2 minutes (by absolute delta)."""
    cur.execute(
        f"""
        SELECT "timestamp", close FROM {table_sql}
        WHERE "timestamp" BETWEEN %s AND %s
          AND close IS NOT NULL
        ORDER BY ABS(EXTRACT(EPOCH FROM ("timestamp" - %s::timestamp)))
        LIMIT 1
        """,
        (target - timedelta(minutes=2), target + timedelta(minutes=2), target),
    )
    row = cur.fetchone()
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill symbol_expiration + win_loss_confirmed from historical price logs.")
    ap.add_argument("--dry-run", action="store_true", help="Print actions only; no UPDATE.")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing symbol_expiration (still needs history bar).",
    )
    ap.add_argument("--limit", type=int, default=0, help="Max trades to process (0 = all).")
    add_user_no_argument(ap)
    args = ap.parse_args()
    user_no = resolve_user_no(args)
    trades_t = legacy_users_trades(user_no)

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("Cannot connect to PostgreSQL")
        return 1

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT id, symbol, date, contract, trade_strategy, ticker,
               COALESCE(market, 'hourly') AS market_col,
               strike, side, win_loss, symbol_expiration, win_loss_confirmed
        FROM {trades_t}
        ORDER BY id
        """
    )
    rows = cur.fetchall()

    attempted = 0
    skipped_no_contract_end = 0
    skipped_no_table = 0
    skipped_no_bar = 0
    skipped_already_had_exp = 0
    updated_exp = 0
    updated_wlc = 0
    errors = 0

    for row in rows:
        if args.limit and attempted >= args.limit:
            break
        (
            tid,
            symbol,
            date_val,
            contract,
            trade_strategy,
            ticker,
            market_col,
            strike,
            side,
            win_loss,
            existing_exp,
            existing_wlc,
        ) = row

        if existing_exp is not None and not args.force:
            skipped_already_had_exp += 1
            attempted += 1
            if existing_wlc is None and win_loss:
                try:
                    wlc = _compute_win_loss_confirmed(strike, side, float(existing_exp), win_loss)
                    if wlc is not None:
                        if args.dry_run:
                            print(f"[dry-run] id={tid} win_loss_confirmed-only {wlc} (existing symbol_expiration)")
                        else:
                            cur.execute(
                                f"""
                                UPDATE {trades_t}
                                SET win_loss_confirmed = COALESCE(%s, win_loss_confirmed)
                                WHERE id = %s
                                """,
                                (wlc, tid),
                            )
                            if cur.rowcount:
                                updated_wlc += 1
                except Exception as e:
                    errors += 1
                    print(f"id={tid} win_loss_confirmed-only error: {e}")
            continue

        market = _infer_market(trade_strategy, ticker, market_col)
        cycle_end = _resolve_cycle_end_naive(date_val, contract, market)
        if cycle_end is None:
            skipped_no_contract_end += 1
            attempted += 1
            continue

        table_sql = _historical_table_for_symbol(cur, symbol)
        if not table_sql:
            skipped_no_table += 1
            attempted += 1
            continue

        bar = _fetch_close_near(cur, table_sql, cycle_end)
        if not bar or bar[1] is None:
            skipped_no_bar += 1
            attempted += 1
            continue

        _, close_raw = bar
        try:
            sym_exp = normalize_trade_spot_price(symbol, float(close_raw))
        except Exception:
            skipped_no_bar += 1
            attempted += 1
            continue

        wlc = _compute_win_loss_confirmed(strike, side, sym_exp, win_loss)

        if args.dry_run:
            print(
                f"[dry-run] id={tid} market={market} cycle_end={cycle_end} "
                f"symbol_expiration={sym_exp} win_loss_confirmed={wlc}"
            )
        else:
            try:
                cur.execute(
                    f"""
                    UPDATE {trades_t}
                    SET symbol_expiration = %s,
                        win_loss_confirmed = COALESCE(%s, win_loss_confirmed)
                    WHERE id = %s
                    """,
                    (sym_exp, wlc, tid),
                )
                if cur.rowcount:
                    updated_exp += 1
                    if wlc is not None:
                        updated_wlc += 1
            except Exception as e:
                errors += 1
                print(f"Error updating id={tid}: {e}")

        attempted += 1

    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    print(
        f"Rows touched in loop: {attempted}, updated symbol_expiration: {updated_exp}, "
        f"win_loss_confirmed updates: {updated_wlc}, "
        f"skip no cycle: {skipped_no_contract_end}, no hist table: {skipped_no_table}, "
        f"no bar: {skipped_no_bar}, skip already had exp: {skipped_already_had_exp}, errors: {errors}"
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
