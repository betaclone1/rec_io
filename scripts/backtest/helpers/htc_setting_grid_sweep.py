"""
Cartesian **monitor-setting grid** over many archived markets: for each combination of overrides
(``max_time``, ``min_probability``, ``stop_loss_price``, …), replay HTC on **tick_backtest_*** tables
built from ``historical_data.strike_table_master`` slices and aggregate PnL / win rate.

Used by ``scripts/backtest/htc_archive_setting_sweep.py``. See ``docs/BACKTESTING.md`` §5.6.
"""

from __future__ import annotations

import itertools
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from scripts.backtest.helpers.grid_sweep_trades import (
    grid_sweep_trades_table_ready,
    insert_grid_sweep_trade,
)
from scripts.backtest.helpers.htc_backtest_replay import (
    fetch_monitor_auto_entry_settings,
    fetch_monitor_trade_meta,
    run_htc_single_market_replay,
)
from scripts.backtest.helpers.tick_backtest_build import build_tick_backtest_from_strike_archive


def parse_int_range_hi_lo_step(spec: str) -> list[int]:
    """
    ``HI:LO:STEP`` integers: start at HI, subtract STEP until below LO (both ends inclusive).

    Example: ``900:120:60`` → [900, 840, …, 120] (15m down to 2m in 1m steps as **seconds**).
    """
    parts = str(spec).strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"expected HI:LO:STEP integers, got {spec!r}")
    hi, lo, step = int(parts[0]), int(parts[1]), int(parts[2])
    if step <= 0:
        raise ValueError("STEP must be positive")
    if hi < lo:
        raise ValueError("HI must be >= LO")
    out: list[int] = []
    x = hi
    while x >= lo:
        out.append(x)
        x -= step
    return out


def parse_float_range_lo_hi_step(spec: str) -> list[float]:
    """``LO:HI:STEP`` inclusive on LO and HI (upward), STEP positive (e.g. ``85:95:1`` or ``0.15:0.25:0.01``)."""
    parts = str(spec).strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"expected LO:HI:STEP, got {spec!r}")
    lo, hi, step = float(parts[0]), float(parts[1]), float(parts[2])
    if step <= 0:
        raise ValueError("STEP must be positive")
    if lo > hi:
        raise ValueError("LO must be <= HI")
    out: list[float] = []
    x = lo
    n = 0
    while x <= hi + 1e-9 and n < 100000:
        out.append(round(x, 8))
        x += step
        n += 1
    return out


def discover_markets_in_archive_window(
    conn: Any,
    *,
    timestamp_start: datetime,
    timestamp_end_exclusive: datetime,
    series_prefix: Optional[str] = None,
    min_archive_rows: int = 1,
) -> list[str]:
    """Distinct ``market_ticker`` values with at least ``min_archive_rows`` in the window, ordered by first tick."""
    mp = (series_prefix or "").strip()
    having = " HAVING COUNT(*) >= %s"
    base_params: list[Any] = [timestamp_start, timestamp_end_exclusive]
    if mp:
        sql = (
            """
            SELECT market_ticker, MIN("timestamp") AS mn
            FROM historical_data.strike_table_master
            WHERE "timestamp" >= %s AND "timestamp" < %s
              AND market_ticker LIKE %s
            GROUP BY market_ticker
            """
            + having
            + """
            ORDER BY mn ASC
            """
        )
        params = list(base_params) + [f"{mp}%", min_archive_rows]
    else:
        sql = (
            """
            SELECT market_ticker, MIN("timestamp") AS mn
            FROM historical_data.strike_table_master
            WHERE "timestamp" >= %s AND "timestamp" < %s
            GROUP BY market_ticker
            """
            + having
            + """
            ORDER BY mn ASC
            """
        )
        params = list(base_params) + [min_archive_rows]
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return [r[0] for r in cur.fetchall()]


