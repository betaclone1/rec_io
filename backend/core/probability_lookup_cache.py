"""
In-process RAM cache for analytics probability lookup tables.

Used by strike_table_generator on the hot path (default ON via live_state_config).
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_AVAILABLE_BUCKETS = [
    -90, -80, -70, -60, -50, -40, -30, -20, -10,
    10, 20, 30, 40, 50, 60, 70, 80, 90,
]
_HIGH_PRECISION = frozenset({"sol", "xrp", "doge"})

_lock = threading.Lock()
_by_symbol: Dict[str, "_SymbolTable"] = {}


class _SymbolTable:
    __slots__ = ("table_name", "max_buffer", "fine_price", "rows")

    def __init__(
        self,
        table_name: str,
        max_buffer: float,
        fine_price: bool,
        rows: List[Tuple[float, float, int, float, float]],
    ):
        self.table_name = table_name
        self.max_buffer = max_buffer
        self.fine_price = fine_price
        self.rows = rows


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


def _load_symbol(symbol: str) -> _SymbolTable:
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
        rows = [
            (
                float(r[0]),
                float(r[1]),
                int(r[2]),
                float(r[3]),
                float(r[4]),
            )
            for r in cur.fetchall()
        ]
        cur.execute(f"SELECT MAX(buffer_points) FROM analytics.{table_name}")
        max_row = cur.fetchone()
        if not max_row or max_row[0] is None:
            raise ValueError(f"No buffer data in {table_name}")
        max_buffer = float(max_row[0])
        conn.close()
        logger.info(
            "probability_lookup_cache loaded %s rows=%s table=%s",
            sym.upper(),
            len(rows),
            table_name,
        )
        return _SymbolTable(
            table_name,
            max_buffer,
            sym in _HIGH_PRECISION,
            rows,
        )
    except Exception:
        if conn:
            conn.close()
        raise


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
    for t, b, m, pos, neg in cache.rows:
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


def _lookup(cache: _SymbolTable, ttc_seconds: int, buffer_points: float, momentum_bucket: int) -> Tuple[Optional[float], Optional[float]]:
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
    """Warm RAM tables at strike_generator startup (optional)."""
    for s in symbols:
        get_probability(s, 300, 100.0, 10)
