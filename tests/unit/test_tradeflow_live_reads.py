"""tradeflow_live_reads — cache-only operational reads."""

from __future__ import annotations

from unittest.mock import patch

from backend.core.tradeflow_live_reads import (
    kalshi_closing_price_for_ticker_monitoring,
    kalshi_market_snapshot,
    kalshi_market_snapshot_for_monitoring,
    strike_ladder,
    symbol_metrics,
    symbol_spot_price,
    symbol_spot_price_for_monitoring,
    ttc_seconds_from_ladder,
    tradeflow_live_state_max_age_sec,
)


def test_tradeflow_max_age_defaults():
    assert tradeflow_live_state_max_age_sec() >= 0.5


def test_symbol_metrics_stale_returns_none():
    env = {"updated_at": "2000-01-01T00:00:00+00:00", "data": {"price": 1.0}}
    with patch("backend.core.tradeflow_live_reads.live_state_cache_enabled", return_value=True):
        with patch(
            "backend.core.tradeflow_live_reads.live_state_cache.get_symbol",
            return_value=env,
        ):
            with patch(
                "backend.core.tradeflow_live_reads.tradeflow_live_state_max_age_sec",
                return_value=3.0,
            ):
                assert symbol_metrics("BTC") is None


def test_symbol_metrics_fresh():
    from datetime import datetime, timezone

    env = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "data": {"price": 99000.0, "momentum_5s_avg": 0.1},
    }
    with patch("backend.core.tradeflow_live_reads.live_state_cache_enabled", return_value=True):
        with patch(
            "backend.core.tradeflow_live_reads.live_state_cache.get_symbol",
            return_value=env,
        ):
            m = symbol_metrics("BTC")
            assert m is not None
            assert m["price"] == 99000.0
            assert symbol_spot_price("BTC") == 99000.0


def test_strike_ladder_cache_only_no_pg_fallback():
    with patch("backend.core.tradeflow_live_reads.live_state_cache_enabled", return_value=True):
        with patch(
            "backend.core.tradeflow_live_reads._check_fresh",
            return_value=(True, "ok", 0.1),
        ):
            with patch(
                "backend.core.tradeflow_live_reads.strike_ladder_from_cache",
                return_value={"strikes": [{"ticker": "T1"}], "ttc": 120},
            ):
                out = strike_ladder("BTC", "15m")
    assert out is not None
    assert out["strikes"][0]["ticker"] == "T1"


def test_ttc_from_ladder():
    assert ttc_seconds_from_ladder({"ttc_seconds": 90}, "15m") == 90
    assert ttc_seconds_from_ladder({"ttc": 60}, "hourly") == 60
