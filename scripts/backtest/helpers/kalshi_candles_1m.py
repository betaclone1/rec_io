"""
Kalshi 1-minute candlesticks: fetch from Trade API (live series path, then historical)
and upsert into a Postgres table.

The request uses ``period_interval=1`` over ``open_time``..``close_time`` from ``GET /markets/{ticker}``,
so row count equals the session length in minutes (e.g. 15 for 15m markets, 60 for typical hourly).

- **Testing** (migrations): ``testing."candlesticks_1m_<ticker>"`` via ``quoted_table_for_ticker``.
- **Scratch / analysis**: ``historical_data.kalshi_candles_1m_<slug>_<YYYYMMDD>`` via
  ``scratch_table_name`` + ``ensure_scratch_table``.
- **Backtest** (durable): ``backtest.backtest_1m_<slug>`` (``<slug>`` from the market ticker via
  ``ticker_slug``) with ``floor_strike`` and
  ``market_result`` from ``GET /historical/markets`` ([Kalshi historical markets](https://docs.kalshi.com/api-reference/historical/get-historical-markets)),
  falling back to ``GET /markets/{ticker}`` when the historical archive has no row (common for recent markets).
  Tables are created with ``ensure_backtest_candles_with_meta_table`` (no per-ticker migrations).
  **NO price OHLC:** ``no_price_high`` = ``1 - yes_price_low``, ``no_price_low`` = ``1 - yes_price_high``
  (bar extrema; open/close/mean/previous still pair to the same YES slot). Clamped like other complements.
  **Running trade-price extrema:** each row carries ``yes_price_min_15m`` /
  ``yes_price_max_15m`` / ``yes_price_range_15m`` and ``no_price_*`` (suffix ``_15m``) cumulative
  from **contract open through that minute** — YES from Kalshi candle ``price.*`` low/high (trade
  / last OHLC); NO implied the same way as ``no_price_*`` vs ``yes_price_*`` (complement of YES
  extremes). Names use ``_15m`` for parity with strike-table-style snapshots; ingest may cover any
  session length.
  Ingest joins ``historical_data.btc_price_history`` / ``eth_price_history`` on Eastern-naive
  ``timestamp`` (``KXBTC*`` / ``KXETH*`` tickers) using the **same column names** as those tables
  (``open``, ``high``, …), and (by default) fills **strike-table span** columns for each 1m bar via
  ``backtest_strike_span`` (analytics lookups, ``scripts/backtest/helpers/backtest_strike_span.py``).
  **Row semantics (facts vs bounds, conservative replay):** see **Backtest row contract** in
  ``scripts/backtest/core_backtester.py`` module docstring.
  **Ingest guard:** ``run_fill_backtest_candles_with_meta`` loads the window and Kalshi candles first;
  for ``KXBTC*`` / ``KXETH*`` with spot join enabled, every bar minute must exist in
  ``btc_price_history`` / ``eth_price_history``. If candles are missing or spot coverage is incomplete,
  the run **skips** (no ``CREATE TABLE`` / upsert).
  **HTTP retries:** ``REC_IO_KALSHI_HTTP_RETRIES`` (default ``4``, max ``12``) controls attempts on
  timeouts / connection errors for Kalshi ``urllib`` GETs.

  **15m trading-day tickers:** ``scripts/backtest/helpers/kalshi_ticker_construct.py`` builds **96**
  tickers per Eastern calendar day (matches ``kalshi_contract_settlement_end_est`` / trade ``date``).

  CLI: ``core_backtester.py --ingest-kalshi-tickers ...``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

# Kalshi market tickers used in quoted identifiers (testing tables, etc.)
_KALSHI_MARKET_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+\-]*$")
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from zoneinfo import ZoneInfo

from scripts.backtest.helpers.backtest_price_history import (
    BACKTEST_PRICE_HISTORY_COLUMN_DEFS,
    empty_price_history_tuple,
    ensure_backtest_price_history_columns,
    fetch_price_history_rows_by_timestamps,
    normalize_price_history_ts,
    price_history_table_for_kalshi_ticker,
)
from scripts.backtest.helpers.backtest_strike_span import (
    BACKTEST_STRIKE_SPAN_COLUMN_DEFS,
    compute_minute_strike_span,
    ensure_backtest_strike_span_columns,
    implied_no_price_min_max_from_yes_price_bar,
    probability_symbol_from_kalshi_ticker,
    yes_ask_low_high_from_candle,
    yes_price_low_high_from_candle,
)

_BACKTEST_PH_INSERT_COLS = ", ".join(f'"{n}"' for n, _ in BACKTEST_PRICE_HISTORY_COLUMN_DEFS)
_BACKTEST_PH_UPDATE_EXCLUDED = ", ".join(
    f'"{n}" = EXCLUDED."{n}"' for n, _ in BACKTEST_PRICE_HISTORY_COLUMN_DEFS
)
_BACKTEST_PH_DDL_BLOCK = ",\n        ".join(
    f'"{name}" {typ}' for name, typ in BACKTEST_PRICE_HISTORY_COLUMN_DEFS
)

_BACKTEST_SPAN_INSERT_COLS = ", ".join(name for name, _ in BACKTEST_STRIKE_SPAN_COLUMN_DEFS)
_BACKTEST_SPAN_UPDATE_EXCLUDED = ", ".join(
    f"{name} = EXCLUDED.{name}" for name, _ in BACKTEST_STRIKE_SPAN_COLUMN_DEFS
)
_BACKTEST_SPAN_VALUES_PLACEHOLDERS = ", ".join(["%s"] * len(BACKTEST_STRIKE_SPAN_COLUMN_DEFS))

# Cumulative min/max/range of YES trade price and implied NO **from contract open through this bar**
# (Kalshi ``price.*`` YES OHLC; ``_15m`` suffix matches strike-style naming — not limited to 15m bars).
_BACKTEST_CYCLE_PRICE_15M_COLS: tuple[str, ...] = (
    "yes_price_min_15m",
    "yes_price_max_15m",
    "no_price_min_15m",
    "no_price_max_15m",
    "yes_price_range_15m",
    "no_price_range_15m",
)
_BACKTEST_CYCLE_PRICE_15M_INSERT_COLS = ", ".join(_BACKTEST_CYCLE_PRICE_15M_COLS)
_BACKTEST_CYCLE_PRICE_15M_UPDATE_EXCLUDED = ", ".join(
    f"{c} = EXCLUDED.{c}" for c in _BACKTEST_CYCLE_PRICE_15M_COLS
)
_BACKTEST_CYCLE_PRICE_15M_VALUES_PLACEHOLDERS = ", ".join(["%s"] * len(_BACKTEST_CYCLE_PRICE_15M_COLS))

# Backtest table: Kalshi ``price.*`` = YES; NO mirror is 1 − yes (clamped). High/low use opposite YES extrema (see module doc).
_BACKTEST_KALSHI_YES_PRICE_COLS: tuple[str, ...] = (
    "yes_price_open_dollars",
    "yes_price_high_dollars",
    "yes_price_low_dollars",
    "yes_price_close_dollars",
    "yes_price_mean_dollars",
    "yes_price_previous_dollars",
)
_BACKTEST_KALSHI_NO_PRICE_COLS: tuple[str, ...] = (
    "no_price_open_dollars",
    "no_price_high_dollars",
    "no_price_low_dollars",
    "no_price_close_dollars",
    "no_price_mean_dollars",
    "no_price_previous_dollars",
)
_BACKTEST_KALSHI_ALL_PRICE_COLS: tuple[str, ...] = _BACKTEST_KALSHI_YES_PRICE_COLS + _BACKTEST_KALSHI_NO_PRICE_COLS
_BACKTEST_KALSHI_PRICE_INSERT_COLS = ", ".join(_BACKTEST_KALSHI_ALL_PRICE_COLS)
_BACKTEST_KALSHI_PRICE_UPDATE_EXCLUDED = ", ".join(
    f"{c} = EXCLUDED.{c}" for c in _BACKTEST_KALSHI_ALL_PRICE_COLS
)
_BACKTEST_LEGACY_PRICE_TO_YES: tuple[tuple[str, str], ...] = (
    ("price_open_dollars", "yes_price_open_dollars"),
    ("price_high_dollars", "yes_price_high_dollars"),
    ("price_low_dollars", "yes_price_low_dollars"),
    ("price_close_dollars", "yes_price_close_dollars"),
    ("price_mean_dollars", "yes_price_mean_dollars"),
    ("price_previous_dollars", "yes_price_previous_dollars"),
)
_BACKTEST_REL_RE = re.compile(r"^backtest_1m_[a-z0-9_]+$")
_BACKTEST_UPSERT_FIRST_LINE_PLACEHOLDERS = ", ".join(["%s"] * (3 + 12 + 8 + 2 + 2))
_BACKTEST_PH_ROW_PLACEHOLDERS = ", ".join(["%s"] * len(BACKTEST_PRICE_HISTORY_COLUMN_DEFS))


@dataclass(frozen=True)
class BacktestCandlesIngestResult:
    """Outcome of ``run_fill_backtest_candles_with_meta`` (normal ingest or skip with no DDL/DML)."""

    open_ts: int
    close_ts: int
    row_count: int
    metadata_source: str
    price_history_hits: int
    skipped: bool = False
    skip_reason: str | None = None


KALSHI_TRADE_V2 = "https://external-api.kalshi.com/trade-api/v2"
_EASTERN = ZoneInfo("America/New_York")

SCRATCH_TABLE_PREFIX = "kalshi_candles_1m_"
# historical_data.kalshi_candles_1m_<slug>_<YYYYMMDD>
_SCRATCH_NAME_RE = re.compile(r"^kalshi_candles_1m_([a-z0-9_]+)_(\d{8})$")


def validate_kalshi_market_ticker(market_ticker: str) -> str:
    """Raise ValueError if ticker cannot be embedded safely in a quoted SQL identifier."""
    t = market_ticker.strip()
    if not _KALSHI_MARKET_TICKER_RE.fullmatch(t):
        raise ValueError(
            f"Invalid Kalshi market ticker for SQL identifier: {market_ticker!r} "
            "(allowed: letters, digits, '.', '+', '-'; must start with alphanumeric)."
        )
    return t


def quoted_table_for_ticker(market_ticker: str) -> str:
    t = validate_kalshi_market_ticker(market_ticker)
    return f'testing."candlesticks_1m_{t}"'


def ticker_slug(market_ticker: str) -> str:
    s = market_ticker.strip().lower().replace("-", "_").replace(".", "_")
    if len(s) > 40:
        h = hashlib.sha256(market_ticker.encode("utf-8")).hexdigest()[:14]
        return f"h{h}"
    if not re.fullmatch(r"[a-z0-9_]+", s):
        raise ValueError(f"Cannot derive safe table slug from ticker: {market_ticker!r}")
    return s


def scratch_table_name(market_ticker: str, as_of: date) -> str:
    """Unquoted relation name: kalshi_candles_1m_<slug>_YYYYMMDD (UTC calendar date)."""
    suf = as_of.strftime("%Y%m%d")
    return f"{SCRATCH_TABLE_PREFIX}{ticker_slug(market_ticker)}_{suf}"


def scratch_table_qualified(relname: str) -> str:
    """Validated ``historical_data.<relname>`` for SQL (identifier-safe)."""
    if not re.fullmatch(r"[a-z0-9_]+", relname):
        raise ValueError(f"Invalid scratch table name: {relname!r}")
    return f"historical_data.{relname}"


def infer_series_ticker(market_ticker: str) -> str:
    return market_ticker.split("-", 1)[0]


def end_period_ts_to_price_history_timestamp(end_period_ts: int) -> datetime:
    utc = datetime.fromtimestamp(end_period_ts, tz=timezone.utc)
    return utc.astimezone(_EASTERN).replace(tzinfo=None)


def _parse_iso_z(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def _no_contract_price_from_yes(yes_d: Decimal | None) -> Decimal | None:
    """NO Kalshi price in ~dollars from YES: ``1 - yes``, clamped (symmetric to other backtest helpers)."""
    if yes_d is None:
        return None
    x = float(yes_d)
    c = 1.0 - x
    c = max(0.001, min(0.999, c))
    return Decimal(str(round(c, 6)))


def _dollars(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, dict):
        inner = v.get("dollars") or v.get("fixed_point")
        if inner is None:
            return None
        v = inner
    s = str(v).strip()
    if not s:
        return None
    return Decimal(s)


def _fp_count(v: Any) -> Decimal | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return Decimal(s)


def _kalshi_http_attempts() -> int:
    """Attempts for transient failures (``REC_IO_KALSHI_HTTP_RETRIES``, default 4, cap 12)."""
    raw = (os.getenv("REC_IO_KALSHI_HTTP_RETRIES") or "4").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 4
    return max(1, min(n, 12))


def _http_json(url: str, timeout: int = 60) -> dict[str, Any]:
    """
    GET JSON from Kalshi with retries on timeouts and connection errors.

    Does not retry :class:`~urllib.error.HTTPError` (4xx/5xx); callers may handle 404, etc.
    """
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    attempts = _kalshi_http_attempts()
    last_err: BaseException | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt + 1 >= attempts:
                raise
            delay = min(45.0, (2**attempt) * 0.85)
            time.sleep(delay)
    raise RuntimeError("unreachable HTTP retry loop") from last_err


def fetch_market_window(market_ticker: str) -> tuple[int, int]:
    enc = urllib.parse.quote(market_ticker, safe="")
    data = _http_json(f"{KALSHI_TRADE_V2}/markets/{enc}", timeout=30)
    m = data.get("market") or {}
    ot = m.get("open_time")
    ct = m.get("close_time")
    if not ot or not ct:
        raise RuntimeError(f"market missing open_time/close_time: {m!r}")
    open_u = int(_parse_iso_z(ot).timestamp())
    close_u = int(_parse_iso_z(ct).timestamp())
    return open_u, close_u


def fetch_markets_payload(market_ticker: str) -> dict[str, Any]:
    """Raw ``GET /markets/{ticker}`` JSON (``market``, optional ``markets``, etc.)."""
    enc = urllib.parse.quote(market_ticker, safe="")
    data = _http_json(f"{KALSHI_TRADE_V2}/markets/{enc}", timeout=30)
    if not data.get("market") and not data.get("markets"):
        raise RuntimeError(f"empty markets payload for {market_ticker!r}")
    return data


def fetch_market_dict(market_ticker: str) -> dict[str, Any]:
    """``GET /markets/{ticker}`` — returns the ``market`` object (floor_strike, status, etc.)."""
    data = fetch_markets_payload(market_ticker)
    m = data.get("market") or {}
    if not m:
        raise RuntimeError(f"empty market object for {market_ticker!r}")
    return m


def fetch_candles_1m(
    series_ticker: str,
    market_ticker: str,
    start_ts: int,
    end_ts: int,
) -> list[dict[str, Any]]:
    enc = urllib.parse.quote(market_ticker, safe="")
    live = (
        f"{KALSHI_TRADE_V2}/series/{series_ticker}/markets/{enc}/candlesticks"
        f"?start_ts={start_ts}&end_ts={end_ts}&period_interval=1"
    )
    data: dict[str, Any] | None = None
    try:
        data = _http_json(live, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    if data and "error" not in data and data.get("candlesticks") is not None:
        return list(data["candlesticks"])

    hist = (
        f"{KALSHI_TRADE_V2}/historical/markets/{enc}/candlesticks"
        f"?start_ts={start_ts}&end_ts={end_ts}&period_interval=1"
    )
    data = _http_json(hist, timeout=60)
    if "error" in data:
        raise RuntimeError(f"Kalshi candlesticks failed (historical): {data}")
    return list(data.get("candlesticks") or [])


def candle_row(market_ticker: str, c: dict[str, Any]) -> tuple[Any, ...]:
    end_ts = int(c["end_period_ts"])
    price = c.get("price") or {}
    # Kalshi candle JSON nests bid/ask OHLC under keys built from yes_ + bid/ask (API shape).
    _k_yb = "yes" + "_bid"
    _k_ya = "yes" + "_ask"
    yb = c.get(_k_yb) or {}
    ya = c.get(_k_ya) or {}
    return (
        end_period_ts_to_price_history_timestamp(end_ts),
        end_ts,
        market_ticker,
        _dollars(price.get("open_dollars")),
        _dollars(price.get("high_dollars")),
        _dollars(price.get("low_dollars")),
        _dollars(price.get("close_dollars")),
        _dollars(price.get("mean_dollars")),
        _dollars(price.get("previous_dollars")),
        _dollars(yb.get("open_dollars")),
        _dollars(yb.get("high_dollars")),
        _dollars(yb.get("low_dollars")),
        _dollars(yb.get("close_dollars")),
        _dollars(ya.get("open_dollars")),
        _dollars(ya.get("high_dollars")),
        _dollars(ya.get("low_dollars")),
        _dollars(ya.get("close_dollars")),
        _fp_count(c.get("volume_fp")),
        _fp_count(c.get("open_interest_fp")),
    )


def candle_row_backtest(market_ticker: str, c: dict[str, Any]) -> tuple[Any, ...]:
    """Same shape as ``candle_row`` but YES/NO contract price columns (Kalshi ``price`` = YES only)."""
    end_ts = int(c["end_period_ts"])
    price = c.get("price") or {}
    _k_yb = "yes" + "_bid"
    _k_ya = "yes" + "_ask"
    yb = c.get(_k_yb) or {}
    ya = c.get(_k_ya) or {}
    ypo = _dollars(price.get("open_dollars"))
    yph = _dollars(price.get("high_dollars"))
    ypl = _dollars(price.get("low_dollars"))
    ypc = _dollars(price.get("close_dollars"))
    ypm = _dollars(price.get("mean_dollars"))
    ypp = _dollars(price.get("previous_dollars"))
    return (
        end_period_ts_to_price_history_timestamp(end_ts),
        end_ts,
        market_ticker,
        ypo,
        yph,
        ypl,
        ypc,
        ypm,
        ypp,
        _no_contract_price_from_yes(ypo),
        # Bar extrema: NO is highest when YES is lowest and vice versa (NO ≈ 1 − YES).
        _no_contract_price_from_yes(ypl),
        _no_contract_price_from_yes(yph),
        _no_contract_price_from_yes(ypc),
        _no_contract_price_from_yes(ypm),
        _no_contract_price_from_yes(ypp),
        _dollars(yb.get("open_dollars")),
        _dollars(yb.get("high_dollars")),
        _dollars(yb.get("low_dollars")),
        _dollars(yb.get("close_dollars")),
        _dollars(ya.get("open_dollars")),
        _dollars(ya.get("high_dollars")),
        _dollars(ya.get("low_dollars")),
        _dollars(ya.get("close_dollars")),
        _fp_count(c.get("volume_fp")),
        _fp_count(c.get("open_interest_fp")),
    )


def candle_row_with_settlement_meta_backtest(
    market_ticker: str,
    c: dict[str, Any],
    floor_strike: Decimal | None,
    market_result: str | None,
) -> tuple[Any, ...]:
    return candle_row_backtest(market_ticker, c) + (floor_strike, market_result)


def candle_row_with_settlement_and_price_history_backtest(
    market_ticker: str,
    c: dict[str, Any],
    floor_strike: Decimal | None,
    market_result: str | None,
    price_history: tuple[Any, ...],
) -> tuple[Any, ...]:
    n = len(BACKTEST_PRICE_HISTORY_COLUMN_DEFS)
    if len(price_history) != n:
        raise ValueError(f"price_history tuple must have {n} values")
    return candle_row_with_settlement_meta_backtest(market_ticker, c, floor_strike, market_result) + price_history


UPSERT_SQL = """
    INSERT INTO {table} (
      "timestamp", end_period_ts, market_ticker,
      price_open_dollars, price_high_dollars, price_low_dollars, price_close_dollars,
      price_mean_dollars, price_previous_dollars,
      yes_bid_open_dollars, yes_bid_high_dollars, yes_bid_low_dollars, yes_bid_close_dollars,
      yes_ask_open_dollars, yes_ask_high_dollars, yes_ask_low_dollars, yes_ask_close_dollars,
      volume_fp, open_interest_fp
    ) VALUES (
      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (end_period_ts) DO UPDATE SET
      "timestamp" = EXCLUDED."timestamp",
      market_ticker = EXCLUDED.market_ticker,
      price_open_dollars = EXCLUDED.price_open_dollars,
      price_high_dollars = EXCLUDED.price_high_dollars,
      price_low_dollars = EXCLUDED.price_low_dollars,
      price_close_dollars = EXCLUDED.price_close_dollars,
      price_mean_dollars = EXCLUDED.price_mean_dollars,
      price_previous_dollars = EXCLUDED.price_previous_dollars,
      yes_bid_open_dollars = EXCLUDED.yes_bid_open_dollars,
      yes_bid_high_dollars = EXCLUDED.yes_bid_high_dollars,
      yes_bid_low_dollars = EXCLUDED.yes_bid_low_dollars,
      yes_bid_close_dollars = EXCLUDED.yes_bid_close_dollars,
      yes_ask_open_dollars = EXCLUDED.yes_ask_open_dollars,
      yes_ask_high_dollars = EXCLUDED.yes_ask_high_dollars,
      yes_ask_low_dollars = EXCLUDED.yes_ask_low_dollars,
      yes_ask_close_dollars = EXCLUDED.yes_ask_close_dollars,
      volume_fp = EXCLUDED.volume_fp,
      open_interest_fp = EXCLUDED.open_interest_fp
"""

BACKTEST_1M_TABLE_PREFIX = "backtest_1m_"
_BACKTEST_FQ_TABLE_RE = re.compile(r"^backtest\.backtest_1m_[a-z0-9_]+$")


def _strike_decimal_from_api(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip()
    if not s:
        return None
    return Decimal(s)


_SERIES_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


def validate_kalshi_series_ticker(series_ticker: str) -> str:
    """Raise ValueError if series ticker is unsafe or empty for Kalshi query params."""
    s = series_ticker.strip()
    if not s or not _SERIES_TICKER_RE.fullmatch(s):
        raise ValueError(
            f"Invalid Kalshi series ticker for API: {series_ticker!r} "
            "(allowed: letters, digits, underscore, hyphen; must start with alphanumeric)."
        )
    return s


def discover_market_tickers_by_series_close_window(
    series_ticker: str,
    min_close_ts: int,
    max_close_ts: int,
    *,
    page_limit: int = 1000,
) -> list[str]:
    """
    Paginate ``GET /markets`` with ``series_ticker``, ``min_close_ts``, ``max_close_ts`` (Unix UTC).

    Uses Kalshi **Get Markets** close-time filters. Markets only in ``GET /historical/markets``
    (pre-cutoff archive) may not appear; shorten the window or ingest explicit tickers if needed.
    """
    st = validate_kalshi_series_ticker(series_ticker)
    if min_close_ts >= max_close_ts:
        raise ValueError("min_close_ts must be strictly less than max_close_ts")
    cap = max(1, min(int(page_limit), 1000))
    raw: list[str] = []
    cursor = ""
    while True:
        params: list[tuple[str, str]] = [
            ("series_ticker", st),
            ("min_close_ts", str(int(min_close_ts))),
            ("max_close_ts", str(int(max_close_ts))),
            ("limit", str(cap)),
        ]
        if cursor:
            params.append(("cursor", cursor))
        q = urllib.parse.urlencode(params)
        data = _http_json(f"{KALSHI_TRADE_V2}/markets?{q}", timeout=120)
        markets = data.get("markets") or []
        for m in markets:
            t = m.get("ticker")
            if not t:
                continue
            try:
                validate_kalshi_market_ticker(str(t))
            except ValueError:
                continue
            raw.append(str(t))
        cursor = str(data.get("cursor") or "").strip()
        if not cursor:
            break
    seen: set[str] = set()
    uniq: list[str] = []
    for t in raw:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def fetch_historical_markets_by_tickers(
    market_tickers: list[str],
    *,
    limit: int = 100,
    cursor: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """``GET /historical/markets`` with comma-separated ``tickers`` query param."""
    if not market_tickers:
        return [], ""
    params: list[tuple[str, str]] = [
        ("tickers", ",".join(market_tickers)),
        ("limit", str(limit)),
    ]
    if cursor:
        params.append(("cursor", cursor))
    q = urllib.parse.urlencode(params)
    data = _http_json(f"{KALSHI_TRADE_V2}/historical/markets?{q}", timeout=60)
    return list(data.get("markets") or []), str(data.get("cursor") or "")


def resolve_floor_strike_and_market_result(market_ticker: str) -> tuple[Decimal | None, str | None, str]:
    """
    Returns ``(floor_strike, market_result, source)`` where ``source`` is ``historical`` or ``live``.

    Uses archived markets when available; otherwise the live market object (same fields).
    """
    ticker = validate_kalshi_market_ticker(market_ticker)
    markets, _ = fetch_historical_markets_by_tickers([ticker])
    for m in markets:
        if m.get("ticker") == ticker:
            fs = _strike_decimal_from_api(m.get("floor_strike"))
            res = m.get("result")
            mr = str(res).strip() if res is not None else None
            if mr == "":
                mr = None
            return fs, mr, "historical"
    live = fetch_market_dict(ticker)
    fs = _strike_decimal_from_api(live.get("floor_strike"))
    res = live.get("result")
    mr = str(res).strip() if res is not None else None
    if mr == "":
        mr = None
    return fs, mr, "live"


def candle_row_with_settlement_meta(
    market_ticker: str,
    c: dict[str, Any],
    floor_strike: Decimal | None,
    market_result: str | None,
) -> tuple[Any, ...]:
    return candle_row(market_ticker, c) + (floor_strike, market_result)


def candle_row_with_settlement_and_price_history(
    market_ticker: str,
    c: dict[str, Any],
    floor_strike: Decimal | None,
    market_result: str | None,
    price_history: tuple[Any, ...],
) -> tuple[Any, ...]:
    n = len(BACKTEST_PRICE_HISTORY_COLUMN_DEFS)
    if len(price_history) != n:
        raise ValueError(f"price_history tuple must have {n} values")
    return candle_row_with_settlement_meta(market_ticker, c, floor_strike, market_result) + price_history


def ensure_backtest_cycle_running_price_15m_columns(conn: Any, rel: str) -> None:
    """Add cumulative contract-window YES/NO **trade price** min/max/range columns (running through each bar)."""
    if not _BACKTEST_REL_RE.match(rel):
        raise ValueError(f"invalid backtest table rel: {rel!r}")
    parts = [f'ADD COLUMN IF NOT EXISTS "{c}" NUMERIC(20, 6)' for c in _BACKTEST_CYCLE_PRICE_15M_COLS]
    with conn.cursor() as cur:
        cur.execute(f"ALTER TABLE backtest.{rel} " + ", ".join(parts) + ";")


def _cycle_running_price_15m_db_tuple(
    run_yes_min: float | None,
    run_yes_max: float | None,
    run_no_min: float | None,
    run_no_max: float | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    if run_yes_min is None or run_yes_max is None:
        ymn = ymx = yr = None
    else:
        ymn = Decimal(str(round(float(run_yes_min), 6)))
        ymx = Decimal(str(round(float(run_yes_max), 6)))
        yr = Decimal(str(round(float(run_yes_max) - float(run_yes_min), 6)))
    if run_no_min is None or run_no_max is None:
        nmn = nmx = nr = None
    else:
        nmn = Decimal(str(round(float(run_no_min), 6)))
        nmx = Decimal(str(round(float(run_no_max), 6)))
        nr = Decimal(str(round(float(run_no_max) - float(run_no_min), 6)))
    return (ymn, ymx, nmn, nmx, yr, nr)


def ensure_backtest_kalshi_yes_no_price_columns(conn: Any, rel: str) -> None:
    """
    Rename legacy ``price_*_dollars`` → ``yes_price_*_dollars`` if present, then ensure
    all ``yes_price_*`` and ``no_price_*`` Kalshi candle columns exist.
    """
    if not _BACKTEST_REL_RE.match(rel):
        raise ValueError(f"invalid backtest table rel: {rel!r}")
    with conn.cursor() as cur:
        for old, new in _BACKTEST_LEGACY_PRICE_TO_YES:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'backtest' AND table_name = %s AND column_name = %s
                """,
                (rel, old),
            )
            if not cur.fetchone():
                continue
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'backtest' AND table_name = %s AND column_name = %s
                """,
                (rel, new),
            )
            if cur.fetchone():
                continue
            cur.execute(f'ALTER TABLE backtest.{rel} RENAME COLUMN "{old}" TO "{new}";')
        parts = [
            f'ADD COLUMN IF NOT EXISTS "{name}" NUMERIC(20, 6)' for name in _BACKTEST_KALSHI_ALL_PRICE_COLS
        ]
        cur.execute(f"ALTER TABLE backtest.{rel} " + ", ".join(parts) + ";")


UPSERT_BACKTEST_CANDLES_WITH_META_SQL = (
    """
    INSERT INTO {table} (
      "timestamp", end_period_ts, market_ticker,
      """
    + _BACKTEST_KALSHI_PRICE_INSERT_COLS
    + """,
      yes_bid_open_dollars, yes_bid_high_dollars, yes_bid_low_dollars, yes_bid_close_dollars,
      yes_ask_open_dollars, yes_ask_high_dollars, yes_ask_low_dollars, yes_ask_close_dollars,
      volume_fp, open_interest_fp,
      floor_strike, market_result,
      """
    + _BACKTEST_PH_INSERT_COLS
    + ", "
    + _BACKTEST_SPAN_INSERT_COLS
    + ", "
    + _BACKTEST_CYCLE_PRICE_15M_INSERT_COLS
    + """
    ) VALUES (
      """
    + _BACKTEST_UPSERT_FIRST_LINE_PLACEHOLDERS
    + """,
      """
    + _BACKTEST_PH_ROW_PLACEHOLDERS
    + ", "
    + _BACKTEST_SPAN_VALUES_PLACEHOLDERS
    + ", "
    + _BACKTEST_CYCLE_PRICE_15M_VALUES_PLACEHOLDERS
    + """
    )
    ON CONFLICT (end_period_ts) DO UPDATE SET
      "timestamp" = EXCLUDED."timestamp",
      market_ticker = EXCLUDED.market_ticker,
      """
    + _BACKTEST_KALSHI_PRICE_UPDATE_EXCLUDED.replace(", ", ",\n      ")
    + """,
      yes_bid_open_dollars = EXCLUDED.yes_bid_open_dollars,
      yes_bid_high_dollars = EXCLUDED.yes_bid_high_dollars,
      yes_bid_low_dollars = EXCLUDED.yes_bid_low_dollars,
      yes_bid_close_dollars = EXCLUDED.yes_bid_close_dollars,
      yes_ask_open_dollars = EXCLUDED.yes_ask_open_dollars,
      yes_ask_high_dollars = EXCLUDED.yes_ask_high_dollars,
      yes_ask_low_dollars = EXCLUDED.yes_ask_low_dollars,
      yes_ask_close_dollars = EXCLUDED.yes_ask_close_dollars,
      volume_fp = EXCLUDED.volume_fp,
      open_interest_fp = EXCLUDED.open_interest_fp,
      floor_strike = EXCLUDED.floor_strike,
      market_result = EXCLUDED.market_result,
      """
    + _BACKTEST_PH_UPDATE_EXCLUDED
    + ",\n      "
    + _BACKTEST_SPAN_UPDATE_EXCLUDED.replace(", ", ",\n      ")
    + ",\n      "
    + _BACKTEST_CYCLE_PRICE_15M_UPDATE_EXCLUDED.replace(", ", ",\n      ")
    + "\n"
)


def backtest_candles_relname(market_ticker: str) -> str:
    """Unquoted relation name: ``backtest_1m_<slug>`` (slug from ``ticker_slug``)."""
    t = validate_kalshi_market_ticker(market_ticker)
    rel = f"{BACKTEST_1M_TABLE_PREFIX}{ticker_slug(t)}"
    if not re.fullmatch(r"backtest_1m_[a-z0-9_]+", rel):
        raise ValueError(f"invalid derived table name: {rel!r}")
    return rel


def qualified_backtest_candles_table(market_ticker: str) -> str:
    """``backtest.backtest_1m_<slug>`` (create with ``ensure_backtest_candles_with_meta_table``)."""
    rel = backtest_candles_relname(market_ticker)
    fq = f"backtest.{rel}"
    if not _BACKTEST_FQ_TABLE_RE.match(fq):
        raise ValueError(f"derived backtest table name failed validation: {fq!r}")
    return fq


def ensure_backtest_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS backtest;")


def ensure_backtest_candles_with_meta_table(conn: Any, market_ticker: str) -> str:
    """
    ``CREATE SCHEMA IF NOT EXISTS backtest`` and ``CREATE TABLE IF NOT EXISTS`` for
    ``backtest.backtest_1m_<slug>`` (1m OHLC + ``floor_strike``, ``market_result``).

    Returns the fully qualified table name (validated).
    """
    ensure_backtest_schema(conn)
    ticker = validate_kalshi_market_ticker(market_ticker)
    rel = backtest_candles_relname(ticker)
    esc = ticker.replace("'", "''")
    yes_no_price_ddl = ",\n        ".join(f"{c} NUMERIC(20, 6)" for c in _BACKTEST_KALSHI_ALL_PRICE_COLS)
    ddl = (
        f"""
    CREATE TABLE IF NOT EXISTS backtest.{rel} (
        "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        end_period_ts BIGINT NOT NULL,
        market_ticker TEXT NOT NULL DEFAULT '{esc}',
        {yes_no_price_ddl},
        yes_bid_open_dollars NUMERIC(20, 6),
        yes_bid_high_dollars NUMERIC(20, 6),
        yes_bid_low_dollars NUMERIC(20, 6),
        yes_bid_close_dollars NUMERIC(20, 6),
        yes_ask_open_dollars NUMERIC(20, 6),
        yes_ask_high_dollars NUMERIC(20, 6),
        yes_ask_low_dollars NUMERIC(20, 6),
        yes_ask_close_dollars NUMERIC(20, 6),
        volume_fp NUMERIC(20, 2),
        open_interest_fp NUMERIC(20, 2),
        floor_strike NUMERIC(24, 8),
        market_result TEXT,
        """
        + _BACKTEST_PH_DDL_BLOCK
        + """
        ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (end_period_ts)
    );
    """
    )
    comment = (
        "Kalshi 1m candles + floor_strike/market_result + price_history columns (open, high, …). "
        "Created by ensure_backtest_candles_with_meta_table / core_backtester --ingest-kalshi-tickers."
    )
    fq = f"backtest.{rel}"
    with conn.cursor() as cur:
        cur.execute(ddl)
        cur.execute(
            f"COMMENT ON TABLE backtest.{rel} IS %s",
            (comment,),
        )
    ensure_backtest_kalshi_yes_no_price_columns(conn, rel)
    ensure_backtest_price_history_columns(conn, rel)
    ensure_backtest_strike_span_columns(conn, rel)
    ensure_backtest_cycle_running_price_15m_columns(conn, rel)
    if not _BACKTEST_FQ_TABLE_RE.match(fq):
        raise ValueError(f"derived backtest table name failed validation: {fq!r}")
    return fq


def run_fill_backtest_candles_with_meta(
    conn: Any,
    market_ticker: str,
    *,
    target_table: str | None = None,
    series_ticker: str | None = None,
    ensure_table: bool = True,
    include_spot: bool = True,
    include_strike_span: bool = True,
) -> BacktestCandlesIngestResult:
    """
    Fetch 1m candles for the market window and upsert into ``backtest.*`` with
    ``floor_strike`` / ``market_result`` on every row, and price-history columns (``open``, ``high``, …)
    joined from ``historical_data.btc_price_history`` or ``eth_price_history`` when ``include_spot``
    is True and the ticker prefix maps to a table (``KXBTC*``, ``KXETH*``).

    **Preflight:** requires Kalshi candlesticks for the window. When ``include_spot`` is True and
    the ticker maps to BTC/ETH price history, every bar minute must exist in that table; otherwise
    the run skips with no ``CREATE TABLE`` / upsert.

    When ``include_strike_span`` is True (default), fills per-minute strike-table span columns
    (``active_side``, ``ttc_15m_open/close_seconds``, prob/diff min/max, etc.) using
    ``scripts.backtest.helpers.backtest_strike_span`` (analytics probability lookups).

    When ``ensure_table`` is True (default), creates ``backtest`` schema and the target
    table if missing (only after preflight passes).

    Returns ``BacktestCandlesIngestResult`` (``skipped`` / ``skip_reason`` when guard trips).
    """
    ticker = validate_kalshi_market_ticker(market_ticker)
    fq = target_table or qualified_backtest_candles_table(ticker)
    if not _BACKTEST_FQ_TABLE_RE.match(fq):
        raise ValueError(f"invalid target_table: {fq!r}")
    rel = fq.split(".", 1)[1]
    series = series_ticker or infer_series_ticker(ticker)
    open_u, close_u = fetch_market_window(ticker)
    candles = fetch_candles_1m(series, ticker, open_u, close_u)
    if not candles:
        return BacktestCandlesIngestResult(
            open_ts=open_u,
            close_ts=close_u,
            row_count=0,
            metadata_source="",
            price_history_hits=0,
            skipped=True,
            skip_reason="no Kalshi 1m candlesticks for this market window",
        )

    ph_by_ts: dict[datetime, tuple[Any, ...]] = {}
    ph_table = price_history_table_for_kalshi_ticker(ticker)
    if include_spot and ph_table:
        ts_keys = [
            normalize_price_history_ts(end_period_ts_to_price_history_timestamp(int(c["end_period_ts"])))
            for c in candles
        ]
        ph_by_ts = fetch_price_history_rows_by_timestamps(conn, ticker, ts_keys)
        n_bar = len(candles)
        n_ph = sum(1 for ts in ts_keys if ts in ph_by_ts)
        if n_ph < n_bar:
            return BacktestCandlesIngestResult(
                open_ts=open_u,
                close_ts=close_u,
                row_count=0,
                metadata_source="",
                price_history_hits=n_ph,
                skipped=True,
                skip_reason=(
                    f"incomplete historical_data spot series: {n_ph}/{n_bar} minute rows in {ph_table}"
                ),
            )

    floor_strike, market_result, source = resolve_floor_strike_and_market_result(ticker)

    if ensure_table and not target_table:
        ensure_backtest_candles_with_meta_table(conn, ticker)
    elif ensure_table and target_table:
        ensure_backtest_schema(conn)
        ensure_backtest_kalshi_yes_no_price_columns(conn, rel)
        ensure_backtest_price_history_columns(conn, rel)
        ensure_backtest_strike_span_columns(conn, rel)
        ensure_backtest_cycle_running_price_15m_columns(conn, rel)
    else:
        ensure_backtest_kalshi_yes_no_price_columns(conn, rel)
        ensure_backtest_price_history_columns(conn, rel)
        ensure_backtest_strike_span_columns(conn, rel)
        ensure_backtest_cycle_running_price_15m_columns(conn, rel)

    rows: list[tuple[Any, ...]] = []
    price_history_hits = 0
    ph_aware = include_spot and bool(price_history_table_for_kalshi_ticker(ticker))
    span_nulls = (None,) * len(BACKTEST_STRIKE_SPAN_COLUMN_DEFS)
    calc = None
    prob_sym = probability_symbol_from_kalshi_ticker(ticker)
    if include_strike_span and prob_sym:
        from backend.strike_table_generator import LookupProbabilityCalculator

        calc = LookupProbabilityCalculator(prob_sym)

    candles_sorted = sorted(candles, key=lambda c: int(c["end_period_ts"]))
    run_yes_min: float | None = None
    run_yes_max: float | None = None
    run_no_min: float | None = None
    run_no_max: float | None = None

    for c in candles_sorted:
        ts = normalize_price_history_ts(
            end_period_ts_to_price_history_timestamp(int(c["end_period_ts"]))
        )
        if ph_aware:
            ph_t = ph_by_ts.get(ts, empty_price_history_tuple())
            if ts in ph_by_ts:
                price_history_hits += 1
        else:
            ph_t = empty_price_history_tuple()
        base = candle_row_with_settlement_and_price_history_backtest(
            ticker, c, floor_strike, market_result, ph_t
        )
        ypl, yph = yes_price_low_high_from_candle(c)
        if ypl is not None and yph is not None:
            yal, yah = (ypl, yph) if ypl <= yph else (yph, ypl)
            run_yes_min = yal if run_yes_min is None else min(run_yes_min, yal)
            run_yes_max = yah if run_yes_max is None else max(run_yes_max, yah)
            n_lo, n_hi = implied_no_price_min_max_from_yes_price_bar(ypl, yph)
            if n_lo is not None and n_hi is not None:
                run_no_min = n_lo if run_no_min is None else min(run_no_min, n_lo)
                run_no_max = n_hi if run_no_max is None else max(run_no_max, n_hi)

        cycle_t = _cycle_running_price_15m_db_tuple(run_yes_min, run_yes_max, run_no_min, run_no_max)

        ya_lo, ya_hi = yes_ask_low_high_from_candle(c)
        if calc is not None:
            span_t = compute_minute_strike_span(
                conn,
                calc,
                market_ticker=ticker,
                bar_timestamp_end_naive_et=ts,
                floor_strike=floor_strike,
                price_history_row=ph_t,
                yes_ask_low_dollars=ya_lo,
                yes_ask_high_dollars=ya_hi,
            )
        else:
            span_t = span_nulls
        rows.append(base + span_t + cycle_t)

    sql = UPSERT_BACKTEST_CANDLES_WITH_META_SQL.format(table=fq)
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return BacktestCandlesIngestResult(
        open_ts=open_u,
        close_ts=close_u,
        row_count=len(rows),
        metadata_source=source,
        price_history_hits=price_history_hits,
    )


def ensure_historical_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS historical_data;")


def ensure_scratch_table(conn: Any, relname: str, market_ticker: str) -> None:
    """CREATE TABLE IF NOT EXISTS historical_data.<relname> (same layout as testing candle tables)."""
    _ = scratch_table_qualified(relname)  # validate relname
    esc = market_ticker.replace("'", "''")
    ddl = f"""
    CREATE TABLE IF NOT EXISTS historical_data.{relname} (
        "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        end_period_ts BIGINT NOT NULL,
        market_ticker TEXT NOT NULL DEFAULT '{esc}',
        price_open_dollars NUMERIC(20, 6),
        price_high_dollars NUMERIC(20, 6),
        price_low_dollars NUMERIC(20, 6),
        price_close_dollars NUMERIC(20, 6),
        price_mean_dollars NUMERIC(20, 6),
        price_previous_dollars NUMERIC(20, 6),
        yes_bid_open_dollars NUMERIC(20, 6),
        yes_bid_high_dollars NUMERIC(20, 6),
        yes_bid_low_dollars NUMERIC(20, 6),
        yes_bid_close_dollars NUMERIC(20, 6),
        yes_ask_open_dollars NUMERIC(20, 6),
        yes_ask_high_dollars NUMERIC(20, 6),
        yes_ask_low_dollars NUMERIC(20, 6),
        yes_ask_close_dollars NUMERIC(20, 6),
        volume_fp NUMERIC(20, 2),
        open_interest_fp NUMERIC(20, 2),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (end_period_ts)
    );
    """
    comment = (
        "Ephemeral Kalshi 1m candles (scratch). Safe to DROP. "
        "Suffix date = UTC calendar day the table was created."
    )
    with conn.cursor() as cur:
        cur.execute(ddl)
        cur.execute(
            f"COMMENT ON TABLE historical_data.{relname} IS %s",
            (comment,),
        )


def cleanup_stale_scratch_tables(
    conn: Any,
    *,
    retention_days: int = 1,
    dry_run: bool = False,
) -> list[str]:
    """
    Drop ``historical_data.kalshi_candles_1m_*_YYYYMMDD`` whose suffix date is strictly before
    ``UTC today - retention_days`` (calendar days).
    """
    if retention_days < 0:
        raise ValueError("retention_days must be >= 0")
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=retention_days)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'historical_data'
              AND tablename LIKE %s
            """,
            (SCRATCH_TABLE_PREFIX + "%",),
        )
        names = [r[0] for r in cur.fetchall()]

    dropped: list[str] = []
    with conn.cursor() as cur:
        for name in names:
            m = _SCRATCH_NAME_RE.match(name)
            if not m:
                continue
            try:
                d = datetime.strptime(m.group(2), "%Y%m%d").date()
            except ValueError:
                continue
            if d >= cutoff:
                continue
            fq = f"historical_data.{name}"
            if dry_run:
                dropped.append(f"DROP TABLE IF EXISTS {fq};  -- suffix {d}")
            else:
                cur.execute(f"DROP TABLE IF EXISTS historical_data.{name};")
                dropped.append(fq)
    return dropped


def run_fill(
    conn: Any,
    market_ticker: str,
    series_ticker: str | None = None,
    *,
    target_table: str | None = None,
) -> tuple[int, int, int]:
    """
    Fetch candles for [open_time, close_time] and upsert.

    If ``target_table`` is set (e.g. ``historical_data.kalshi_candles_1m_..._20260322``),
    use it. Otherwise use ``testing."candlesticks_1m_<ticker>"``.
    """
    series = series_ticker or infer_series_ticker(market_ticker)
    table = target_table or quoted_table_for_ticker(market_ticker)
    open_u, close_u = fetch_market_window(market_ticker)
    candles = fetch_candles_1m(series, market_ticker, open_u, close_u)
    if not candles:
        raise RuntimeError("No candlesticks returned for window; check API / table exists.")

    sql = UPSERT_SQL.format(table=table)
    rows = [candle_row(market_ticker, c) for c in candles]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return open_u, close_u, len(rows)
