"""Lean commodity symbols get ticker+trade, never orderbook."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.core.market_watchdog.config import IngestConfig
from backend.core.market_watchdog.venues.kalshi import ws_ingest as wi


def _cfg(symbols):
    return IngestConfig(
        exchange="kalshi",
        market_interval="15m",
        symbols=tuple(symbols),
        prediscover_hours=4.0,
        schedule_refresh_sec=900.0,
        orderbook_cutover_sec=2.0,
        outgoing_track_sec=960.0,
        hourly_atm_strikes_each_side=20,
        publish_coalesce_sec=0.05,
        ws_market_chunk=80,
        channel_resync_debounce_sec=10.0,
        channel_resync_min_interval_sec=45.0,
        lifecycle_sync_sec=1.0,
        periodic_snapshot_sec=0.0,
        event_log_enabled=False,
        disturbance_log_enabled=False,
        settled_redis_key="rec_io:market_watchdog:settled:v1",
    )


def test_lean_symbols_skip_orderbook():
    cfg = _cfg(["BTC", "GOLD"])
    master = wi.KalshiMarketWsMaster(cfg=cfg, symbols=list(cfg.symbols))
    master.schedule_by_symbol = {
        "BTC": {"15m": []},
        "GOLD": {"15m": []},
    }
    with patch.object(wi, "_resolve_live_15m_current", side_effect=lambda sym, *a, **k: f"KX{sym}15M-CUR"):
        with patch.object(wi, "_latest_outgoing_15m", return_value=None):
            ticker, ob, trade, _new = wi._lifecycle_sets(master, 0.0)
    assert "KXBTC15M-CUR" in ticker
    assert "KXBTC15M-CUR" in ob
    assert "KXBTC15M-CUR" in trade
    assert "KXGOLD15M-CUR" in ticker
    assert "KXGOLD15M-CUR" not in ob
    assert "KXGOLD15M-CUR" in trade
