"""Replay sealed cycle packages for historical HWS controls (L2 only; tape UNKNOWN)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.cycle_package import iter_book_states, load_cycle_package
from backend.core.position_risk.metrics import LatencyTracker
from backend.core.position_risk.replay import replay_frames

_ET = "America/New_York"


def _parse_trade_window_et(date_s: str, time_s: str, closed_at: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Best-effort ET naive → aware window from CSV date/time/closed_at."""
    try:
        from zoneinfo import ZoneInfo

        et = ZoneInfo(_ET)
    except Exception:
        et = timezone.utc
    try:
        start = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=et)
    except Exception:
        return None, None
    end = None
    try:
        # closed_at often time-only
        if closed_at and len(closed_at) <= 8:
            end = datetime.strptime(f"{date_s} {closed_at}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=et)
        else:
            end = datetime.strptime(closed_at[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=et)
    except Exception:
        end = start
    return start, end


def package_frames_for_window(
    package_path: Path,
    *,
    start: Optional[datetime],
    end: Optional[datetime],
    side: str,
    size: float,
    floor_owned: Optional[float],
    max_frames: int = 400,
) -> List[Dict[str, Any]]:
    pkg = load_cycle_package(package_path)
    frames: List[Dict[str, Any]] = []
    t0 = None
    start_utc = start.astimezone(timezone.utc) if start is not None else None
    end_utc = end.astimezone(timezone.utc) if end is not None else None
    for i, st in enumerate(iter_book_states(pkg)):
        ts = st.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if start_utc and ts < start_utc:
            continue
        if end_utc and ts > end_utc:
            break
        if t0 is None:
            t0 = ts
        t_ms = int((ts - t0).total_seconds() * 1000)
        frames.append(
            {
                "t_ms": t_ms,
                "seq": i + 1,
                "side": side,
                "size": size,
                "floor_owned": floor_owned,
                "yes": dict(st.yes),
                "no": dict(st.no),
                "ticker": pkg.meta.get("ticker") or package_path.stem,
            }
        )
        if len(frames) >= max_frames:
            break
    return frames


def replay_historical_package(
    *,
    package_path: Path,
    side: str,
    size: float,
    floor_owned: Optional[float],
    date: str,
    time: str,
    closed_at: str,
    pad_seconds: float = 5.0,
) -> Dict[str, Any]:
    start, end = _parse_trade_window_et(date, time, closed_at)
    if start is not None:
        from datetime import timedelta

        start = start - timedelta(seconds=pad_seconds)
    if end is not None:
        from datetime import timedelta

        end = end + timedelta(seconds=pad_seconds)
    frames = package_frames_for_window(
        package_path,
        start=start,
        end=end,
        side=side,
        size=size,
        floor_owned=floor_owned,
    )
    tracker = LatencyTracker()
    result = replay_frames(frames, ticker=package_path.stem, tracker=tracker)
    result["provenance"] = {
        "package_path": str(package_path),
        "window_start": start.isoformat() if start else None,
        "window_end": end.isoformat() if end else None,
        "n_frames": len(frames),
        "tape": "UNKNOWN",
    }
    return result
