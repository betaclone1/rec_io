"""Unit tests for rolling-rates chart read helper."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from backend.core.tail_backtest_rolling_rates_read import (
    SERIES_META,
    rolling_rates_chart_payload,
)


def test_series_start_dates():
    assert SERIES_META["KXBTC15M"]["start_date"] == date(2026, 5, 1)
    assert SERIES_META["KXSILVER15M"]["start_date"] == date(2026, 9, 1)


def test_rolling_rates_chart_payload_pivots_windows():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = [
        ("KXBTC15M", date(2026, 5, 10), 7, 0.02, 100, 2),
        ("KXBTC15M", date(2026, 5, 10), 30, 0.015, 400, 6),
        ("KXBTC15M", date(2026, 5, 10), 90, 0.012, 900, 11),
        ("KXSILVER15M", date(2026, 9, 15), 7, 0.014523, 483, 7),
        ("KXSILVER15M", date(2026, 9, 15), 30, 0.012534, 2235, 28),
        ("KXSILVER15M", date(2026, 9, 15), 90, 0.014297, 6435, 92),
    ]
    payload = rolling_rates_chart_payload(conn, side="lt")
    assert payload["side"] == "lt"
    by_sym = {a["symbol"]: a for a in payload["assets"]}
    btc = by_sym["BTC"]
    assert btc["start_date"] == "2026-05-01"
    assert btc["latest"]["w7"] == 2.0
    assert btc["latest"]["w30"] == 1.5
    assert btc["latest"]["w90"] == 1.2
    silver = by_sym["SILVER"]
    assert silver["asset_class"] == "commodity"
    assert silver["latest"]["w90"] == 1.4297
    assert silver["latest"]["scored90"] == 6435
