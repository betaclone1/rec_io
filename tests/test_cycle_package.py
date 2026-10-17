"""Unit tests for cycle package path helpers."""

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.core.cycle_hot_tables import (
    active_hot_tickers_for_ts,
    cycle_window_utc,
    is_cycle_ticker,
    parse_cycle_ticker_end_est,
    series_from_ticker,
    symbol_from_cycle_ticker,
)
from backend.core.cycle_package_members import (
    PROPRIETARY_MEMBERS,
    export_external_variant,
    volume_path_csv_bytes,
)
from backend.core.cycle_packager import (
    PACKAGE_SCHEMA_VERSION,
    _existing_package_complete,
    month_folder,
    package_path_for_ticker,
    public_trades_to_csv_bytes,
    quality_gate,
)

_MT = "KXBTC15M-26JUL271045-45"
_ETH = "KXETH15M-26JUL271045-45"


def test_parse_ticker_end_est():
    end = parse_cycle_ticker_end_est("KXBTC15M-26JUL261345-45")
    assert end is not None
    assert end.tzinfo is not None
    assert end.year == 2026 and end.month == 7 and end.day == 26
    assert end.hour == 13 and end.minute == 45


def test_cycle_window_utc():
    open_u, close_u = cycle_window_utc("KXBTC15M-26JUL261345-45")
    assert (close_u - open_u).total_seconds() == 900


def test_cycle_window_quarter_hour_bounds_utc():
    """Named ticker ends 10:45 EDT → open 14:30Z, close 14:45Z inclusive endpoints."""
    open_u, close_u = cycle_window_utc(_MT)
    assert open_u == datetime(2026, 7, 27, 14, 30, tzinfo=timezone.utc)
    assert close_u == datetime(2026, 7, 27, 14, 45, tzinfo=timezone.utc)


def test_active_hot_includes_open_and_close_ticks():
    with (
        patch("backend.core.cycle_hot_tables.list_hot_tickers", return_value=[_MT]),
        patch("backend.core.cycle_hot_tables.refresh_hot_tickers_from_db"),
    ):
        assert _MT in active_hot_tickers_for_ts("2026-07-27T14:30:00.000Z")
        assert _MT in active_hot_tickers_for_ts("2026-07-27T14:45:00.000Z")
        assert _MT in active_hot_tickers_for_ts("2026-07-27T14:37:30.000Z")
        assert _MT not in active_hot_tickers_for_ts("2026-07-27T14:29:59.000Z")
        assert _MT not in active_hot_tickers_for_ts("2026-07-27T14:45:01.000Z")


def test_eth_ticker_identity_and_path():
    assert is_cycle_ticker(_ETH)
    assert series_from_ticker(_ETH) == "KXETH15M"
    assert symbol_from_cycle_ticker(_ETH) == "ETH"
    open_u, close_u = cycle_window_utc(_ETH)
    assert open_u == datetime(2026, 7, 27, 14, 30, tzinfo=timezone.utc)
    assert close_u == datetime(2026, 7, 27, 14, 45, tzinfo=timezone.utc)
    path = package_path_for_ticker(_ETH)
    assert path is not None
    assert path.parts[-3:] == ("2026", "2026_07_JUL", f"{_ETH}.tar.xz")
    assert "KXETH15M" in path.parts


def test_month_folder_and_path():
    end = parse_cycle_ticker_end_est("KXBTC15M-26JUL261345-45")
    year, month = month_folder(end)
    assert year == "2026"
    assert month == "2026_07_JUL"
    path = package_path_for_ticker("KXBTC15M-26JUL261345-45")
    assert path is not None
    assert path.parts[-3:] == ("2026", "2026_07_JUL", "KXBTC15M-26JUL261345-45.tar.xz")
    assert "backtesting_data" in path.parts
    assert "KXBTC15M" in path.parts