def discover_markets_for_contract_cycle(
    conn: Any,
    *,
    contract_symbol: str,
    contract_cadence: str,
    contract_date_et: str,
    contract_hour_et: int,
) -> list[str]:
    """
    Discover all strike markets for one exact ET contract cycle.

    For hourly contracts this means one ET hour close (e.g. BTC 01:00 ET on date D) and
    returns all strike tickers sharing that cycle stem (e.g. ``KXBTCD-YYMONDDHH-T*``).
    """
    symbol = str(contract_symbol or "").strip().upper()
    if symbol not in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        raise ValueError(f"unsupported contract_symbol: {contract_symbol!r}")
    cadence = str(contract_cadence or "").strip().lower()
    if cadence != "hourly":
        raise ValueError("contract cycle discovery currently supports cadence=hourly only")
    try:
        d = datetime.strptime(str(contract_date_et), "%Y-%m-%d")
    except ValueError as e:
        raise ValueError("--contract-date-et must be YYYY-MM-DD") from e
    h = int(contract_hour_et)
    if h < 0 or h > 23:
        raise ValueError("--contract-hour-et must be in 0..23")

    yy = d.strftime("%y").upper()
    mon = d.strftime("%b").upper()
    dd = d.strftime("%d")
    hh = f"{h:02d}"
    prefix = f"KX{symbol}D-{yy}{mon}{dd}{hh}-T"

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT market_ticker, MIN("timestamp") AS mn
            FROM historical_data.strike_table_master
            WHERE market_ticker LIKE %s
            GROUP BY market_ticker
            ORDER BY mn ASC, market_ticker ASC
            """,
            (f"{prefix}%",),
        )
        out = [r[0] for r in cur.fetchall()]

    # Defensive: keep only exact cycle stem match (ignore similarly prefixed noise).
    stem = re.compile(rf"^KX{symbol}D-{yy}{mon}{dd}{hh}-T")
    return [t for t in out if stem.match(str(t))]


def _materialize_ticks(
    conn: Any,
    tickers: Sequence[str],
    *,
    timestamp_start: datetime,
    timestamp_end_exclusive: datetime,
) -> dict[str, int]:
    """Build window-sliced tick tables; return ticker → rows inserted."""
    out: dict[str, int] = {}
    for t in tickers:
        r = build_tick_backtest_from_strike_archive(
            conn,
            t,
            truncate=True,
            timestamp_start=timestamp_start,
            timestamp_end_exclusive=timestamp_end_exclusive,
        )
        out[t] = int(r.get("rows_inserted") or 0)
    return out


def _replay_one_market(
    conn: Any,
    market_ticker: str,
    *,
    bankroll: float,
    ret_pct_reference_balance: Optional[float],
    allocation_pct: float,
    entry_settings: Mapping[str, Any],
    replay_user: str,
    monitor_id: int,
    gate_profile: str,
    spike_alert_active: bool,
) -> dict[str, Any]:
    return run_htc_single_market_replay(
        conn,
        market_ticker=market_ticker,
        bankroll=float(bankroll),
        allocation_pct=float(allocation_pct),
        entry_settings=dict(entry_settings),
        entry_settings_source="monitor_list",
        replay_user=str(replay_user),
        monitor_id=int(monitor_id),
        spike_alert_active=bool(spike_alert_active),
        gate_profile=str(gate_profile),
        ret_pct_reference_balance=ret_pct_reference_balance,
        from_tick_table=True,
    )


@dataclass
class ComboResult:
    max_time: int
    min_probability: float
    stop_loss_price: float
    synthetic_monitor_id: int
    traded_markets: int
    skipped_markets: int
    wins: int
    losses: int
    sum_pnl: float
    sum_ret_pct: float
    final_equity: float
    compound: bool

    def objective(self, name: str) -> float:
        n = self.traded_markets
        if name == "sum_pnl":
            return self.sum_pnl
        if name == "mean_pnl":
            return self.sum_pnl / n if n else float("-inf")
        if name == "win_rate":
            return self.wins / n if n else float("-inf")
        if name == "sum_ret_pct":
            return self.sum_ret_pct
        raise ValueError(f"unknown objective {name!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_time": self.max_time,
            "min_probability": self.min_probability,
            "stop_loss_price": self.stop_loss_price,
            "synthetic_monitor_id": self.synthetic_monitor_id,
            "traded_markets": self.traded_markets,
            "skipped_markets": self.skipped_markets,
            "wins": self.wins,
            "losses": self.losses,
            "sum_pnl": round(self.sum_pnl, 4),
            "sum_ret_pct": round(self.sum_ret_pct, 6),
            "win_rate": (self.wins / self.traded_markets) if self.traded_markets else None,
            "final_equity": round(self.final_equity, 4),
            "compound": self.compound,
        }


def run_setting_grid_sweep(
    conn: Any,
    *,
    tickers: Sequence[str],
    timestamp_start: datetime,
    timestamp_end_exclusive: datetime,
    monitor_table: str,
    monitor_id: int,
    replay_user: str,
    bankroll: float,
    allocation_pct: float,
    max_time_values: Sequence[int],
    min_probability_values: Sequence[float],
    stop_loss_price_values: Sequence[float],
    gate_profile: str = "full",
    spike_alert_active: bool = False,
    materialize_ticks: bool = True,
    compound: bool = True,
    persist_trades: bool = False,
    sweep_batch_id: Optional[str] = None,
    synthetic_monitor_id_base: int = 9_000_000,
    progress: Optional[Callable[[int, int, ComboResult], None]] = None,
) -> list[ComboResult]:
    """
    Full Cartesian product of the three override lists. Base monitor row supplies all other gates.

    If ``materialize_ticks`` is True, rebuilds each ``tick_backtest_*`` slice (windowed) before the grid;
    otherwise assumes tables already match the same window.

    **Compound bankroll:** when ``compound`` is True, each market is replayed with ``bankroll`` and
    ``ret_pct`` denominator equal to **current equity** after prior closed trades in chronological
    market order. When False, every replay uses the initial ``bankroll`` and fixed allocation.

    **Persist:** with ``persist_trades``, writes one row per closed replay into
    ``backtest.grid_sweep_trades`` (requires migration). ``synthetic_monitor_id`` is
    ``synthetic_monitor_id_base + combo_index``; ``sweep_batch_id`` groups one CLI run.
    """
    if not tickers:
        return []

    if persist_trades:
        if not grid_sweep_trades_table_ready(conn):
            raise RuntimeError(
                "backtest.grid_sweep_trades missing; apply migration 20260416_1015_backtest_grid_sweep_trades"
            )
    batch_id = (sweep_batch_id or "").strip() or str(uuid.uuid4())
    trade_meta: Optional[dict[str, Any]] = None
    if persist_trades:
        trade_meta = fetch_monitor_trade_meta(conn, monitor_table=monitor_table, monitor_id=monitor_id)

    if materialize_ticks:
        _materialize_ticks(
            conn,
            tickers,
            timestamp_start=timestamp_start,
            timestamp_end_exclusive=timestamp_end_exclusive,
        )

    base = fetch_monitor_auto_entry_settings(conn, monitor_table=monitor_table, monitor_id=monitor_id)

    grid = list(
        itertools.product(max_time_values, min_probability_values, stop_loss_price_values)
    )
    total = len(grid)
    results: list[ComboResult] = []

    for idx, (mx_t, min_p, sl) in enumerate(grid):
        st = dict(base)
        st["max_time"] = int(mx_t)
        st["min_probability"] = float(min_p)
        st["stop_loss_price"] = float(sl)

        traded = skipped = wins = losses = 0
        sum_pnl = 0.0
        sum_ret = 0.0
        equity = float(bankroll)
        synth_id = int(synthetic_monitor_id_base) + int(idx)

        for tkr in tickers:
            ref_bal = float(equity) if compound else float(bankroll)
            br = ref_bal
            r = _replay_one_market(
                conn,
                tkr,
                bankroll=br,
                ret_pct_reference_balance=ref_bal if compound else None,
                allocation_pct=allocation_pct,
                entry_settings=st,
                replay_user=replay_user,
                monitor_id=monitor_id,
                gate_profile=gate_profile,
                spike_alert_active=spike_alert_active,
            )
            if r.get("no_trade"):
                skipped += 1
                continue
            traded += 1
            pnl_i = float(r.get("pnl") or r.get("pnl_dollars") or 0.0)
            sum_pnl += pnl_i
            sum_ret += float(r.get("ret_pct") or 0.0)
            if compound:
                equity += pnl_i
            wl = (r.get("win_loss") or "").strip().upper()
            if wl == "W":
                wins += 1
            elif wl == "L":
                losses += 1
            if persist_trades and trade_meta is not None:
                insert_grid_sweep_trade(
                    conn,
                    sweep_batch_id=batch_id,
                    synthetic_monitor_id=synth_id,
                    source_monitor_id=int(monitor_id),
                    replay_user=str(replay_user),
                    replay_out=r,
                    trade_meta=trade_meta,
                    reference_bankroll=ref_bal,
                )

        final_equity = float(equity) if compound else float(bankroll) + sum_pnl
        cr = ComboResult(
            max_time=int(mx_t),
            min_probability=float(min_p),
            stop_loss_price=float(sl),
            synthetic_monitor_id=synth_id,
            traded_markets=traded,
            skipped_markets=skipped,
            wins=wins,
            losses=losses,
            sum_pnl=sum_pnl,
            sum_ret_pct=sum_ret,
            final_equity=final_equity,
            compound=bool(compound),
        )
        results.append(cr)
        if progress is not None:
            progress(idx + 1, total, cr)

    return results


def rank_results(results: Iterable[ComboResult], objective: str, *, top: int = 25) -> list[ComboResult]:
    rlist = list(results)
    rlist.sort(key=lambda r: r.objective(objective), reverse=True)
    return rlist[: max(0, int(top))]
