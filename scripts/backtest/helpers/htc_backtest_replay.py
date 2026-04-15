"""
Single-market **HTC-style** replay against ``backtest.backtest_1m_*`` rows (1-minute bars), or
``backtest.tick_backtest_*`` (1-second strike-shaped rows) when ``from_tick_table=True``.

- **Tick replay:** chronological ``ORDER BY timestamp``; AES uses ``ttc_15m`` and
  ``tick_backtest_row_to_strike_mapping``; ATS uses ``ttc_15m``, point ``yes_prob_15m`` / ``no_prob_15m``,
  and trade-carried asks (same harness as 1m, finer timestep).

- Entry (1m): ``min_time <= ttc_15m_close_seconds <= max_time`` from **strategy defaults**
  (``users.strategy_list_<user>`` by name, usually ``15m HTC`` vs ``Hourly HTC`` from the ticker) or
  optionally a specific ``users.monitor_list_<user>`` row; then
  ``backend.util.auto_entry_htc_gates.evaluate_hourly_htc_strike_entry`` on a strike-shaped dict built
  from the minute row. NO **ask** for Kalshi ingest rows is implied from YES ask OHLC when
  ``no_ask_high_dollars`` is absent (same geometry as ``backtest_strike_span``).

- Exit (**ATS canonical**, ``active_trade_supervisor.check_auto_stop_conditions_hourly_htc``):
  ``min_time`` / ``max_time`` apply to **entry only** (AES), not to forcing an exit while flat is
  open. Auto-stops run only while ``ttc_15m_close_seconds >= min_ttc_seconds`` (strategy/monitor
  ``min_ttc_seconds``); below that floor ATS **skips** probability and ask-floor stops (final
  minutes ride to expiry). When eligible: **stop_loss_floor** (``_try_stop_loss_ask_floor``) then
  **probability** vs ``current_probability``. Verification deferral not modeled.
  Otherwise **expiration** at ``market_result`` payoff (``close_method=expiration``).

- Bankroll / sizing: allocation = ``bankroll * allocation_pct / 100``; integer contracts capped by
  premium + open taker fee (``trade_manager.estimate_kalshi_taker_fee``).

- **Trade report** (JSON): ``trade`` object and top-level mirrors include entry/exit bar timestamps
  (Eastern-naive bar end per ``backtest`` contract), side, contracts, premium, fees, total cost at
  open, proceeds at close, close method, PnL / return. ``ret_pct`` = ``100 * pnl / ret_pct_reference_balance``
  when that argument is set, else ``100 * pnl / bankroll_start`` (stored trade ``ret_pct`` semantics);
  ``return_on_notional_pct`` = ``100 * pnl / notional_entry``.
  ``win_loss`` = economic (PnL sign); ``win_loss_from_settlement`` = W/L if only ``market_result`` vs side mattered at expiry; ``win_loss_confirmed`` = those agree when result is known.

This is a v1 harness; expand stop/settlement parity with ``active_trade_supervisor`` gradually.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Mapping, Optional

from scripts.backtest.helpers.hypothetical_trades import estimate_kalshi_taker_fee
from backend.util.auto_entry_htc_gates import (
    evaluate_hourly_htc_strike_entry,
    format_strike_label,
)
from datetime import datetime

from zoneinfo import ZoneInfo

from scripts.backtest.helpers.backtest_strike_span import implied_no_ask_min_max_from_yes_ask_bar
from scripts.backtest.helpers.htc_aes_replay import infer_contract_market_from_kalshi_ticker
from scripts.backtest.helpers.kalshi_candles_1m import (
    qualified_backtest_candles_table,
    resolve_floor_strike_and_market_result,
)
from scripts.backtest.helpers.tick_backtest_build import tick_backtest_relname

_EASTERN = ZoneInfo("America/New_York")
# US Eastern legal time (EST/EDT via DST). All replay clock strings use this IANA zone.


def serialize_tick_row_for_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """JSON-friendly dict from a tick / strike-shaped DB row (for sweep inserts and debugging)."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            if v.tzinfo is None:
                out[k] = v.isoformat()
            else:
                out[k] = v.astimezone(_EASTERN).isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def _eastern_naive_iso(ts: Any) -> Optional[str]:
    """Wall-clock time in America/New_York as a naive ISO string (no ``Z``); used for ``*_et_naive`` fields."""
    if ts is None:
        return None
    if not isinstance(ts, datetime):
        return str(ts)
    if ts.tzinfo is None:
        return ts.isoformat()
    return ts.astimezone(_EASTERN).replace(tzinfo=None).isoformat()


