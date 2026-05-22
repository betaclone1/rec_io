"""live_state_active_trades — Redis open-position pool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backend.core import live_state_active_trades as ls_at


def test_tenant_key_format():
    assert ls_at.tenant_active_trades_key("1") == ls_at.tenant_active_trades_key("0001")
    assert ":tenant:0001:active_trades" in ls_at.tenant_active_trades_key("0001")


def test_upsert_list_remove_roundtrip():
    store: dict = {}

    def fake_hset(key, field, value):
        store[f"{key}:{field}"] = value
        return 1

    def fake_hget(key, field):
        return store.get(f"{key}:{field}")

    def fake_hgetall(key):
        prefix = f"{key}:"
        return {
            k.split(":", 1)[1]: v
            for k, v in store.items()
            if k.startswith(prefix)
        }

    def fake_hdel(key, field):
        store.pop(f"{key}:{field}", None)

    mock_r = MagicMock()
    mock_r.hset.side_effect = fake_hset
    mock_r.hget.side_effect = fake_hget
    mock_r.hgetall.side_effect = fake_hgetall
    mock_r.hdel.side_effect = fake_hdel
    mock_r.expire.return_value = True
    mock_r.publish.return_value = 1

    trade = {
        "trade_id": 42,
        "monitor_id": "10002",
        "ticker": "KXBTC-TEST",
        "status": "active",
        "buy_price": 0.55,
    }
    with patch.object(ls_at, "live_state_active_trades_enabled", return_value=True):
        with patch.object(ls_at, "redis_client_optional", return_value=mock_r):
            assert ls_at.upsert_trade("0001", trade)
            got = ls_at.get_trade("0001", 42)
            assert got is not None
            assert got["ticker"] == "KXBTC-TEST"
            rows = ls_at.list_trades("0001", monitor_id="10002")
            assert len(rows) == 1
            assert ls_at.update_trade_fields("0001", 42, {"current_pnl": "1.25"})
            got2 = ls_at.get_trade("0001", 42)
            assert got2["current_pnl"] == "1.25"
            assert ls_at.remove_trade("0001", 42)
            assert ls_at.get_trade("0001", 42) is None


def test_pool_status_map_filters_monitor():
    store: dict = {}

    def fake_hset(key, field, value):
        store[f"{key}:{field}"] = value

    def fake_hgetall(key):
        prefix = f"{key}:"
        return {k.split(":", 1)[1]: v for k, v in store.items() if k.startswith(prefix)}

    mock_r = MagicMock()
    mock_r.hset.side_effect = fake_hset
    mock_r.hgetall.side_effect = fake_hgetall
    mock_r.expire.return_value = True
    mock_r.publish.return_value = 1

    with patch.object(ls_at, "live_state_active_trades_enabled", return_value=True):
        with patch.object(ls_at, "redis_client_optional", return_value=mock_r):
            ls_at.upsert_trade(
                "0001",
                {"trade_id": 1, "monitor_id": "10001", "status": "active"},
                publish=False,
            )
            ls_at.upsert_trade(
                "0001",
                {"trade_id": 2, "monitor_id": "10002", "status": "pending"},
                publish=False,
            )
            m = ls_at.pool_status_map("0001", monitor_id="10002")
            assert m == {2: "pending"}


def test_publish_payload_kind():
    published = []

    def capture_publish(channel, msg):
        published.append(json.loads(msg))

    mock_r = MagicMock()
    mock_r.publish.side_effect = capture_publish

    with patch.object(ls_at, "live_state_active_trades_enabled", return_value=True):
        with patch.object(ls_at, "redis_client_optional", return_value=mock_r):
            ls_at._publish_active_trades_updated("0001")
    assert published[0]["kind"] == "active_trades"
