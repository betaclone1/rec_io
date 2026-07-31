"""Request-time trade detail aggregation for the desktop trade-history modal."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from backend.core.kalshi_event_market_fetch import (
    event_ticker_from_market_ticker,
    kalshi_trade_api_base,
)
from backend.core.trades_list_query import (
    TRADES_LIST_HTTP_COLUMNS,
    trades_dicts_from_rows,
)
from backend.util.trade_log_archivist import (
    fetch_master_trades_column_names,
    union_trades_with_archives_select_columns,
)

_HEADERS = {"Accept": "application/json", "User-Agent": "rec_io_trade_history/1.0"}
_TIMEOUT_SEC = 20.0
_EASTERN = ZoneInfo("America/New_York")
_EVENT_DATE_TOKEN_RE = re.compile(
    r"^(?P<series>[A-Z0-9]+)-(?P<date>\d{2}[A-Z]{3}\d{2})(?P<clock>\d{2}|\d{4})$"
)
_TICKER_COLUMNS = tuple(
    dict.fromkeys(
        (
            *TRADES_LIST_HTTP_COLUMNS,
            "market_result",
            "symbol_expiration",
            "order_id_open",
            "order_id_close",
            "initial_count",
            "initial_price",
            "initial_proj_price",
            "slippage",
            "order_type",
            "loss_prevention_state",
            "subaccount",
        )
    )
)


class KalshiDetailError(RuntimeError):
    """A public Kalshi endpoint failed or returned an invalid payload."""

    def __init__(self, endpoint: str, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.endpoint = endpoint
        self.status_code = status_code

    def as_dict(self) -> Dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "status_code": self.status_code,
            "message": str(self),
        }


def load_trade_detail_record(cursor: Any, *, slot: str, trade_id: int) -> Optional[Dict[str, Any]]:
    """Load one tenant trade from the master/archive union by numeric id."""
    if trade_id < 1:
        return None
    if not fetch_master_trades_column_names(cursor, slot):
        return None
    union_sql, _ = union_trades_with_archives_select_columns(
        cursor, slot, _TICKER_COLUMNS
    )
    cursor.execute(
        f"""
        SELECT *
        FROM ({union_sql}) AS all_trades
        WHERE id = %s
        ORDER BY archived_at NULLS FIRST
        LIMIT 1
        """,
        (trade_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    columns = [desc[0] for desc in cursor.description]
    return trades_dicts_from_rows([row], columns)[0]


def load_trade_detail_fills(
    cursor: Any,
    *,
    slot: str,
    order_id_open: Any,
    order_id_close: Any,
) -> list[Dict[str, Any]]:
    """Return exact fill rows for a trade's opening and closing Kalshi orders."""
    if not re.fullmatch(r"\d{4}", str(slot or "")):
        raise ValueError(f"Invalid tenant slot: {slot}")

    open_id = str(order_id_open or "").strip()
    close_id = str(order_id_close or "").strip()
    order_ids = list(dict.fromkeys(value for value in (open_id, close_id) if value))
    if not order_ids:
        return []

    cursor.execute(
        f"""
        SELECT
            trade_id,
            order_id,
            created_time,
            count_fp,
            action,
            outcome_side,
            yes_price_dollars,
            no_price_dollars,
            orderbook_side
        FROM users.fills_{slot}
        WHERE order_id = ANY(%s)
        ORDER BY created_time ASC, id ASC
        """,
        (order_ids,),
    )

    fills: list[Dict[str, Any]] = []
    for row in cursor.fetchall():
        outcome_side = str(row[5] or "").strip().lower()
        price = row[6] if outcome_side == "yes" else row[7] if outcome_side == "no" else None
        fills.append(
            {
                "fill_id": row[0],
                "order_id": row[1],
                "phase": "open" if row[1] == open_id else "close",
                "created_time": row[2],
                "count": str(row[3]) if row[3] is not None else None,
                "action": row[4],
                "outcome_side": outcome_side or None,
                "price": str(price) if price is not None else None,
                "orderbook_side": row[8],
            }
        )
    return fills


