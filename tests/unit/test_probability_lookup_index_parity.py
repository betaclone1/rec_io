"""Indexed prob lookup must match full-scan neighbors and probabilities exactly."""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import backend.core.probability_lookup_cache as plc


def _tiny_arr() -> np.ndarray:
    arr = np.empty(12, dtype=plc._ROW_DTYPE)
    # Two momentum buckets, several ttc/buffer combos
    i = 0
    for mom in (10, 20):
        for ttc in (298.0, 300.0, 302.0):
            for buf, pos, neg in ((95.0, 60.0, 40.0), (100.0, 61.0, 39.0), (105.0, 62.0, 38.0)):
                if i >= 12:
                    break
                arr[i] = (ttc, buf, mom, pos + mom * 0.01, neg)
                i += 1
    return arr


@pytest.fixture()
def tiny_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PROB_LOOKUP_SHARED_MMAP", "0")
    monkeypatch.setenv("PROB_LOOKUP_USE_INDEX", "1")
    monkeypatch.setenv("PROB_LOOKUP_MMAP_DIR", str(tmp_path))
    plc.clear_cache_for_tests()
    arr = _tiny_arr()
    table = plc._SymbolTable(
        "probability_lookup_btc_master_test",
        500.0,
        False,
        arr,
        shared=False,
    )
    yield table
    plc.clear_cache_for_tests()


def test_index_neighbors_match_scan(tiny_cache):
    cache = tiny_cache
    assert cache.index
    queries = [
        (300, 100.0, 10),
        (300, 97.0, 10),
        (298, 105.0, 20),
        (302, 100.0, 20),
        (310, 100.0, 10),  # may be empty
    ]
    for ttc, buf, mom in queries:
        a = plc._query_neighbors_scan(cache, ttc, buf, mom)
        b = plc._query_neighbors_indexed(cache, ttc, buf, mom)
        assert a == b, (ttc, buf, mom, a, b)


def test_index_lookup_matches_scan_path(tiny_cache, monkeypatch):
    cache = tiny_cache
    plc._by_symbol["btc"] = cache
    monkeypatch.setattr(
        "backend.core.live_state_config.probability_lookup_ram_enabled",
        lambda: True,
    )
    queries = [(300, 100.0, 10), (300, 102.0, 20), (290, 100.0, 10)]
    for ttc, buf, mom in queries:
        monkeypatch.setenv("PROB_LOOKUP_USE_INDEX", "0")
        # force re-read of flag
        pos_s, neg_s = plc._lookup(cache, ttc, buf, mom)
        # compare via explicit neighbor+interp by toggling query path
        n_scan = plc._query_neighbors_scan(cache, ttc, buf, mom)
        n_idx = plc._query_neighbors_indexed(cache, ttc, buf, mom)
        assert n_scan == n_idx
        monkeypatch.setenv("PROB_LOOKUP_USE_INDEX", "1")
        pos_i, neg_i = plc._lookup(cache, ttc, buf, mom)
        # _lookup always uses _query_neighbors which respects env — set and compare
        assert pos_s == pos_i and neg_s == neg_i


@pytest.mark.integration
def test_btc_table_index_parity_sample():
    """Against local analytics BTC master table when available."""
    plc.clear_cache_for_tests()
    os.environ["PROB_LOOKUP_SHARED_MMAP"] = "0"
    os.environ["PROB_LOOKUP_USE_INDEX"] = "1"
    try:
        # Load once
        pos, neg = plc.get_probability("BTC", 300, 100.0, 10)
    except Exception as e:
        pytest.skip(f"BTC lookup table unavailable: {e}")
    if pos is None:
        pytest.skip("BTC lookup returned None")

    cache = plc._by_symbol["btc"]
    rng = np.random.default_rng(42)
    ttcs = rng.integers(0, 3601, size=80)
    bufs = rng.uniform(0, min(500.0, float(cache.max_buffer)), size=80)
    moms = rng.choice(plc._AVAILABLE_BUCKETS, size=80)

    mismatches = 0
    t0 = time.perf_counter()
    for ttc, buf, mom in zip(ttcs, bufs, moms):
        a = plc._query_neighbors_scan(cache, int(ttc), float(buf), int(mom))
        b = plc._query_neighbors_indexed(cache, int(ttc), float(buf), int(mom))
        if a != b:
            mismatches += 1
            if mismatches <= 3:
                print("mismatch", ttc, buf, mom, a, b)
    scan_idx_sec = time.perf_counter() - t0

    # Timing: indexed should be faster on full table for many lookups
    t1 = time.perf_counter()
    for ttc, buf, mom in zip(ttcs, bufs, moms):
        plc._query_neighbors_indexed(cache, int(ttc), float(buf), int(mom))
    idx_only = time.perf_counter() - t1
    t2 = time.perf_counter()
    for ttc, buf, mom in zip(ttcs, bufs, moms):
        plc._query_neighbors_scan(cache, int(ttc), float(buf), int(mom))
    scan_only = time.perf_counter() - t2

    assert mismatches == 0
    # Soft speed check: indexed not slower than 50% of scan on this sample
    assert idx_only < scan_only * 0.5 or scan_only < 0.05
    print(
        f"parity_ok n=80 scan={scan_only:.3f}s indexed={idx_only:.3f}s "
        f"combined={scan_idx_sec:.3f}s"
    )
