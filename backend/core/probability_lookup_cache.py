"""
Probability lookup tables: shared mmap (Phase 2 B1) or private RAM.

Default: OS-shared numpy memmap under ``var/prob_lookup_mmap/`` so STG + ATS
processes share one physical copy per symbol (~1.6GB) instead of 4× private heaps.

Fail-closed lookup semantics unchanged: missing/unloadable → ``(None, None)``;
callers may use SQL. Never invents probability values.

Env:
  PROBABILITY_LOOKUP_RAM=0          disable RAM/mmap path entirely
  PROB_LOOKUP_SHARED_MMAP=0         use private Python lists (legacy)
  PROB_LOOKUP_MMAP_DIR=/path        mmap directory (default: <repo>/var/prob_lookup_mmap)
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_AVAILABLE_BUCKETS = [
    -90, -80, -70, -60, -50, -40, -30, -20, -10,
    10, 20, 30, 40, 50, 60, 70, 80, 90,
]
_HIGH_PRECISION = frozenset({"sol", "xrp", "doge"})

_ROW_DTYPE = np.dtype(
    [
        ("ttc", "<f8"),
        ("buf", "<f8"),
        ("mom", "<i4"),
        ("pos", "<f8"),
        ("neg", "<f8"),
    ]
)

_lock = threading.Lock()
_by_symbol: Dict[str, "_SymbolTable"] = {}

# Magic for meta schema version (bump if layout changes).
_META_VERSION = 1


class _SymbolTable:
    __slots__ = ("table_name", "max_buffer", "fine_price", "rows", "shared")

    def __init__(
        self,
        table_name: str,
        max_buffer: float,
        fine_price: bool,
        rows,
        *,
        shared: bool,
    ):
        self.table_name = table_name
        self.max_buffer = max_buffer
        self.fine_price = fine_price
        self.rows = rows  # List[tuple] or np.memmap / ndarray
        self.shared = shared


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def shared_mmap_enabled() -> bool:
    raw = os.getenv("PROB_LOOKUP_SHARED_MMAP", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def mmap_dir() -> str:
    raw = os.getenv("PROB_LOOKUP_MMAP_DIR", "").strip()
    if raw:
        return raw
    return os.path.join(_project_root(), "var", "prob_lookup_mmap")


def _meta_path(sym: str, table_name: str) -> str:
    return os.path.join(mmap_dir(), f"{sym}_{table_name}.meta.json")


def _bin_path(sym: str, table_name: str) -> str:
    return os.path.join(mmap_dir(), f"{sym}_{table_name}.npy")


def _find_latest_table(symbol: str, cursor) -> str:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'analytics'
        AND table_name LIKE %s
        ORDER BY table_name DESC
        """,
        (f"probability_lookup_{symbol.lower()}_master_%",),
    )
    results = cursor.fetchall()
    if not results:
        raise ValueError(f"No probability lookup table for {symbol.upper()}")
    return str(results[0][0])


def _fetch_rows_from_pg(symbol: str) -> Tuple[str, float, bool, np.ndarray]:
    from backend.core.config.database import get_system_postgresql_connection

    sym = symbol.lower()
    conn = get_system_postgresql_connection()
    try:
        cur = conn.cursor()
        table_name = _find_latest_table(sym, cur)
        cur.execute(
            f"""
            SELECT ttc_seconds, buffer_points, momentum_bucket,
                   prob_within_positive, prob_within_negative
            FROM analytics.{table_name}
            """
        )
        raw = cur.fetchall()
        cur.execute(f"SELECT MAX(buffer_points) FROM analytics.{table_name}")
        max_row = cur.fetchone()
        if not max_row or max_row[0] is None:
            raise ValueError(f"No buffer data in {table_name}")
        max_buffer = float(max_row[0])
        conn.close()
    except Exception:
        if conn:
            conn.close()
        raise

    arr = np.empty(len(raw), dtype=_ROW_DTYPE)
    for i, r in enumerate(raw):
        arr[i] = (float(r[0]), float(r[1]), int(r[2]), float(r[3]), float(r[4]))
    return table_name, max_buffer, sym in _HIGH_PRECISION, arr


