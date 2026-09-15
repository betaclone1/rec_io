"""PRE package must never import TM/TE or call place_order."""

from __future__ import annotations

import re
from pathlib import Path

PRE_ROOT = Path(__file__).resolve().parents[3] / "backend" / "core" / "position_risk"

_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+\S*trade_(?:manager|executor)\S*\s+import|import\s+\S*trade_(?:manager|executor))",
)


def test_no_tm_te_imports_in_pre():
    offenders = []
    for path in sorted(PRE_ROOT.glob("*.py")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _IMPORT_RE.search(line):
                offenders.append(f"{path.name}:{i}:{line.strip()}")
            if "place_order(" in line and not line.strip().startswith("#"):
                offenders.append(f"{path.name}:{i}:{line.strip()}")
    assert not offenders, offenders
