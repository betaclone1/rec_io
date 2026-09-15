"""Soft-skip historical fixture replay for 59597 / 59721 when packages missing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "position_risk"
MANIFEST = FIXTURE_ROOT / "manifest.json"


def _entry(trade_id: int):
    if not MANIFEST.is_file():
        return None
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for row in man.get("historical") or []:
        if int(row.get("trade_id") or -1) == int(trade_id):
            return row
    return None


@pytest.mark.parametrize("trade_id", [59597, 59721])
def test_historical_fixture_package_present_or_skip(trade_id):
    row = _entry(trade_id)
    if row is None:
        pytest.skip(f"trade {trade_id} not in manifest")
    pkg = row.get("l2_package_path")
    if not pkg or not Path(pkg).is_file():
        pytest.skip(f"L2 package missing for {trade_id}: {pkg}")
    data = Path(pkg).read_bytes()[:6]
    assert len(data) >= 6
