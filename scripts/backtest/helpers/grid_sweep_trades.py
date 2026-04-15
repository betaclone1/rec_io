"""
Insert synthetic sweep trades into ``backtest.grid_sweep_trades`` (mirror of ``users.trades_0001``).

Requires migration ``20260416_1015_backtest_grid_sweep_trades`` applied.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional


def grid_sweep_trades_table_ready(conn: Any) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'backtest' AND table_name = 'grid_sweep_trades'
            """
        )
        return cur.fetchone() is not None


def _split_et_naive(s: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not s:
        return None, None
    t = str(s).strip().replace("T", " ")
    parts = t.split()
    if len(parts) >= 2:
        return parts[0], parts[1].split(".")[0]
    if len(parts) == 1:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]):
            return parts[0], None
    return None, None


def _close_method_for_trades(cm: str) -> str:
    if (cm or "").strip().lower() == "expiration":
        return "expired"
    return str(cm or "")


def _status_for_close(cm_tr: str) -> str:
    if cm_tr == "expired":
        return "expired"
    return "closed"


def _entry_prob(entry: Mapping[str, Any], side: str) -> Optional[float]:
    su = (side or "").strip().lower()
    if su == "yes":
        v = entry.get("yes_prob_15m")
    elif su == "no":
        v = entry.get("no_prob_15m")
    else:
        return None
    if v is None:
        return None
    return float(v)


def _entry_diff(entry: Mapping[str, Any], side: str) -> Optional[str]:
    su = (side or "").strip().lower()
    key = "yes_diff" if su == "yes" else "no_diff"
    v = entry.get(key)
    if v is None:
        return None
    return str(v)


def _ticket_id(*, sweep_batch_id: str, synthetic_monitor_id: int, ticker: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", ticker)[:40]
    b = (sweep_batch_id or "")[:16]
    return f"GS-{b}-{synthetic_monitor_id}-{slug}"


def _market_result_norm(mr: Any) -> Optional[str]:
    if mr is None:
        return None
    u = str(mr).strip().upper()
    if u == "YES":
        return "yes"
    if u == "NO":
        return "no"
    return None


def insert_grid_sweep_trade(
    conn: Any,
    *,
    sweep_batch_id: str,
    synthetic_monitor_id: int,
    source_monitor_id: int,
    replay_user: str,
    replay_out: Mapping[str, Any],
    trade_meta: Mapping[str, Any],
    reference_bankroll: float,
) -> int:
    """Map a successful tick replay row to ``backtest.grid_sweep_trades``; returns inserted ``id``."""
    entry = replay_out.get("entry_tick_row") or {}
    exit_ = replay_out.get("exit_tick_row") or {}
    side = str(replay_out.get("side") or "").strip().lower()
    if side not in ("yes", "no"):
        raise ValueError("replay_out.side must be yes or no")

    cm_raw = str(replay_out.get("close_method") or "")
    cm_tr = _close_method_for_trades(cm_raw)
    status = _status_for_close(cm_tr)

    date_s, time_s = _split_et_naive(replay_out.get("entry_timestamp_et_naive"))
    if not date_s or not time_s:
        raise ValueError("replay_out missing entry_timestamp_et_naive for date/time")
    _, closed_time = _split_et_naive(replay_out.get("exit_timestamp_et_naive"))

    ticker = str(replay_out.get("ticker") or "")
    strike = str(replay_out.get("strike_label") or "")
    u = str(replay_user).strip().zfill(4)
    monitor_label = f"mon_{u}_{synthetic_monitor_id}"

    prob = _entry_prob(entry, side)
    diff_s = _entry_diff(entry, side)

    sym_open = entry.get("current_price")
    sym_close = exit_.get("current_price")

    mom_pct = entry.get("momentum_percentile")
    mom_pct_f = float(mom_pct) if mom_pct is not None else None

    mws = entry.get("momentum_weighted_score")
    try:
        mom_i = int(round(float(mws))) if mws is not None else None
    except (TypeError, ValueError):
        mom_i = None

    vol = entry.get("volatility")
    vol_pct = entry.get("volatility_percentile")
    mov = entry.get("movement")
    mov_pct = entry.get("movement_percentile")

    mult = trade_meta.get("multiplier")
    try:
        mult_d = float(mult) if mult is not None else None
    except (TypeError, ValueError):
        mult_d = None

    mr_db = _market_result_norm(replay_out.get("market_result"))
    wlc = replay_out.get("win_loss_confirmed")
    if wlc is not None:
        wlc = bool(wlc)

    fees = replay_out.get("fees_total_dollars")
    pnl = replay_out.get("pnl_dollars")
    ret_pct = replay_out.get("ret_pct")
    roi_pct = replay_out.get("return_on_notional_pct")
    buy_p = replay_out.get("buy_price")
    sell_p = replay_out.get("sell_price")
    pos = replay_out.get("contracts")
    wl = replay_out.get("win_loss")

    cadence = str(trade_meta.get("market") or "15m")[:10]

    sql = """
    INSERT INTO backtest.grid_sweep_trades (
        sweep_batch_id, synthetic_monitor_id, source_monitor_id,
        status, date, time, symbol, exchange, trade_strategy, market, contract, strike, side,
        prob, diff, buy_price, position, sell_price, closed_at, fees, pnl,
        symbol_open, symbol_close, win_loss, ticker, ticket_id,
        momentum_percentile, entry_method, close_method, paper_trade, monitor,
        bankroll, ret_pct, roi_pct, market_result, win_loss_confirmed,
        yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
        yes_ask_range_15m, no_ask_range_15m,
        momentum, volatility, volatility_percentile, movement, movement_percentile,
        multiplier
    ) VALUES (
        %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s
    )
    RETURNING id
    """
    params = (
        str(sweep_batch_id),
        int(synthetic_monitor_id),
        int(source_monitor_id),
        status,
        date_s,
        time_s,
        trade_meta.get("symbol") or None,
        "kalshi",
        trade_meta.get("trade_strategy") or None,
        cadence,
        ticker,
        strike,
        side,
        prob,
        diff_s,
        float(buy_p) if buy_p is not None else None,
        int(pos) if pos is not None else None,
        float(sell_p) if sell_p is not None else None,
        closed_time,
        float(fees) if fees is not None else None,
        float(pnl) if pnl is not None else None,
        float(sym_open) if sym_open is not None else None,
        float(sym_close) if sym_close is not None else None,
        str(wl) if wl is not None else None,
        ticker,
        _ticket_id(
            sweep_batch_id=str(sweep_batch_id),
            synthetic_monitor_id=int(synthetic_monitor_id),
            ticker=ticker,
        ),
        mom_pct_f,
        "auto",
        cm_tr,
        True,
        monitor_label,
        float(reference_bankroll),
        float(ret_pct) if ret_pct is not None else None,
        float(roi_pct) if roi_pct is not None else None,
        mr_db,
        wlc,
        entry.get("yes_ask_min_15m"),
        entry.get("yes_ask_max_15m"),
        entry.get("no_ask_min_15m"),
        entry.get("no_ask_max_15m"),
        entry.get("yes_ask_range_15m"),
        entry.get("no_ask_range_15m"),
        mom_i,
        vol,
        vol_pct,
        mov,
        mov_pct,
        mult_d,
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            raise RuntimeError("INSERT grid_sweep_trades did not return id")
        new_id = int(row[0])
    conn.commit()
    return new_id