def _eastern_offset_iso(ts: Any) -> Optional[str]:
    """ISO-8601 with numeric offset in America/New_York (unambiguous EST vs EDT)."""
    if ts is None or not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=_EASTERN).isoformat()
    return ts.astimezone(_EASTERN).isoformat()


def _epoch_unix_utc(ts: Any) -> Optional[int]:
    """UTC epoch seconds for the instant; naive datetimes are interpreted as Eastern wall time."""
    if ts is None or not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return int(ts.replace(tzinfo=_EASTERN).timestamp())
    return int(ts.timestamp())


def infer_strategy_list_name_for_kalshi_ticker(market_ticker: str) -> str:
    """Default ``users.strategy_list_*``.``name`` for replay: 15m vs hourly HTC."""
    return (
        "15m HTC"
        if infer_contract_market_from_kalshi_ticker(market_ticker) == "15m"
        else "Hourly HTC"
    )


def fetch_monitor_auto_entry_settings(conn: Any, *, monitor_table: str, monitor_id: int) -> dict[str, Any]:
    """Mirror ``get_auto_entry_settings`` shape using ``users.monitor_list_<user>`` (no AES context)."""
    if not re.fullmatch(r"monitor_list_[0-9]+", monitor_table):
        raise ValueError(f"invalid monitor table: {monitor_table!r}")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT min_probability, max_probability, min_differential, max_differential,
                   min_time, max_time, allow_re_entry,
                   spike_alert_enabled, spike_alert_momentum_threshold,
                   spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                   min_volume, momentum_scalp_entry_threshold, min_ask, max_ask, max_price_spread,
                   prob_adj, min_cooldown_timer, max_cooldown_timer, min_ask_range,
                   current_probability, stop_loss_price, min_ttc_seconds
            FROM users.{monitor_table}
            WHERE id = %s
            """,
            (monitor_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"no monitor row id={monitor_id} in users.{monitor_table}")
        strategy_result = row
    return {
        "min_probability": float(strategy_result[0]) if strategy_result[0] is not None else 95.0,
        "max_probability": float(strategy_result[1]) if strategy_result[1] is not None else 100.0,
        "min_differential": float(strategy_result[2]) if strategy_result[2] is not None else None,
        "max_differential": float(strategy_result[3]) if strategy_result[3] is not None else None,
        "min_time": strategy_result[4],
        "max_time": strategy_result[5],
        "allow_re_entry": strategy_result[6],
        "spike_alert_enabled": strategy_result[7],
        "spike_alert_momentum_threshold": strategy_result[8],
        "spike_alert_cooldown_threshold": strategy_result[9],
        "spike_alert_cooldown_minutes": strategy_result[10],
        "min_volume": strategy_result[11],
        "momentum_scalp_entry_threshold": float(strategy_result[12]) if strategy_result[12] is not None else None,
        "min_ask": float(strategy_result[13]) if strategy_result[13] is not None else 0.0000,
        "max_ask": float(strategy_result[14]) if strategy_result[14] is not None else 0.9800,
        "max_price_spread": float(strategy_result[15]) if strategy_result[15] is not None else 0.0300,
        "prob_adj": float(strategy_result[16]) if strategy_result[16] is not None else 5.00,
        "min_cooldown_timer": strategy_result[17],
        "max_cooldown_timer": strategy_result[18],
        "min_ask_range": float(strategy_result[19]) if strategy_result[19] is not None else None,
        "current_probability": strategy_result[20],
        "stop_loss_price": float(strategy_result[21]) if strategy_result[21] is not None else 0.0,
        "min_ttc_seconds": strategy_result[22],
    }


def fetch_monitor_trade_meta(conn: Any, *, monitor_table: str, monitor_id: int) -> dict[str, Any]:
    """Strategy / symbol / market / display name / multiplier for labeling synthetic sweep trades."""
    if not re.fullmatch(r"monitor_list_[0-9]+", monitor_table):
        raise ValueError(f"invalid monitor table: {monitor_table!r}")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT strategy, market, symbol, name, multiplier
            FROM users.{monitor_table}
            WHERE id = %s
            """,
            (monitor_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"no monitor row id={monitor_id} in users.{monitor_table}")
    return {
        "trade_strategy": row[0] or "15m HTC",
        "market": row[1] or "15m",
        "symbol": row[2] or "",
        "monitor_name": row[3] or "",
        "multiplier": float(row[4]) if row[4] is not None else 1.0,
    }