def _try_open_mmap(sym: str, table_name: str) -> Optional[_SymbolTable]:
    meta_p = _meta_path(sym, table_name)
    bin_p = _bin_path(sym, table_name)
    if not os.path.isfile(meta_p) or not os.path.isfile(bin_p):
        return None
    try:
        with open(meta_p, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if int(meta.get("meta_version", -1)) != _META_VERSION:
            return None
        if str(meta.get("table_name")) != table_name:
            return None
        nrows = int(meta["nrows"])
        max_buffer = float(meta["max_buffer"])
        fine_price = bool(meta["fine_price"])
        arr = np.memmap(bin_p, dtype=_ROW_DTYPE, mode="r", shape=(nrows,))
        if arr.shape[0] != nrows:
            return None
        return _SymbolTable(
            table_name, max_buffer, fine_price, arr, shared=True
        )
    except Exception as e:
        logger.warning("probability_lookup mmap open failed %s %s: %s", sym, table_name, e)
        return None


def _write_mmap_atomic(
    sym: str,
    table_name: str,
    max_buffer: float,
    fine_price: bool,
    arr: np.ndarray,
) -> _SymbolTable:
    d = mmap_dir()
    os.makedirs(d, exist_ok=True)
    meta_p = _meta_path(sym, table_name)
    bin_p = _bin_path(sym, table_name)
    tmp_bin = bin_p + f".tmp.{os.getpid()}"
    tmp_meta = meta_p + f".tmp.{os.getpid()}"
    try:
        mm = np.memmap(tmp_bin, dtype=_ROW_DTYPE, mode="w+", shape=(arr.shape[0],))
        mm[:] = arr
        mm.flush()
        del mm
        meta = {
            "meta_version": _META_VERSION,
            "symbol": sym,
            "table_name": table_name,
            "nrows": int(arr.shape[0]),
            "max_buffer": float(max_buffer),
            "fine_price": bool(fine_price),
            "built_at_unix": time.time(),
        }
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_bin, bin_p)
        os.replace(tmp_meta, meta_p)
    finally:
        for p in (tmp_bin, tmp_meta):
            try:
                if os.path.isfile(p):
                    os.unlink(p)
            except OSError:
                pass
    opened = _try_open_mmap(sym, table_name)
    if opened is None:
        raise RuntimeError(f"mmap write succeeded but open failed for {sym} {table_name}")
    return opened


def _load_symbol_shared(symbol: str) -> _SymbolTable:
    """Load via shared mmap; build from PG under flock if missing."""
    import fcntl

    from backend.core.config.database import get_system_postgresql_connection

    sym = symbol.lower()
    conn = get_system_postgresql_connection()
    try:
        cur = conn.cursor()
        table_name = _find_latest_table(sym, cur)
        conn.close()
    except Exception:
        if conn:
            conn.close()
        raise

    existing = _try_open_mmap(sym, table_name)
    if existing is not None:
        logger.info(
            "probability_lookup_cache mmap attach %s rows=%s table=%s",
            sym.upper(),
            len(existing.rows),
            table_name,
        )
        return existing

    os.makedirs(mmap_dir(), exist_ok=True)
    lock_path = os.path.join(mmap_dir(), f"{sym}_{table_name}.build.lock")
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        existing = _try_open_mmap(sym, table_name)
        if existing is not None:
            logger.info(
                "probability_lookup_cache mmap attach %s rows=%s table=%s",
                sym.upper(),
                len(existing.rows),
                table_name,
            )
            return existing
        table_name, max_buffer, fine_price, arr = _fetch_rows_from_pg(sym)
        built = _write_mmap_atomic(sym, table_name, max_buffer, fine_price, arr)
        logger.info(
            "probability_lookup_cache mmap built %s rows=%s table=%s path=%s",
            sym.upper(),
            len(built.rows),
            table_name,
            _bin_path(sym, table_name),
        )
        return built


def _load_symbol_private(symbol: str) -> _SymbolTable:
    table_name, max_buffer, fine_price, arr = _fetch_rows_from_pg(symbol)
    rows = [
        (float(r["ttc"]), float(r["buf"]), int(r["mom"]), float(r["pos"]), float(r["neg"]))
        for r in arr
    ]
    logger.info(
        "probability_lookup_cache loaded private %s rows=%s table=%s",
        symbol.upper(),
        len(rows),
        table_name,
    )
    return _SymbolTable(table_name, max_buffer, fine_price, rows, shared=False)


