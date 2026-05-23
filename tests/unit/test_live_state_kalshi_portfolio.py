import json
from unittest.mock import MagicMock, patch

from backend.core import live_state_kalshi_portfolio as lskp
from backend.core.kalshi_portfolio_records import (
    normalize_fill_record,
    normalize_order_record,
    normalize_position_record,
)
from backend.core.portfolio_pg_spool import PortfolioPgSpool


def test_normalize_position_record_maps_rest_market_exposure_to_cost():
    rec = normalize_position_record(
        {
            "ticker": "KXBTC-1",
            "position_fp": "2",
            "market_exposure_dollars": "1.500000",
        }
    )
    assert rec is not None
    assert rec["position_cost_dollars"] == "1.500000"
    assert "market_exposure_dollars" not in rec


def test_normalize_position_record_keeps_zero():
    rec = normalize_position_record({"ticker": "KXBTC-1", "position_fp": "0"})
    assert rec is not None
    assert rec["position_fp"] == "0"
    rec2 = normalize_position_record({"ticker": "KXBTC-1", "position_fp": "5"})
    assert rec2 is not None
    assert rec2["ticker"] == "KXBTC-1"


def test_normalize_position_record_preserves_ws_decimal_strings():
    rec = normalize_position_record(
        {
            "ticker": "KXBTC-1",
            "position_fp": "0.000000000012",
            "position_cost_dollars": "0.000000",
            "realized_pnl_dollars": "-0.050000",
        }
    )
    assert rec["position_fp"] == "0.000000000012"
    assert rec["position_cost_dollars"] == "0.000000"
    assert rec["realized_pnl_dollars"] == "-0.050000"


def test_normalize_position_flat_zeros_cost_when_omitted():
    rec = normalize_position_record({"ticker": "KXBTC-1", "position_fp": "0"})
    assert rec["position_fp"] == "0"
    assert rec["position_cost_dollars"] == "0"


def test_normalize_position_flat_keeps_ws_cost_zero():
    rec = normalize_position_record(
        {"market_ticker": "KXBTC-1", "position": 0, "position_cost": 0, "realized_pnl": 9999}
    )
    assert rec["position_cost_dollars"] == "0"
    assert rec["realized_pnl_dollars"] == "0.9999"


def test_normalize_position_record_ws_centi_cents():
    rec = normalize_position_record(
        {
            "market_ticker": "KXBTC-1",
            "position": "5",
            "position_cost": 50000,
            "realized_pnl": 123456,
        }
    )
    assert rec is not None
    assert rec["ticker"] == "KXBTC-1"
    assert rec["position_fp"] == "5"
    assert rec["position_cost_dollars"] == "5"
    assert rec["realized_pnl_dollars"] == "12.3456"


def test_normalize_position_record_strips_legacy_market_exposure():
    rec = normalize_position_record(
        {
            "ticker": "KXBTC-1",
            "position_fp": "1",
            "market_exposure_dollars": "9.99",
            "position_cost_dollars": "0.500000",
        }
    )
    assert rec is not None
    assert "market_exposure_dollars" not in rec
    assert rec["position_cost_dollars"] == "0.500000"


def test_normalize_position_record_ws_dollars_passthrough():
    rec = normalize_position_record(
        {
            "ticker": "KXBTC-1",
            "position_fp": "3",
            "position_cost_dollars": "4.50",
            "realized_pnl_dollars": "-1.25",
        }
    )
    assert rec["position_cost_dollars"] == "4.50"
    assert rec["realized_pnl_dollars"] == "-1.25"


def test_normalize_fill_and_order():
    fill = normalize_fill_record(
        {"trade_id": "t1", "ticker": "ABC", "action": "buy", "count_fp": "10"}
    )
    assert fill and fill["trade_id"] == "t1"
    order = normalize_order_record(
        {"order_id": "o1", "ticker": "ABC", "status": "resting", "action": "buy"}
    )
    assert order and order["order_id"] == "o1"


