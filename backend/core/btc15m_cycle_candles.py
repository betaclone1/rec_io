"""Build KXBTC15M cycle candles from Kalshi market + live_data timeseries.

Open = floor_strike. High / low / close come from the event timeseries values
(same Kalshi /live_data/events path as trade-history detail charts).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from backend.core.kalshi_event_market_fetch import event_ticker_from_market_ticker
from backend.core.trade_history_detail import (
    KalshiDetailError,
    fetch_kalshi_live_data,
    fetch_kalshi_market,
)

_EASTERN = ZoneInfo("America/New_York")
_UTC = timezone.utc
_MON = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def utc_iso_z(dt: datetime) -> str:
    """Format like cycle price rings: 2026-08-02T04:00:00.000Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    else:
        dt = dt.astimezone(_UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _format_15m_contract(symbol: str, hour_24: int, minute: int) -> str:
    s = symbol.upper()
    if hour_24 == 0:
        return f"{s} 12:{minute:02d}am"
    if hour_24 == 12:
        return f"{s} 12:{minute:02d}pm"
    if hour_24 > 12:
        return f"{s} {hour_24 - 12}:{minute:02d}pm"
    return f"{s} {hour_24}:{minute:02d}am"


def contract_label_from_15m_ticker(ticker: str, *, symbol: str = "BTC") -> Optional[str]:
    """
    Human contract label matching trade_manager.derive_contract_label_from_kalshi_ticker
    for 15m tickers (e.g. KXBTC15M-26AUG020015-15 → 'BTC 12:15am').
    """
    parts = str(ticker or "").strip().upper().split("-")
    if len(parts) < 2:
        return None
    mid = parts[1]
    if len(mid) < 11 or not mid[-4:].isdigit():
        return None
    hhmm = int(mid[-4:])
    h, m = hhmm // 100, hhmm % 100
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return _format_15m_contract(symbol, h, m)


def settlement_end_utc_from_ticker(ticker: str) -> datetime:
    """Parse KXBTC15M-{YY}{MON}{DD}{HHMM}-{MM} Eastern end → aware UTC datetime."""
    parts = str(ticker or "").strip().upper().split("-")
    if len(parts) < 3:
        raise ValueError(f"Unsupported ticker: {ticker!r}")
    mid = parts[1]
    if len(mid) < 11:
        raise ValueError(f"Unsupported ticker mid token: {ticker!r}")
    yy = int(mid[0:2])
    mon = _MON.get(mid[2:5])
    if mon is None:
        raise ValueError(f"Unsupported ticker month: {ticker!r}")
    dd = int(mid[5:7])
    hh = int(mid[7:9])
    minute = int(mid[9:11])
    end_est = datetime(2000 + yy, mon, dd, hh, minute, tzinfo=_EASTERN)
    return end_est.astimezone(_UTC)


def settlement_end_utc_iso_from_ticker(ticker: str) -> str:
    """Settlement end as UTC ISO-Z TEXT (price-ring convention)."""
    return utc_iso_z(settlement_end_utc_from_ticker(ticker))


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, TypeError, ValueError):
        return None