def _load_symbol(symbol: str) -> _SymbolTable:
    if shared_mmap_enabled():
        try:
            return _load_symbol_shared(symbol)
        except Exception as e:
            logger.warning(
                "probability_lookup shared mmap failed %s (%s); using private RAM",
                symbol.upper(),
                e,
            )
    return _load_symbol_private(symbol)


def _iter_rows(cache: _SymbolTable):
    rows = cache.rows
    if isinstance(rows, np.ndarray):
        for r in rows:
            yield float(r["ttc"]), float(r["buf"]), int(r["mom"]), float(r["pos"]), float(r["neg"])
    else:
        for t, b, m, pos, neg in rows:
            yield t, b, m, pos, neg


def _nearest_momentum_bucket(momentum_bucket: int) -> int:
    return min(_AVAILABLE_BUCKETS, key=lambda x: abs(x - momentum_bucket))


def _query_neighbors(
    cache: _SymbolTable,
    ttc_seconds: int,
    buffer_points: float,
    momentum_bucket: int,
) -> List[Tuple[float, float, float, float]]:
    mb = float(cache.max_buffer)
    if cache.fine_price:
        buffer_range = max(1e-4, mb * 0.05)
    else:
        buffer_range = max(5.0, mb * 0.01)
    bp = float(buffer_points)
    ttc = float(ttc_seconds)
    scored: List[Tuple[float, Tuple[float, float, float, float]]] = []
    for t, b, m, pos, neg in _iter_rows(cache):
        if m != momentum_bucket:
            continue
        if t < ttc - 5 or t > ttc + 5:
            continue
        if b < bp - buffer_range or b > bp + buffer_range:
            continue
        dist = abs(t - ttc) + abs(b - bp)
        scored.append((dist, (t, b, pos, neg)))
    scored.sort(key=lambda x: x[0])
    return [r[1] for r in scored[:4]]


def _bilinear(
    results: List[Tuple[float, float, float, float]], ttc_seconds: float, buffer_points: float
) -> Tuple[float, float]:
    sorted_results = sorted(results, key=lambda x: (x[0], x[1]))
    ttc_values = sorted(set(r[0] for r in sorted_results))
    buffer_values = sorted(set(r[1] for r in sorted_results))
    if len(ttc_values) < 2 or len(buffer_values) < 2:
        return _linear(sorted_results, ttc_seconds, buffer_points)
    ttc_lower, ttc_upper = ttc_values[0], ttc_values[-1]
    buffer_lower, buffer_upper = buffer_values[0], buffer_values[-1]
    corners: Dict[Tuple[float, float], Tuple[float, float]] = {}
    for ttc in (ttc_lower, ttc_upper):
        for buf in (buffer_lower, buffer_upper):
            for result in sorted_results:
                if abs(float(result[0]) - float(ttc)) < 1e-6 and math.isclose(
                    float(result[1]), float(buf), rel_tol=0, abs_tol=1e-5
                ):
                    corners[(ttc, buf)] = (float(result[2]), float(result[3]))
                    break
    if len(corners) != 4:
        return _linear(sorted_results, ttc_seconds, buffer_points)
    pos = _interp_2d(
        float(corners[(ttc_lower, buffer_lower)][0]),
        float(corners[(ttc_upper, buffer_lower)][0]),
        float(corners[(ttc_lower, buffer_upper)][0]),
        float(corners[(ttc_upper, buffer_upper)][0]),
        float(ttc_lower),
        float(ttc_upper),
        float(buffer_lower),
        float(buffer_upper),
        float(ttc_seconds),
        float(buffer_points),
    )
    neg = _interp_2d(
        float(corners[(ttc_lower, buffer_lower)][1]),
        float(corners[(ttc_upper, buffer_lower)][1]),
        float(corners[(ttc_lower, buffer_upper)][1]),
        float(corners[(ttc_upper, buffer_upper)][1]),
        float(ttc_lower),
        float(ttc_upper),
        float(buffer_lower),
        float(buffer_upper),
        float(ttc_seconds),
        float(buffer_points),
    )
    return pos, neg