@patch.object(lskp, "live_state_kalshi_portfolio_enabled", return_value=True)
@patch.object(lskp, "redis_client_optional")
def test_upsert_publishes_embedded_row(mock_redis_fn, _enabled):
    r = MagicMock()
    mock_redis_fn.return_value = r
    published = []

    def _capture_publish(channel, payload):
        published.append(json.loads(payload))

    r.publish.side_effect = _capture_publish
    ok = lskp.upsert_fill_from_ws(
        "0001",
        {
            "msg": {
                "trade_id": "pub-test-1",
                "ticker": "T",
                "action": "buy",
                "count_fp": "1",
                "created_time": "2099-01-01T00:00:00Z",
            }
        },
    )
    assert ok is True
    assert published
    msg = published[-1]
    assert msg.get("row") is not None
    assert msg["row"]["trade_id"] == "pub-test-1"


@patch.object(lskp, "live_state_kalshi_portfolio_enabled", return_value=True)
@patch.object(lskp, "redis_client_optional")
def test_upsert_and_list_positions(mock_redis_fn, _enabled):
    r = MagicMock()
    r.hgetall.return_value = {
        "T1": '{"ticker":"T1","position_fp":5.0,"last_updated_ts":"2026-05-23T12:00:00Z"}'
    }
    mock_redis_fn.return_value = r
    assert len(lskp.list_positions("0001")) == 1
    ok = lskp.upsert_position_from_ws(
        "0001",
        {"msg": {"market_ticker": "T2", "position_fp": "3", "last_updated_ts": "x"}},
    )
    assert ok is True
    r.hset.assert_called()


@patch.object(lskp, "live_state_kalshi_portfolio_enabled", return_value=True)
@patch.object(lskp, "redis_client_optional")
def test_upsert_position_zero_keeps_row_in_hot_cache(mock_redis_fn, _enabled):
    r = MagicMock()
    mock_redis_fn.return_value = r
    published = []

    def _capture_publish(channel, payload):
        published.append(json.loads(payload))

    r.publish.side_effect = _capture_publish
    ok = lskp.upsert_position_from_ws(
        "0001",
        {"msg": {"market_ticker": "T1", "position_fp": "0", "last_updated_ts": "x"}},
    )
    assert ok is True
    r.hset.assert_called()
    r.hdel.assert_not_called()
    assert published
    assert published[-1].get("row", {}).get("position_fp") == "0"


@patch.object(lskp, "live_state_kalshi_portfolio_enabled", return_value=True)
@patch.object(lskp, "redis_client_optional")
def test_replace_positions_baseline_seeds_rest_snapshot(mock_redis_fn, _enabled):
    r = MagicMock()
    mock_redis_fn.return_value = r
    r.hgetall.return_value = {"OLD": "{}"}
    published = []

    def _capture_publish(channel, payload):
        published.append(json.loads(payload))

    r.publish.side_effect = _capture_publish
    count = lskp.replace_positions_baseline(
        "0001",
        [
            {
                "ticker": "T1",
                "position_fp": "1",
                "market_exposure_dollars": "0.950000",
                "realized_pnl_dollars": "-0.060000",
            }
        ],
    )
    assert count == 1
    r.hset.assert_called()
    r.hdel.assert_called_with(lskp.tenant_kalshi_positions_key("0001"), "OLD")
    assert published
    assert published[-1].get("detail") == "baseline"


def test_portfolio_spool_flush_calls_upsert():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    flushed = []

    spool = PortfolioPgSpool(
        get_pg_connection=lambda: conn,
        fills_table=lambda: "users.fills_0001",
        orders_table=lambda: "users.orders_0001",
        on_flush=lambda entity, n: flushed.append((entity, n)),
    )
    spool.append_fill(
        normalize_fill_record({"trade_id": "f1", "ticker": "X", "action": "buy", "count_fp": "1"})
    )
    spool._flush_batch(spool._drain_batch())
    cur.execute.assert_called()
    conn.commit.assert_called()
    assert ("fills", 1) in flushed


def test_live_path_catalog_includes_kalshi_sources():
    from backend.core.live_path_cache_monitor import (
        SOURCE_KALSHI_FILLS,
        SOURCE_KALSHI_ORDERS,
        SOURCE_KALSHI_POSITIONS,
        source_catalog,
    )

    ids = {s["id"] for s in source_catalog()}
    assert SOURCE_KALSHI_POSITIONS in ids
    assert SOURCE_KALSHI_ORDERS in ids
    assert SOURCE_KALSHI_FILLS in ids


