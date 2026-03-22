#!/usr/bin/env python3
"""
Live-fill **pattern check**: does ``buy_price`` move systematically with **TTC** and **signed spot
minus strike**, within each **market segment**?

- **TTC** uses the same boundary convention as the core backtester (hourly vs **15m** grid inferred
  from ``trade_strategy``, timezone from ``--ttc-tz``).
- **Spot − strike** is ``symbol_open`` minus parsed numeric ``strike`` (same sign as stored prices:
  positive when the live spot snapshot is **above** the strike number).

Default output: coverage counts, Pearson r vs ``buy_price`` for TTC and distance, marginal **median
``buy_price``** by quantile bins, and a **joint** TTC × distance table of cell medians (sparse cells
marked ``.``).

Optional **legacy** flags still run prob/momentum OLS and holdout eval for comparison.

Use ``--paper paper`` to analyze **paper-only** rows; ``--spot-check-dual IDS`` compares peer
expected price from **live-only** vs **paper-only** training pools side by side.

**Methodology and evaluation protocol:** ``docs/BACKTEST_PRICE_ESTIMATOR.md``.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.backtest.helpers.constants import TRADES_TABLE
from scripts.backtest.helpers.db import get_connection
from scripts.backtest.helpers.filters import exclude_test_filter_sql
from scripts.backtest.helpers.hypothetical_trades import open_to_next_boundary_minutes
from scripts.backtest.helpers.trade_filters import paper_trade_sql, strategy_implies_15m_ttc_grid

# Features used for OLS and holdout eval (must be finite on each row used).
OLS_FEATURES: tuple[str, ...] = (
    "prob",
    "ttc_minutes",
    "diff_points",
    "momentum",
    "momentum_percentile",
)


def _parse_instant(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"Datetime must include a timezone offset (e.g. ...-05:00 or Z): {s!r}"
        )
    return dt


def _parse_monitors_opt(s: str | None) -> list[str] | None:
    if not s or not str(s).strip():
        return None
    parts = [p.strip() for p in str(s).split(",")]
    out = [p for p in parts if p]
    return out or None


def parse_money_field(value: Any) -> float | None:
    if value is None:
        return None
    t = str(value).strip().replace("$", "").replace(",", "")
    if not t or t.lower() in ("nan", "none", ""):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_diff_points(diff: Any) -> float | None:
    if diff is None:
        return None
    t = str(diff).strip().replace("+", "").replace(" ", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def infer_market_segment(
    symbol: str | None,
    trade_strategy: str | None,
    contract: str | None,
) -> str:
    sym = (symbol or "?").strip().upper() or "?"
    ts = (trade_strategy or "").lower()
    ct = (contract or "").upper()
    compact = ts.replace(" ", "")
    is_15m = "15m" in compact or "15 m" in ts
    cadence = "15m" if is_15m else "hourly"
    weekly = "WBTC" in ct or "weekly" in ts
    w = " weekly" if weekly else ""
    return f"{sym} {cadence}{w}"


def _norm_side(side: Any) -> str | None:
    if side is None:
        return None
    s = str(side).strip().upper()
    if s in ("Y", "YES"):
        return "Y"
    if s in ("N", "NO"):
        return "N"
    return s or None


def subset_keep(row: Mapping[str, Any], subset: str) -> bool:
    m = subset.strip().lower()
    if m in ("all", "a"):
        return True
    side = _norm_side(row.get("side"))
    prob = row.get("prob")
    try:
        pf = float(prob) if prob is not None else None
    except (TypeError, ValueError):
        pf = None
    if m in ("below_yes", "below-yes"):
        return side == "Y" and pf is not None and pf < 50.0
    if m in ("above_no", "above-no"):
        return side == "N" and pf is not None and pf > 50.0
    raise ValueError(f"Unknown subset {subset!r} (use all, below_yes, above_no)")


_FETCH_COLUMNS = (
    "id",
    "paper_trade",
    "created_at",
    "monitor",
    "symbol",
    "trade_strategy",
    "contract",
    "strike",
    "side",
    "prob",
    "diff",
    "buy_price",
    "symbol_open",
    "momentum",
    "momentum_percentile",
    "momentum_5s_avg",
    "volatility",
    "volatility_percentile",
    "movement",
    "movement_percentile",
)


def fetch_rows(
    conn,
    *,
    start: datetime,
    end: datetime,
    monitors: list[str] | None,
    include_test_filter: bool,
    paper_mode: str = "live",
) -> list[dict[str, Any]]:
    cols = ", ".join(_FETCH_COLUMNS)
    clauses: list[str] = [
        "t.created_at >= %s",
        "t.created_at < %s",
        "t.buy_price IS NOT NULL",
    ]
    params: list[Any] = [start, end]
    pm = (paper_mode or "live").strip().lower()
    if pm not in ("live", "paper", "all"):
        raise ValueError("paper_mode must be live, paper, or all")
    if pm != "all":
        paper_clause = paper_trade_sql("t", pm).strip()
        if paper_clause.upper().startswith("AND "):
            paper_clause = paper_clause[4:].strip()
        clauses.append(paper_clause)
    if not include_test_filter:
        clauses.append(exclude_test_filter_sql("t"))
    if monitors:
        clauses.append("t.monitor = ANY(%s)")
        params.append(monitors)
    sql = f"SELECT {cols} FROM {TRADES_TABLE} t WHERE {' AND '.join(clauses)} ORDER BY t.created_at"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]


def fetch_trade_by_id(
    conn,
    trade_id: int,
    *,
    include_test_filter: bool,
) -> dict[str, Any] | None:
    """Single trade by ``id`` (live or paper); must have ``buy_price``."""
    cols = ", ".join(_FETCH_COLUMNS)
    clauses: list[str] = ["t.id = %s", "t.buy_price IS NOT NULL"]
    params: list[Any] = [trade_id]
    if not include_test_filter:
        clauses.append(exclude_test_filter_sql("t"))
    sql = f"SELECT {cols} FROM {TRADES_TABLE} t WHERE {' AND '.join(clauses)}"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        names = [d[0] for d in cur.description]
        return dict(zip(names, row))


def enrich_row(
    row: dict[str, Any],
    *,
    ttc_tz: str,
) -> dict[str, Any]:
    ts = row.get("trade_strategy")
    grid_15m = strategy_implies_15m_ttc_grid(ts)
    created = row.get("created_at")
    ttc = None
    if isinstance(created, datetime):
        ttc = open_to_next_boundary_minutes(created, ttc_tz, grid_15m=grid_15m)
    strike_n = parse_money_field(row.get("strike"))
    open_n = parse_money_field(row.get("symbol_open"))
    spot_minus_strike = None
    if strike_n is not None and open_n is not None:
        spot_minus_strike = open_n - strike_n
    out = dict(row)
    out["segment"] = infer_market_segment(
        row.get("symbol"),
        row.get("trade_strategy"),
        row.get("contract"),
    )
    out["ttc_minutes"] = ttc
    out["diff_points"] = parse_diff_points(row.get("diff"))
    out["strike_num"] = strike_n
    out["symbol_open_num"] = open_n
    out["spot_minus_strike"] = spot_minus_strike
    out["side_norm"] = _norm_side(row.get("side"))
    return out


def _finite_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pop_std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    v = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(v)


def _quantile_sorted(sorted_x: Sequence[float], q: float) -> float:
    """Linear interpolation quantile on sorted values (q in [0, 1])."""
    n = len(sorted_x)
    if n == 0:
        return float("nan")
    if n == 1:
        return float(sorted_x[0])
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_x[lo])
    w = pos - lo
    return float(sorted_x[lo] * (1 - w) + sorted_x[hi] * w)


def _median(vals: Sequence[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return float("nan")
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return 0.5 * (s[mid - 1] + s[mid])


def _gaussian_solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Solve A x = b for square A; partial pivot. Returns None if singular."""
    n = len(a)
    m_aug = [a[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        piv_row = max(range(col, n), key=lambda r: abs(m_aug[r][col]))
        if abs(m_aug[piv_row][col]) < 1e-12:
            return None
        m_aug[col], m_aug[piv_row] = m_aug[piv_row], m_aug[col]
        div = m_aug[col][col]
        for j in range(col, n + 1):
            m_aug[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            f = m_aug[r][col]
            if abs(f) < 1e-15:
                continue
            for j in range(col, n + 1):
                m_aug[r][j] -= f * m_aug[col][j]
    return [m_aug[i][n] for i in range(n)]


def _least_squares_beta(rows_X: list[list[float]], y: list[float]) -> list[float] | None:
    """Normal equations for overdetermined X beta ~ y (X is m x n)."""
    m = len(rows_X)
    if m == 0 or not rows_X[0]:
        return None
    n = len(rows_X[0])
    ata = [[0.0] * n for _ in range(n)]
    aty = [0.0] * n
    for i in range(n):
        for j in range(n):
            ata[i][j] = sum(rows_X[k][i] * rows_X[k][j] for k in range(m))
        aty[i] = sum(rows_X[k][i] * y[k] for k in range(m))
    return _gaussian_solve(ata, aty)


def pearson_corr(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    xs = [a for a, _ in pairs]
    ys = [b for _, b in pairs]
    sx = _pop_std(xs)
    sy = _pop_std(ys)
    if sx < 1e-12 or sy < 1e-12:
        return None
    mx, my = _mean(xs), _mean(ys)
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs))) / (len(xs) - 1)
    return cov / (sx * sy)


def _pattern_triples(
    rows: list[dict[str, Any]],
) -> list[tuple[float, float, float]]:
    """(ttc_minutes, spot_minus_strike, buy_price) with all finite."""
    out: list[tuple[float, float, float]] = []
    for r in rows:
        ttc = _finite_float(r.get("ttc_minutes"))
        d = _finite_float(r.get("spot_minus_strike"))
        bp = _finite_float(r.get("buy_price"))
        if ttc is None or d is None or bp is None:
            continue
        out.append((ttc, d, bp))
    return out


def print_pattern_coverage(rows: list[dict[str, Any]], *, label: str = "") -> None:
    n = len(rows)
    if not n:
        return
    pref = f"{label}: " if label else ""
    n_ttc = sum(1 for r in rows if _finite_float(r.get("ttc_minutes")) is not None)
    n_dist = sum(1 for r in rows if _finite_float(r.get("spot_minus_strike")) is not None)
    n_bp = sum(1 for r in rows if _finite_float(r.get("buy_price")) is not None)
    trip = len(_pattern_triples(rows))
    print(
        f"{pref}n={n}  finite TTC={n_ttc}  finite spot−strike={n_dist}  "
        f"finite buy_price={n_bp}  rows with all three (pattern pool)={trip}"
    )


def print_pattern_correlations(rows: list[dict[str, Any]], *, target: str = "buy_price") -> None:
    print(f"\nPearson r vs {target} (TTC and spot−strike only):")
    for pk in ("ttc_minutes", "spot_minus_strike"):
        pairs: list[tuple[float, float]] = []
        for r in rows:
            yv = _finite_float(r.get(target))
            xv = _finite_float(r.get(pk))
            if yv is None or xv is None:
                continue
            pairs.append((xv, yv))
        r_val = pearson_corr(pairs)
        n = len(pairs)
        rs = f"{r_val:.4f}" if r_val is not None else "n/a"
        print(f"  {pk:22s} n={n:6d}  r={rs}")


def print_full_feature_correlations(rows: list[dict[str, Any]], *, target: str = "buy_price") -> None:
    y_key = target
    predictors = (
        "prob",
        "ttc_minutes",
        "diff_points",
        "momentum",
        "momentum_percentile",
        "movement",
        "movement_percentile",
        "volatility",
        "volatility_percentile",
        "spot_minus_strike",
    )
    print(f"\nPearson r vs {y_key} (legacy extended predictors):")
    for pk in predictors:
        pairs: list[tuple[float, float]] = []
        for r in rows:
            yv = _finite_float(r.get(y_key))
            xv = _finite_float(r.get(pk))
            if yv is None or xv is None:
                continue
            pairs.append((xv, yv))
        r_val = pearson_corr(pairs)
        n = len(pairs)
        rs = f"{r_val:.4f}" if r_val is not None else "n/a"
        print(f"  {pk:22s} n={n:6d}  r={rs}")


def bucket_median_buy(
    rows: list[dict[str, Any]],
    *,
    key: str,
    n_bins: int = 5,
    label: str | None = None,
) -> None:
    vals: list[tuple[float, float]] = []
    for r in rows:
        bp = _finite_float(r.get("buy_price"))
        xv = _finite_float(r.get(key))
        if bp is None or xv is None:
            continue
        vals.append((xv, bp))
    if len(vals) < n_bins * 3:
        disp = label or key
        print(f"\nNot enough rows with {disp} + buy_price for {n_bins} bins (have {len(vals)}).")
        return
    xs_sorted = sorted(a for a, _ in vals)
    edges = [_quantile_sorted(xs_sorted, i / n_bins) for i in range(n_bins + 1)]
    disp = label or key
    print(f"\nMedian buy_price by {disp} quantile bins (edges from data):")
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        bucket_ys: list[float] = []
        for xv, yv in vals:
            if i == n_bins - 1:
                if lo <= xv <= hi:
                    bucket_ys.append(yv)
            else:
                if lo <= xv < hi:
                    bucket_ys.append(yv)
        if not bucket_ys:
            continue
        med = _median(bucket_ys)
        print(f"  bin {i + 1}: [{lo:.4g}, {hi:.4g}]  n={len(bucket_ys):5d}  median_buy={med:.4f}")


def print_joint_ttc_distance_medians(
    rows: list[dict[str, Any]],
    *,
    ttc_bins: int = 5,
    dist_bins: int = 5,
    min_cell_n: int = 8,
) -> None:
    """
    Quantile bins on TTC and on ``spot_minus_strike``; cell value = median ``buy_price``.
    """
    triples = _pattern_triples(rows)
    if len(triples) < max(min_cell_n * 3, ttc_bins * dist_bins):
        print(
            f"\nJoint TTC × (spot−strike) median buy_price: not enough pattern-pool rows "
            f"(have {len(triples)}, need more for a {ttc_bins}×{dist_bins} grid)."
        )
        return
    ttcs = sorted(t[0] for t in triples)
    ds = sorted(t[1] for t in triples)
    t_edges = [_quantile_sorted(ttcs, i / ttc_bins) for i in range(ttc_bins + 1)]
    d_edges = [_quantile_sorted(ds, i / dist_bins) for i in range(dist_bins + 1)]

    def ttc_bin_idx(t: float) -> int | None:
        for i in range(ttc_bins):
            lo, hi = t_edges[i], t_edges[i + 1]
            if i == ttc_bins - 1:
                if lo <= t <= hi:
                    return i
            elif lo <= t < hi:
                return i
        return None

    def dist_bin_idx(x: float) -> int | None:
        for j in range(dist_bins):
            lo, hi = d_edges[j], d_edges[j + 1]
            if j == dist_bins - 1:
                if lo <= x <= hi:
                    return j
            elif lo <= x < hi:
                return j
        return None

    cells: dict[tuple[int, int], list[float]] = defaultdict(list)
    for ttc, d, bp in triples:
        ti, di = ttc_bin_idx(ttc), dist_bin_idx(d)
        if ti is None or di is None:
            continue
        cells[(ti, di)].append(bp)

    print(
        f"\nJoint median buy_price: TTC quantile rows × (spot−strike) quantile cols "
        f"(min n per cell={min_cell_n}; '.' = sparse)"
    )
    hdr = " " * 14 + "".join(f"  dist{j + 1:>2}" for j in range(dist_bins))
    print(hdr)
    for i in range(ttc_bins):
        line = f"  ttc bin {i + 1:>2}  "
        for j in range(dist_bins):
            xs = cells.get((i, j), [])
            if len(xs) < min_cell_n:
                line += "     .   "
            else:
                line += f"  {_median(xs):5.3f} "
        print(line)

    populated = [_median(v) for v in cells.values() if len(v) >= min_cell_n]
    if len(populated) >= 2:
        print(
            f"  Populated cells: median of cell-medians={_median(populated):.4f}  "
            f"range [{min(populated):.4f}, {max(populated):.4f}]  (wide range -> more structure)"
        )
    elif len(populated) == 1:
        print("  Only one populated cell; no spread to compare.")


def _run_segment_pattern_block(
    chunk: list[dict[str, Any]],
    *,
    seg_label: str,
    by_side: bool,
    no_buckets: bool,
    joint_min_cell_n: int,
) -> None:
    print(f"\n=== Segment: {seg_label} (n={len(chunk)}) ===")
    print_pattern_coverage(chunk)

    sides: list[str | None]
    if by_side:
        sides = ["Y", "N"]
    else:
        sides = [None]

    for side in sides:
        if side is None:
            sub = chunk
        else:
            sub = [r for r in chunk if r.get("side_norm") == side]
            print(f"\n  --- side {side} (n={len(sub)}) ---")
            if len(sub) < 5:
                print("  (too few rows for split)")
                continue
            print_pattern_coverage(sub, label="  pool")
        print_pattern_correlations(sub)
        if no_buckets:
            continue
        bucket_median_buy(sub, key="ttc_minutes")
        bucket_median_buy(sub, key="spot_minus_strike", label="spot_minus_strike (symbol_open − strike)")
        print_joint_ttc_distance_medians(sub, min_cell_n=joint_min_cell_n)


def _ols_design_matrix(
    rows: list[dict[str, Any]],
    *,
    features: tuple[str, ...] = OLS_FEATURES,
) -> tuple[list[list[float]], list[float], list[dict[str, Any]]]:
    """Rows with full finite feature vector + buy_price; aligned X, y, row refs."""
    X_list: list[list[float]] = []
    y_list: list[float] = []
    kept_rows: list[dict[str, Any]] = []
    for r in rows:
        yv = _finite_float(r.get("buy_price"))
        if yv is None:
            continue
        vec: list[float] = [1.0]
        ok = True
        for fk in features:
            xv = _finite_float(r.get(fk))
            if xv is None:
                ok = False
                break
            vec.append(xv)
        if not ok:
            continue
        X_list.append(vec)
        y_list.append(yv)
        kept_rows.append(r)
    return X_list, y_list, kept_rows


def _ols_predict(beta: Sequence[float], x_row: Sequence[float]) -> float:
    return sum(float(beta[j]) * float(x_row[j]) for j in range(len(beta)))


def fit_linear_buy_price(
    rows: list[dict[str, Any]],
    *,
    features: tuple[str, ...] = OLS_FEATURES,
) -> None:
    feat_list = ("intercept",) + features
    X_list, y_list, _ = _ols_design_matrix(rows, features=features)
    if len(y_list) < len(features) + 5:
        print(f"\nFit skipped: need more complete rows (have {len(y_list)}).")
        return
    beta = _least_squares_beta(X_list, y_list)
    if beta is None:
        print("\nFit failed: singular normal equations (try fewer features or more data).")
        return
    y_hat = [_ols_predict(beta, X_list[i]) for i in range(len(y_list))]
    my = _mean(y_list)
    ss_res = sum((y_list[i] - y_hat[i]) ** 2 for i in range(len(y_list)))
    ss_tot = sum((y - my) ** 2 for y in y_list)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    print(f"\nOLS buy_price ~ {' + '.join(feat_list)}  (n={len(y_list)})")
    print(f"  R^2 = {r2:.4f}")
    for name, b in zip(feat_list, beta):
        print(f"  {name:18s}  {float(b):+.6g}")


def run_holdout_eval(
    enriched: list[dict[str, Any]],
    *,
    n_holdout: int,
    seed: int,
    features: tuple[str, ...] = OLS_FEATURES,
) -> None:
    """
    Train OLS on a random subset; predict ``n_holdout`` held-out live trades and compare to ``buy_price``.
    """
    feat_list = ("intercept",) + features
    X_all, y_all, rows_all = _ols_design_matrix(enriched, features=features)
    min_train = len(features) + 8
    if len(y_all) < n_holdout + min_train:
        print(
            f"\nHoldout eval skipped: need at least {n_holdout + min_train} complete-case rows "
            f"(have {len(y_all)}). Widen --start/--end or relax filters."
        )
        return

    idx = list(range(len(y_all)))
    rng = random.Random(seed)
    rng.shuffle(idx)
    test_i = idx[:n_holdout]
    train_i = idx[n_holdout:]
    train_X = [X_all[i] for i in train_i]
    train_y = [y_all[i] for i in train_i]
    beta = _least_squares_beta(train_X, train_y)
    if beta is None:
        print("\nHoldout eval failed: singular normal equations on training split.")
        return

    y_hat_tr = [_ols_predict(beta, train_X[i]) for i in range(len(train_X))]
    my_tr = _mean(train_y)
    ss_res_tr = sum((train_y[i] - y_hat_tr[i]) ** 2 for i in range(len(train_y)))
    ss_tot_tr = sum((y - my_tr) ** 2 for y in train_y)
    r2_tr = 1.0 - ss_res_tr / ss_tot_tr if ss_tot_tr > 0 else 0.0

    print(
        f"\n=== Random holdout eval (n_holdout={n_holdout}, seed={seed}) ===\n"
        f"Complete-case pool: {len(y_all)} rows (all features + buy_price finite)\n"
        f"Train: {len(train_i)}  |  Test: {len(test_i)}\n"
        f"Model: buy_price ~ {' + '.join(feat_list)}\n"
        f"In-sample R^2 on training split: {r2_tr:.4f}"
    )

    errs: list[float] = []
    print(
        "\n"
        f"{'id':>8}  {'segment':<22}  {'side':^4}  {'actual':>8}  {'predicted':>10}  "
        f"{'err':>8}  {'|err|':>8}  {'created_at'}"
    )
    for i in test_i:
        r = rows_all[i]
        act = y_all[i]
        pred = _ols_predict(beta, X_all[i])
        err = pred - act
        errs.append(abs(err))
        rid = r.get("id", "")
        seg = str(r.get("segment") or "")[:22]
        side = str(r.get("side_norm") or r.get("side") or "")[:4]
        ts = r.get("created_at")
        ts_s = ts.isoformat()[:19] if isinstance(ts, datetime) else str(ts)[:19]
        print(
            f"{rid!s:>8}  {seg:<22}  {side:^4}  {act:8.4f}  {pred:10.4f}  "
            f"{err:+8.4f}  {abs(err):8.4f}  {ts_s}"
        )

    mae = sum(errs) / len(errs) if errs else float("nan")
    test_y = [y_all[i] for i in test_i]
    pred_y = [_ols_predict(beta, X_all[i]) for i in test_i]
    rmse = math.sqrt(sum((test_y[j] - pred_y[j]) ** 2 for j in range(len(test_y))) / len(test_y))
    mape = (
        sum(abs(pred_y[j] - test_y[j]) / max(abs(test_y[j]), 1e-6) for j in range(len(test_y)))
        / len(test_y)
        * 100.0
    )
    print(f"\nHoldout MAE: {mae:.4f}  RMSE: {rmse:.4f}  mean |pct| error vs actual: {mape:.2f}%")


def _assign_quantile_bin(val: float, edges: Sequence[float]) -> int | None:
    n = len(edges) - 1
    for i in range(n):
        lo, hi = edges[i], edges[i + 1]
        if i == n - 1:
            if lo <= val <= hi:
                return i
        elif lo <= val < hi:
            return i
    return None


def _quantile_edges(sorted_vals: Sequence[float], n_bins: int) -> list[float]:
    return [_quantile_sorted(sorted_vals, i / n_bins) for i in range(n_bins + 1)]


def _peer_pool_segment(
    train: list[dict[str, Any]],
    segment: str,
    *,
    side: str | None = None,
) -> list[dict[str, Any]]:
    out = [r for r in train if str(r.get("segment") or "?") == segment]
    if side in ("Y", "N"):
        out = [r for r in out if r.get("side_norm") == side]
    return out


def expected_peer_median_bins2d(
    target: dict[str, Any],
    train: list[dict[str, Any]],
    *,
    ttc_bins: int = 5,
    dist_bins: int = 5,
    min_cell: int = 3,
    min_segment_train: int = 20,
    stratify_side: bool = False,
) -> float | None:
    """Median peer ``buy_price`` in same segment (optional same side), TTC×distance quantile cell."""
    seg = str(target.get("segment") or "?")
    side = target.get("side_norm") if stratify_side else None
    ttc_t = _finite_float(target.get("ttc_minutes"))
    dist_t = _finite_float(target.get("spot_minus_strike"))
    if ttc_t is None or dist_t is None:
        return None
    pool = _peer_pool_segment(train, seg, side=side if stratify_side else None)
    triples: list[tuple[float, float, float]] = []
    for r in pool:
        tt = _finite_float(r.get("ttc_minutes"))
        d = _finite_float(r.get("spot_minus_strike"))
        bp = _finite_float(r.get("buy_price"))
        if tt is None or d is None or bp is None:
            continue
        triples.append((tt, d, bp))
    if len(triples) < min_segment_train:
        return None
    ttcs = sorted(x[0] for x in triples)
    ds = sorted(x[1] for x in triples)
    t_edges = _quantile_edges(ttcs, ttc_bins)
    d_edges = _quantile_edges(ds, dist_bins)
    ti = _assign_quantile_bin(ttc_t, t_edges)
    di = _assign_quantile_bin(dist_t, d_edges)
    if ti is None or di is None:
        return None

    def cell(tt: float, d: float) -> tuple[int | None, int | None]:
        return _assign_quantile_bin(tt, t_edges), _assign_quantile_bin(d, d_edges)

    joint = [bp for tt, d, bp in triples if cell(tt, d) == (ti, di)]
    if len(joint) >= min_cell:
        return _median(joint)
    ttc_only = [bp for tt, d, bp in triples if _assign_quantile_bin(tt, t_edges) == ti]
    if len(ttc_only) >= min_cell:
        return _median(ttc_only)
    dist_only = [bp for tt, d, bp in triples if _assign_quantile_bin(d, d_edges) == di]
    if len(dist_only) >= min_cell:
        return _median(dist_only)
    return _median([x[2] for x in triples])


def expected_peer_median_bins3d(
    target: dict[str, Any],
    train: list[dict[str, Any]],
    *,
    ttc_bins: int = 5,
    dist_bins: int = 5,
    prob_bins: int = 4,
    min_cell: int = 3,
    min_segment_train: int = 30,
    stratify_side: bool = False,
) -> float | None:
    """TTC × distance × ``prob`` quantile bins; fallback to :func:`expected_peer_median_bins2d`."""
    seg = str(target.get("segment") or "?")
    ttc_t = _finite_float(target.get("ttc_minutes"))
    dist_t = _finite_float(target.get("spot_minus_strike"))
    prob_t = _finite_float(target.get("prob"))
    if ttc_t is None or dist_t is None or prob_t is None:
        return None
    side = target.get("side_norm") if stratify_side else None
    pool = _peer_pool_segment(train, seg, side=side if stratify_side else None)
    quads: list[tuple[float, float, float, float]] = []
    for r in pool:
        tt = _finite_float(r.get("ttc_minutes"))
        d = _finite_float(r.get("spot_minus_strike"))
        pr = _finite_float(r.get("prob"))
        bp = _finite_float(r.get("buy_price"))
        if tt is None or d is None or pr is None or bp is None:
            continue
        quads.append((tt, d, pr, bp))
    if len(quads) < min_segment_train:
        return expected_peer_median_bins2d(
            target,
            train,
            ttc_bins=ttc_bins,
            dist_bins=dist_bins,
            min_cell=min_cell,
            min_segment_train=min_segment_train,
            stratify_side=stratify_side,
        )
    ttcs = sorted(q[0] for q in quads)
    ds = sorted(q[1] for q in quads)
    prs = sorted(q[2] for q in quads)
    t_edges = _quantile_edges(ttcs, ttc_bins)
    d_edges = _quantile_edges(ds, dist_bins)
    p_edges = _quantile_edges(prs, prob_bins)
    ti = _assign_quantile_bin(ttc_t, t_edges)
    di = _assign_quantile_bin(dist_t, d_edges)
    pi = _assign_quantile_bin(prob_t, p_edges)
    if ti is None or di is None or pi is None:
        return expected_peer_median_bins2d(
            target,
            train,
            ttc_bins=ttc_bins,
            dist_bins=dist_bins,
            min_cell=min_cell,
            min_segment_train=min_segment_train,
            stratify_side=stratify_side,
        )

    def cell(
        tt: float, d: float, pr: float
    ) -> tuple[int | None, int | None, int | None]:
        return (
            _assign_quantile_bin(tt, t_edges),
            _assign_quantile_bin(d, d_edges),
            _assign_quantile_bin(pr, p_edges),
        )

    joint3 = [q[3] for q in quads if cell(q[0], q[1], q[2]) == (ti, di, pi)]
    if len(joint3) >= min_cell:
        return _median(joint3)
    return expected_peer_median_bins2d(
        target,
        train,
        ttc_bins=ttc_bins,
        dist_bins=dist_bins,
        min_cell=min_cell,
        min_segment_train=max(15, min_segment_train - 10),
        stratify_side=stratify_side,
    )


def expected_peer_knn(
    target: dict[str, Any],
    train: list[dict[str, Any]],
    *,
    k: int = 15,
    min_segment_train: int = 25,
    stratify_side: bool = True,
) -> float | None:
    """Median ``buy_price`` of ``k`` nearest neighbors in z-scored (TTC, distance, prob) space."""
    seg = str(target.get("segment") or "?")
    side = target.get("side_norm") if stratify_side else None
    ttc_t = _finite_float(target.get("ttc_minutes"))
    dist_t = _finite_float(target.get("spot_minus_strike"))
    prob_t = _finite_float(target.get("prob"))
    if ttc_t is None or dist_t is None or prob_t is None:
        return None
    pool = _peer_pool_segment(train, seg, side=side if stratify_side else None)
    pts: list[tuple[float, float, float, float]] = []
    for r in pool:
        tt = _finite_float(r.get("ttc_minutes"))
        d = _finite_float(r.get("spot_minus_strike"))
        pr = _finite_float(r.get("prob"))
        bp = _finite_float(r.get("buy_price"))
        if tt is None or d is None or pr is None or bp is None:
            continue
        pts.append((tt, d, pr, bp))
    if len(pts) < min_segment_train:
        return None
    ttc_s = [p[0] for p in pts]
    d_s = [p[1] for p in pts]
    pr_s = [p[2] for p in pts]
    mt, md, mp = _mean(ttc_s), _mean(d_s), _mean(pr_s)
    st, sd, sp = _pop_std(ttc_s), _pop_std(d_s), _pop_std(pr_s)
    if st < 1e-12:
        st = 1.0
    if sd < 1e-12:
        sd = 1.0
    if sp < 1e-12:
        sp = 1.0

    def z(tt: float, d: float, pr: float) -> tuple[float, float, float]:
        return ((tt - mt) / st, (d - md) / sd, (pr - mp) / sp)

    zt = z(ttc_t, dist_t, prob_t)
    scored: list[tuple[float, float]] = []
    for tt, d, pr, bp in pts:
        zz = z(tt, d, pr)
        dist2 = (zz[0] - zt[0]) ** 2 + (zz[1] - zt[1]) ** 2 + (zz[2] - zt[2]) ** 2
        scored.append((dist2, bp))
    scored.sort(key=lambda x: x[0])
    kk = min(k, len(scored))
    return _median([scored[i][1] for i in range(kk)])


def _peer_holdout_metrics(
    predictions: list[tuple[float, float]],
) -> tuple[float, float, float, float, float, float | None]:
    """MAE, RMSE, MAPE%, pct within 0.01, pct within 0.02, Pearson r."""
    if not predictions:
        return (float("nan"),) * 5 + (None,)
    errs = [e - a for e, a in predictions]
    abs_e = [abs(x) for x in errs]
    mae = sum(abs_e) / len(abs_e)
    rmse = math.sqrt(sum(x * x for x in errs) / len(errs))
    mape = (
        sum(abs_e[i] / max(abs(predictions[i][1]), 1e-9) for i in range(len(predictions)))
        / len(predictions)
        * 100.0
    )
    w1 = sum(1 for x in abs_e if x <= 0.01) / len(abs_e) * 100.0
    w2 = sum(1 for x in abs_e if x <= 0.02) / len(abs_e) * 100.0
    r = pearson_corr([(predictions[i][0], predictions[i][1]) for i in range(len(predictions))])
    return (mae, rmse, mape, w1, w2, r)


def run_peer_holdout_eval(
    enriched: list[dict[str, Any]],
    *,
    n_holdout: int,
    seed: int,
    knn_k: int = 15,
) -> None:
    """
    Compare peer median predictors on a random holdout: 2D bins (segment), 3D bins (+prob),
    2D bins (segment+side), k-NN (segment+side, z-scored TTC/distance/prob).
    """
    strict: list[dict[str, Any]] = []
    for r in enriched:
        if (
            _finite_float(r.get("ttc_minutes")) is not None
            and _finite_float(r.get("spot_minus_strike")) is not None
            and _finite_float(r.get("prob")) is not None
            and _finite_float(r.get("buy_price")) is not None
        ):
            strict.append(r)

    if len(strict) < n_holdout + 80:
        print(
            f"\nPeer holdout skipped: need at least {n_holdout + 80} rows with "
            f"TTC, spot−strike, prob, buy_price (have {len(strict)})."
        )
        return

    rng = random.Random(seed)
    test_rows = rng.sample(strict, n_holdout)
    test_ids = {r["id"] for r in test_rows}
    train = [r for r in enriched if r["id"] not in test_ids]

    print(
        f"\n=== Peer median holdout (n={n_holdout}, seed={seed}) ===\n"
        f"Strict pool (TTC + spot−strike + prob + buy_price): {len(strict)} rows\n"
        f"Train rows (all columns, excl. holdout ids): {len(train)}"
    )

    methods: list[tuple[str, list[tuple[float, float]]]] = []

    def collect(pred_fn) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for t in test_rows:
            act = _finite_float(t.get("buy_price"))
            pr = pred_fn(t, train)
            if act is None or pr is None:
                continue
            out.append((pr, act))
        return out

    methods.append(
        (
            "2d bins (segment only, TTC×dist)",
            collect(
                lambda tr, trn: expected_peer_median_bins2d(
                    tr, trn, stratify_side=False
                )
            ),
        )
    )
    methods.append(
        (
            "3d bins (segment, TTC×dist×prob)",
            collect(
                lambda tr, trn: expected_peer_median_bins3d(
                    tr, trn, stratify_side=False
                )
            ),
        )
    )
    methods.append(
        (
            "2d bins (segment+side, TTC×dist)",
            collect(
                lambda tr, trn: expected_peer_median_bins2d(
                    tr, trn, stratify_side=True
                )
            ),
        )
    )
    methods.append(
        (
            f"k-NN z(ttc,dist,prob) k={knn_k} (segment+side)",
            collect(
                lambda tr, trn: expected_peer_knn(
                    tr, trn, k=knn_k, stratify_side=True
                )
            ),
        )
    )

    print(
        f"\n{'method':<42}  {'n':>4}  {'MAE':>8}  {'RMSE':>8}  "
        f"{'MAPE%':>8}  {'≤0.01':>7}  {'≤0.02':>7}  {'r':>7}"
    )
    for name, pairs in methods:
        mae, rmse, mape, w1, w2, r = _peer_holdout_metrics(pairs)
        rs = f"{r:.4f}" if r is not None else "n/a"
        print(
            f"{name:<42}  {len(pairs):4d}  {mae:8.5f}  {rmse:8.5f}  "
            f"{mape:8.2f}  {w1:6.1f}%  {w2:6.1f}%  {rs:>7}"
        )


def _parse_trade_id_list(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError as e:
            raise ValueError(f"invalid trade id {p!r}") from e
    return out


def run_spot_check_dual(
    conn,
    enriched_live: list[dict[str, Any]],
    enriched_paper: list[dict[str, Any]],
    trade_ids: list[int],
    *,
    include_test_filter: bool,
    ttc_tz: str,
) -> None:
    """
    For each trade id: recorded ``buy_price`` vs 3D peer median trained on **live-only** pool vs
    **paper-only** pool (same time window). Training rows exclude the target id if present.
    """
    print(
        "\n=== Dual-pool spot check (3D peer median: segment, TTC x dist x prob) ===\n"
        f"Live training pool: {len(enriched_live)} rows  |  "
        f"Paper training pool: {len(enriched_paper)} rows"
    )
    hdr = (
        f"{'id':>7}  {'db':^4}  {'segment':<14}  {'rec':>6}  "
        f"{'exp_L':>7}  {'exp_P':>7}  {'rec-exp_L':>10}  {'rec-exp_P':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    rows_out: list[tuple[float, float | None, float | None]] = []
    for tid in trade_ids:
        raw = fetch_trade_by_id(conn, tid, include_test_filter=include_test_filter)
        if raw is None:
            print(f"{tid:7d}  (not found or filtered)")
            continue
        t = enrich_row(raw, ttc_tz=ttc_tz)
        rec = _finite_float(t.get("buy_price"))
        db_p = bool(t.get("paper_trade") is True)
        db_lbl = "P" if db_p else "L"
        seg = str(t.get("segment") or "?")[:14]
        train_l = [r for r in enriched_live if r.get("id") != tid]
        train_p = [r for r in enriched_paper if r.get("id") != tid]
        exp_l = expected_peer_median_bins3d(t, train_l, stratify_side=False)
        exp_p = expected_peer_median_bins3d(t, train_p, stratify_side=False)
        el = f"{exp_l:.4f}" if exp_l is not None else "   n/a"
        ep = f"{exp_p:.4f}" if exp_p is not None else "   n/a"
        rl = f"{rec - exp_l:+.4f}" if rec is not None and exp_l is not None else "       n/a"
        rp = f"{rec - exp_p:+.4f}" if rec is not None and exp_p is not None else "       n/a"
        rc = f"{rec:.4f}" if rec is not None else "  n/a"
        print(f"{tid:7d}  {db_lbl:^4}  {seg:<14}  {rc:>6}  {el:>7}  {ep:>7}  {rl:>10}  {rp:>10}")
        if rec is not None:
            rows_out.append((rec, exp_l, exp_p))

    if rows_out:
        abs_l = [abs(rec - el) for rec, el, ep in rows_out if el is not None]
        abs_p = [abs(rec - ep) for rec, el, ep in rows_out if ep is not None]
        print("\nAcross spot checks with finite expected:")
        if abs_l:
            print(f"  mean |recorded - exp_live|  = {sum(abs_l) / len(abs_l):.5f}  (n={len(abs_l)})")
        else:
            print("  mean |recorded - exp_live|  = n/a (no finite exp_live)")
        if abs_p:
            print(f"  mean |recorded - exp_paper| = {sum(abs_p) / len(abs_p):.5f}  (n={len(abs_p)})")
        else:
            print("  mean |recorded - exp_paper| = n/a (no finite exp_paper)")
        print(
            "  Live pool peers reflect executed fills; paper pool peers reflect paper-log prices. "
            "They need not match on the same row: compare columns to see which baseline sits closer "
            "to recorded for your mix of ids (try paper ids vs live ids separately)."
        )


def write_csv(path: str, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    # Flatten for CSV: only stringify-friendly keys
    keys = sorted({k for r in rows for k in r.keys()})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {}
            for k in keys:
                v = r.get(k)
                if isinstance(v, datetime):
                    out[k] = v.isoformat()
                else:
                    out[k] = v
            w.writerow(out)
    print(f"\nWrote {len(rows)} rows to {path}")


def run() -> int:
    p = argparse.ArgumentParser(
        description=__doc__.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  .venv/bin/python3 scripts/backtest/price_estimator.py \\\n"
            "    --start 2025-06-01T00:00:00-04:00 --end 2026-03-22T00:00:00-04:00\n"
            "  .venv/bin/python3 scripts/backtest/price_estimator.py \\\n"
            "    --start 2025-06-01T00:00:00-04:00 --end 2026-03-22T00:00:00-04:00 \\\n"
            "    --by-side --no-buckets\n"
            "  .venv/bin/python3 scripts/backtest/price_estimator.py ... --legacy-full-correlations --fit \\\n"
            "    --holdout-eval 20 --holdout-seed 42\n"
            "  .venv/bin/python3 scripts/backtest/price_estimator.py \\\n"
            "    --start 2025-06-01T00:00:00-04:00 --end 2026-03-22T00:00:00-04:00 \\\n"
            "    --peer-holdout 100 --peer-holdout-seed 42\n"
            "  .venv/bin/python3 scripts/backtest/price_estimator.py \\\n"
            "    --start 2025-06-01T00:00:00-04:00 --end 2026-03-22T00:00:00-04:00 \\\n"
            "    --spot-check-dual 8459,6911 --spot-check-dual-only\n"
            "  .venv/bin/python3 scripts/backtest/price_estimator.py ... --paper paper --peer-holdout 100"
        ),
    )
    p.add_argument("--start", type=_parse_instant, required=True)
    p.add_argument("--end", type=_parse_instant, required=True)
    p.add_argument(
        "--paper",
        type=str,
        default="live",
        choices=("live", "paper", "all"),
        help="Which rows to load for the main report and --peer-holdout: live (default), paper only, or all",
    )
    p.add_argument(
        "--monitors",
        type=str,
        default=None,
        help="Comma-separated monitor names (default: all monitors in window)",
    )
    p.add_argument(
        "--ttc-tz",
        default="America/New_York",
        help="IANA zone for TTC boundaries (default America/New_York)",
    )
    p.add_argument(
        "--segment",
        default=None,
        help="If set, keep only rows whose segment label contains this substring (case-insensitive)",
    )
    p.add_argument(
        "--subset",
        default="all",
        help="Row filter: all | below_yes (Y & prob<50) | above_no (N & prob>50)",
    )
    p.add_argument(
        "--include-test-filter",
        action="store_true",
        help="Include rows with test_filter=TRUE (default: exclude)",
    )
    p.add_argument("--export", default=None, help="Write enriched rows to CSV path")
    p.add_argument(
        "--by-side",
        action="store_true",
        help="Within each segment, repeat TTC/distance pattern analysis for Y vs N",
    )
    p.add_argument(
        "--joint-min-cell-n",
        type=int,
        default=8,
        metavar="N",
        help="Minimum row count to print a joint TTC×distance cell median (default 8)",
    )
    p.add_argument(
        "--legacy-full-correlations",
        action="store_true",
        help="After the TTC/distance report, also print Pearson r for prob/momentum/etc. (legacy)",
    )
    p.add_argument(
        "--fit",
        action="store_true",
        help="Legacy: OLS buy_price ~ prob + ttc + diff + momentum + momentum_percentile",
    )
    p.add_argument(
        "--no-buckets",
        action="store_true",
        help="Skip marginal and joint median-bin tables (correlations + coverage only)",
    )
    p.add_argument(
        "--holdout-eval",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Legacy: OLS holdout eval on prob+ttc+diff+momentum features (see --fit); "
            "use --segment-report to also print the TTC/distance pattern blocks"
        ),
    )
    p.add_argument(
        "--holdout-seed",
        type=int,
        default=42,
        help="RNG seed for shuffling before holdout split (default 42)",
    )
    p.add_argument(
        "--segment-report",
        action="store_true",
        help="With --holdout-eval or --peer-holdout, still print per-segment pattern blocks",
    )
    p.add_argument(
        "--peer-holdout",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Random holdout: compare peer median predictors — 2D TTC×dist (segment), "
            "3D +prob (segment), 2D (segment+side), k-NN on z(ttc,dist,prob) (segment+side)"
        ),
    )
    p.add_argument(
        "--peer-holdout-seed",
        type=int,
        default=42,
        help="RNG seed for --peer-holdout (default 42)",
    )
    p.add_argument(
        "--peer-knn-k",
        type=int,
        default=15,
        help="k for k-NN peer predictor in --peer-holdout (default 15)",
    )
    p.add_argument(
        "--spot-check-dual",
        type=str,
        default=None,
        metavar="IDS",
        help=(
            "Comma-separated trade ids: for each row, show recorded buy vs 3D peer median from "
            "live-only pool vs paper-only pool (same --start/--end window)"
        ),
    )
    p.add_argument(
        "--spot-check-dual-only",
        action="store_true",
        help="After --spot-check-dual, exit without segment / peer tables on --paper",
    )
    args = p.parse_args()

    if args.spot_check_dual:
        try:
            sc_ids = _parse_trade_id_list(args.spot_check_dual)
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 2
        if not sc_ids:
            print("--spot-check-dual requires at least one id", file=sys.stderr)
            return 2
        conn = get_connection()
        try:
            rl = fetch_rows(
                conn,
                start=args.start,
                end=args.end,
                monitors=_parse_monitors_opt(args.monitors),
                include_test_filter=args.include_test_filter,
                paper_mode="live",
            )
            rp = fetch_rows(
                conn,
                start=args.start,
                end=args.end,
                monitors=_parse_monitors_opt(args.monitors),
                include_test_filter=args.include_test_filter,
                paper_mode="paper",
            )
            el = [enrich_row(r, ttc_tz=args.ttc_tz) for r in rl]
            ep = [enrich_row(r, ttc_tz=args.ttc_tz) for r in rp]
            run_spot_check_dual(
                conn,
                el,
                ep,
                sc_ids,
                include_test_filter=args.include_test_filter,
                ttc_tz=args.ttc_tz,
            )
        finally:
            conn.close()
        if args.spot_check_dual_only:
            return 0

    conn = get_connection()
    try:
        raw = fetch_rows(
            conn,
            start=args.start,
            end=args.end,
            monitors=_parse_monitors_opt(args.monitors),
            include_test_filter=args.include_test_filter,
            paper_mode=args.paper,
        )
    finally:
        conn.close()

    enriched: list[dict[str, Any]] = []
    for r in raw:
        e = enrich_row(r, ttc_tz=args.ttc_tz)
        try:
            if not subset_keep(e, args.subset):
                continue
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 2
        if args.segment:
            if args.segment.lower() not in str(e.get("segment") or "").lower():
                continue
        enriched.append(e)

    print(
        f"Trades with buy_price: {len(enriched)} "
        f"(window {args.start.isoformat()} .. {args.end.isoformat()}, "
        f"subset={args.subset!r}, paper={args.paper!r})"
    )
    if not enriched:
        return 0

    by_seg: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in enriched:
        by_seg[str(r.get("segment") or "?")].append(r)

    print("\nCounts by segment:")
    for seg in sorted(by_seg.keys(), key=lambda s: (-len(by_seg[s]), s)):
        print(f"  {seg:28s}  n={len(by_seg[seg]):5d}")

    skip_segment_detail = (
        (args.holdout_eval > 0 or args.peer_holdout > 0) and not args.segment_report
    )
    if not skip_segment_detail:
        for seg in sorted(by_seg.keys(), key=lambda s: (-len(by_seg[s]), s)):
            chunk = by_seg[seg]
            _run_segment_pattern_block(
                chunk,
                seg_label=seg,
                by_side=args.by_side,
                no_buckets=args.no_buckets,
                joint_min_cell_n=args.joint_min_cell_n,
            )
            if args.legacy_full_correlations:
                print_full_feature_correlations(chunk)

    if args.fit:
        print("\n--- Global OLS (all kept segments combined) ---")
        fit_linear_buy_price(enriched)

    if args.holdout_eval > 0:
        run_holdout_eval(
            enriched,
            n_holdout=args.holdout_eval,
            seed=args.holdout_seed,
        )

    if args.peer_holdout > 0:
        run_peer_holdout_eval(
            enriched,
            n_holdout=args.peer_holdout,
            seed=args.peer_holdout_seed,
            knn_k=args.peer_knn_k,
        )

    if args.export:
        write_csv(args.export, enriched)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
