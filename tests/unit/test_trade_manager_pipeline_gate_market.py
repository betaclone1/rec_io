"""Live open pipeline gate must key health by the trade's market interval (not silent hourly)."""

from __future__ import annotations

from unittest.mock import patch

import backend.trade_manager as tm


def test_normalize_kalshi_market_interval():
    assert tm._normalize_kalshi_market_interval("15m") == "15m"
    assert tm._normalize_kalshi_market_interval("HOURLY") == "hourly"
    assert tm._normalize_kalshi_market_interval(None) is None
    assert tm._normalize_kalshi_market_interval("") is None
    assert tm._normalize_kalshi_market_interval("daily") is None


def test_market_from_ticker_15m_not_hourly():
    assert (
        tm._kalshi_market_interval_from_ticker("KXBTC15M-26AUG051330-30") == "15m"
    )
    assert (
        tm._kalshi_market_interval_from_ticker("KXETH15M-26AUG060200-00") == "15m"
    )


def test_market_from_ticker_hourly():
    assert tm._kalshi_market_interval_from_ticker("KXBTCD-26AUG0513-T64599.99") == "hourly"
    assert tm._kalshi_market_interval_from_ticker("NOT-A-TICKER") is None


def test_resolve_gate_prefers_payload_market():
    m, src = tm._resolve_market_for_open_pipeline_gate(
        {
            "market": "15m",
            "ticker": "KXBTCD-26AUG0513-T64599.99",  # would be hourly if ticker won
            "monitor": "mon_0001_10046",
        }
    )
    assert m == "15m"
    assert src == "payload"


def test_resolve_gate_uses_ticker_when_payload_missing():
    with patch.object(tm, "_lookup_monitor_market_interval", return_value="hourly"):
        m, src = tm._resolve_market_for_open_pipeline_gate(
            {
                "ticker": "KXBTC15M-26AUG051330-30",
                "monitor": "mon_0001_10046",
            }
        )
    assert m == "15m"
    assert src == "ticker"


def test_resolve_gate_does_not_default_15m_ticker_to_hourly():
    """Regression: old TM used data.get('market') or 'hourly' with AES omitting market."""
    with patch.object(tm, "_lookup_monitor_market_interval", return_value=None):
        m, src = tm._resolve_market_for_open_pipeline_gate(
            {
                "symbol": "BTC",
                "ticker": "KXBTC15M-26AUG051330-30",
                "paper_trade": False,
            }
        )
    assert m == "15m"
    assert src == "ticker"
    assert m != "hourly"


def test_resolve_gate_falls_back_to_monitor_then_unresolved():
    with patch.object(tm, "_lookup_monitor_market_interval", return_value="15m"):
        m, src = tm._resolve_market_for_open_pipeline_gate(
            {"symbol": "BTC", "monitor": "mon_0001_10046"}
        )
    assert m == "15m"
    assert src == "monitor"

    with patch.object(tm, "_lookup_monitor_market_interval", return_value=None):
        m2, src2 = tm._resolve_market_for_open_pipeline_gate(
            {"symbol": "BTC", "ticker": "NOT-A-REAL-TICKER"}
        )
    assert m2 is None
    assert src2 == "market_unresolved"


def test_resolve_trade_market_for_insert_prefers_15m_ticker_over_hourly_monitor_default():
    """Insert path must not stamp hourly on a clear 15m Kalshi ticker."""
    class _Cur:
        def execute(self, *a, **k):
            return None

        def fetchone(self):
            return ("hourly",)

    with patch.object(tm, "_monitor_key_matches_worker", return_value=True):
        with patch.object(tm, "_monitor_slot_and_id", return_value=("0001", "10046")):
            m = tm._resolve_trade_market_for_insert(
                _Cur(),
                "mon_0001_10046",
                "Expiration Scalp",
                "KXBTC15M-26AUG051330-30",
            )
    assert m == "15m"
