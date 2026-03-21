"""SQL fragments for SUM/AVG/MIN/MAX/COUNT/STDDEV on trade PnL and return columns."""

from __future__ import annotations

# Trade-level column (alias t)
_TRADE_COL = {
    "ret_pct": "t.ret_pct",
    "ret_pct_base": "t.ret_pct_base",
    "pnl": "t.pnl",
}

# Per-cycle grouped column names inside cyc CTE
_CYCLE_COL = {
    "pnl": "spnl",
    "ret_pct": "sret",
    "ret_pct_base": "sretb",
}

_ALLOWED_METRICS = frozenset(_TRADE_COL)
_ALLOWED_AGGS = frozenset(("sum", "mean", "min", "max", "count", "stdev"))


def parse_metrics_list(s: str) -> list[str]:
    """Comma-separated: ret_pct, ret_pct_base, pnl, or ``all``. ``none`` disables financial stats."""
    raw = (s or "").strip().lower()
    if not raw or raw == "none":
        return []
    if raw == "all":
        return ["ret_pct", "ret_pct_base", "pnl"]
    out = [p.strip() for p in s.split(",") if p.strip()]
    for m in out:
        if m not in _ALLOWED_METRICS:
            raise ValueError(
                f"Unknown metric {m!r}; use ret_pct, ret_pct_base, pnl, or all (comma-separated)"
            )
    return out


def parse_aggs_list(s: str) -> list[str]:
    """Comma-separated: sum, mean, min, max, count, stdev."""
    raw = (s or "").strip().lower()
    if not raw:
        return []
    out = [p.strip() for p in s.split(",") if p.strip()]
    for a in out:
        if a not in _ALLOWED_AGGS:
            raise ValueError(
                f"Unknown aggregation {a!r}; use sum, mean, min, max, count, stdev (comma-separated)"
            )
    return out


def _trade_agg_expr(agg: str, col: str) -> str:
    if agg == "sum":
        return f"COALESCE(SUM({col})::double precision, 0)"
    if agg == "mean":
        return f"AVG({col})::double precision"
    if agg == "min":
        return f"MIN({col}::double precision)"
    if agg == "max":
        return f"MAX({col}::double precision)"
    if agg == "count":
        return f"(COUNT({col}) FILTER (WHERE {col} IS NOT NULL))::bigint"
    if agg == "stdev":
        return f"STDDEV_SAMP({col}::double precision)"
    raise ValueError(agg)


def build_trade_financial_select(metrics: list[str], aggs: list[str]) -> str:
    """Comma-prefixed SELECT fragments (empty if no metrics)."""
    if not metrics or not aggs:
        return ""
    parts: list[str] = []
    for m in metrics:
        col = _TRADE_COL[m]
        for a in aggs:
            parts.append(f"{_trade_agg_expr(a, col)} AS {a}_{m}")
    return ",\n            " + ",\n            ".join(parts)


def build_cycle_financial_select(metrics: list[str], aggs: list[str]) -> str:
    """Trailing SELECT list items: scalar subqueries over ``cyc`` CTE."""
    if not metrics or not aggs:
        return ""
    parts: list[str] = []
    for m in metrics:
        c = _CYCLE_COL[m]
        for a in aggs:
            inner = _cycle_agg_inner(a, c)
            parts.append(f"(SELECT {inner} FROM cyc) AS {a}_{m}")
    return ",\n            " + ",\n            ".join(parts)


def _cycle_agg_inner(agg: str, ccol: str) -> str:
    if agg == "sum":
        return f"COALESCE(SUM({ccol})::double precision, 0)"
    if agg == "mean":
        return f"AVG({ccol})::double precision"
    if agg == "min":
        return f"MIN({ccol}::double precision)"
    if agg == "max":
        return f"MAX({ccol}::double precision)"
    if agg == "count":
        return f"(COUNT({ccol}) FILTER (WHERE {ccol} IS NOT NULL))::bigint"
    if agg == "stdev":
        return f"STDDEV_SAMP({ccol}::double precision)"
    raise ValueError(agg)


def format_financial_lines(
    st: dict,
    metrics: list[str],
    aggs: list[str],
) -> list[str]:
    lines = []
    for m in metrics:
        for a in aggs:
            key = f"{a}_{m}"
            if key not in st:
                continue
            lines.append(f"    {key}: {_fmt_financial(key, st[key])}")
    return lines


def _fmt_financial(key: str, v: object) -> str:
    if v is None:
        return "n/a"
    if key.startswith("count_"):
        return str(int(v))
    if key.endswith("_pnl") or "_pnl" in key:
        return f"{float(v):.2f}"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(x) >= 1000 or abs(x) < 0.0001:
        return f"{x:.6g}"
    return f"{x:.4f}"


def financial_keys(metrics: list[str], aggs: list[str]) -> list[str]:
    return [f"{a}_{m}" for m in metrics for a in aggs]