def test_record_epoch_and_retention():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    assert lskp._record_epoch(now) is not None
    rec = {"created_time": now}
    assert lskp._within_retention(rec, "created_time") is True
    old = {"created_time": "2020-01-01T00:00:00Z"}
    assert lskp._within_retention(old, "created_time") is False


@patch.object(lskp, "live_state_kalshi_portfolio_enabled", return_value=True)
@patch.object(lskp, "redis_client_optional")
def test_get_order(mock_redis_fn, _enabled):
    r = MagicMock()
    mock_redis_fn.return_value = r
    order = {"order_id": "ord-1", "status": "executed", "fill_count_fp": "1"}
    r.hget.return_value = json.dumps(order)
    got = lskp.get_order("0001", "ord-1")
    assert got == order
    r.hget.assert_called_once()


@patch.object(lskp, "live_state_kalshi_portfolio_enabled", return_value=True)
@patch.object(lskp, "redis_client_optional")
def test_prune_positions_to_rest_tickers(mock_redis_fn, _enabled):
    r = MagicMock()
    mock_redis_fn.return_value = r
    r.hgetall.return_value = {
        "KEEP": '{"ticker":"KEEP"}',
        "DROP": '{"ticker":"DROP"}',
    }
    r.hdel.side_effect = lambda _k, f: f == "DROP"
    published = []

    def _capture_publish(channel, payload):
        published.append(json.loads(payload))

    r.publish.side_effect = _capture_publish
    removed = lskp.prune_positions_to_rest_tickers("0001", ["KEEP"])
    assert removed == 1
    r.hdel.assert_called()
    assert published
    assert published[-1].get("removes") == ["DROP"]


@patch.object(lskp, "live_state_kalshi_portfolio_enabled", return_value=True)
@patch.object(lskp, "redis_client_optional")
def test_merge_fills_baseline_respects_retention(mock_redis_fn, _enabled):
    r = MagicMock()
    mock_redis_fn.return_value = r
    fills = [
        {"trade_id": "new", "created_time": "2099-01-01T00:00:00Z", "action": "buy", "count_fp": "1"},
        {"trade_id": "old", "created_time": "2020-01-01T00:00:00Z", "action": "buy", "count_fp": "1"},
    ]
    count = lskp.merge_fills_baseline("0001", fills)
    assert count == 1
    r.hset.assert_called_once()


@patch.object(lskp, "live_state_kalshi_portfolio_enabled", return_value=True)
@patch.object(lskp, "list_fills")
def test_sum_fill_count_for_order(_list_fills, _enabled):
    _list_fills.return_value = [
        {"order_id": "oid-a", "count_fp": 1.0},
        {"order_id": "oid-a", "count_fp": 50.0},
        {"order_id": "oid-b", "count_fp": 10.0},
    ]
    assert lskp.sum_fill_count_for_order("0001", "oid-a") == 51.0
    assert lskp.sum_fill_count_for_order("0001", "oid-b") == 10.0
    assert lskp.sum_fill_count_for_order("0001", "") == 0.0


@patch.object(lskp, "live_state_kalshi_portfolio_enabled", return_value=True)
@patch.object(lskp, "list_fills")
@patch.object(lskp, "redis_client_optional")
def test_get_order_merges_fill_legs_when_order_row_stale(mock_redis_fn, mock_list_fills, _enabled):
    r = MagicMock()
    mock_redis_fn.return_value = r
    order = {
        "order_id": "oid-a",
        "status": "canceled",
        "initial_count_fp": 623.0,
        "fill_count_fp": 0.0,
        "remaining_count_fp": 623.0,
        "last_update_time": "2099-01-01T00:00:00Z",
    }
    r.hget.return_value = json.dumps(order)
    mock_list_fills.return_value = [
        {
            "order_id": "oid-a",
            "count_fp": 51.0,
            "outcome_side": "no",
            "yes_price_dollars": "0.0500",
            "raw_json": {"fee_cost": "0.170000"},
        }
    ]
    merged = lskp.get_order("0001", "oid-a")
    assert merged is not None
    assert float(merged["fill_count_fp"]) == 51.0
    assert float(merged["remaining_count_fp"]) == 572.0
    assert float(merged["taker_fees_dollars"]) == 0.17
