"""Replay book timelines through shadow features (observe-only)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.position_risk.features import ShadowFeatures, compute_shadow_features
from backend.core.position_risk.metrics import LatencyTracker
from backend.core.position_risk.persistence_grid import run_persistence_grid


def replay_frames(
    frames: Sequence[Dict[str, Any]],
    *,
    ticker: str = "SYNTHETIC",
    tracker: Optional[LatencyTracker] = None,
) -> Dict[str, Any]:
    features: List[ShadowFeatures] = []
    series: List[Tuple[int, Optional[float]]] = []
    prev_best = None
    prev_ts = None
    prev_depth = None
    t_recv0 = time.perf_counter()
    for fr in frames:
        t_ms = int(fr["t_ms"])
        yes = {str(k): str(v) for k, v in (fr.get("yes") or {}).items()}
        no = {str(k): str(v) for k, v in (fr.get("no") or {}).items()}
        t_apply = time.perf_counter()
        feat = compute_shadow_features(
            ticker=str(fr.get("ticker") or ticker),
            side=str(fr.get("side") or "N"),
            size=float(fr.get("size") or 1),
            yes=yes,
            no=no,
            floor_owned=fr.get("floor_owned"),
            seq=fr.get("seq"),
            ts_ms=t_ms,
            prev_best=prev_best,
            prev_ts_ms=prev_ts,
            prev_depth_above_floor=prev_depth,
        )
        t_eval = time.perf_counter()
        if tracker:
            tracker.record("apply_to_eval_ms", (t_eval - t_apply) * 1000.0)
            tracker.record("feature_eval_ms", feat.eval_mono_ms)
            # publish = recording feature (shadow)
            tracker.record("eval_to_publish_ms", 0.05)
        features.append(feat)
        series.append((t_ms, feat.liquidation_vwap))
        prev_best = feat.best_executable
        prev_ts = t_ms
        prev_depth = feat.depth_above_floor
    if tracker:
        tracker.record("replay_wall_ms", (time.perf_counter() - t_recv0) * 1000.0)

    grid = run_persistence_grid(series)
    return {
        "ticker": ticker,
        "n_frames": len(frames),
        "features": [f.to_dict() for f in features],
        "vwap_series": [{"t_ms": t, "liquidation_vwap": v} for t, v in series],
        "persistence_grid": grid,
        "tape_state": "UNKNOWN",
        "latency": tracker.summary() if tracker else {},
    }
