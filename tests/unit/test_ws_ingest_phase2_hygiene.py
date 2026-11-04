"""Phase 2 OB ingest hygiene: hint-before-prebuild, narrow periodic resync, trade deferral, cycle enqueue off-lock."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.core.market_watchdog.config import IngestConfig
from backend.core.market_watchdog.venues.kalshi import ws_ingest as wi


def _cfg(symbols=("BTC",)):
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


def test_flush_publishes_hint_before_prebuild():
    master = _master("KXBTC15M-HOT")
    order: list[str] = []

    pipe = MagicMock()
    redis = MagicMock()
    redis.pipeline.return_value = pipe

    def _track_publish(hint):
        order.append(f"hint:{hint.get('market_ticker')}")

    def _track_prebuild(mt, *, redis_written_ms):
        order.append(f"prebuild:{mt}")

    with (
        patch.object(wi, "_redis", return_value=redis),
        patch.object(
            wi,
            "_orderbook_redis_payload",
            return_value={
                "seq": 7,
                "ts_ms": 100,
                "venue_ts_ms": 100,
                "sending_ts_ms": 101,
                "t_ws_recv_ms": 102,
                "t_apply_ms": 103,
                "clock": 1,
                "yes": {"0.99": "1"},
                "no": {"0.01": "2"},
            },
        ),
        patch.object(wi, "_redis_publish_push", side_effect=_track_publish),
        patch.object(wi, "_maybe_prebuild_orderbook_ws_payload", side_effect=_track_prebuild),
    ):
        wi._flush_orderbook_tickers_sync(master, ["KXBTC15M-HOT"])

    assert order == ["hint:KXBTC15M-HOT", "prebuild:KXBTC15M-HOT"]


def test_periodic_resync_prefers_hot_crypto_and_stale_only(monkeypatch):
    monkeypatch.setenv("MARKET_WATCHDOG_PERIODIC_RESYNC_STALE_SEC", "30")
    master = _master(
        "KXBTC15M-CUR",
        "KXETH15M-CUR",
        "KXGOLD15M-CUR",
        "KXSILVER15M-FRESH",
        "KXSILVER15M-STALE",
    )
    now = 1_000_000.0
    master.books["KXGOLD15M-CUR"]["last_book_mono"] = 0.0  # never applied
    master.books["KXSILVER15M-FRESH"]["last_book_mono"] = now - 5.0
    master.books["KXSILVER15M-STALE"]["last_book_mono"] = now - 60.0

    with (
        patch("time.monotonic", return_value=now),
        patch(
            "backend.core.orderbook_hot_publish_registry.should_wake_tradeflow_on_orderbook",
            side_effect=lambda mt: mt.startswith("KXBTC15M"),
        ),
        patch(
            "backend.core.orderbook_hot_publish_registry.is_crypto_15m_orderbook_ticker",
            side_effect=lambda mt: mt.startswith(("KXBTC15M", "KXETH15M")),
        ),
    ):
        got = wi._periodic_resync_tickers(master)

    assert "KXBTC15M-CUR" in got
    assert "KXETH15M-CUR" in got
    assert "KXGOLD15M-CUR" in got  # never applied
    assert "KXSILVER15M-STALE" in got
    assert "KXSILVER15M-FRESH" not in got


def test_schedule_channel_resync_periodic_uses_subset():
    master = _master("KXBTC15M-A", "KXGOLD15M-B")
    master.channel_resync_debounce_until = 0.0
    master.channel_resync_last_mono = 0.0
    master.resync_in_progress = False
    queued: list[tuple[list[str], str]] = []

    with (
        patch.object(wi, "_periodic_resync_tickers", return_value=["KXBTC15M-A"]),
        patch.object(
            wi,
            "_queue_resync",
            side_effect=lambda m, tickers, reason: queued.append((list(tickers), reason)),
        ),
        patch("time.monotonic", return_value=10_000.0),
    ):
        wi._schedule_channel_resync(master, "periodic")

    assert queued == [(["KXBTC15M-A"], "periodic")]


def test_schedule_channel_resync_non_periodic_full_universe():
    master = _master("KXBTC15M-A", "KXGOLD15M-B")
    master.channel_resync_debounce_until = 0.0
    master.channel_resync_last_mono = 0.0
    master.resync_in_progress = False
    queued: list[tuple[list[str], str]] = []

    with (
        patch.object(
            wi,
            "_queue_resync",
            side_effect=lambda m, tickers, reason: queued.append((list(tickers), reason)),
        ),
        patch("time.monotonic", return_value=10_000.0),
    ):
        wi._schedule_channel_resync(master, "sid_change")

    assert queued[0][1] == "sid_change"
    assert set(queued[0][0]) == {"KXBTC15M-A", "KXGOLD15M-B"}


def test_trade_handler_defers_public_trade_off_loop():
    master = _master()
    master.trade_subscribed = {"KXGOLD15M-X"}
    published: list[tuple] = []

    def _fake_publish(m, mt, msg):
        published.append((mt, msg.get("yes_price_dollars")))

    raw = {
        "type": "trade",
        "msg": {
            "market_ticker": "KXGOLD15M-X",
            "yes_price_dollars": "0.42",
            "count_fp": "1",
        },
    }

    async def _run():
        with (
            patch.object(wi, "_publish_public_trade", side_effect=_fake_publish),
            patch.object(wi, "_emit_event"),
        ):
            await wi._on_ws_message(master, json.dumps(raw))
            # Allow create_task(to_thread(...)) to finish.
            for _ in range(50):
                if published:
                    break
                await asyncio.sleep(0.01)

    asyncio.run(_run())
    assert published == [("KXGOLD15M-X", "0.42")]
    assert master.last_trade_mono_by_ticker["KXGOLD15M-X"] > 0


def test_ob_delta_enqueues_cycle_hot_after_lock():
    master = _master("KXBTC15M-CUR")
    master.books["KXBTC15M-CUR"]["valid"] = True
    master.ob_channel_last_seq = 10
    jobs: list[dict] = []

    raw = {
        "type": "orderbook_delta",
        "sid": 1,
        "seq": 11,
        "msg": {
            "market_ticker": "KXBTC15M-CUR",
            "side": "yes",
            "price_dollars": "0.55",
            "delta_fp": "1.00",
        },
        "sending_ts_ms": 1_700_000_000_200,
    }

    scheduled: list[str] = []

    async def _run():
        with (
            patch.object(wi, "_enqueue_cycle_ob", side_effect=lambda job: jobs.append(job)),
            patch.object(
                wi,
                "_schedule_hot_ob_flush",
                side_effect=lambda m, mt: scheduled.append(mt),
            ),
        ):
            await wi._on_ws_message(master, json.dumps(raw))

    asyncio.run(_run())
    assert len(jobs) == 1
    assert jobs[0]["kind"] == "delta"
    assert jobs[0]["market_ticker"] == "KXBTC15M-CUR"
    assert jobs[0]["side"] == "yes"
    assert "KXBTC15M-CUR" in master.dirty_ob
    assert scheduled == ["KXBTC15M-CUR"]


def test_enqueue_cycle_ob_snapshot_and_delta():
    snap_calls = []
    delta_calls = []
    with patch(
        "backend.core.cycle_hot_tables.enqueue_snapshot",
        side_effect=lambda *a, **k: snap_calls.append(k),
    ), patch(
        "backend.core.cycle_hot_tables.enqueue_delta",
        side_effect=lambda *a, **k: delta_calls.append(k),
    ):
        wi._enqueue_cycle_ob(
            {
                "kind": "snapshot",
                "market_ticker": "KXBTC15M-X",
                "yes": {"0.5": "1"},
                "no": {"0.5": "1"},
                "seq": 3,
                "reason": "snapshot",
            }
        )
        wi._enqueue_cycle_ob(
            {
                "kind": "delta",
                "market_ticker": "KXBTC15M-X",
                "side": "no",
                "price": "0.010000",
                "delta": Decimal("2"),
                "seq": 4,
            }
        )
    assert len(snap_calls) == 1
    assert snap_calls[0]["seq"] == 3
    assert len(delta_calls) == 1
    assert delta_calls[0]["side"] == "no"
