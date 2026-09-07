"""Unit tests for Postgres/ET trade-log resolution (no live DB required)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.core.cycle_recon.orchestrator import RunRequest, resolve_markets, resolve_time_bounds
from backend.core.cycle_recon.time_util import et_date_str, parse_et_wall, range_preset_et_bounds
from backend.core.cycle_recon.trade_log import StrategyTradeRef


def test_parse_et_wall_to_utc():
    # 2026-09-05 10:00 EDT = 14:00 UTC
    dt = parse_et_wall("2026-09-05 10:00:00")
    assert dt.tzinfo is not None
    assert dt.astimezone(timezone.utc).hour == 14
    assert dt.astimezone(timezone.utc).day == 5


def test_parse_et_wall_datetime_local_shape():
    dt = parse_et_wall("2026-09-05T10:00")
    assert et_date_str(dt) == "2026-09-05"


def test_range_preset_24h():
    now = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    start, end = range_preset_et_bounds("24h", now=now)
    assert end == now
    assert (end - start).total_seconds() == 24 * 3600


def test_range_preset_all():
    start, end = range_preset_et_bounds("all")
    assert start is None and end is None


def test_resolve_time_bounds_prefers_et():
    req = RunRequest(start_et="2026-09-05 10:00:00", end_et="2026-09-05 12:00:00")
    start, end = resolve_time_bounds(req)
    assert start.astimezone(timezone.utc).hour == 14
    assert end.astimezone(timezone.utc).hour == 16


def test_resolve_markets_pg_default(monkeypatch):
    fake = StrategyTradeRef(
        source_path="postgresql:users_0001.trades_0001",
        source_sha256="abc",
        source_namespace="pg:users_0001",
        trade_id="99",
        ticker="KXBTC15M-26SEP060000-00",
        monitor="mon_0001_10058",
        side="Y",
        date="2026-09-06",
        entry_utc=datetime(2026, 9, 6, 16, 0, tzinfo=timezone.utc),
        close_utc=None,
        row={"id": "99", "ticker": "KXBTC15M-26SEP060000-00"},
    )

    def _fake_list(user_no, **kwargs):
        assert user_no == "0001"
        assert kwargs.get("symbols") == ["BTC"]
        return ["KXBTC15M-26SEP060000-00", "KXBTC15M-26SEP060015-15"]

    def _fake_select(user_no, **kwargs):
        assert user_no == "0001"
        return [fake]

    with patch(
        "backend.core.cycle_recon.orchestrator.list_distinct_tickers_pg",
        side_effect=_fake_list,
    ), patch(
        "backend.core.cycle_recon.orchestrator.select_strategy_trades_pg",
        side_effect=_fake_select,
    ), patch(
        "backend.core.cycle_recon.orchestrator._tickers_in_range",
        return_value=["KXBTC15M-26SEP060030-30"],
    ):
        tickers, trades, notes = resolve_markets(
            RunRequest(
                user_no="0001",
                use_pg=True,
                symbols=["BTC"],
                range_preset="7d",
                tickers=[],
            )
        )
    assert notes["ticker_mode"] == "window_all"
    assert "KXBTC15M-26SEP060000-00" in tickers
    assert "KXBTC15M-26SEP060015-15" in tickers
    assert "KXBTC15M-26SEP060030-30" in tickers
    assert len(trades) == 1
    assert notes["source"] == "pg:users_0001"


def test_resolve_markets_explicit_tickers_only():
    fake = StrategyTradeRef(
        source_path="postgresql:users_0001.trades_0001",
        source_sha256="abc",
        source_namespace="pg:users_0001",
        trade_id="1",
        ticker="KXBTC15M-26SEP060000-00",
        monitor=None,
        side="Y",
        date="2026-09-06",
        entry_utc=datetime(2026, 9, 6, 16, 0, tzinfo=timezone.utc),
        close_utc=None,
        row={},
    )

    def _fake_select(user_no, **kwargs):
        assert kwargs.get("tickers") == ["KXBTC15M-26SEP060000-00"]
        return [fake]

    with patch(
        "backend.core.cycle_recon.orchestrator.select_strategy_trades_pg",
        side_effect=_fake_select,
    ), patch(
        "backend.core.cycle_recon.orchestrator.list_distinct_tickers_pg",
    ) as list_fn:
        tickers, trades, notes = resolve_markets(
            RunRequest(
                user_no="0001",
                use_pg=True,
                symbols=["BTC"],
                range_preset="7d",
                tickers=["KXBTC15M-26SEP060000-00"],
            )
        )
    list_fn.assert_not_called()
    assert notes["ticker_mode"] == "explicit"
    assert tickers == ["KXBTC15M-26SEP060000-00"]


def test_resolve_markets_requires_user_no_for_pg():
    with pytest.raises(ValueError, match="user_no"):
        resolve_markets(RunRequest(use_pg=True, range_preset="7d"))


def test_resolve_markets_csv_override(tmp_path):
    csv_path = tmp_path / "t.csv"
    csv_path.write_text(
        "id,date,time,created_at,updated_at,ticker,symbol,side,monitor,trade_strategy,closed_at\n"
        "1,2026-09-05,10:00:00,2026-09-05T14:00:00Z,,KXBTC15M-26SEP051000-00,BTC,Y,m1,HWS,\n",
        encoding="utf-8",
    )
    tickers, trades, notes = resolve_markets(
        RunRequest(
            trade_log=str(csv_path),
            use_pg=False,
            trade_ids=["1"],
        )
    )
    assert notes["source"] == "csv"
    assert tickers == ["KXBTC15M-26SEP051000-00"]
    assert trades[0].trade_id == "1"
