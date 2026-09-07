"""Correctness tests for cycle reconstruction (lookahead, bids, public windows, quality)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.core.cycle_package import CyclePackage
from backend.core.cycle_recon.book_engine import collect_lifecycle_targets, reconstruct_book
from backend.core.cycle_recon.lifecycle import build_lifecycle_rows
from backend.core.cycle_recon.measurements import (
    map_taker_signed_contracts,
    normalize_yes_price_dollars,
    public_trade_window_stats,
)
from backend.core.cycle_recon.time_util import parse_utc, to_iso_z
from backend.core.cycle_recon.trade_log import StrategyTradeRef, find_trade_refs

_UTC = timezone.utc
FIXTURE_CSV = Path("tests/fixtures/cycle_recon/10058_full_09_05.csv")


def _pkg(snapshots, deltas, open_utc, close_utc, ticker="KXBTC15M-TEST"):
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
        price_rows=[
            {
                "timestamp": (open_utc + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
                "price": "100050",
                "avg_60s": "100040",
            }
        ],
        metrics_rows=[],
    )


def test_no_lookahead_as_of_book():
    open_u = datetime(2026, 9, 5, 15, 0, tzinfo=_UTC)
    close_u = open_u + timedelta(minutes=15)
    snap = {
        "seq": "1",
        "received_at": open_u.isoformat().replace("+00:00", "Z"),
        "yes": {"0.500000": "10"},
        "no": {"0.400000": "10"},
        "reason": "initial",
    }
    d1 = {
        "seq": "10",
        "snapshot_seq": "1",
        "received_at": (open_u + timedelta(seconds=46, milliseconds=100)).isoformat().replace("+00:00", "Z"),
        "side": "yes",
        "price": "0.500000",
        "delta": "1",
    }
    d2 = {
        "seq": "11",
        "snapshot_seq": "1",
        "received_at": (open_u + timedelta(seconds=46, milliseconds=900)).isoformat().replace("+00:00", "Z"),
        "side": "yes",
        "price": "0.500000",
        "delta": "100",
    }
    entry = open_u + timedelta(seconds=46, milliseconds=515)
    # Need a later event so capture_before finalizes entry before d2
    pkg = _pkg([snap], [d1, d2], open_u, close_u)
    recon = reconstruct_book(pkg, as_of_targets=[entry])
    assert entry in recon.as_of_books
    idx, book_ts, yes, no = recon.as_of_books[entry]
    assert book_ts <= entry
    assert book_ts == open_u + timedelta(seconds=46, milliseconds=100)
    assert float(yes["0.500000"]) == pytest.approx(11.0)


def test_lifecycle_book_timestamp_le_observation():
    open_u = datetime(2026, 9, 5, 15, 0, tzinfo=_UTC)
    close_u = open_u + timedelta(minutes=15)
    snap = {
        "seq": "1",
        "received_at": open_u.isoformat().replace("+00:00", "Z"),
        "yes": {"0.50": "10"},
        "no": {"0.40": "10"},
        "reason": "initial",
    }
    deltas = []
    for i, ms in enumerate((100, 400, 700, 999)):
        deltas.append(
            {
                "seq": str(100 + i),
                "snapshot_seq": "1",
                "received_at": (open_u + timedelta(seconds=60, milliseconds=ms))
                .isoformat()
                .replace("+00:00", "Z"),
                "side": "no",
                "price": "0.40",
                "delta": "1",
            }
        )
    entry = open_u + timedelta(seconds=60, milliseconds=515)
    trade = StrategyTradeRef(
        source_path="x",
        source_sha256="abc",
        source_namespace="csv:test",
        trade_id="1",
        ticker="KXBTC15M-TEST",
        monitor="mon_test",
        side="Y",
        date="2026-09-05",
        entry_utc=entry,
        close_utc=entry + timedelta(seconds=5),
        row={"position": "10", "side": "Y"},
    )
    pkg = _pkg([snap], deltas, open_u, close_u)
    targets = collect_lifecycle_targets(pkg, entry=entry, close=trade.close_utc)
    recon = reconstruct_book(pkg, as_of_targets=targets)
    rows = build_lifecycle_rows(pkg, recon, trade=trade, public_trades=[])
    assert rows
    for r in rows:
        book_ts = parse_utc(r["book_timestamp_utc"])
        obs = parse_utc(r["timestamp_utc"])
        assert book_ts <= obs, r
        assert float(r["book_age_ms"]) >= -1e-6
        assert isinstance(r["best_bid"], (int, float, type(None)))
        assert not isinstance(r["best_bid"], dict)


def test_best_bid_is_scalar_not_vwap_map():
    open_u = datetime(2026, 9, 5, 15, 0, tzinfo=_UTC)
    close_u = open_u + timedelta(minutes=1)
    snap = {
        "seq": "1",
        "received_at": open_u.isoformat().replace("+00:00", "Z"),
        "yes": {"0.55": "10"},
        "no": {"0.40": "10"},
        "reason": "initial",
    }
    pkg = _pkg([snap], [], open_u, close_u)
    entry = open_u + timedelta(seconds=1)
    trade = StrategyTradeRef(
        source_path="x",
        source_sha256="abc",
        source_namespace="csv:test",
        trade_id="1",
        ticker="KXBTC15M-TEST",
        monitor=None,
        side="Y",
        date="2026-09-05",
        entry_utc=entry,
        close_utc=None,
        row={"position": "5", "side": "Y"},
    )
    recon = reconstruct_book(pkg, as_of_targets=[open_u, entry, close_u])
    rows = build_lifecycle_rows(pkg, recon, trade=trade)
    entry_row = next(r for r in rows if r["observation"] == "entry")
    assert entry_row["best_bid"] == pytest.approx(0.55)
    assert isinstance(entry_row["entry_vwap_actual_size"], dict)
    assert "vwap" in entry_row["entry_vwap_actual_size"]


def test_public_trade_windows_trailing_no_future():
    obs = datetime(2026, 9, 5, 15, 30, tzinfo=_UTC).timestamp()
    trades = [
        {"_ts": obs - 2, "count": 1, "yes_price_dollars": 0.5, "taker_side": "yes"},
        {"_ts": obs - 0.5, "count": 2, "yes_price_dollars": 0.6, "taker_side": "no"},
        {"_ts": obs + 0.1, "count": 9, "yes_price_dollars": 0.9, "taker_side": "yes"},  # future
        {"_ts": obs - 10, "count": 1, "yes_price_dollars": 0.1, "taker_side": "yes"},  # outside
    ]
    # Decision-time: strictly trailing [obs-window, obs], never centered ±
    included = [t for t in trades if (obs - 5.0) <= float(t["_ts"]) <= obs]
    assert len(included) == 2
    for t in included:
        assert float(t["_ts"]) <= obs

    stats = public_trade_window_stats(trades, center_ts=obs, window_s=5.0, mode="trailing")
    assert stats["mode"] == "trailing"
    assert stats["window_start_ts"] == pytest.approx(obs - 5.0)
    assert stats["window_end_ts"] == pytest.approx(obs)
    assert stats["count"] == 2
    assert stats["contracts"] == pytest.approx(3.0)
    assert stats["signed_flow"] == pytest.approx(1 - 2)

    post = public_trade_window_stats(trades, center_ts=obs, window_s=5.0, mode="post")
    assert post["mode"] == "post"
    assert post["count"] == 1
    assert post["contracts"] == pytest.approx(9.0)


def test_yes_price_normalization_and_unknown_aggressor():
    assert normalize_yes_price_dollars({"yes_price": 55}) == pytest.approx(0.55)
    assert normalize_yes_price_dollars({"yes_price_dollars": 0.55}) == pytest.approx(0.55)
    assert map_taker_signed_contracts({"taker_side": "yes"}, 3) == 3
    assert map_taker_signed_contracts({}, 3) is None
    obs = 1000.0
    stats = public_trade_window_stats(
        [{"_ts": 999.0, "count": 1, "yes_price_dollars": 0.4}],
        center_ts=obs,
        window_s=5,
        mode="trailing",
    )
    assert stats["signed_flow"] == "UNKNOWN"
    assert stats["aggressor_flow"] == "UNKNOWN"


def test_duplicate_requires_same_seq_not_same_value():
    open_u = datetime(2026, 9, 5, 15, 0, tzinfo=_UTC)
    close_u = open_u + timedelta(minutes=1)
    snap = {
        "seq": "1",
        "received_at": open_u.isoformat().replace("+00:00", "Z"),
        "yes": {"0.50": "10"},
        "no": {},
        "reason": "initial",
    }
    # Same value updates, different seq — NOT duplicates
    d1 = {
        "seq": "10",
        "snapshot_seq": "1",
        "received_at": (open_u + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "side": "yes",
        "price": "0.50",
        "delta": "1",
    }
    d2 = {
        "seq": "11",
        "snapshot_seq": "1",
        "received_at": (open_u + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "side": "yes",
        "price": "0.50",
        "delta": "1",
    }
    pkg = _pkg([snap], [d1, d2], open_u, close_u)
    recon = reconstruct_book(pkg)
    assert "DELTA_DUPLICATE" not in recon.reason_codes
    assert recon.quality_evidence["delta_duplicate_count"] == 0

    # True duplicate: same seq twice
    d3 = dict(d2)
    d3["seq"] = "10"
    pkg2 = _pkg([snap], [d1, d3], open_u, close_u)
    recon2 = reconstruct_book(pkg2)
    assert "DELTA_DUPLICATE" in recon2.reason_codes
    assert recon2.quality_evidence["delta_duplicate_count"] >= 1


def test_snapshot_levels_emitted():
    open_u = datetime(2026, 9, 5, 15, 0, tzinfo=_UTC)
    close_u = open_u + timedelta(minutes=1)
    snap = {
        "seq": "1",
        "received_at": open_u.isoformat().replace("+00:00", "Z"),
        "yes": {"0.50": "10", "0.49": "2"},
        "no": {"0.40": "3"},
        "reason": "initial",
    }
    pkg = _pkg([snap], [], open_u, close_u)
    recon = reconstruct_book(pkg)
    assert len(recon.snapshot_level_rows) == 3
    sides = {r["side"] for r in recon.snapshot_level_rows}
    assert sides == {"yes", "no"}


def test_gap_interval_has_recovery():
    open_u = datetime(2026, 9, 5, 15, 0, tzinfo=_UTC)
    close_u = open_u + timedelta(minutes=15)
    snap = {
        "seq": "1",
        "received_at": open_u.isoformat().replace("+00:00", "Z"),
        "yes": {"0.50": "10"},
        "no": {"0.40": "10"},
        "reason": "initial",
    }
    d1 = {
        "seq": "10",
        "snapshot_seq": "1",
        "received_at": (open_u + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "side": "yes",
        "price": "0.50",
        "delta": "1",
    }
    d2 = {
        "seq": "11",
        "snapshot_seq": "1",
        "received_at": (open_u + timedelta(seconds=21)).isoformat().replace("+00:00", "Z"),
        "side": "yes",
        "price": "0.50",
        "delta": "1",
    }
    pkg = _pkg([snap], [d1, d2], open_u, close_u)
    recon = reconstruct_book(pkg, gap_threshold_s=10.0)
    assert "TIMESTAMP_GAP" in recon.reason_codes
    assert recon.intervals
    assert recon.intervals[0].recovered_at_utc is not None


@pytest.mark.skipif(not FIXTURE_CSV.is_file(), reason="fixture missing")
def test_fixture_trade_ids_present():
    found, missing = find_trade_refs(FIXTURE_CSV, ["55286", "55388"])
    assert not missing
    assert all(t.ticker.startswith("KXBTC15M-26SEP05") for t in found)


def test_touch_fields_matches_asks_from_book():
    from backend.core.cycle_package import asks_from_book
    from backend.core.cycle_recon.book_engine import _touch_fields

    cases = [
        ({"0.55": "10"}, {"0.40": "10"}),
        ({"0.97": "5", "0.96": "2"}, {"0.03": "8"}),
        ({"0.50": "1"}, {}),
        ({}, {"0.25": "3"}),
    ]
    for yes, no in cases:
        fast = _touch_fields(yes, no)
        ya, na = asks_from_book(yes, no)
        if ya is None:
            assert fast["yes_ask"] is None
        else:
            assert fast["yes_ask"] == pytest.approx(ya, abs=1e-9)
        if na is None:
            assert fast["no_ask"] is None
        else:
            assert fast["no_ask"] == pytest.approx(na, abs=1e-9)
