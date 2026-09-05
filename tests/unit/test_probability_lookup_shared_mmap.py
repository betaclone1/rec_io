"""Phase 2 B1: shared probability mmap + preload BTC-first ordering."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import backend.core.probability_lookup_cache as plc


@pytest.fixture()
def mmap_tmpdir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROB_LOOKUP_SHARED_MMAP", "1")
    monkeypatch.setenv("PROB_LOOKUP_MMAP_DIR", str(tmp_path))
    monkeypatch.delenv("PROBABILITY_LOOKUP_RAM", raising=False)
    plc.clear_cache_for_tests()
    yield tmp_path
    plc.clear_cache_for_tests()


def _tiny_arr() -> np.ndarray:
    arr = np.empty(4, dtype=plc._ROW_DTYPE)
    # 2x2 grid inside ±5 ttc and ±5 buffer of (300, 100)
    arr[0] = (298.0, 95.0, 10, 60.0, 40.0)
    arr[1] = (298.0, 105.0, 10, 61.0, 39.0)
    arr[2] = (302.0, 95.0, 10, 62.0, 38.0)
    arr[3] = (302.0, 105.0, 10, 63.0, 37.0)
    return arr


def test_shared_mmap_write_attach_and_lookup(mmap_tmpdir, monkeypatch):
    arr = _tiny_arr()

    def fake_fetch(symbol: str):
        return "probability_lookup_btc_master_test", 500.0, False, arr

    monkeypatch.setattr(plc, "_fetch_rows_from_pg", fake_fetch)
    monkeypatch.setattr(
        plc,
        "_find_latest_table",
        lambda symbol, cursor: "probability_lookup_btc_master_test",
    )

    # Bypass PG for latest-table discovery inside _load_symbol_shared
    class FakeCur:
        def execute(self, *_a, **_k):
            pass

        def fetchall(self):
            return [("probability_lookup_btc_master_test",)]

        def fetchone(self):
            return (500.0,)

    class FakeConn:
        def cursor(self):
            return FakeCur()

        def close(self):
            pass

    monkeypatch.setattr(
        "backend.core.config.database.get_system_postgresql_connection",
        lambda: FakeConn(),
    )

    pos, neg = plc.get_probability("BTC", 300, 100.0, 10)
    assert pos is not None and neg is not None
    info = plc.cache_info()
    assert info["btc"]["shared"] is True
    assert (mmap_tmpdir / "btc_probability_lookup_btc_master_test.npy").is_file()

    # Second load attaches without rebuild
    plc.clear_cache_for_tests()
    builds = {"n": 0}
    real_fetch = plc._fetch_rows_from_pg

    def counting_fetch(symbol: str):
        builds["n"] += 1
        return fake_fetch(symbol)

    monkeypatch.setattr(plc, "_fetch_rows_from_pg", counting_fetch)
    pos2, neg2 = plc.get_probability("BTC", 300, 100.0, 10)
    assert builds["n"] == 0
    assert abs(pos2 - pos) < 1e-9
    assert abs(neg2 - neg) < 1e-9


def test_preload_btc_first(monkeypatch):
    order = []

    def fake_get(symbol, *a, **k):
        order.append(str(symbol).upper())
        return 50.0, 50.0

    monkeypatch.setattr(plc, "get_probability", fake_get)
    plc.preload_symbols(("ETH", "BTC", "SOL"))
    assert order[0] == "BTC"
    assert set(order) == {"BTC", "ETH", "SOL"}


def test_private_mode_flag(mmap_tmpdir, monkeypatch):
    monkeypatch.setenv("PROB_LOOKUP_SHARED_MMAP", "0")
    arr = _tiny_arr()
    monkeypatch.setattr(
        plc,
        "_fetch_rows_from_pg",
        lambda symbol: ("probability_lookup_btc_master_test", 500.0, False, arr),
    )
    plc.clear_cache_for_tests()
    pos, neg = plc.get_probability("BTC", 300, 100.0, 10)
    assert pos is not None
    assert plc.cache_info()["btc"]["shared"] is False
