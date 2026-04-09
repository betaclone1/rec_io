"""
Per-minute **strike-table span** fields for ``backtest.backtest_1m_*`` rows.

**Probability envelope:** axis-aligned rectangle over the minute — TTC at **bar open** and **bar
close** (``seconds_to_next_15m_boundary_ny``), buffer **min/max** from ``abs(spot - floor_strike)``
at joined price-history **low** / **high**. Four **corners** each run ``get_probability``; then
min/max of the stored **yes** and **no** probability columns.

**Active-side complement (0–100 lookup scale):** at each corner, after raw ``pos`` / ``neg``:

- ``active_side == "yes"``: store corner yes = ``pos``, corner no = ``100 - pos``.
- ``active_side == "no"``: store corner no = ``neg``, corner yes = ``100 - neg``.
- ``active_side == "cross"``: keep raw ``pos`` and ``neg``.

Min/max are taken over the four corner **yes** values and four **no** values (skipping corners
with missing lookup).

**Diff ranges:** ``money_line_diffs_and_active_side`` at two correlated corners — **low spot** with
**min** active prob and **low YES ask** (NO ask = ``1 - yes_ask``); **high spot** with **max**
active prob and **high YES ask**. Same geometry as ``auto_entry_htc_gates``; spot is BTC
``low`` / ``high`` (strike scale). Asks from Kalshi **yes_ask** candle OHLC.

**Momentum:** one bucket from ``momentum_percentile`` for the minute.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from decimal import Decimal
from typing import Any, Mapping, Optional

from zoneinfo import ZoneInfo

from backend.strike_table_generator import LookupProbabilityCalculator, round_price_buffer, uses_high_precision_price
from backend.util.auto_entry_htc_gates import money_line_diffs_and_active_side
from scripts.backtest.helpers.backtest_price_history import BACKTEST_PRICE_HISTORY_COLUMN_DEFS
from scripts.backtest.helpers.htc_aes_replay import seconds_to_next_15m_boundary_ny

_EASTERN = ZoneInfo("America/New_York")

# Columns added via ensure_backtest_strike_span_columns (order matches UPSERT).
BACKTEST_STRIKE_SPAN_COLUMN_DEFS: tuple[tuple[str, str], ...] = (
    ("active_side", "TEXT"),
    ("minute_tradeable", "BOOLEAN"),
    ("ttc_15m_open_seconds", "INTEGER"),
    ("ttc_15m_close_seconds", "INTEGER"),
    ("strike_buffer_min", "NUMERIC(24, 8)"),
    ("strike_buffer_max", "NUMERIC(24, 8)"),
    ("yes_prob_15m_min", "NUMERIC(8, 4)"),
    ("yes_prob_15m_max", "NUMERIC(8, 4)"),
    ("no_prob_15m_min", "NUMERIC(8, 4)"),
    ("no_prob_15m_max", "NUMERIC(8, 4)"),
    ("yes_diff_min", "NUMERIC(8, 4)"),
    ("yes_diff_max", "NUMERIC(8, 4)"),
    ("no_diff_min", "NUMERIC(8, 4)"),
    ("no_diff_max", "NUMERIC(8, 4)"),
)

_BACKTEST_STRIKE_SPAN_REL_RE = re.compile(r"^backtest_1m_[a-z0-9_]+$")
_COL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_OBSOLETE_STRIKE_SPAN_COLUMNS: tuple[str, ...] = (
    "ttc_15m_mid30_seconds",
    "strike_buffer_avg",
    "yes_prob_15m",
    "no_prob_15m",
    "yes_diff",
    "no_diff",
    "no_ask_min_dollars",
    "no_ask_max_dollars",
)


def _quote_col(name: str) -> str:
    if not _COL_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid SQL column name: {name!r}")
    return f'"{name}"'


def ensure_backtest_strike_span_columns(conn: Any, rel: str) -> None:
    if not _BACKTEST_STRIKE_SPAN_REL_RE.match(rel):
        raise ValueError(f"invalid backtest table rel: {rel!r}")
    with conn.cursor() as cur:
        for col in _OBSOLETE_STRIKE_SPAN_COLUMNS:
            cur.execute(f"ALTER TABLE backtest.{rel} DROP COLUMN IF EXISTS {_quote_col(col)};")
        parts = [
            f"ADD COLUMN IF NOT EXISTS {_quote_col(name)} {typ}"
            for name, typ in BACKTEST_STRIKE_SPAN_COLUMN_DEFS
        ]
        cur.execute(f"ALTER TABLE backtest.{rel} " + ", ".join(parts) + ";")


def probability_symbol_from_kalshi_ticker(market_ticker: str) -> Optional[str]:
    u = market_ticker.strip().upper()
    if "BTC" in u:
        return "btc"
    if "ETH" in u:
        return "eth"
    if "SOL" in u:
        return "sol"
    if "XRP" in u:
        return "xrp"
    return None


def _naive_et_to_aware(ts: datetime) -> datetime:
    if ts.tzinfo is not None:
        raise ValueError("expected naive Eastern timestamp")
    return ts.replace(tzinfo=_EASTERN)


def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _dec(x: Any) -> Optional[Decimal]:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except Exception:
        return None


def _buffer_points(
    *,
    spot: float,
    floor_strike: float,
    symbol: str,
) -> float:
    raw = abs(float(spot) - float(floor_strike))
    if uses_high_precision_price(symbol):
        return float(round_price_buffer(raw))
    return float(raw)


def _dollars_to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, dict):
        inner = v.get("dollars") or v.get("fixed_point")
        if inner is None:
            return None
        v = inner
    return _f(v)


def yes_price_mean_dollars_from_candle(c: Mapping[str, Any]) -> Optional[float]:
    """Kalshi candle ``price.*`` fields are YES prices (contract 0–1 dollars)."""
    pr = c.get("price") or {}
    return _dollars_to_float(pr.get("mean_dollars"))


def yes_ask_close_from_candle(c: Mapping[str, Any]) -> Optional[float]:
    ya = c.get("yes" + "_ask") or {}
    return _dollars_to_float(ya.get("close_dollars"))


def yes_ask_low_high_from_candle(c: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
    ya = c.get("yes" + "_ask") or {}
    return _dollars_to_float(ya.get("low_dollars")), _dollars_to_float(ya.get("high_dollars"))


def yes_price_low_high_from_candle(c: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """Kalshi candle ``price.*`` YES trade/last OHLC extremes for the minute bar."""
    pr = c.get("price") or {}
    return _dollars_to_float(pr.get("low_dollars")), _dollars_to_float(pr.get("high_dollars"))


def implied_no_envelope_from_unordered_yes_low_high(
    y_lo: Optional[float],
    y_hi: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """
    Implied **NO** dollar envelope from YES low/high (unordered). Same complement geometry for
    both YES **ask** bars and YES **trade price** bars: ``no_max = 1 - min(YES)``, ``no_min = 1 - max(YES)``,
    then ordered ascending. ``(None, None)`` if inputs missing.
    """
    if y_lo is None or y_hi is None:
        return None, None
    yal, yah = (y_lo, y_hi) if y_lo <= y_hi else (y_hi, y_lo)
    no_max = 1.0 - yal
    no_min = 1.0 - yah
    if no_min > no_max:
        no_min, no_max = no_max, no_min
    return no_min, no_max


def implied_no_ask_min_max_from_yes_ask_bar(
    yes_ask_low_dollars: Optional[float],
    yes_ask_high_dollars: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """Implied NO **ask** envelope from YES best-ask OHLC (see ``compute_minute_strike_span``)."""
    return implied_no_envelope_from_unordered_yes_low_high(yes_ask_low_dollars, yes_ask_high_dollars)


def implied_no_price_min_max_from_yes_price_bar(
    yes_price_low_dollars: Optional[float],
    yes_price_high_dollars: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """Implied NO contract envelope from YES **trade price** bar (matches ``no_price_*`` vs ``yes_price_*`` OHLC)."""
    return implied_no_envelope_from_unordered_yes_low_high(
        yes_price_low_dollars, yes_price_high_dollars
    )


def _corner_yes_no_probs(
    pos: Optional[float],
    neg: Optional[float],
    active: str,
) -> tuple[Optional[float], Optional[float]]:
    """Map raw lookup legs to corner yes/no columns using active-side complement rules."""
    if active == "cross":
        if pos is None or neg is None:
            return None, None
        return float(pos), float(neg)
    if active == "yes":
        if pos is None:
            return None, None
        p, n = float(pos), 100.0 - float(pos)
        return p, n
    if active == "no":
        if neg is None:
            return None, None
        p, n = 100.0 - float(neg), float(neg)
        return p, n
    return None, None


def unpack_price_history_tuple(ph: tuple[Any, ...]) -> dict[str, Any]:
    names = [n for n, _ in BACKTEST_PRICE_HISTORY_COLUMN_DEFS]
    if len(ph) != len(names):
        raise ValueError(f"price history tuple length {len(ph)} != {len(names)}")
    return dict(zip(names, ph))


def compute_minute_strike_span(
    conn: Any,
    calc: LookupProbabilityCalculator,
    *,
    market_ticker: str,
    bar_timestamp_end_naive_et: datetime,
    floor_strike: Any,
    price_history_row: tuple[Any, ...],
    yes_ask_low_dollars: Optional[float],
    yes_ask_high_dollars: Optional[float],
) -> tuple[Any, ...]:
    """Returns a tuple matching BACKTEST_STRIKE_SPAN_COLUMN_DEFS order."""
    null_row: tuple[Any, ...] = (None,) * len(BACKTEST_STRIKE_SPAN_COLUMN_DEFS)
    sym = probability_symbol_from_kalshi_ticker(market_ticker)
    if sym is None:
        return null_row

    strike = _f(floor_strike)
    ph = unpack_price_history_tuple(price_history_row)
    lo = _f(ph.get("low"))
    hi = _f(ph.get("high"))
    mom = ph.get("momentum_percentile")
    if strike is None or lo is None or hi is None:
        return null_row

    lo_s, hi_s = (lo, hi) if lo <= hi else (hi, lo)
    bar_low = lo_s
    bar_high = hi_s

    if strike > bar_high:
        active = "no"
        tradeable = True
    elif strike < bar_low:
        active = "yes"
        tradeable = True
    else:
        active = "cross"
        tradeable = False

    buf_low = _buffer_points(spot=bar_low, floor_strike=strike, symbol=sym)
    buf_high = _buffer_points(spot=bar_high, floor_strike=strike, symbol=sym)
    b_min = min(buf_low, buf_high)
    b_max = max(buf_low, buf_high)

    ts_close = _naive_et_to_aware(bar_timestamp_end_naive_et)
    ts_open = ts_close - timedelta(minutes=1)
    ttc_open = seconds_to_next_15m_boundary_ny(ts_open)
    ttc_close = seconds_to_next_15m_boundary_ny(ts_close)
    t_lo = min(ttc_open, ttc_close)
    t_hi = max(ttc_open, ttc_close)

    corners = ((t_hi, b_min), (t_hi, b_max), (t_lo, b_min), (t_lo, b_max))
    yes_samples: list[float] = []
    no_samples: list[float] = []
    mom_f = _f(mom)
    if mom_f is not None:
        m_bucket = int(round(mom_f))
        for ttc_s, buf in corners:
            pos, neg = calc.get_probability(int(ttc_s), float(buf), m_bucket, conn=conn)
            yc, nc = _corner_yes_no_probs(
                float(pos) if pos is not None else None,
                float(neg) if neg is not None else None,
                active,
            )
            if yc is not None:
                yes_samples.append(yc)
            if nc is not None:
                no_samples.append(nc)

    if not yes_samples or not no_samples:
        y_min = y_max = n_min = n_max = None
    else:
        y_min = min(yes_samples)
        y_max = max(yes_samples)
        n_min = min(no_samples)
        n_max = max(no_samples)

    def _r4(x: Optional[float]) -> Optional[float]:
        if x is None:
            return None
        return round(float(x), 4)

    yes_prob_min_r = _r4(y_min)
    yes_prob_max_r = _r4(y_max)
    no_prob_min_r = _r4(n_min)
    no_prob_max_r = _r4(n_max)

    ya_lo = yes_ask_low_dollars
    ya_hi = yes_ask_high_dollars
    no_ask_min_d, no_ask_max_d = implied_no_ask_min_max_from_yes_ask_bar(ya_lo, ya_hi)
    if ya_lo is not None and ya_hi is not None:
        yal, yah = (ya_lo, ya_hi) if ya_lo <= ya_hi else (ya_hi, ya_lo)
    else:
        yal = yah = None

    yd_lo = yd_hi = nd_lo = nd_hi = None
    if (
        tradeable
        and active in ("yes", "no")
        and y_min is not None
        and y_max is not None
        and n_min is not None
        and n_max is not None
        and ya_lo is not None
        and ya_hi is not None
        and no_ask_min_d is not None
        and no_ask_max_d is not None
    ):
        if active == "yes":
            p_corner_lo, p_corner_hi = yes_prob_min_r, yes_prob_max_r
        else:
            p_corner_lo, p_corner_hi = no_prob_min_r, no_prob_max_r

        pair_a = money_line_diffs_and_active_side(
            strike, bar_low, float(p_corner_lo), float(yal), float(no_ask_max_d)
        )
        pair_b = money_line_diffs_and_active_side(
            strike, bar_high, float(p_corner_hi), float(yah), float(no_ask_min_d)
        )
        if pair_a is None or pair_b is None:
            yd_lo = yd_hi = nd_lo = nd_hi = None
        else:
            ya1, na1, _ = pair_a
            ya2, na2, _ = pair_b
            yd_lo = min(ya1, ya2)
            yd_hi = max(ya1, ya2)
            nd_lo = min(na1, na2)
            nd_hi = max(na1, na2)

    return (
        active,
        tradeable,
        int(ttc_open),
        int(ttc_close),
        _dec(round(b_min, 8)),
        _dec(round(b_max, 8)),
        _dec(yes_prob_min_r),
        _dec(yes_prob_max_r),
        _dec(no_prob_min_r),
        _dec(no_prob_max_r),
        _dec(_r4(yd_lo)),
        _dec(_r4(yd_hi)),
        _dec(_r4(nd_lo)),
        _dec(_r4(nd_hi)),
    )
