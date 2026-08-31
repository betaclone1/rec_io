"""
Exact-style AES replay over archived strike ticks for one hourly contract cycle.

This replays entry gates in timestamp order across all strikes in the cycle, using
the same gate function as Hourly HTC and the monitor row settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from scripts.backtest.helpers.hypothetical_trades import estimate_kalshi_taker_fee

TRADE_COOLDOWN_SECONDS = 1


def _settlement_price(side: str, market_result: Optional[str]) -> float:
    mr = (market_result or "").strip().upper()
    s = (side or "").strip().lower()
    if s == "yes":
        return 1.0 if mr == "YES" else 0.0
    if s == "no":
        return 1.0 if mr == "NO" else 0.0
    return 0.0


def _contracts_for_allocation(buy_price: float, allocation_dollars: float) -> int:
    if buy_price <= 0 or buy_price >= 1 or allocation_dollars <= 0:
        return 0
    n = int(allocation_dollars / buy_price)
    n = max(1, n)
    while n > 0:
        fee = estimate_kalshi_taker_fee(n, buy_price)
        if n * buy_price + fee <= allocation_dollars + 1e-9:
            return n
        n -= 1
    return 0


@dataclass
class AesReplaySummary:
    markets: int
    entries: int
    exits: int
    wins: int
    losses: int
    open_left: int
    sum_pnl: float
    final_equity: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "markets": self.markets,
            "entries": self.entries,
            "exits": self.exits,
            "wins": self.wins,
            "losses": self.losses,
            "open_left": self.open_left,
            "sum_pnl": round(self.sum_pnl, 4),
            "final_equity": round(self.final_equity, 4),
            "win_rate": (self.wins / self.entries) if self.entries else None,
        }


def run_exact_hourly_cycle_aes_replay(
    conn: Any,
    *,
    monitor_table: str,
    monitor_id: int,
    cycle_prefix: str,
    timestamp_start: Any,
    timestamp_end_exclusive: Any,
    bankroll: float,
    allocation_pct: float,
    spike_alert_active: bool = False,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT min_probability, max_probability, min_differential, max_differential,
                   min_time, max_time, allow_re_entry, min_volume, max_ask, max_price_spread,
                   prob_adj, current_probability, stop_loss_price, min_ttc_seconds,
                   stop_verification_period_enabled, stop_verification_period_seconds
            FROM users_0001.{monitor_table}
            WHERE id = %s
            """,
            (monitor_id,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"no monitor row id={monitor_id} in users_0001.{monitor_table}")
    settings = {
        "min_probability": float(row[0]) if row[0] is not None else 95.0,
        "max_probability": float(row[1]) if row[1] is not None else 100.0,
        "min_differential": float(row[2]) if row[2] is not None else None,
        "max_differential": float(row[3]) if row[3] is not None else None,
        "min_time": int(row[4]) if row[4] is not None else 120,
        "max_time": int(row[5]) if row[5] is not None else 900,
        "allow_re_entry": bool(row[6]) if row[6] is not None else False,
        "min_volume": int(row[7]) if row[7] is not None else 1000,
        "max_ask": float(row[8]) if row[8] is not None else 0.98,
        "max_price_spread": float(row[9]) if row[9] is not None else 0.03,
        "prob_adj": float(row[10]) if row[10] is not None else 5.0,
        "current_probability": float(row[11]) if row[11] is not None else 40.0,
        "stop_loss_price": float(row[12]) if row[12] is not None else 0.0,
        "min_ttc_seconds": int(row[13]) if row[13] is not None else 0,
        "stop_verification_period_enabled": bool(row[14]) if row[14] is not None else False,
        "stop_verification_period_seconds": int(row[15]) if row[15] is not None else 60,
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT market_ticker
            FROM historical_data.strike_table_master
            WHERE market_ticker LIKE %s
            GROUP BY market_ticker
            ORDER BY market_ticker ASC
            """,
            (f"{cycle_prefix}%",),
        )
        tickers = [r[0] for r in cur.fetchall()]
    if not tickers:
        return {
            "ok": True,
            "cycle_prefix": cycle_prefix,
            "summary": AesReplaySummary(0, 0, 0, 0, 0, 0, 0.0, bankroll).as_dict(),
            "events": [],
        }

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT "timestamp", market_ticker, strike, active_side, ttc_hourly, ttc_15m,
                   yes_prob_hourly, no_prob_hourly, yes_prob_15m, no_prob_15m,
                   yes_diff, no_diff, yes_ask_dollars, no_ask_dollars,
                   volume_fp, market_result
            FROM historical_data.strike_table_master
            WHERE market_ticker LIKE %s
              AND "timestamp" >= %s
              AND "timestamp" < %s
            ORDER BY "timestamp" ASC, strike ASC
            """,
            (f"{cycle_prefix}%", timestamp_start, timestamp_end_exclusive),
        )
        rows = cur.fetchall()

    market_result_by_ticker: dict[str, Optional[str]] = {}
    for r in rows:
        mr = r[15]
        if mr:
            market_result_by_ticker[r[1]] = str(mr)

    entered_keys: set[tuple[str, str, str]] = set()
    allow_re_entry = bool(settings.get("allow_re_entry")) if settings.get("allow_re_entry") is not None else False
    stop_prob_threshold = float(settings.get("current_probability", 40.0))
    stop_floor = max(0.0, min(float(settings.get("stop_loss_price", 0.0)), 0.99))
    min_ttc_stop = int(settings.get("min_ttc_seconds", 0))
    verification_enabled = bool(settings.get("stop_verification_period_enabled", False))
    verification_seconds = int(settings.get("stop_verification_period_seconds", 60))
    equity = float(bankroll)
    entries = exits = wins = losses = 0
    sum_pnl = 0.0
    events: list[dict[str, Any]] = []
    open_trades: list[dict[str, Any]] = []
    verification_pending: dict[int, tuple[float, float]] = {}
    last_trade_times: dict[str, float] = {}
    seq = 1
    ts_seen: datetime | None = None
    processed_strikes: set[str] = set()

    for r in rows:
        ts, ticker = r[0], str(r[1])
        strike_val = r[2]
        active_side = (r[3] or "").strip().lower()
        ttc_hourly = r[4]
        yes_prob_hourly, no_prob_hourly = r[6], r[7]
        yes_diff, no_diff = r[10], r[11]
        yes_ask, no_ask = r[12], r[13]
        vol = r[14]
        ts_epoch = ts.timestamp() if hasattr(ts, "timestamp") else None

        if ts_seen != ts:
            ts_seen = ts
            processed_strikes = set()

        for trade in open_trades:
            if trade.get("status") != "active":
                continue
            if trade["ticker"] != ticker:
                continue

            ttc_ok_for_stops = ttc_hourly is not None and int(ttc_hourly) >= min_ttc_stop
            if not ttc_ok_for_stops:
                continue

            side = trade["side"]
            current_prob = float(yes_prob_hourly) if side == "yes" and yes_prob_hourly is not None else (
                float(no_prob_hourly) if side == "no" and no_prob_hourly is not None else None
            )
            current_close_price = float(no_ask) if side == "yes" and no_ask is not None else (
                float(yes_ask) if side == "no" and yes_ask is not None else None
            )
            sell_price_live = float(yes_ask) if side == "yes" and yes_ask is not None else (
                float(no_ask) if side == "no" and no_ask is not None else None
            )

            close_method: Optional[str] = None
            if stop_floor > 0 and current_close_price is not None and current_close_price > (1.0 - stop_floor):
                close_method = "auto_stop_loss_floor"
            elif current_prob is not None and current_prob < stop_prob_threshold:
                if verification_enabled:
                    tid = int(trade["id"])
                    pending = verification_pending.get(tid)
                    now = ts_epoch or 0.0
                    if pending is None:
                        verification_pending[tid] = (now, now + verification_seconds)
                    elif now >= pending[1]:
                        close_method = "auto_probability"
                        verification_pending.pop(tid, None)
                else:
                    close_method = "auto_probability"
            else:
                verification_pending.pop(int(trade["id"]), None)

            if close_method and sell_price_live is not None:
                close_fee = estimate_kalshi_taker_fee(trade["contracts"], sell_price_live) if 0 < sell_price_live < 1 else 0.0
                pnl = trade["contracts"] * (sell_price_live - trade["buy_price"]) - trade["open_fee"] - close_fee
                trade["status"] = "closed"
                trade["close_method"] = close_method
                trade["exit_price"] = sell_price_live
                trade["exit_ts"] = ts
                trade["pnl"] = pnl
                equity += pnl
                sum_pnl += pnl
                exits += 1
                wl = "W" if pnl > 0 else ("L" if pnl < 0 else "D")
                if wl == "W":
                    wins += 1
                elif wl == "L":
                    losses += 1
                events.append(
                    {
                        "event": "exit",
                        "close_method": close_method,
                        "trade_id": trade["id"],
                        "entry_timestamp": trade["entry_ts"].isoformat() if hasattr(trade["entry_ts"], "isoformat") else str(trade["entry_ts"]),
                        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                        "ticker": ticker,
                        "side": side,
                        "strike": trade["strike"],
                        "sell_price": sell_price_live,
                        "contracts": trade["contracts"],
                        "pnl": round(float(pnl), 4),
                        "win_loss": wl,
                        "ttc_hourly": int(ttc_hourly) if ttc_hourly is not None else None,
                    }
                )

        if active_side not in ("yes", "no"):
            continue
        if ttc_hourly is None:
            continue
        ttc_i = int(ttc_hourly)
        if not (int(settings["min_time"]) <= ttc_i <= int(settings["max_time"])):
            continue

        strike_key = (ticker, active_side, str(strike_val))
        cooldown_key = f"{active_side}:{strike_val}"
        if cooldown_key in processed_strikes:
            continue
        processed_strikes.add(cooldown_key)

        if ts_epoch is not None and cooldown_key in last_trade_times:
            if ts_epoch - last_trade_times[cooldown_key] < TRADE_COOLDOWN_SECONDS:
                continue

        has_inflight = any(
            t.get("status") == "active" and t["ticker"] == ticker and t["side"] == active_side
            for t in open_trades
        )
        if has_inflight:
            continue

        if not allow_re_entry and strike_key in entered_keys:
            continue

        prob = float(yes_prob_hourly) if active_side == "yes" and yes_prob_hourly is not None else (
            float(no_prob_hourly) if active_side == "no" and no_prob_hourly is not None else None
        )
        if prob is None:
            continue
        min_probability = float(settings["min_probability"]) + (float(settings["prob_adj"]) if spike_alert_active else 0.0)
        if prob < min_probability or prob > float(settings["max_probability"]):
            continue
        if settings.get("min_differential") is not None:
            diff = float(yes_diff) if active_side == "yes" and yes_diff is not None else (
                float(no_diff) if active_side == "no" and no_diff is not None else None
            )
            if diff is None or diff < (float(settings["min_differential"]) - 0.5):
                continue
        if settings.get("max_differential") is not None:
            diff = float(yes_diff) if active_side == "yes" and yes_diff is not None else (
                float(no_diff) if active_side == "no" and no_diff is not None else None
            )
            if diff is None or diff > float(settings["max_differential"]):
                continue
        volume = int(float(vol)) if vol is not None else 0
        if volume < int(settings["min_volume"]):
            continue
        if yes_ask is None or no_ask is None:
            continue
        if max(float(yes_ask), float(no_ask)) > float(settings["max_ask"]):
            continue

        buy_price = float(yes_ask) if active_side == "yes" else float(no_ask)
        contracts = 1
        open_fee = estimate_kalshi_taker_fee(contracts, buy_price)
        if ts_epoch is not None:
            last_trade_times[cooldown_key] = ts_epoch
        entries += 1
        entered_keys.add(strike_key)
        open_trades.append(
            {
                "id": seq,
                "status": "active",
                "entry_ts": ts,
                "ticker": ticker,
                "side": active_side,
                "strike": strike_val,
                "buy_price": buy_price,
                "contracts": contracts,
                "open_fee": open_fee,
            }
        )
        seq += 1
        events.append(
            {
                "event": "entry",
                "trade_id": seq - 1,
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "ticker": ticker,
                "side": active_side,
                "strike": strike_val,
                "buy_price": buy_price,
                "contracts": contracts,
                "ttc_hourly": ttc_i,
            }
        )

    for trade in open_trades:
        if trade.get("status") != "active":
            continue
        mr = market_result_by_ticker.get(trade["ticker"])
        sell_price = _settlement_price(str(trade["side"]), mr)
        close_fee = estimate_kalshi_taker_fee(trade["contracts"], sell_price) if 0 < sell_price < 1 else 0.0
        pnl = trade["contracts"] * (sell_price - trade["buy_price"]) - trade["open_fee"] - close_fee
        trade["status"] = "closed"
        trade["close_method"] = "expired"
        trade["pnl"] = pnl
        equity += pnl
        sum_pnl += pnl
        exits += 1
        wl = "W" if pnl > 0 else ("L" if pnl < 0 else "D")
        if wl == "W":
            wins += 1
        elif wl == "L":
            losses += 1
        events.append(
            {
                "event": "exit",
                "close_method": "expired",
                "trade_id": trade["id"],
                "entry_timestamp": trade["entry_ts"].isoformat() if hasattr(trade["entry_ts"], "isoformat") else str(trade["entry_ts"]),
                "timestamp": None,
                "ticker": trade["ticker"],
                "side": trade["side"],
                "strike": trade["strike"],
                "sell_price": sell_price,
                "contracts": trade["contracts"],
                "market_result": mr,
                "pnl": round(float(pnl), 4),
                "win_loss": wl,
                "ttc_hourly": None,
            }
        )

    summary = AesReplaySummary(
        markets=len(tickers),
        entries=entries,
        exits=exits,
        wins=wins,
        losses=losses,
        open_left=sum(1 for t in open_trades if t.get("status") == "active"),
        sum_pnl=sum_pnl,
        final_equity=equity,
    )
    return {
        "ok": True,
        "cycle_prefix": cycle_prefix,
        "settings": {
            "min_probability": settings.get("min_probability"),
            "max_probability": settings.get("max_probability"),
            "min_differential": settings.get("min_differential"),
            "max_differential": settings.get("max_differential"),
            "min_volume": settings.get("min_volume"),
            "max_ask": settings.get("max_ask"),
            "allow_re_entry": settings.get("allow_re_entry"),
            "min_time": settings.get("min_time"),
            "max_time": settings.get("max_time"),
        },
        "summary": summary.as_dict(),
        "events": events,
    }

