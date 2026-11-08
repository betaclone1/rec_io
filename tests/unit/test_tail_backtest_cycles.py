"""Unit tests for exact-cent LT/UT cycle scoring (no DB required)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import backend.core.tail_backtest_cycles as tbc


def test_first_exact_touch_prefers_earliest():
    rows = [
        {
            "created_time": "2026-11-06T12:01:00Z",
            "trade_id": "b",
            "yes_price_dollars": "0.50",
            "no_price_dollars": "0.50",
        },
        {
            "created_time": "2026-11-06T12:00:00Z",
            "trade_id": "a",
            "yes_price_dollars": "0.01",
            "no_price_dollars": "0.99",
        },
        {
            "created_time": "2026-11-06T12:02:00Z",
            "trade_id": "c",
            "yes_price_dollars": "0.01",
            "no_price_dollars": "0.99",
        },
    ]
    hit = tbc.first_exact_touch(rows, 0.01)
    assert hit is not None
    assert hit.side == "yes"
    assert hit.price == 0.01
    assert hit.fill_ts == datetime(2026, 11, 6, 7, 0, 0)  # ET from 12:00Z


def test_first_exact_touch_ut_on_no():
    rows = [
        {
            "created_time": "2026-11-06T15:00:00Z",
            "trade_id": "1",
            "yes_price_dollars": "0.01",
            "no_price_dollars": "0.99",
        }
    ]
    ut = tbc.first_exact_touch(rows, 0.99)
    assert ut is not None
    assert ut.side == "no"
    assert ut.price == 0.99


def test_first_exact_touch_rejects_round_to_cent_neighbors():
    """round(0.014, 2)==0.01 must not count as an exact $0.01 fill."""
    rows = [
        {
            "created_time": "2026-11-06T12:00:00Z",
            "trade_id": "near",
            "yes_price_dollars": "0.014",
            "no_price_dollars": "0.986",
        },
        {
            "created_time": "2026-11-06T12:01:00Z",
            "trade_id": "exact",
            "yes_price_dollars": "0.0100",
            "no_price_dollars": "0.9900",
        },
    ]
    hit = tbc.first_exact_touch(rows, 0.01)
    assert hit is not None
    assert hit.side == "yes"
    assert hit.fill_ts == datetime(2026, 11, 6, 7, 1, 0)
    assert tbc.first_exact_touch(rows[:1], 0.01) is None


def test_win_loss_null_when_no_fill_or_unsettled():
    fill = tbc.TailFill(side="yes", fill_ts=datetime(2026, 11, 6, 10, 0, 0), price=0.01)
    assert tbc._win_loss(None, "yes") is None
    assert tbc._win_loss(fill, None) is None
    assert tbc._win_loss(fill, "yes") is True
    assert tbc._win_loss(fill, "no") is False


def test_score_day_never_omits_cycle_and_nulls_no_fill(tmp_path: Path):
    day = date(2026, 11, 5)  # Wednesday
    series = "KXBTC15M"
    # Minimal CSV: one ticker with LT fill only
    tickers = tbc.expected_tickers_for_day(series, day)
    assert len(tickers) == 96
    target = tickers[40]
    csv_path = tmp_path / f"{series}_public_trades_{day.isoformat()}_et.csv"
    csv_path.write_text(
        "trade_id,ticker,created_time,yes_price_dollars,no_price_dollars\n"
        f"1,{target},2026-11-05T16:00:00Z,0.0100,0.9900\n",
        encoding="utf-8",
    )
    # Pad trade count so crypto day is not flagged sparse
    with csv_path.open("a", encoding="utf-8") as f:
        for i in range(120):
            f.write(
                f"{i+2},{tickers[0]},2026-11-05T05:00:00Z,0.5000,0.5000\n"
            )
    cache = {target: {"mr": "yes"}}
    scores = tbc.score_day(series, day, cache=cache, root=tmp_path)
    assert len(scores) == 96
    by_t = {s.ticker: s for s in scores}
    hit = by_t[target]
    assert hit.lt is not None
    assert hit.lt.side == "yes"
    assert hit.lt_win_loss is True
    assert hit.ut is not None
    assert hit.ut.side == "no"
    assert hit.ut_win_loss is False  # mr=yes, ut side=no
    # A different cycle with no exact-cent print
    other = by_t[tickers[41]]
    assert other.lt is None
    assert other.ut is None
    assert other.lt_win_loss is None
    assert other.ut_win_loss is None
    assert other.market_result is None


def test_score_day_includes_csv_tickers_when_session_dark(tmp_path: Path):
    """Metal Saturdays can still have tape; charts counted those ≥100-trade days."""
    day = date(2026, 8, 8)  # Saturday
    series = "KXSILVER15M"
    assert tbc.expected_tickers_for_day(series, day) == []
    ticker = "KXSILVER15M-26AUG081600-00"
    csv_path = tmp_path / f"{series}_public_trades_{day.isoformat()}_et.csv"
    lines = [
        "trade_id,ticker,created_time,yes_price_dollars,no_price_dollars\n",
        f"1,{ticker},2026-08-08T16:00:00Z,0.0100,0.9900\n",
    ]
    for i in range(120):
        lines.append(f"{i+2},{ticker},2026-08-08T15:00:00Z,0.5000,0.5000\n")
    csv_path.write_text("".join(lines), encoding="utf-8")
    scores = tbc.score_day(
        series, day, cache={ticker: {"mr": "yes"}}, root=tmp_path
    )
    assert len(scores) == 1
    assert scores[0].ticker == ticker
    assert scores[0].lt is not None
    assert scores[0].lt_win_loss is True
    assert scores[0].data_gap is False


def test_crypto_missing_csv_sets_data_gap(tmp_path: Path):
    day = date(2026, 11, 5)
    scores = tbc.score_day("KXBTC15M", day, cache={}, root=tmp_path)
    assert scores
    assert all(s.data_gap for s in scores)
    assert scores[0].data_gap_reason == "missing_day_csv"


def test_commodity_expected_fewer_than_96_on_saturday():
    # Energy: only Fri-night last close (Sat 00:00 ET settlement) lists on Saturday's grid
    sat = date(2026, 11, 7)  # Saturday
    wti = tbc.expected_tickers_for_day("KXWTI15M", sat)
    assert wti == ["KXWTI15M-26NOV070000-00"]
    # Crypto still 96
    assert len(tbc.expected_tickers_for_day("KXBTC15M", sat)) == 96


def test_market_result_for_object_and_string():
    assert tbc.market_result_for({"T": {"mr": "no"}}, "T") == "no"
    assert tbc.market_result_for({"T": "yes"}, "T") == "yes"
    assert tbc.market_result_for({"T": {"mr": None}}, "T") is None
