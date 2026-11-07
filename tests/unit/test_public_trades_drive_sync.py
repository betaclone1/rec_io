"""Unit tests for public-trades Drive sync helpers (no network)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import backend.core.public_trades_drive_sync as sync


def test_month_archive_path_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("CYCLE_PACKAGE_ROOT", str(tmp_path))
    p = sync.month_archive_path("KXBTC15M", 2026, 9)
    assert p.name == "KXBTC15M_public_trades_2026-09_et.tar.xz"
    assert p.parent.name == "2026_09_SEP"
    assert p.parent.parent.name == "2026"
    assert p.parent.parent.parent.name == "KXBTC15M"


def test_local_months_with_day_csvs(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "TRADES_DIR", tmp_path)
    (tmp_path / "KXBTC15M_public_trades_2026-09-01_et.csv").write_text("h\n")
    (tmp_path / "KXBTC15M_public_trades_2026-09-02_et.csv").write_text("h\n")
    (tmp_path / "KXBTC15M_public_trades_2026-10-01_et.csv").write_text("h\n")
    (tmp_path / "empty.csv").write_text("")
    found = sync.local_months_with_day_csvs(["KXBTC15M"])
    assert found == [("KXBTC15M", 2026, 9), ("KXBTC15M", 2026, 10)]


def test_package_month_writes_archive(tmp_path, monkeypatch):
    trades = tmp_path / "trades"
    pkg = tmp_path / "pkg"
    trades.mkdir()
    pkg.mkdir()
    monkeypatch.setattr(sync, "TRADES_DIR", trades)
    monkeypatch.setenv("CYCLE_PACKAGE_ROOT", str(pkg))
    day = date(2026, 9, 1)
    (trades / f"KXBTC15M_public_trades_{day.isoformat()}_et.csv").write_text(
        "trade_id\nx\n"
    )
    (trades / "KXBTC15M_market_results_2026-09_et.csv").write_text("ticker,market_result\n")
    out = sync.package_month("KXBTC15M", 2026, 9)
    assert out is not None
    assert out.is_file()
    assert out.stat().st_size > 0
