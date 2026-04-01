"""
Public Kalshi Trade API: event + nested markets for paper-trade outcome verification.

No auth required for GET /events/{event_ticker} in current deployment patterns.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.elections.kalshi.com/trade-api/v2"
_HEADERS = {"Accept": "application/json", "User-Agent": "rec_io_trade_manager/1.0"}


def kalshi_trade_api_base() -> str:
    return (os.getenv("KALSHI_TRADE_API_BASE") or _DEFAULT_BASE).rstrip("/")


def event_ticker_from_market_ticker(market_ticker: Optional[str]) -> Optional[str]:
    """Kalshi market ticker: last hyphen segment is strike-specific; prefix is event_ticker."""
    if not market_ticker:
        return None
    s = str(market_ticker).strip()
    parts = s.split("-")
    if len(parts) < 2:
        return s
    return "-".join(parts[:-1])


def _markets_from_payload(data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not data or not isinstance(data, dict):
        return []
    m = data.get("markets")
    if isinstance(m, list):
        return [x for x in m if isinstance(x, dict)]
    ev = data.get("event")
    if isinstance(ev, dict):
        m2 = ev.get("markets")
        if isinstance(m2, list):
            return [x for x in m2 if isinstance(x, dict)]
    return []


def fetch_event_payload(event_ticker: str, *, timeout_sec: float = 12.0) -> Optional[Dict[str, Any]]:
    if not event_ticker:
        return None
    url = f"{kalshi_trade_api_base()}/events/{event_ticker}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout_sec)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            return None
        if data.get("error"):
            logger.warning("Kalshi events API error for %s: %s", event_ticker, data.get("error"))
            return None
        return data
    except Exception as e:
        logger.warning("Kalshi events fetch failed %s: %s", event_ticker, e)
        return None


def normalize_market_result_field(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return "yes" if raw else "no"
    if isinstance(raw, int) and not isinstance(raw, bool):
        if raw == 1:
            return "yes"
        if raw == 0:
            return "no"
    s = str(raw).strip().lower()
    if s in ("yes", "no"):
        return s
    if s in ("true", "false"):
        return "yes" if s == "true" else "no"
    if s in ("1", "0"):
        return "yes" if s == "1" else "no"
    if s in ("", "scalar"):
        return None
    return None


def normalized_result_for_market_in_payload(
    payload: Optional[Dict[str, Any]], market_ticker: str
) -> Optional[str]:
    """Return 'yes' / 'no' / None from an already-fetched /events/{event_ticker} JSON body."""
    if not payload or not market_ticker:
        return None
    mt = str(market_ticker).strip()
    for m in _markets_from_payload(payload):
        if str(m.get("ticker") or "").strip() == mt:
            return normalize_market_result_field(m.get("result"))
    return None


def market_result_for_ticker(market_ticker: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (normalized_binary_result, error_or_none).
    Normalized result is 'yes' or 'no' when the market has a binary result; else None.
    """
    et = event_ticker_from_market_ticker(market_ticker)
    if not et:
        return None, "missing_event_ticker"
    payload = fetch_event_payload(et)
    if not payload:
        return None, "fetch_failed"
    mt = str(market_ticker).strip()
    for m in _markets_from_payload(payload):
        if str(m.get("ticker") or "").strip() == mt:
            raw = m.get("result")
            out = normalize_market_result_field(raw)
            if out is not None:
                return out, None
            if raw is None:
                return None, None
            s = str(raw).strip().lower()
            if s in ("", "scalar"):
                return None, None
            return None, f"non_binary_result:{raw!r}"
    return None, "market_not_in_event"