def load_trade_detail_orders(
    cursor: Any,
    *,
    slot: str,
    order_id_open: Any,
    order_id_close: Any,
) -> list[Dict[str, Any]]:
    """Return the opening and closing orders associated with one tenant trade."""
    if not re.fullmatch(r"\d{4}", str(slot or "")):
        raise ValueError(f"Invalid tenant slot: {slot}")

    open_id = str(order_id_open or "").strip()
    close_id = str(order_id_close or "").strip()
    order_ids = list(dict.fromkeys(value for value in (open_id, close_id) if value))
    if not order_ids:
        return []

    cursor.execute(
        f"""
        SELECT
            order_id,
            created_time,
            status,
            outcome_side,
            orderbook_side,
            CASE
                WHEN LOWER(TRIM(outcome_side)) = 'yes'
                    THEN NULLIF(TRIM(yes_price_dollars), '')::numeric
                WHEN LOWER(TRIM(outcome_side)) = 'no'
                     AND NULLIF(TRIM(no_price_dollars), '') IS NOT NULL
                    THEN NULLIF(TRIM(no_price_dollars), '')::numeric
                WHEN LOWER(TRIM(outcome_side)) = 'no'
                     AND NULLIF(TRIM(yes_price_dollars), '') IS NOT NULL
                    THEN 1 - NULLIF(TRIM(yes_price_dollars), '')::numeric
                ELSE NULL
            END AS price,
            initial_count_fp,
            fill_count_fp,
            CASE
                WHEN NULLIF(TRIM(taker_fees_dollars), '') IS NOT NULL
                     AND NULLIF(TRIM(maker_fees_dollars), '') IS NOT NULL
                    THEN NULLIF(TRIM(taker_fees_dollars), '')::numeric
                       + NULLIF(TRIM(maker_fees_dollars), '')::numeric
                ELSE NULL
            END AS total_fees,
            subaccount
        FROM users.orders_{slot}
        WHERE order_id = ANY(%s)
        ORDER BY created_time ASC, id ASC
        """,
        (order_ids,),
    )

    orders: list[Dict[str, Any]] = []
    for row in cursor.fetchall():
        orders.append(
            {
                "order_id": row[0],
                "phase": "open" if row[0] == open_id else "close",
                "created_time": row[1],
                "status": row[2],
                "outcome_side": row[3],
                "orderbook_side": row[4],
                "price": str(row[5]) if row[5] is not None else None,
                "initial_count": str(row[6]) if row[6] is not None else None,
                "fill_count": str(row[7]) if row[7] is not None else None,
                "total_fees": str(row[8]) if row[8] is not None else None,
                "subaccount": row[9],
            }
        )
    return orders


def _request_json(
    endpoint: str,
    *,
    http_get: Callable[..., Any],
) -> Tuple[int, Dict[str, Any]]:
    url = f"{kalshi_trade_api_base()}{endpoint}"
    try:
        response = http_get(url, headers=_HEADERS, timeout=_TIMEOUT_SEC)
    except requests.RequestException as exc:
        raise KalshiDetailError(endpoint, f"Kalshi request failed: {exc}") from exc
    status_code = int(response.status_code)
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise KalshiDetailError(
            endpoint,
            "Kalshi returned non-JSON data",
            status_code=status_code,
        ) from exc
    if not isinstance(payload, dict):
        raise KalshiDetailError(
            endpoint,
            "Kalshi returned an invalid JSON object",
            status_code=status_code,
        )
    return status_code, payload


def fetch_kalshi_market(
    market_ticker: str,
    *,
    http_get: Callable[..., Any] = requests.get,
) -> Tuple[Dict[str, Any], str]:
    """Fetch current market metadata, then the historical store only when absent."""
    current_endpoint = f"/markets/{market_ticker}"
    status, payload = _request_json(current_endpoint, http_get=http_get)
    market = payload.get("market")
    if status == 200 and isinstance(market, dict):
        return market, "current"
    if status != 404 and not (status == 200 and market is None):
        raise KalshiDetailError(
            current_endpoint,
            f"Kalshi current market returned HTTP {status}",
            status_code=status,
        )

    historical_endpoint = f"/historical/markets/{market_ticker}"
    hist_status, hist_payload = _request_json(
        historical_endpoint, http_get=http_get
    )
    historical_market = hist_payload.get("market")
    if hist_status == 200 and isinstance(historical_market, dict):
        return historical_market, "historical"
    if hist_status == 404 or (hist_status == 200 and historical_market is None):
        raise KalshiDetailError(
            historical_endpoint,
            "Market not found in current or historical Kalshi data",
            status_code=hist_status,
        )
    raise KalshiDetailError(
        historical_endpoint,
        f"Kalshi historical market returned HTTP {hist_status}",
        status_code=hist_status,
    )


