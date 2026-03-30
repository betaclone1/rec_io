"""
Kalshi 1-minute candlesticks: fetch from Trade API (live series path, then historical)
and upsert into a Postgres table.

The request uses ``period_interval=1`` over ``open_time``..``close_time`` from ``GET /markets/{ticker}``,
so row count equals the session length in minutes (e.g. 15 for 15m markets, 60 for typical hourly).

- **Testing** (migrations): ``testing."candlesticks_1m_<ticker>"`` via ``quoted_table_for_ticker``.
- **Scratch / analysis**: ``historical_data.kalshi_candles_1m_<slug>_<YYYYMMDD>`` via
  ``scratch_table_name`` + ``ensure_scratch_table``.
"""

from __future__ import annotations

import hashlib
import json
import re

# Kalshi market tickers used in quoted identifiers (testing tables, etc.)
_KALSHI_MARKET_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+\-]*$")
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from zoneinfo import ZoneInfo

KALSHI_TRADE_V2 = "https://api.elections.kalshi.com/trade-api/v2"
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


def _http_json(url: str, timeout: int = 60) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
