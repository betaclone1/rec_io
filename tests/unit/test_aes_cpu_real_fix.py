"""AES CPU real-fix: dead-monitor skip, out-of-window early-out, cheap status."""

from __future__ import annotations

import os
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
sys.argv = ["auto_entry_supervisor.py", "unified"]

import backend.auto_entry_supervisor as aes  # noqa: E402


def test_list_lane_monitor_rows_excludes_auto_trade_false(monkeypatch):
    aes._aes_lane_monitor_rows_cache = None
    aes._aes_lane_monitor_rows_at = 0.0
    rows = [
        {
            "user_number": "0001",
            "monitor_id": "1",
            "symbol": "BTC",
            "market": "15m",
            "strategy": "Hourly HTC",
            "auto_trade": True,
        },
        {
            "user_number": "0001",
            "monitor_id": "2",
            "symbol": "ETH",
            "market": "15m",
            "strategy": "Hourly HTC",
            "auto_trade": False,
        },
        {
            "user_number": "0001",
            "monitor_id": "3",
            "symbol": "SOL",
            "market": "hourly",
            "strategy": "Hourly HTC",
            # missing auto_trade → treated as not True
        },
    ]
    monkeypatch.setattr(aes, "AES_BTC15M_EXP_SCALP", False)
    monkeypatch.setattr(aes, "AES_UNIFIED_15M", False)
    monkeypatch.setattr(aes, "AES_UNIFIED_HOURLY", False)
    monkeypatch.setattr(aes, "AES_UNIFIED_ALL", True)

    fake_all = types.ModuleType("backend.core.unified_all_monitors")
    fake_all.list_active_unified_monitor_rows = lambda: rows
    monkeypatch.setitem(sys.modules, "backend.core.unified_all_monitors", fake_all)

    fake_cut = types.ModuleType("backend.core.aes_btc15m_exp_scalp_cutout")
    fake_cut.filter_out_cutout_rows = lambda r: r
    fake_cut.list_active_btc15m_exp_scalp_cutout_rows = lambda: []
    monkeypatch.setitem(sys.modules, "backend.core.aes_btc15m_exp_scalp_cutout", fake_cut)

    out = aes._aes_list_lane_monitor_rows()
    assert [r["monitor_id"] for r in out] == ["1"]


def test_bind_worker_out_of_window_skips_open_ticker_prime(monkeypatch):
    slot = types.SimpleNamespace(
        epoch=1,
        generation_id="g1",
        symbol="BTC",
        market="15m",
        snap={"event_ticker": "E", "ttc": 200, "strikes": []},
        captured_mono=None,
    )
    lane = MagicMock()
    lane.is_current.return_value = True

    prime = MagicMock()
    impl = MagicMock()
    status_updates = []

    monkeypatch.setattr(aes, "_aes_prime_open_ticker_sides_cache", prime)
    monkeypatch.setattr(aes, "_check_auto_entry_conditions_impl", impl)
    monkeypatch.setattr(aes, "get_trade_strategy", lambda: "Expiration Scalp")
    monkeypatch.setattr(aes, "is_auto_trade_enabled", lambda: True)
    monkeypatch.setattr(aes, "_aes_ttc_outside_entry_window", lambda: True)
    monkeypatch.setattr(
        aes,
        "determine_auto_entry_status",
        lambda: "INACTIVE",
    )
    monkeypatch.setattr(
        aes,
        "update_auto_entry_status_in_db",
        lambda s: status_updates.append(s),
    )

    @aes.contextmanager
    def _bind(_u, _m):
        yield

    monkeypatch.setattr(aes, "aes_monitor_bind", _bind)

    aes._aes_lane_bind_worker("0001", "10046", slot, lane)

    prime.assert_not_called()
    impl.assert_not_called()
    assert status_updates == ["INACTIVE"]


def test_bind_worker_in_window_runs_full_path(monkeypatch):
    slot = types.SimpleNamespace(
        epoch=1,
        generation_id="g1",
        symbol="BTC",
        market="15m",
        snap={"event_ticker": "E", "ttc": 30, "strikes": []},
        captured_mono=None,
    )
    lane = MagicMock()
    lane.is_current.return_value = True

    prime = MagicMock()
    impl = MagicMock()
    monkeypatch.setattr(aes, "_aes_prime_open_ticker_sides_cache", prime)
    monkeypatch.setattr(aes, "_check_auto_entry_conditions_impl", impl)
    monkeypatch.setattr(aes, "get_trade_strategy", lambda: "Expiration Scalp")
    monkeypatch.setattr(aes, "is_auto_trade_enabled", lambda: True)
    monkeypatch.setattr(aes, "_aes_ttc_outside_entry_window", lambda: False)
    monkeypatch.setattr(
        aes, "get_current_monitor_symbol_and_market", lambda: ("BTC", "15m")
    )

    @aes.contextmanager
    def _bind(_u, _m):
        yield

    monkeypatch.setattr(aes, "aes_monitor_bind", _bind)

    aes._aes_lane_bind_worker("0001", "10046", slot, lane)

    prime.assert_called_once()
    impl.assert_called_once()