def test_public_trades_csv_bytes_empty_and_sorted():
    empty = public_trades_to_csv_bytes([])
    assert empty.startswith(b"trade_id,")
    raw = public_trades_to_csv_bytes(
        [
            {
                "trade_id": "b",
                "ticker": _MT,
                "created_time": "2026-07-27T14:40:00Z",
                "yes_price_dollars": "0.50",
                "no_price_dollars": "0.50",
                "count_fp": "1.00",
            },
            {
                "trade_id": "a",
                "ticker": _MT,
                "created_time": "2026-07-27T14:31:00Z",
                "yes_price_dollars": "0.40",
                "no_price_dollars": "0.60",
                "count_fp": "2.00",
            },
        ]
    )
    text = raw.decode("utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert "trade_id" in lines[0]
    assert lines[1].startswith("a,")
    assert lines[2].startswith("b,")


def test_quality_gate_requires_public_trades_and_v4_members():
    mm = {"floor_strike": 100.0, "market_result": "yes"}
    base = {"deltas.csv": 10, "price_ring.csv": 10, "strike_table.csv": 10}
    ok, reason = quality_gate(row_counts=base, market_meta=mm, require_public_trades=True)
    assert not ok and reason == "public_trades missing"
    ok2, _ = quality_gate(
        row_counts={**base, "public_trades.csv": 0},
        market_meta=mm,
        require_public_trades=True,
    )
    assert ok2
    # Legacy v2 on-disk: no public_trades key still complete
    ok3, _ = _existing_package_complete(
        names={"meta.json", "market_meta.json", "deltas.csv"},
        meta_obj={
            "schema_version": 2,
            "tables": {
                "deltas.csv": {"rows": 10},
                "price_ring.csv": {"rows": 10},
                "strike_table.csv": {"rows": 10},
            },
        },
        market_meta=mm,
    )
    assert ok3
    assert PACKAGE_SCHEMA_VERSION == 4
    ok4, reason4 = _existing_package_complete(
        names={"meta.json", "market_meta.json", "deltas.csv"},
        meta_obj={
            "schema_version": 3,
            "tables": {
                "deltas.csv": {"rows": 10},
                "price_ring.csv": {"rows": 10},
                "strike_table.csv": {"rows": 10},
                "public_trades.csv": {"rows": 5},
            },
        },
        market_meta=mm,
    )
    assert not ok4 and "public_trades" in reason4
    v4_counts = {
        **base,
        "public_trades.csv": 5,
        "volume_path.csv": 3,
        "quality.json": 1,
    }
    ok5, reason5 = quality_gate(
        row_counts={**base, "public_trades.csv": 5},
        market_meta=mm,
        require_public_trades=True,
        require_v4_members=True,
    )
    assert not ok5 and reason5 == "volume_path missing"
    ok6, _ = quality_gate(
        row_counts=v4_counts,
        market_meta=mm,
        require_public_trades=True,
        require_v4_members=True,
    )
    assert ok6
    ok7, reason7 = _existing_package_complete(
        names={
            "meta.json",
            "market_meta.json",
            "deltas.csv",
            "public_trades.csv",
            "volume_path.csv",
        },
        meta_obj={
            "schema_version": 4,
            "tables": {
                "deltas.csv": {"rows": 10},
                "price_ring.csv": {"rows": 10},
                "strike_table.csv": {"rows": 10},
                "public_trades.csv": {"rows": 5},
                "volume_path.csv": {"rows": 3},
            },
        },
        market_meta=mm,
    )
    assert not ok7 and "quality.json" in reason7


def test_volume_path_cumulates_by_second():
    open_u = datetime(2026, 7, 27, 14, 30, tzinfo=timezone.utc)
    close_u = datetime(2026, 7, 27, 14, 45, tzinfo=timezone.utc)
    raw, n = volume_path_csv_bytes(
        [
            {
                "created_time": "2026-07-27T14:31:00Z",
                "count_fp": "10",
            },
            {
                "created_time": "2026-07-27T14:31:00.500Z",
                "count_fp": "5",
            },
            {
                "created_time": "2026-07-27T14:32:00Z",
                "count": "2",
            },
        ],
        open_utc=open_u,
        close_utc=close_u,
    )
    assert n >= 3
    text = raw.decode("utf-8")
    assert "cum_count_fp" in text.splitlines()[0]
    assert "15" in text  # 10+5


def test_export_external_strips_proprietary(tmp_path: Path):
    src = tmp_path / "KXBTC15M-demo.tar.xz"
    members = {
        "meta.json": b'{"schema_version":4,"variant":"full","tables":{"strike_table.csv":{"rows":1},"metrics_ring.csv":{"rows":1},"price_ring.csv":{"rows":1}}}\n',
        "market_meta.json": b'{"market_result":"yes"}\n',
        "strike_table.csv": b"timestamp,probability_15m\n",
        "metrics_ring.csv": b"timestamp,momentum\n",
        "price_ring.csv": b"timestamp,price\n",
        "public_trades.csv": b"trade_id\n",
        "volume_path.csv": b"timestamp,cum_count_fp\n",
        "quality.json": b'{"status":"COMPLETE"}\n',
    }
    with tarfile.open(src, "w:xz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    out = export_external_variant(src)
    assert out.name.endswith(".external.tar.xz")
    with tarfile.open(out, "r:xz") as tar:
        names = {Path(n).name for n in tar.getnames()}
    for prop in PROPRIETARY_MEMBERS:
        assert prop not in names
    assert "price_ring.csv" in names
    assert "public_trades.csv" in names
    with tarfile.open(out, "r:xz") as tar:
        meta = json.loads(tar.extractfile("meta.json").read().decode("utf-8"))
    assert meta["variant"] == "external"
    assert "strike_table.csv" not in (meta.get("tables") or {})
