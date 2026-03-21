"""Composable SQL fragments and params for backtest trade queries (safety: allowlists only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence


def paper_trade_sql(alias: str, mode: str) -> str:
    """
    ``all``: no filter (paper and live).
    ``live``: exclude paper trades (same idea as read_api realized PnL).
    ``paper``: only paper trades.
    """
    m = (mode or "all").strip().lower()
    if m == "all":
        return ""
    if m == "live":
        return f"AND ({alias}.paper_trade IS NOT TRUE OR {alias}.paper_trade IS NULL)"
    if m == "paper":
        return f"AND ({alias}.paper_trade IS TRUE)"
    raise ValueError(f"paper mode must be all, live, or paper; got {mode!r}")


def open_to_next_boundary_ttc_sql(ts_expr: str, tz: str, *, grid_15m: bool) -> str:
    """
    Minutes from ``ts_expr`` (timestamptz) until the **next** market-style boundary in ``tz``:

    - **Hourly**: next top-of-hour (10:17 -> 11:00).
    - **15m**: next :00 / :15 / :30 / :45 (10:07 -> 10:15; 10:15:00 -> 10:30).
    """
    tz_esc = tz.replace("'", "''")
    et = f"({ts_expr}) AT TIME ZONE '{tz_esc}'"
    if grid_15m:
        return f"""(
          EXTRACT(EPOCH FROM (
            (
              date_trunc('hour', {et})
              + ((EXTRACT(minute FROM {et})::int / 15) + 1) * INTERVAL '15 minutes'
            ) AT TIME ZONE '{tz_esc}'
            - ({ts_expr})
          )) / 60.0
        )"""
    return f"""(
          EXTRACT(EPOCH FROM (
            ((date_trunc('hour', {et}) + INTERVAL '1 hour') AT TIME ZONE '{tz_esc}')
            - ({ts_expr})
          )) / 60.0
        )"""


def strategy_implies_15m_ttc_grid(strategy: str | None) -> bool:
    """Use 15m boundary stepping when monitor strategy mentions 15m (e.g. ``15m HTC``)."""
    if not strategy:
        return False
    s = strategy.lower()
    return "15m" in s.replace(" ", "") or "15 m" in s


# column_key -> (sql_type, sql_expression)  sql_type: numeric | text | bool
_TRADE_FILTER_COLUMNS: dict[str, tuple[str, str]] = {
    "momentum": ("numeric", "t.momentum"),
    "momentum_percentile": ("numeric", "t.momentum_percentile"),
    "movement_percentile": ("numeric", "t.movement_percentile"),
    "volatility_percentile": ("numeric", "t.volatility_percentile"),
    "volatility": ("numeric", "t.volatility"),
    "movement": ("numeric", "t.movement"),
    "buy_price": ("numeric", "t.buy_price"),
    "sell_price": ("numeric", "t.sell_price"),
    "position": ("numeric", "t.position"),
    "hour_idx": ("numeric", "t.hour_idx"),
    "weekly_cycle": ("numeric", "t.weekly_cycle"),
    "roi_pct": ("numeric", "t.roi_pct"),
    "ret_pct": ("numeric", "t.ret_pct"),
    "pnl": ("numeric", "t.pnl"),
    "prob": ("numeric", "t.prob"),
    "side": ("text", "t.side"),
    "trade_strategy": ("text", "t.trade_strategy"),
    "symbol": ("text", "t.symbol"),
    "contract": ("text", "t.contract"),
    "strike": ("text", "t.strike"),
    "status": ("text", "t.status"),
    "entry_method": ("text", "t.entry_method"),
    "close_method": ("text", "t.close_method"),
    "loss_prevention": ("bool", "t.loss_prevention"),
    "monitor_confirmed": ("bool", "t.monitor_confirmed"),
}

_FILTER_OPS_NUMERIC = {
    "eq": "=",
    "ne": "!=",
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
}

_FILTER_OPS_TEXT = {
    "eq": "=",
    "ne": "!=",
    "like": "LIKE",
    "ilike": "ILIKE",
}

_FILTER_OPS_BOOL = {
    "eq": "=",
    "ne": "!=",
}


def _parse_bool(v: str) -> bool:
    x = v.strip().lower()
    if x in ("true", "t", "1", "yes"):
        return True
    if x in ("false", "f", "0", "no"):
        return False
    raise ValueError(f"boolean filter value must be true/false; got {v!r}")


def parse_trade_filter(spec: str) -> tuple[str, Any]:
    """
    ``column:op:value`` with column in allowlist, op in eq/ne/gt/... (numeric) or eq/ne/like/ilike (text).
    Boolean columns use true/false.
    """
    m = re.match(r"^([a-zA-Z0-9_]+):([a-z]+):(.+)$", spec.strip())
    if not m:
        raise ValueError(
            f"Invalid --trade-filter {spec!r}; use column:op:value (e.g. momentum:gte:3 or side:eq:YES)"
        )
    col, op, raw_val = m.group(1).lower(), m.group(2).lower(), m.group(3)
    if col not in _TRADE_FILTER_COLUMNS:
        allowed = ", ".join(sorted(_TRADE_FILTER_COLUMNS))
        raise ValueError(f"Unknown filter column {col!r}; allowed: {allowed}")
    kind, sql_col = _TRADE_FILTER_COLUMNS[col]
    if kind == "numeric":
        if op not in _FILTER_OPS_NUMERIC:
            raise ValueError(f"Op {op!r} not allowed for numeric column {col}; use eq,ne,gt,lt,gte,lte")
        try:
            val: Any = float(raw_val)
        except ValueError as e:
            raise ValueError(f"Numeric value expected for {col}: {raw_val!r}") from e
        sym = _FILTER_OPS_NUMERIC[op]
        return f"{sql_col} {sym} %s", val
    if kind == "text":
        if op not in _FILTER_OPS_TEXT:
            raise ValueError(f"Op {op!r} not allowed for text column {col}")
        sym = _FILTER_OPS_TEXT[op]
        return f"{sql_col} {sym} %s", raw_val
    if kind == "bool":
        if op not in _FILTER_OPS_BOOL:
            raise ValueError(f"Op {op!r} not allowed for boolean column {col}")
        sym = _FILTER_OPS_BOOL[op]
        b = _parse_bool(raw_val)
        return f"{sql_col} {sym} %s", b
    raise ValueError(f"internal: unknown kind {kind}")


@dataclass
class TradeWhereParts:
    """Extra ``AND ...`` fragments after monitor + time window; trailing params only (no monitor/start/end)."""

    fragments: list[str] = field(default_factory=list)
    params: list[Any] = field(default_factory=list)

    def add_raw(self, sql_fragment: str) -> None:
        self.fragments.append(sql_fragment)

    def add_param(self, sql_fragment_with_one_placeholder: str, value: Any) -> None:
        if sql_fragment_with_one_placeholder.count("%s") != 1:
            raise ValueError("expected exactly one %s placeholder")
        self.fragments.append(sql_fragment_with_one_placeholder)
        self.params.append(value)

    def sql(self) -> str:
        return "".join(self.fragments)


def build_trade_where_parts(
    *,
    paper_mode: str,
    min_prob: float | None,
    max_prob: float | None,
    min_ttc_minutes: float | None,
    max_ttc_minutes: float | None,
    ttc_timezone: str,
    ttc_grid_15m: bool,
    trade_filters: Sequence[str],
    omit_ttc: bool = False,
) -> TradeWhereParts:
    w = TradeWhereParts()
    w.add_raw(paper_trade_sql("t", paper_mode))
    if min_prob is not None:
        w.add_param("AND t.prob IS NOT NULL AND t.prob >= %s", min_prob)
    if max_prob is not None:
        w.add_param("AND t.prob IS NOT NULL AND t.prob <= %s", max_prob)
    if not omit_ttc:
        ttc_expr = open_to_next_boundary_ttc_sql("t.created_at", ttc_timezone, grid_15m=ttc_grid_15m)
        if min_ttc_minutes is not None:
            w.add_param(f"AND ({ttc_expr}) >= %s", min_ttc_minutes)
        if max_ttc_minutes is not None:
            w.add_param(f"AND ({ttc_expr}) <= %s", max_ttc_minutes)
    for spec in trade_filters:
        frag, val = parse_trade_filter(spec)
        w.add_param(f"AND ({frag})", val)
    return w


def format_filters_for_display(
    *,
    paper_mode: str,
    min_prob: float | None,
    max_prob: float | None,
    min_ttc: float | None,
    max_ttc: float | None,
    ttc_timezone: str,
    trade_filters: Sequence[str],
) -> list[str]:
    lines = [f"paper_trade filter: {paper_mode} (default all = live + paper)"]
    if min_prob is not None or max_prob is not None:
        lines.append(f"prob: min={min_prob} max={max_prob} (DB scale 0–100, e.g. 96 for 96%)")
    if min_ttc is not None or max_ttc is not None:
        lines.append(
            f"TTC minutes (open → next boundary in {ttc_timezone}): min={min_ttc} max={max_ttc}"
        )
    if trade_filters:
        lines.append("extra trade filters: " + "; ".join(trade_filters))
    return lines