def fetch_kalshi_live_data(
    event_ticker: str,
    *,
    http_get: Callable[..., Any] = requests.get,
) -> Dict[str, Any]:
    """Fetch authoritative event-keyed live/historical chart data."""
    endpoint = f"/live_data/events/{event_ticker}"
    status, payload = _request_json(endpoint, http_get=http_get)
    live_data = payload.get("live_data")
    if status == 200 and isinstance(live_data, dict):
        return live_data
    raise KalshiDetailError(
        endpoint,
        f"Kalshi live data returned HTTP {status}",
        status_code=status,
    )


def following_event_ticker(
    event_ticker: str,
    market: Dict[str, Any],
) -> Tuple[str, datetime]:
    """Derive the next cycle event from authoritative market open/close timestamps."""
    match = _EVENT_DATE_TOKEN_RE.fullmatch(str(event_ticker or "").strip())
    if not match:
        raise ValueError(f"Unsupported Kalshi event ticker: {event_ticker}")
    try:
        open_time = datetime.fromisoformat(str(market["open_time"]).replace("Z", "+00:00"))
        close_time = datetime.fromisoformat(str(market["close_time"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Kalshi market has no valid cycle open/close timestamps") from exc
    duration = close_time - open_time
    if duration <= timedelta(0):
        raise ValueError("Kalshi market cycle duration is invalid")

    following_close = close_time + duration
    following_eastern = following_close.astimezone(_EASTERN)
    clock_format = "%H%M" if len(match.group("clock")) == 4 else "%H"
    token = following_eastern.strftime(f"%y%b%d{clock_format}").upper()
    return f"{match.group('series')}-{token}", following_close


def fetch_kalshi_trade_context(
    market_ticker: str,
    *,
    http_get: Callable[..., Any] = requests.get,
) -> Dict[str, Any]:
    """Fetch chart and market metadata without persisting temporary artifacts."""
    ticker = str(market_ticker or "").strip()
    event_ticker = event_ticker_from_market_ticker(ticker)
    if not ticker or not event_ticker or event_ticker == ticker:
        raise ValueError("Trade has no valid Kalshi market ticker")

    result: Dict[str, Any] = {
        "market_ticker": ticker,
        "event_ticker": event_ticker,
        "market": None,
        "market_source": None,
        "market_error": None,
        "live_data": None,
        "live_data_error": None,
        "following_event_ticker": None,
        "following_cycle_close_time": None,
        "following_live_data": None,
        "following_live_data_error": None,
    }
    market: Optional[Dict[str, Any]] = None
    try:
        market, source = fetch_kalshi_market(ticker, http_get=http_get)
        result["market"] = market
        result["market_source"] = source
    except KalshiDetailError as exc:
        result["market_error"] = exc.as_dict()

    try:
        result["live_data"] = fetch_kalshi_live_data(
            event_ticker, http_get=http_get
        )
    except KalshiDetailError as exc:
        result["live_data_error"] = exc.as_dict()

    if market is not None:
        try:
            next_event, next_close = following_event_ticker(event_ticker, market)
            result["following_event_ticker"] = next_event
            result["following_cycle_close_time"] = next_close.isoformat()
            result["following_live_data"] = fetch_kalshi_live_data(
                next_event, http_get=http_get
            )
        except (KalshiDetailError, ValueError) as exc:
            if isinstance(exc, KalshiDetailError):
                result["following_live_data_error"] = exc.as_dict()
            else:
                result["following_live_data_error"] = {
                    "endpoint": None,
                    "status_code": None,
                    "message": str(exc),
                }
    return result
