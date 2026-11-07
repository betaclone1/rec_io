"""Dedicated OB live feed: ownership gate + apply/publish contract."""

from __future__ import annotations

from backend.core import kalshi_ob_live as ob
from backend.core.kalshi_ob_live import ObLiveFeed


def test_ob_live_owner_enabled_default(monkeypatch):
    monkeypatch.delenv("REC_KALSHI_OB_LIVE_OWNER", raising=False)
    assert ob.ob_live_owner_enabled() is True
    monkeypatch.setenv("REC_KALSHI_OB_LIVE_OWNER", "0")
    assert ob.ob_live_owner_enabled() is False


def test_apply_delta_submits_payload_with_raw_venue_stamp():
    submitted = []

    class Pub:
        def submit(self, payload):
            submitted.append(payload)

    feed = ObLiveFeed(["BTC"], Pub())  # type: ignore[arg-type]
    feed.bind("BTC", "KXBTC15M-TEST")
    book = feed.books["BTC"]
    book.valid = True
    book.yes = {"0.500000": "10.00"}
    book.no = {"0.500000": "10.00"}

    envelope = {"seq": 10, "sending_ts_ms": 1_700_000_000_050}
    msg = {
        "side": "yes",
        "price_dollars": "0.99",
        "delta_fp": "5.00",
        "ts_ms": 1_700_000_000_000,
    }
    feed.apply_delta(book, envelope, msg, recv_ms=1_700_000_000_080)
    assert len(submitted) == 1
    body = submitted[0]
    assert body["market_ticker"] == "KXBTC15M-TEST"
    assert body["venue_ts_ms"] == 1_700_000_000_000
    assert body["sending_ts_ms"] == 1_700_000_000_050
    assert body["t_ws_recv_ms"] == 1_700_000_000_080
    assert body["yes"]["0.990000"] == "5.00"
    assert book.t_ws_recv_ms - book.venue_ts_ms == 80


def test_lifecycle_skips_full_15m_ob_when_live_owner(monkeypatch):
    from backend.core.market_watchdog.config import load_config
    from backend.core.market_watchdog.venues.kalshi import ws_ingest as wi

    monkeypatch.setenv("REC_KALSHI_OB_LIVE_OWNER", "1")
    cfg = load_config(exchange="kalshi", market_interval="15m")
    master = wi.KalshiMarketWsMaster(cfg=cfg, symbols=["BTC"])
    master.schedule_by_symbol = {"BTC": {"15m": []}}
    _ticker_sub, ob_sub, _trade_sub, _ = wi._lifecycle_sets(master, 1_700_000_000.0)
    assert not any(str(t).startswith("KXBTC15M-") for t in ob_sub)


def test_lifecycle_includes_ob_when_live_owner_off(monkeypatch):
    from backend.core.market_watchdog.config import load_config
    from backend.core.market_watchdog.venues.kalshi import ws_ingest as wi

    monkeypatch.setenv("REC_KALSHI_OB_LIVE_OWNER", "0")
    cfg = load_config(exchange="kalshi", market_interval="15m")
    master = wi.KalshiMarketWsMaster(cfg=cfg, symbols=["BTC"])
    master.schedule_by_symbol = {"BTC": {"15m": []}}
    _ticker_sub, ob_sub, _trade_sub, _ = wi._lifecycle_sets(master, 1_700_000_000.0)
    assert any(str(t).startswith("KXBTC15M-") for t in ob_sub)
