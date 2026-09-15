"""Synthetic scenario fixtures (not historical trade IDs) + book timeline helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Owned-side NO bids: price -> size. Liquidation VWAP walks high→low bids.


def _book(no_bids: Dict[str, str], yes_bids: Dict[str, str] | None = None) -> Dict[str, Any]:
    return {"yes": yes_bids or {}, "no": no_bids}


def gradual_collapse_reference_v1() -> List[Dict[str, Any]]:
    """
    Documented shape: LVWAP crosses ~0.95 ~7.6s after entry, ~0.90 ~13.5s,
    ~0.88 near 20.2s. Size=100 for easy VWAP control via single-level books.
    """
    size = 100.0
    # Single-level books so liquidation_vwap == best bid
    frames = [
        (0, {"0.98": "500"}),
        (2000, {"0.97": "500"}),
        (5000, {"0.96": "500"}),
        (7600, {"0.949": "500"}),  # below 0.95
        (10000, {"0.93": "500"}),
        (13500, {"0.899": "500"}),  # below 0.90
        (17000, {"0.89": "500"}),
        (20200, {"0.88": "500"}),
    ]
    out = []
    for i, (t_ms, no) in enumerate(frames):
        out.append(
            {
                "t_ms": t_ms,
                "seq": i + 1,
                "size": size,
                "side": "N",
                "floor_owned": 0.90,
                **_book(no),
            }
        )
    return out


def flash_collapse_reference_v1() -> List[Dict[str, Any]]:
    """Documented flash: ~0.98 → 0.917 → 0.793 in 25ms → 0.681 in 50ms."""
    size = 100.0
    frames = [
        (0, {"0.98": "500"}),
        (10, {"0.917": "500"}),
        (25, {"0.793": "500"}),
        (50, {"0.681": "500"}),
    ]
    out = []
    for i, (t_ms, no) in enumerate(frames):
        out.append(
            {
                "t_ms": t_ms,
                "seq": i + 1,
                "size": size,
                "side": "N",
                "floor_owned": 0.90,
                **_book(no),
            }
        )
    return out


def write_synthetic_fixtures(dir_path: Path) -> Dict[str, Path]:
    dir_path.mkdir(parents=True, exist_ok=True)
    mapping = {
        "gradual_collapse_reference_v1.json": gradual_collapse_reference_v1(),
        "flash_collapse_reference_v1.json": flash_collapse_reference_v1(),
    }
    paths = {}
    for name, frames in mapping.items():
        p = dir_path / name
        p.write_text(json.dumps({"name": name.replace(".json", ""), "frames": frames}, indent=2))
        paths[name] = p
    return paths


def load_synthetic_fixture(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    data = json.loads(path.read_text())
    return str(data.get("name") or path.stem), list(data.get("frames") or [])