def market_result_from_market(market: Mapping[str, Any] | None) -> Optional[str]:
    """Authoritative Kalshi settlement outcome from market payload; NULL if unset."""
    if not isinstance(market, Mapping):
        return None
    for key in ("result", "market_result"):
        raw = market.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def _parse_market_instant(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def timeseries_prices(
    live_data: Mapping[str, Any] | None,
    *,
    open_time: datetime | None = None,
    close_time: datetime | None = None,
) -> List[Decimal]:
    """
    Extract finite spot values from Kalshi live_data.details.timeseries.

    When open_time/close_time are provided, only points inside the cycle window
    [open_time, close_time] are kept. Kalshi often returns ~45m of pre-open ticks
    in the same series; those must not affect high/low/close.
    """
    details = (live_data or {}).get("details") or {}
    series = details.get("timeseries") if isinstance(details, dict) else None
    if not isinstance(series, Sequence):
        return []

    open_ms = int(open_time.timestamp() * 1000) if open_time is not None else None
    close_ms = int(close_time.timestamp() * 1000) if close_time is not None else None

    out: List[Decimal] = []
    for point in series:
        if not isinstance(point, Mapping):
            continue
        if open_ms is not None or close_ms is not None:
            try:
                t_ms = int(float(point.get("t")))
            except (TypeError, ValueError):
                continue
            if open_ms is not None and t_ms < open_ms:
                continue
            if close_ms is not None and t_ms > close_ms:
                continue
        price = _to_decimal(point.get("v"))
        if price is None:
            continue
        out.append(price)
    return out


def build_cycle_candle_from_payloads(
    *,
    ticker: str,
    contract: Optional[str],
    market: Mapping[str, Any],
    live_data: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    Assemble one candle row.

    High / low / close use only timeseries points inside market open_time..close_time
    (the live 15m cycle). Missing authoritative inputs stay NULL (no substitutes).
    """
    floor_strike = _to_decimal(market.get("floor_strike"))
    open_time = _parse_market_instant(market.get("open_time"))
    close_time = _parse_market_instant(market.get("close_time"))
    prices = timeseries_prices(
        live_data,
        open_time=open_time,
        close_time=close_time,
    )
    high_price = max(prices) if prices else None
    low_price = min(prices) if prices else None
    close = prices[-1] if prices else None

    total_range_pct: Optional[Decimal] = None
    final_diff_pct: Optional[Decimal] = None
    if (
        floor_strike is not None
        and floor_strike != 0
        and high_price is not None
        and low_price is not None
    ):
        total_range_pct = ((high_price - low_price) / floor_strike) * Decimal("100")
    if floor_strike is not None and floor_strike != 0 and close is not None:
        final_diff_pct = ((close - floor_strike) / floor_strike) * Decimal("100")

    try:
        ts = settlement_end_utc_iso_from_ticker(ticker)
    except ValueError:
        if close_time is not None:
            ts = utc_iso_z(close_time)
        else:
            raise

    return {
        "timestamp": ts,
        "ticker": ticker,
        "contract": contract,
        "floor_strike": floor_strike,
        "high_price": high_price,
        "low_price": low_price,
        "close": close,
        "total_range_pct": total_range_pct,
        "final_diff_pct": final_diff_pct,
        "market_result": market_result_from_market(market),
        "price_points": len(prices),
        "event_ticker": event_ticker_from_market_ticker(ticker),
    }



def fetch_cycle_candle(
    ticker: str,
    *,
    contract: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Fetch Kalshi market + live_data and build a candle dict."""
    market, market_source = fetch_kalshi_market(ticker)
    event_ticker = event_ticker_from_market_ticker(ticker)
    if not event_ticker or event_ticker == ticker:
        raise KalshiDetailError(
            f"/live_data/events/{ticker}",
            "Could not derive event ticker from market ticker",
        )
    live_data = fetch_kalshi_live_data(event_ticker)
    if contract is None:
        contract = contract_label_from_15m_ticker(ticker, symbol="BTC")
    row = build_cycle_candle_from_payloads(
        ticker=ticker,
        contract=contract,
        market=market,
        live_data=live_data,
    )
    meta = {
        "market_source": market_source,
        "event_ticker": event_ticker,
        "price_points": row.get("price_points"),
    }
    return row, meta


UPSERT_SQL = """
INSERT INTO historical_data.btc15m_cycle_candles (
    "timestamp", ticker, contract, floor_strike,
    high_price, low_price, close, total_range_pct, final_diff_pct, market_result
) VALUES (
    %(timestamp)s, %(ticker)s, %(contract)s, %(floor_strike)s,
    %(high_price)s, %(low_price)s, %(close)s, %(total_range_pct)s, %(final_diff_pct)s,
    %(market_result)s
)
ON CONFLICT (ticker) DO UPDATE SET
    "timestamp" = EXCLUDED."timestamp",
    contract = EXCLUDED.contract,
    floor_strike = EXCLUDED.floor_strike,
    high_price = EXCLUDED.high_price,
    low_price = EXCLUDED.low_price,
    close = EXCLUDED.close,
    total_range_pct = EXCLUDED.total_range_pct,
    final_diff_pct = EXCLUDED.final_diff_pct,
    market_result = EXCLUDED.market_result
"""


def upsert_cycle_candle(cursor: Any, row: Mapping[str, Any]) -> None:
    payload = {
        "timestamp": row["timestamp"],
        "ticker": row["ticker"],
        "contract": row.get("contract"),
        "floor_strike": row.get("floor_strike"),
        "high_price": row.get("high_price"),
        "low_price": row.get("low_price"),
        "close": row.get("close"),
        "total_range_pct": row.get("total_range_pct"),
        "final_diff_pct": row.get("final_diff_pct"),
        "market_result": row.get("market_result"),
    }
    cursor.execute(UPSERT_SQL, payload)