def fetch_strategy_auto_entry_settings(
    conn: Any, *, strategy_table: str, strategy_name: str
) -> dict[str, Any]:
    """Same shape as ``fetch_monitor_auto_entry_settings`` from ``users.strategy_list_<user>``."""
    if not re.fullmatch(r"strategy_list_[0-9]+", strategy_table):
        raise ValueError(f"invalid strategy table: {strategy_table!r}")
    name = (strategy_name or "").strip()
    if not name:
        raise ValueError("strategy_name is required")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT min_probability, max_probability, min_differential, max_differential,
                   min_time, max_time, allow_re_entry,
                   spike_alert_enabled, spike_alert_momentum_threshold,
                   spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                   min_volume, momentum_scalp_entry_threshold, min_ask, max_ask, max_price_spread,
                   prob_adj, min_cooldown_timer, max_cooldown_timer, min_ask_range,
                   current_probability, stop_loss_price, min_ttc_seconds
            FROM users.{strategy_table}
            WHERE LOWER(name) = LOWER(%s)
            LIMIT 1
            """,
            (name,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"no strategy {name!r} in users.{strategy_table}")
        strategy_result = row
    return {
        "min_probability": float(strategy_result[0]) if strategy_result[0] is not None else 95.0,
        "max_probability": float(strategy_result[1]) if strategy_result[1] is not None else 100.0,
        "min_differential": float(strategy_result[2]) if strategy_result[2] is not None else None,
        "max_differential": float(strategy_result[3]) if strategy_result[3] is not None else None,
        "min_time": strategy_result[4],
        "max_time": strategy_result[5],
        "allow_re_entry": strategy_result[6],
        "spike_alert_enabled": strategy_result[7],
        "spike_alert_momentum_threshold": strategy_result[8],
        "spike_alert_cooldown_threshold": strategy_result[9],
        "spike_alert_cooldown_minutes": strategy_result[10],
        "min_volume": strategy_result[11],
        "momentum_scalp_entry_threshold": float(strategy_result[12]) if strategy_result[12] is not None else None,
        "min_ask": float(strategy_result[13]) if strategy_result[13] is not None else 0.0000,
        "max_ask": float(strategy_result[14]) if strategy_result[14] is not None else 0.9800,
        "max_price_spread": float(strategy_result[15]) if strategy_result[15] is not None else 0.0300,
        "prob_adj": float(strategy_result[16]) if strategy_result[16] is not None else 5.00,
        "min_cooldown_timer": strategy_result[17],
        "max_cooldown_timer": strategy_result[18],
        "min_ask_range": float(strategy_result[19]) if strategy_result[19] is not None else None,
        "current_probability": strategy_result[20],
        "stop_loss_price": float(strategy_result[21]) if strategy_result[21] is not None else 0.0,
        "min_ttc_seconds": strategy_result[22],
    }


def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _bar_timing(row: Mapping[str, Any]) -> dict[str, Any]:
    """Bar time in America/New_York; ``timestamp`` may be naive (Eastern) or timestamptz from Postgres."""
    ts = row.get("timestamp")
    eps = row.get("end_period_ts")
    ep: Optional[int] = None
    if eps is not None:
        try:
            ep = int(eps)
        except (TypeError, ValueError):
            ep = None
    if ep is None and ts is not None:
        ep = _epoch_unix_utc(ts)
    return {
        "bar_timestamp_et_naive": _eastern_naive_iso(ts),
        "bar_timestamp_eastern_iso": _eastern_offset_iso(ts),
        "end_period_ts": ep,
    }


def _mid(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return (float(a) + float(b)) / 2.0


def _opposite_ask_high_for_stop_floor(row: Mapping[str, Any], side: str) -> Optional[float]:
    """
    Opposite-side **ask** (dollars) for ``stop_loss_floor`` (cf. ``current_close_price`` in supervisor):
    YES position → NO ask; NO position → YES ask. Uses bar highs consistent with conservative replay.
    """
    s = (side or "").strip().lower()
    if s == "yes":
        return conservative_no_ask_dollars(row)
    if s == "no":
        return _f(row.get("yes_ask_high_dollars"))
    return None


def conservative_no_ask_dollars(row: Mapping[str, Any]) -> Optional[float]:
    """
    Executable NO ask (dollars) for replay. Prefer an explicit column if present; else
    ``1 - yes_ask_low`` envelope high from YES ask OHLC (matches strike-span implied NO ask).
    """
    explicit = _f(row.get("no_ask_high_dollars"))
    if explicit is not None and explicit > 0:
        return explicit
    ya_lo = _f(row.get("yes_ask_low_dollars"))
    ya_hi = _f(row.get("yes_ask_high_dollars"))
    _n_min, n_max = implied_no_ask_min_max_from_yes_ask_bar(ya_lo, ya_hi)
    return n_max


def backtest_row_to_strike_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    """Shape ``evaluate_hourly_htc_strike_entry`` expects (ladder row analog)."""
    yp_lo = _f(row.get("yes_prob_15m_min"))
    yp_hi = _f(row.get("yes_prob_15m_max"))
    np_lo = _f(row.get("no_prob_15m_min"))
    np_hi = _f(row.get("no_prob_15m_max"))
    active = (row.get("active_side") or "").strip().lower()
    if active == "yes":
        prob_mid = _mid(yp_lo, yp_hi)
        ydiff = _mid(_f(row.get("yes_diff_min")), _f(row.get("yes_diff_max")))
        ndiff = _mid(_f(row.get("no_diff_min")), _f(row.get("no_diff_max")))
    elif active == "no":
        prob_mid = _mid(np_lo, np_hi)
        ydiff = _mid(_f(row.get("yes_diff_min")), _f(row.get("yes_diff_max")))
        ndiff = _mid(_f(row.get("no_diff_min")), _f(row.get("no_diff_max")))
    else:
        prob_mid = _mid(yp_lo, yp_hi)
        ydiff = _mid(_f(row.get("yes_diff_min")), _f(row.get("yes_diff_max")))
        ndiff = _mid(_f(row.get("no_diff_min")), _f(row.get("no_diff_max")))

    vol = _f(row.get("volume_fp"))
    out: dict[str, Any] = {
        "strike": row.get("floor_strike"),
        "probability": prob_mid,
        "yes_ask_dollars": _f(row.get("yes_ask_high_dollars")),
        "no_ask_dollars": conservative_no_ask_dollars(row),
        "yes_diff": ydiff,
        "no_diff": ndiff,
        "active_side": row.get("active_side"),
        "volume": int(vol) if vol is not None else 0,
        "ticker": row.get("market_ticker"),
    }
    yd_lo, yd_hi = _f(row.get("yes_diff_min")), _f(row.get("yes_diff_max"))
    if yd_lo is not None and yd_hi is not None:
        out["yes_diff_min"] = float(min(yd_lo, yd_hi))
        out["yes_diff_max"] = float(max(yd_lo, yd_hi))
    nd_lo, nd_hi = _f(row.get("no_diff_min")), _f(row.get("no_diff_max"))
    if nd_lo is not None and nd_hi is not None:
        out["no_diff_min"] = float(min(nd_lo, nd_hi))
        out["no_diff_max"] = float(max(nd_lo, nd_hi))
    # Span-aware probability band (live ladder uses a single lookup prob; backtest rows have min/max).
    if active == "yes" and yp_lo is not None and yp_hi is not None:
        out["probability_min"] = float(min(yp_lo, yp_hi))
        out["probability_max"] = float(max(yp_lo, yp_hi))
    elif active == "no" and np_lo is not None and np_hi is not None:
        out["probability_min"] = float(min(np_lo, np_hi))
        out["probability_max"] = float(max(np_lo, np_hi))
    return out


def _volume_fp_to_int(volume_fp: Any) -> int:
    if volume_fp is None:
        return 0
    s = str(volume_fp).strip().replace(",", "")
    if not s:
        return 0
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def tick_backtest_row_to_strike_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    """
    Map a ``backtest.tick_backtest_*`` row (strike-table-shaped, one row per second) to the
    ``strike`` dict expected by ``evaluate_hourly_htc_strike_entry`` (point values, no min/max span).
    """
    prob = _f(row.get("probability_15m"))
    yd = _f(row.get("yes_ask_dollars"))
    nd = _f(row.get("no_ask_dollars"))
    ydiff = _f(row.get("yes_diff"))
    ndiff = _f(row.get("no_diff"))
    out: dict[str, Any] = {
        "strike": row.get("strike"),
        "probability": prob,
        "yes_ask_dollars": yd,
        "no_ask_dollars": nd,
        "yes_diff": ydiff,
        "no_diff": ndiff,
        "active_side": row.get("active_side"),
        "volume": _volume_fp_to_int(row.get("volume_fp")),
        "ticker": row.get("ticker"),
    }
    return out


def _bar_timing_tick_row(row: Mapping[str, Any]) -> dict[str, Any]:
    ts = row.get("timestamp")
    ep = _epoch_unix_utc(ts)
    return {
        "bar_timestamp_et_naive": _eastern_naive_iso(ts),
        "bar_timestamp_eastern_iso": _eastern_offset_iso(ts),
        "end_period_ts": ep,
    }


def _tick_opposite_ask_for_stop(row: Mapping[str, Any], side: str) -> Optional[float]:
    s = (side or "").strip().lower()
    if s == "yes":
        return _f(row.get("no_ask_dollars"))
    if s == "no":
        return _f(row.get("yes_ask_dollars"))
    return None


def _ttc_window_ok(ttc: Any, settings: Mapping[str, Any]) -> bool:
    if ttc is None or settings.get("min_time") is None or settings.get("max_time") is None:
        return False
    return int(settings["min_time"]) <= int(ttc) <= int(settings["max_time"])


def first_htc_entry_hit(
    rows: list[Any],
    settings: Mapping[str, Any],
    *,
    spike_alert_active: bool,
    gate_profile: str,
) -> Optional[tuple[int, dict[str, Any]]]:
    """
    First bar that passes tradeable + AES; returns ``(entry_i, payload)`` with ``buy_price`` set.
    """
    for i, row in enumerate(rows):
        if not row.get("minute_tradeable", True):
            continue
        active = (row.get("active_side") or "").strip().lower()
        if active not in ("yes", "no"):
            continue
        ttc = row.get("ttc_15m_close_seconds")
        if not _ttc_window_ok(ttc, settings):
            continue
        strike = backtest_row_to_strike_mapping(row)
        pay, _reason = evaluate_hourly_htc_strike_entry(
            settings,
            strike,
            spike_alert_active=spike_alert_active,
            gate_profile=gate_profile,  # type: ignore[arg-type]
        )
        if pay is None:
            continue
        side = pay["side"]
        if side == "yes":
            buy_high = _f(row.get("yes_ask_high_dollars"))
        else:
            buy_high = conservative_no_ask_dollars(row)
        if buy_high is None or buy_high <= 0:
            continue
        pay = dict(pay)
        pay["buy_price"] = float(buy_high)
        return i, pay
    return None


def first_htc_entry_hit_tick(
    rows: list[Any],
    settings: Mapping[str, Any],
    *,
    spike_alert_active: bool,
    gate_profile: str,
) -> Optional[tuple[int, dict[str, Any]]]:
    """
    AES scan: chronological tick rows with ``ttc_15m`` (strike-table replay), same gates as 1m bars.
    """
    for i, row in enumerate(rows):
        active = (row.get("active_side") or "").strip().lower()
        if active not in ("yes", "no"):
            continue
        ttc = row.get("ttc_15m")
        if not _ttc_window_ok(ttc, settings):
            continue
        strike = tick_backtest_row_to_strike_mapping(row)
        pay, _reason = evaluate_hourly_htc_strike_entry(
            settings,
            strike,
            spike_alert_active=spike_alert_active,
            gate_profile=gate_profile,  # type: ignore[arg-type]
        )
        if pay is None:
            continue
        side = pay["side"]
        if side == "yes":
            buy_high = _f(row.get("yes_ask_dollars"))
        else:
            buy_high = _f(row.get("no_ask_dollars"))
        if buy_high is None or buy_high <= 0:
            continue
        pay = dict(pay)
        pay["buy_price"] = float(buy_high)
        return i, pay
    return None


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


def _settlement_price(side: str, market_result: Optional[str]) -> float:
    mr = (market_result or "").strip().upper()
    if side == "yes":
        return 1.0 if mr == "YES" else 0.0
    if side == "no":
        return 1.0 if mr == "NO" else 0.0
    return 0.0


def run_htc_single_market_replay(
    conn: Any,
    *,
    market_ticker: str,
    bankroll: float,
    allocation_pct: float,
    entry_settings: Mapping[str, Any],
    entry_settings_source: str,
    replay_user: str = "0001",
    strategy_name: Optional[str] = None,
    monitor_id: Optional[int] = None,
    spike_alert_active: bool = False,
    gate_profile: str = "full",
    allocation_dollars_override: Optional[float] = None,
    contracts_cap: Optional[int] = None,
    ret_pct_reference_balance: Optional[float] = None,
    from_tick_table: bool = False,
) -> dict[str, Any]:
    settings = entry_settings
    u = str(replay_user).strip()
    if not re.fullmatch(r"[0-9]+", u):
        raise ValueError(f"invalid replay_user (digits only): {replay_user!r}")

    if from_tick_table:
        rel = tick_backtest_relname(market_ticker)
        fq = f"backtest.{rel}"
    else:
        fq = qualified_backtest_candles_table(market_ticker)
    _provenance = {
        "entry_settings_source": entry_settings_source,
        "replay_user": u,
        "strategy_name": strategy_name,
        "monitor_id": monitor_id,
        "replay_source": "tick_backtest" if from_tick_table else "backtest_1m",
        "time_zone": "America/New_York",
    }

    from psycopg2 import extras

    with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        if from_tick_table:
            cur.execute(f'SELECT * FROM {fq} ORDER BY "timestamp" ASC')
        else:
            cur.execute(f"SELECT * FROM {fq} ORDER BY end_period_ts ASC")
        rows = cur.fetchall()

    if not rows:
        out = {"ok": True, "no_trade": True, "reason": "no_backtest_rows", "table": fq}
        out.update({k: v for k, v in _provenance.items() if v is not None})
        return out

    if from_tick_table:
        hit = first_htc_entry_hit_tick(
            rows,
            settings,
            spike_alert_active=spike_alert_active,
            gate_profile=gate_profile,
        )
    else:
        hit = first_htc_entry_hit(
            rows,
            settings,
            spike_alert_active=spike_alert_active,
            gate_profile=gate_profile,
        )
    if hit is None:
        entry_i = None
        payload = None
    else:
        entry_i, payload = hit

    if entry_i is None or payload is None:
        out = {
            "ok": True,
            "no_trade": True,
            "reason": "no_entry_signal",
            "table": fq,
            "rows": len(rows),
        }
        out.update({k: v for k, v in _provenance.items() if v is not None})
        return out

    side = str(payload["side"])
    buy_price = float(payload["buy_price"])
    if allocation_dollars_override is not None:
        allocation = float(allocation_dollars_override)
    else:
        allocation = float(bankroll) * float(allocation_pct) / 100.0
    contracts = _contracts_for_allocation(buy_price, allocation)
    if contracts_cap is not None:
        try:
            cap_i = int(contracts_cap)
            if cap_i >= 1:
                contracts = min(contracts, cap_i)
        except (TypeError, ValueError):
            pass
    if contracts <= 0:
        out = {
            "ok": True,
            "no_trade": True,
            "reason": "zero_contracts_after_sizing",
            "allocation_dollars": allocation,
            "buy_price": buy_price,
        }
        out.update({k: v for k, v in _provenance.items() if v is not None})
        return out

    open_fee = estimate_kalshi_taker_fee(contracts, buy_price)

    raw_cp = settings.get("current_probability")
    stop_prob_threshold = 40.0 if raw_cp is None else float(raw_cp)

    try:
        min_ttc_stop = int(settings.get("min_ttc_seconds") or 0)
    except (TypeError, ValueError):
        min_ttc_stop = 0

    try:
        stop_floor = float(settings.get("stop_loss_price") or 0.0)
    except (TypeError, ValueError):
        stop_floor = 0.0
    stop_floor = max(0.0, min(stop_floor, 0.99))

    if from_tick_table:
        _, mr_resolve, _src = resolve_floor_strike_and_market_result(market_ticker)
        market_result = mr_resolve
    else:
        market_result = rows[-1].get("market_result")
    exit_i = len(rows) - 1
    sell_price: float
    close_method = "expiration"
    stopped = False

    if from_tick_table:
        for j in range(entry_i + 1, len(rows)):
            r = rows[j]
            ttc = r.get("ttc_15m")
            try:
                ttc_i = int(ttc) if ttc is not None else -1
            except (TypeError, ValueError):
                ttc_i = -1
            ttc_ok_for_stops = ttc is not None and ttc_i >= min_ttc_stop

            if ttc_ok_for_stops and stop_floor > 0:
                opp = _tick_opposite_ask_for_stop(r, side)
                thresh_ask = 1.0 - stop_floor
                if opp is not None and opp > thresh_ask:
                    stopped = True
                    close_method = "auto_stop_loss_floor"
                    exit_i = j
                    if side == "yes":
                        sell_price = float(_f(r.get("yes_ask_dollars")) or 0.0)
                    else:
                        sell_price = float(_f(r.get("no_ask_dollars")) or 0.0)
                    break

            if ttc_ok_for_stops:
                if side == "yes":
                    ypv = _f(r.get("yes_prob_15m"))
                    if ypv is not None and ypv < stop_prob_threshold:
                        stopped = True
                        close_method = "auto_probability"
                        exit_i = j
                        sell_price = float(_f(r.get("yes_ask_dollars")) or 0.0)
                        break
                else:
                    npv = _f(r.get("no_prob_15m"))
                    if npv is not None and npv < stop_prob_threshold:
                        stopped = True
                        close_method = "auto_probability"
                        exit_i = j
                        sell_price = float(_f(r.get("no_ask_dollars")) or 0.0)
                        break
        else:
            close_method = "expiration"
            stopped = False
            sell_price = _settlement_price(side, str(market_result) if market_result else None)
    else:
        for j in range(entry_i + 1, len(rows)):
            r = rows[j]
            ttc = r.get("ttc_15m_close_seconds")
            try:
                ttc_i = int(ttc) if ttc is not None else -1
            except (TypeError, ValueError):
                ttc_i = -1
            ttc_ok_for_stops = ttc is not None and ttc_i >= min_ttc_stop

            if ttc_ok_for_stops and stop_floor > 0:
                opp = _opposite_ask_high_for_stop_floor(r, side)
                thresh_ask = 1.0 - stop_floor
                if opp is not None and opp > thresh_ask:
                    stopped = True
                    close_method = "auto_stop_loss_floor"
                    exit_i = j
                    if side == "yes":
                        sell_price = float(r.get("yes_price_low_dollars") or 0.0)
                    else:
                        sell_price = float(r.get("no_price_low_dollars") or 0.0)
                    break

            if ttc_ok_for_stops:
                if side == "yes":
                    ypmin = _f(r.get("yes_prob_15m_min"))
                    if ypmin is not None and ypmin < stop_prob_threshold:
                        stopped = True
                        close_method = "auto_probability"
                        exit_i = j
                        sell_price = float(r.get("yes_price_low_dollars") or 0.0)
                        break
                else:
                    npmin = _f(r.get("no_prob_15m_min"))
                    if npmin is not None and npmin < stop_prob_threshold:
                        stopped = True
                        close_method = "auto_probability"
                        exit_i = j
                        sell_price = float(r.get("no_price_low_dollars") or 0.0)
                        break
        else:
            close_method = "expiration"
            stopped = False
            sell_price = _settlement_price(side, str(market_result) if market_result else None)

    if sell_price < 0:
        sell_price = 0.0
    if sell_price > 1.0:
        sell_price = 1.0

    close_fee = estimate_kalshi_taker_fee(contracts, sell_price) if 0 < sell_price < 1 else 0.0
    gross = contracts * (sell_price - buy_price)
    pnl = gross - open_fee - close_fee
    notional = contracts * buy_price + open_fee
    ref_bal = float(ret_pct_reference_balance) if ret_pct_reference_balance is not None else float(bankroll)
    ret_pct = (pnl / ref_bal * 100.0) if ref_bal > 0 else 0.0
    return_on_notional_pct = (pnl / notional * 100.0) if notional > 0 else 0.0
    econ_wl = "W" if pnl > 0 else ("D" if pnl == 0 else "L")
    mr = (market_result or "").strip().upper()
    side_u = side.upper()
    won_re = (side_u == "YES" and mr == "YES") or (side_u == "NO" and mr == "NO")
    if mr in ("YES", "NO"):
        settlement_wl: str = "W" if won_re else "L"
    else:
        settlement_wl = "unknown"
    win_loss_confirmed: Optional[bool]
    if mr in ("YES", "NO"):
        win_loss_confirmed = econ_wl == settlement_wl  # economic W/L vs settlement W/L for our side
    else:
        win_loss_confirmed = None

    er = rows[entry_i]
    raw_sl = payload.get("strike") or er.get("floor_strike") or er.get("strike")
    strike_label = format_strike_label(raw_sl, market_ticker)
    entry_row = er
    exit_row = rows[exit_i]

    notional_r = round(float(notional), 2)
    premium_r = round(float(contracts * buy_price), 2)
    fees_total_r = round(float(open_fee + close_fee), 2)
    proceeds_r = round(float(contracts * sell_price), 2)
    pnl_r = round(float(pnl), 2)
    ret_r = round(float(ret_pct), 4)
    ret_notional_r = round(float(return_on_notional_pct), 4)
    if from_tick_table:
        entry_t = _bar_timing_tick_row(entry_row)
        exit_t = _bar_timing_tick_row(exit_row)
    else:
        entry_t = _bar_timing(entry_row)
        exit_t = _bar_timing(exit_row)
    trade_one_liner = (
        f"{side_u} x{contracts} {market_ticker} strike={strike_label} "
        f"@ {buy_price:.4f} → {sell_price:.4f}"
    )
    summary = (
        f"{trade_one_liner} | entry={entry_t.get('bar_timestamp_et_naive')} "
        f"exit={exit_t.get('bar_timestamp_et_naive')} | close={close_method} "
        f"pnl={pnl_r} ret_pct={ret_r}% econ_wl={econ_wl} settlement_wl={settlement_wl} "
        f"confirmed={win_loss_confirmed}"
    )

    trade_block = {
        "description": trade_one_liner,
        "ticker": market_ticker,
        "strike_label": strike_label,
        "side": side_u,
        "contracts": contracts,
        "entry": {
            **entry_t,
            "bar_index": entry_i,
            "price_dollars_per_contract": round(buy_price, 6),
            "premium_dollars": premium_r,
            "open_fee_dollars": round(float(open_fee), 2),
            "total_cost_dollars": notional_r,
        },
        "exit": {
            **exit_t,
            "bar_index": exit_i,
            "price_dollars_per_contract": round(sell_price, 6),
            "proceeds_dollars": proceeds_r,
            "close_fee_dollars": round(float(close_fee), 2),
            "close_method": close_method,
            "stopped_early": stopped,
        },
        "fees_total_dollars": fees_total_r,
        "pnl_dollars": pnl_r,
        "return_on_bankroll_pct": ret_r,
        "return_on_notional_pct": ret_notional_r,
        "win_loss": econ_wl,
        "win_loss_from_settlement": settlement_wl,
        "win_loss_confirmed": win_loss_confirmed,
        "market_result": market_result,
    }

    entry_tick_payload = serialize_tick_row_for_payload(entry_row) if from_tick_table else None
    exit_tick_payload = serialize_tick_row_for_payload(exit_row) if from_tick_table else None

    out = {
        "ok": True,
        "no_trade": False,
        "table": fq,
        "bankroll_start": bankroll,
        "allocation_dollars": allocation,
        "allocation_pct": allocation_pct,
        "contracts": contracts,
        "position_contracts": contracts,
        "premium_dollars": premium_r,
        "notional_entry_dollars": notional_r,
        "fees_total_dollars": fees_total_r,
        "proceeds_dollars": proceeds_r,
        "side": side,
        "strike_label": strike_label,
        "ticker": market_ticker,
        "entry_bar_index": entry_i,
        "exit_bar_index": exit_i,
        "entry_timestamp_et_naive": entry_t.get("bar_timestamp_et_naive"),
        "exit_timestamp_et_naive": exit_t.get("bar_timestamp_et_naive"),
        "entry_timestamp_eastern_iso": entry_t.get("bar_timestamp_eastern_iso"),
        "exit_timestamp_eastern_iso": exit_t.get("bar_timestamp_eastern_iso"),
        "entry_end_period_ts": entry_t.get("end_period_ts"),
        "exit_end_period_ts": exit_t.get("end_period_ts"),
        "buy_price": buy_price,
        "sell_price": sell_price,
        "open_fee": round(float(open_fee), 2),
        "close_fee": round(float(close_fee), 2),
        "pnl": pnl_r,
        "pnl_dollars": pnl_r,
        "ret_pct": ret_r,
        "ret_pct_reference_balance": ref_bal,
        "return_on_notional_pct": ret_notional_r,
        "win_loss": econ_wl,
        "win_loss_from_settlement": settlement_wl,
        "close_method": close_method,
        "stopped": stopped,
        "market_result": market_result,
        "win_loss_confirmed": win_loss_confirmed,
        "trade": trade_block,
        "replay_summary": summary,
        "entry_tick_row": entry_tick_payload,
        "exit_tick_row": exit_tick_payload,
    }
    out.update({k: v for k, v in _provenance.items() if v is not None})
    return out
