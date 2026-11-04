"""System-wide OB foundation: immediate flush + embedded levels for every subscribed book."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

from backend.core.market_watchdog.config import IngestConfig
from backend.core.market_watchdog.venues.kalshi import ws_ingest as wi
from backend.core import orderbook_hot_publish_registry as reg


def _cfg():
    return IngestConfig(
        exchange="kalshi",
        market_interval="15m",
        symbols=("BTC",),
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


def _master(*tickers: str) -> wi.KalshiMarketWsMaster:
    master = wi.KalshiMarketWsMaster(cfg=_cfg(), symbols=["BTC"])
    master.orderbook_subscribed = set(tickers)
    for mt in tickers:
        master.books[mt] = {
            "yes": {"0.50": "1"},
            "no": {"0.50": "1"},
            "valid": True,
            "last_seq": 1,
            "last_book_mono": 0.0,
            "venue_ts_ms": 1_700_000_000_000,
            "sending_ts_ms": 1_700_000_000_000,
            "ts_ms": 1_700_000_000_000,
            "t_ws_recv_ms": 1_700_000_000_000,
            "t_apply_ms": 1_700_000_000_000,
        }
    return master


def test_immediate_flush_covers_commodity_not_just_crypto(monkeypatch):
    monkeypatch.setenv("MARKET_WATCHDOG_IMMEDIATE_ORDERBOOK_FLUSH", "1")
    monkeypatch.setenv("MARKET_WATCHDOG_HOT_CRYPTO_15M", "1")
    assert reg.should_immediate_flush_orderbook("KXGOLD15M-ANY") is True
    assert reg.should_immediate_flush_orderbook("KXBTC15M-ANY") is True
    assert reg.is_hot_orderbook_ticker("KXGOLD15M-ANY") is True


def test_ut_watch_does_not_gate_flush(monkeypatch):
    monkeypatch.setenv("MARKET_WATCHDOG_IMMEDIATE_ORDERBOOK_FLUSH", "1")
    monkeypatch.setenv("MARKET_WATCHDOG_HOT_CRYPTO_15M", "0")
    monkeypatch.setattr(reg, "_parse_allowlist_env", lambda: set())
    monkeypatch.setattr(
        "backend.core.trade_monitor_orderbook_watch.get_trade_monitor_orderbook_watch",
        lambda: None,
    )
    from backend.core import upper_tail_orderbook_watch as utw

    utw.set_upper_tail_orderbook_arm({})
    with reg._lock:
        reg._last_refresh_mono = 0.0
        reg._watched = None
        reg._allowlist = set()
    # Flush is universal even with empty UT arm.
    assert reg.should_immediate_flush_orderbook("KXETH15M-X") is True
    # Wake stays filtered.
    assert reg.should_wake_tradeflow_on_orderbook("KXETH15M-X") is False
    assert reg.should_wake_tradeflow_on_orderbook("KXBTC15M-X") is False  # crypto wake off


def test_tradeflow_wake_crypto_independent_of_flush(monkeypatch):
    monkeypatch.setenv("MARKET_WATCHDOG_IMMEDIATE_ORDERBOOK_FLUSH", "1")
    monkeypatch.setenv("MARKET_WATCHDOG_HOT_CRYPTO_15M", "1")
    assert reg.should_wake_tradeflow_on_orderbook("KXBTC15M-A") is True
    assert reg.should_wake_tradeflow_on_orderbook("KXGOLD15M-A") is False
    # Gold still flushes.
    assert reg.should_immediate_flush_orderbook("KXGOLD15M-A") is True


def test_flush_embeds_levels_for_commodity_book():
    master = _master("KXGOLD15M-CUR")
    hints: list[dict] = []

    pipe = MagicMock()
    redis = MagicMock()
    redis.pipeline.return_value = pipe

    with (
        patch.object(wi, "_redis", return_value=redis),
        patch.object(
            wi,
            "_orderbook_redis_payload",
            return_value={
                "seq": 9,
                "ts_ms": 100,
                "venue_ts_ms": 100,
                "sending_ts_ms": 101,
                "t_ws_recv_ms": 102,
                "t_apply_ms": 103,
                "clock": 1,
                "yes": {"0.40": "3"},
                "no": {"0.60": "4"},
            },
        ),
        patch.object(wi, "_redis_publish_push", side_effect=lambda h: hints.append(h)),
        patch.object(wi, "_maybe_prebuild_orderbook_ws_payload"),
    ):
        wi._flush_orderbook_tickers_sync(master, ["KXGOLD15M-CUR"])

    assert len(hints) == 1
    assert hints[0]["market_ticker"] == "KXGOLD15M-CUR"
    assert hints[0]["yes"] == {"0.40": "3"}
    assert hints[0]["no"] == {"0.60": "4"}


def test_delta_schedules_immediate_flush_even_when_not_ut_armed():
    master = _master("KXGOLD15M-CUR")
    master.books["KXGOLD15M-CUR"]["valid"] = True
    master.ob_channel_last_seq = 10
    scheduled: list[str] = []

    raw = {
        "type": "orderbook_delta",
        "sid": 1,
        "seq": 11,
        "msg": {
            "market_ticker": "KXGOLD15M-CUR",
            "side": "yes",
            "price_dollars": "0.55",
            "delta_fp": "1.00",
        },
        "sending_ts_ms": 1_700_000_000_200,
    }

    async def _run():
        with (
            patch.object(wi, "_enqueue_cycle_ob"),
            patch.object(
                wi,
                "_schedule_hot_ob_flush",
                side_effect=lambda m, mt: scheduled.append(mt),
            ),
        ):
            await wi._on_ws_message(master, json.dumps(raw))

    asyncio.run(_run())
    assert scheduled == ["KXGOLD15M-CUR"]
