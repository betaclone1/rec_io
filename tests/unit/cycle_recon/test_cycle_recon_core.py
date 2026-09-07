"""Unit tests for cycle reconstruction (synthetic + fixture-backed)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.core.cycle_package import CyclePackage
from backend.core.cycle_recon.book_engine import reconstruct_book
from backend.core.cycle_recon.measurements import (
    aggregate_whole_cent,
    complementary_asks,
    vwap_metrics,
    liquidation_vwap,
)
from backend.core.cycle_recon.package_writer import write_table, pyarrow_available
from backend.core.cycle_recon.time_util import combine_trade_log_open_utc, parse_utc
from backend.core.cycle_recon.trade_log import find_trade_refs, select_strategy_trades


_UTC = timezone.utc
FIXTURE_CSV = Path("tests/fixtures/cycle_recon/10058_full_09_05.csv")


def _pkg_from(
    *,
    snapshots,
    deltas,
    open_utc: datetime,
    close_utc: datetime,
    ticker: str = "KXBTC15M-TEST",
) -> CyclePackage:
    return CyclePackage(
        path=Path("/tmp/fake.tar.xz"),
        meta={
            "market_ticker": ticker,
            "cycle_open_utc": open_utc.isoformat().replace("+00:00", "Z"),
            "cycle_close_utc": close_utc.isoformat().replace("+00:00", "Z"),
        },
        market_meta={"floor_strike": "100000", "market_result": "yes"},
        snapshots=snapshots,
        deltas=deltas,
        strike_rows=[],
        price_rows=[],
        metrics_rows=[],
    )


def test_complementary_asks_and_whole_cent():
    yes = {"0.40": "10"}
    no = {"0.55": "5", "0.549": "2"}  # implies yes asks at 0.45 and 0.451
    asks = complementary_asks(yes, no, "yes")
    assert asks[0][0] == pytest.approx(0.45)
    wc = aggregate_whole_cent({"0.451": "2", "0.459": "1", "0.46": "3"})
    assert wc["0.45"] == pytest.approx(3.0)
    assert wc["0.46"] == pytest.approx(3.0)


def test_vwap_and_liquidation():
    # YES buy walks NO bids as asks: no bid 0.40 -> yes ask 0.60 size 10
    yes = {"0.50": "100"}
    no = {"0.40": "10", "0.30": "10"}
    m = vwap_metrics(yes, no, "yes", 15)
    assert m["filled"] == pytest.approx(15)
    assert m["vwap"] is not None
    liq = liquidation_vwap(yes, no, "yes", 50)
    assert liq["filled"] == pytest.approx(50)
    assert liq["vwap"] == pytest.approx(0.50)


def test_reconstruction_gap_and_stale():
    open_u = datetime(2026, 9, 5, 15, 0, tzinfo=_UTC)
    close_u = open_u + timedelta(minutes=15)
    snap = {
        "seq": "1",
        "received_at": open_u.isoformat().replace("+00:00", "Z"),
        "yes": {"0.50": "10"},
        "no": {"0.40": "10"},
    }
    d1 = {
        "snapshot_seq": "1",
        "received_at": (open_u + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "side": "yes",
        "price": "0.50",
        "delta": "1",
    }
    d2 = {
        "snapshot_seq": "1",
        "received_at": (open_u + timedelta(seconds=21)).isoformat().replace("+00:00", "Z"),
        "side": "yes",
        "price": "0.50",
        "delta": "1",
    }
    pkg = _pkg_from(snapshots=[snap], deltas=[d1, d2], open_utc=open_u, close_utc=close_u)
    recon = reconstruct_book(pkg, gap_threshold_s=10.0, stale_threshold_s=2.0)
    assert "TIMESTAMP_GAP" in recon.reason_codes
    assert recon.quality_state == "DEGRADED"
    assert any(i.reason_code == "TIMESTAMP_GAP" for i in recon.intervals)
    # samples inside gap marked stale
    gap_samples = [s for s in recon.samples_1s if "TIMESTAMP_GAP" in s.quality_flags]
    assert gap_samples
    assert all(s.stale for s in gap_samples)


def test_duplicate_and_negative_depth():
    open_u = datetime(2026, 9, 5, 15, 0, tzinfo=_UTC)
    close_u = open_u + timedelta(minutes=1)
    snap = {
        "seq": "1",
        "received_at": open_u.isoformat().replace("+00:00", "Z"),
        "yes": {"0.50": "5"},
        "no": {},
    }
    raw = (open_u + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    d = {
        "seq": "10",
        "snapshot_seq": "1",
        "received_at": raw,
        "side": "yes",
        "price": "0.50",
        "delta": "1",
    }
    d_dup = dict(d)  # same seq => true duplicate
    d_neg = {
        "seq": "11",
        "snapshot_seq": "1",
        "received_at": (open_u + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        "side": "yes",
        "price": "0.50",
        "delta": "-100",
    }
    pkg = _pkg_from(snapshots=[snap], deltas=[d, d_dup, d_neg], open_utc=open_u, close_utc=close_u)
    recon = reconstruct_book(pkg)
    assert "DELTA_DUPLICATE" in recon.reason_codes
    assert "NEGATIVE_DEPTH" in recon.reason_codes


def test_timezone_midnight_et():
    # 2026-09-05 00:00:00 ET is 2026-09-05 04:00:00 UTC (EDT)
    dt = combine_trade_log_open_utc("2026-09-05", "00:00:00")
    assert dt.astimezone(_UTC).hour == 4


@pytest.mark.skipif(not FIXTURE_CSV.is_file(), reason="fixture csv missing")
def test_trade_log_source_scoped_ids():
    found, missing = find_trade_refs(FIXTURE_CSV, ["55286", "55388"])
    assert not missing
    assert {t.trade_id for t in found} == {"55286", "55388"}
    assert found[0].ticker.startswith("KXBTC15M-26SEP05")
    assert "csv:" in found[0].source_namespace
    assert found[0].source_sha256
    # identity includes source hash
    assert "sha=" in found[0].identity_key


def test_package_writer_parquet_or_fallback(tmp_path: Path):
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    meta = write_table(tmp_path / "t", rows, prefer_parquet=True)
    assert meta["rows"] == 2
    assert (tmp_path / meta["path"]).is_file()
    if pyarrow_available():
        assert meta["encoding"] == "parquet"
    else:
        assert meta["encoding"] in ("jsonl.zst", "jsonl")


def test_trade_id_pg_requires_user_no():
    from backend.core.cycle_recon.orchestrator import RunRequest, resolve_markets

    with pytest.raises(ValueError, match="user_no"):
        resolve_markets(RunRequest(trade_ids=["55286"], use_pg=True))