def test_cheap_status_uses_cached_snap_not_failsafe_refresh(monkeypatch):
    """Cheap status flips from aged TTC without calling failsafe_refresh_all."""
    monkeypatch.setattr(aes, "AES_UNIFIED_POOL", True)
    snap = {
        "event_ticker": "KXBTC15M-X",
        "ttc": 90,
        "settlement_end_ms": None,
        "strikes": [],
    }
    cur = types.SimpleNamespace(snap=snap, captured_mono=None)
    lane = MagicMock()
    lane.current.return_value = cur
    hub = MagicMock()
    hub.lane.return_value = lane
    hub.failsafe_refresh_all = MagicMock()

    monkeypatch.setattr(aes, "_aes_ensure_lane_hub", lambda: hub)
    monkeypatch.setattr(
        aes,
        "_aes_list_lane_monitor_rows",
        lambda: [
            {
                "user_number": "0001",
                "monitor_id": "10046",
                "symbol": "BTC",
                "market": "15m",
                "auto_trade": True,
            }
        ],
    )

    statuses = []

    @aes.contextmanager
    def _bind(_u, _m):
        yield

    monkeypatch.setattr(aes, "aes_monitor_bind", _bind)
    monkeypatch.setattr(aes, "determine_auto_entry_status", lambda: "ACTIVE")
    monkeypatch.setattr(
        aes, "update_auto_entry_status_in_db", lambda s: statuses.append(s)
    )

    with patch(
        "backend.core.tradeflow_live_reads.ttc_seconds_from_ladder", return_value=30
    ):
        aes._aes_cheap_status_pass()

    hub.failsafe_refresh_all.assert_not_called()
    assert statuses == ["ACTIVE"]
    hub.lane.assert_called_with("BTC", "15m")


def test_failsafe_redis_env_defaults():
    assert aes._AES_FAILSAFE_POLL_SEC == float(os.getenv("AES_FAILSAFE_POLL_SEC", "1"))
    assert aes._AES_FAILSAFE_REDIS_SEC == float(os.getenv("AES_FAILSAFE_REDIS_SEC", "5"))


def test_strike_regen_floor_default():
    from backend import strike_table_generator_ws as sg

    assert float(sg.STRIKE_REGEN_MIN_INTERVAL_SEC) >= 1.0


def test_live_state_strike_feed_sync_symbols_filter(monkeypatch):
    from backend.core.market_watchdog.venues.kalshi import ws_ingest as wi

    calls = []

    class FakeCache:
        @staticmethod
        def set_market(ex, market, sym, body, source_event_at=None):
            calls.append((market, sym))

    monkeypatch.setattr(
        "backend.core.live_state_cache.set_market", FakeCache.set_market, raising=False
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.live_state_cache",
        types.SimpleNamespace(set_market=FakeCache.set_market),
    )

    master = MagicMock()
    master.symbols = ["BTC", "ETH", "SOL"]
    master.cfg.exchange = "kalshi"
    master.cfg.includes_15m = True
    master.cfg.includes_hourly = False
    master.ticker_subscribed = set()
    master.books = {}
    master.ticker_pending = {}

    # No subscribed tickers → no publishes, but filter must not iterate all symbols
    # via set_market. Call with symbols={"ETH"} and ensure BTC/SOL never appear.
    wi._live_state_strike_feed_sync(master, symbols={"ETH"})
    assert all(sym == "ETH" for _, sym in calls)


def test_periodic_status_sync_uses_lane_membership_not_all_monitors(monkeypatch):
    """Cutout/unified status sync must not walk unfiltered unified bindings."""
    bound = []

    monkeypatch.setattr(aes, "AES_UNIFIED_POOL", True)
    monkeypatch.setattr(
        aes,
        "_aes_list_lane_monitor_rows",
        lambda: [
            {"user_number": "0001", "monitor_id": "10046"},
            {"user_number": "0001", "monitor_id": "10056"},
        ],
    )

    @contextmanager
    def _bind(u, m):
        bound.append((u, m))
        yield

    monkeypatch.setattr(aes, "aes_monitor_bind", _bind)
    monkeypatch.setattr(aes, "is_auto_trade_enabled", lambda: True)
    monkeypatch.setattr(aes, "determine_auto_entry_status", lambda: "ACTIVE")
    monkeypatch.setattr(aes, "update_auto_entry_status_in_db", lambda _s: None)

    def _must_not_import_all():
        raise AssertionError("periodic_status_sync must not iterate all unified monitors")

    fake_all = types.ModuleType("backend.core.unified_all_monitors")
    fake_all.iter_active_unified_monitor_bindings = _must_not_import_all
    monkeypatch.setitem(sys.modules, "backend.core.unified_all_monitors", fake_all)

    aes.periodic_status_sync()
    assert bound == [("0001", "10046"), ("0001", "10056")]