def _interp_2d(
    q11: float,
    q21: float,
    q12: float,
    q22: float,
    x1: float,
    x2: float,
    y1: float,
    y2: float,
    x: float,
    y: float,
) -> float:
    if x2 == x1 or y2 == y1:
        return q11
    f1 = q11 * (x2 - x) * (y2 - y) / ((x2 - x1) * (y2 - y1))
    f2 = q21 * (x - x1) * (y2 - y) / ((x2 - x1) * (y2 - y1))
    f3 = q12 * (x2 - x) * (y - y1) / ((x2 - x1) * (y2 - y1))
    f4 = q22 * (x - x1) * (y - y1) / ((x2 - x1) * (y2 - y1))
    return f1 + f2 + f3 + f4


def _linear(
    results: List[Tuple[float, float, float, float]], ttc_seconds: float, buffer_points: float
) -> Tuple[float, float]:
    if len(results) < 1:
        return 50.0, 50.0
    if len(results) == 1:
        return float(results[0][2]), float(results[0][3])
    distances = []
    for r in results:
        distances.append((abs(r[0] - ttc_seconds) + abs(r[1] - buffer_points), r))
    distances.sort(key=lambda x: x[0])
    closest, second = distances[0][1], distances[1][1]
    total = distances[0][0] + distances[1][0]
    if total == 0:
        return float(closest[2]), float(closest[3])
    w1 = 1 - distances[0][0] / total
    w2 = 1 - w1
    return (
        w1 * float(closest[2]) + w2 * float(second[2]),
        w1 * float(closest[3]) + w2 * float(second[3]),
    )


def _lookup(
    cache: _SymbolTable, ttc_seconds: int, buffer_points: float, momentum_bucket: int
) -> Tuple[Optional[float], Optional[float]]:
    ttc_seconds = round(ttc_seconds / 10) * 10
    momentum_bucket = _nearest_momentum_bucket(momentum_bucket)
    bp = float(buffer_points)
    if bp > cache.max_buffer:
        bp = cache.max_buffer
    results = _query_neighbors(cache, ttc_seconds, bp, momentum_bucket)
    if not results:
        return None, None
    tuples4 = [(r[0], r[1], r[2], r[3]) for r in results]
    if len(tuples4) == 1:
        return float(tuples4[0][2]), float(tuples4[0][3])
    if len(tuples4) == 2:
        return _linear(tuples4, float(ttc_seconds), bp)
    if len(tuples4) == 3:
        tuples4 = sorted(
            tuples4,
            key=lambda r: abs(r[0] - ttc_seconds) + abs(r[1] - bp),
        )[:2]
        return _linear(tuples4, float(ttc_seconds), bp)
    return _bilinear(tuples4, float(ttc_seconds), bp)


def get_probability(
    symbol: str,
    ttc_seconds: int,
    buffer_points: float,
    momentum_bucket: int,
) -> Tuple[Optional[float], Optional[float]]:
    from backend.core.live_state_config import probability_lookup_ram_enabled

    if not probability_lookup_ram_enabled():
        return None, None
    sym = symbol.lower()
    with _lock:
        cache = _by_symbol.get(sym)
        if cache is None:
            try:
                cache = _load_symbol(sym)
                _by_symbol[sym] = cache
            except Exception as e:
                logger.warning("probability_lookup_cache load failed %s: %s", sym, e)
                return None, None
    try:
        return _lookup(cache, ttc_seconds, buffer_points, momentum_bucket)
    except Exception as e:
        logger.warning("probability_lookup_cache lookup %s: %s", sym, e)
        return None, None


def preload_symbols(symbols: Tuple[str, ...]) -> None:
    """Warm tables at startup. BTC first (HWS priority)."""
    ordered = sorted(
        {str(s).strip().upper() for s in symbols if str(s).strip()},
        key=lambda s: (0 if s == "BTC" else 1, s),
    )
    for s in ordered:
        get_probability(s, 300, 100.0, 10)


def cache_info() -> Dict[str, dict]:
    """Diagnostics: which symbols are loaded and whether shared mmap."""
    with _lock:
        out = {}
        for sym, c in _by_symbol.items():
            out[sym] = {
                "table_name": c.table_name,
                "max_buffer": c.max_buffer,
                "shared": c.shared,
                "nrows": int(len(c.rows)),
            }
        return out


def clear_cache_for_tests() -> None:
    """Unit tests only."""
    with _lock:
        _by_symbol.clear()
