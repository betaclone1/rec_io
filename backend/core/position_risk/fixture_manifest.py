"""Historical fixture provenance (exact paths/hashes; never invent)."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.cycle_recon.sources import locate_package

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "position_risk"
HISTORICAL_CSV = FIXTURE_ROOT / "historical" / "10058_rows_59597_59721_59863.csv"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"

# Authoritative export (may live outside repo)
SOURCE_CSV_DEFAULT = Path.home() / "Downloads" / "10058_full_09_07.csv"


@dataclass
class HistoricalFixtureRef:
    trade_id: int
    role: str  # gradual_loss | flash_loss | supplemental_loss | win_control
    status: str  # RESOLVED_L2 | UNRESOLVED | SUPPLEMENTAL
    ticker: str
    side: str
    trade_strategy: str
    buy_price: str
    sell_price: str
    position: str
    date: str
    time: str
    closed_at: str
    close_method: str
    row_csv: str
    row_csv_sha256: str
    source_csv: str
    source_csv_sha256: Optional[str]
    l2_package_path: Optional[str]
    l2_package_sha256: Optional[str]
    l2_package_bytes: Optional[int]
    public_tape_path: Optional[str]
    public_tape_sha256: Optional[str]
    notes: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_historical_rows(csv_path: Path = HISTORICAL_CSV) -> List[Dict[str, str]]:
    with csv_path.open(newline="") as f:
        return list(csv.DictReader(f))


def build_manifest() -> Dict[str, Any]:
    row_sha = _sha256(HISTORICAL_CSV) if HISTORICAL_CSV.is_file() else None
    source_sha = _sha256(SOURCE_CSV_DEFAULT) if SOURCE_CSV_DEFAULT.is_file() else None
    roles = {
        59597: "gradual_loss",
        59721: "flash_loss",
        59863: "supplemental_loss",
        59860: "win_control",
        59847: "win_control",
        59838: "win_control",
        59835: "win_control",
    }
    refs: List[HistoricalFixtureRef] = []
    rows = load_historical_rows() if HISTORICAL_CSV.is_file() else []
    by_id = {int(r["id"]): r for r in rows}
    for tid, role in roles.items():
        r = by_id.get(tid)
        if not r:
            refs.append(
                HistoricalFixtureRef(
                    trade_id=tid,
                    role=role,
                    status="UNRESOLVED",
                    ticker="",
                    side="",
                    trade_strategy="",
                    buy_price="",
                    sell_price="",
                    position="",
                    date="",
                    time="",
                    closed_at="",
                    close_method="",
                    row_csv=str(HISTORICAL_CSV),
                    row_csv_sha256=row_sha or "",
                    source_csv=str(SOURCE_CSV_DEFAULT),
                    source_csv_sha256=source_sha,
                    l2_package_path=None,
                    l2_package_sha256=None,
                    l2_package_bytes=None,
                    public_tape_path=None,
                    public_tape_sha256=None,
                    notes="trade row missing from extracted CSV fixture",
                )
            )
            continue
        ticker = r["ticker"]
        loc = locate_package(ticker)
        tape = (
            REPO_ROOT
            / "backend"
            / "data"
            / "historical_data"
            / "cycle_recon_cache"
            / "markets"
            / f"{ticker}.json"
        )
        tape_ok = tape.is_file()
        status = "RESOLVED_L2" if loc.path else "UNRESOLVED"
        if role == "supplemental_loss" and loc.path:
            status = "SUPPLEMENTAL"
        notes = []
        if not loc.path:
            notes.append("L2 package not found locally — UNRESOLVED historical fixture")
        else:
            notes.append(f"L2 located source={loc.source}")
        if not tape_ok:
            notes.append("public tape cache missing — Stage 1 tape=UNKNOWN")
        if role == "supplemental_loss":
            notes.append("supplemental only; incomplete relative to primary pair if tape missing")
        # Local DB may differ from CSV (tenant 10058 export) — never claim DB id match.
        notes.append(
            "Authoritative trade row from monitor 10058 CSV export; "
            "local users_* trade id space may differ — do not join on id alone"
        )
        refs.append(
            HistoricalFixtureRef(
                trade_id=tid,
                role=role,
                status=status,
                ticker=ticker,
                side=r.get("side") or "",
                trade_strategy=r.get("trade_strategy") or "",
                buy_price=r.get("buy_price") or "",
                sell_price=r.get("sell_price") or "",
                position=r.get("position") or "",
                date=r.get("date") or "",
                time=r.get("time") or "",
                closed_at=r.get("closed_at") or "",
                close_method=r.get("close_method") or "",
                row_csv=str(HISTORICAL_CSV.relative_to(REPO_ROOT)),
                row_csv_sha256=row_sha or "",
                source_csv=str(SOURCE_CSV_DEFAULT),
                source_csv_sha256=source_sha,
                l2_package_path=str(loc.path) if loc.path else None,
                l2_package_sha256=loc.sha256 if loc.path else None,
                l2_package_bytes=loc.bytes if loc.path else None,
                public_tape_path=str(tape) if tape_ok else None,
                public_tape_sha256=_sha256(tape) if tape_ok else None,
                notes="; ".join(notes),
            )
        )

    synthetic = {
        "gradual_collapse_reference_v1": {
            "path": "tests/fixtures/position_risk/synthetic/gradual_collapse_reference_v1.json",
            "note": "Synthetic scenario — NOT trade 59597",
        },
        "flash_collapse_reference_v1": {
            "path": "tests/fixtures/position_risk/synthetic/flash_collapse_reference_v1.json",
            "note": "Synthetic scenario — NOT trade 59721",
        },
    }

    return {
        "stage": 1,
        "observe_only": True,
        "source_of_truth_trade_rows": {
            "description": "Monitor 10058 HWS export",
            "path": str(SOURCE_CSV_DEFAULT),
            "sha256": source_sha,
            "extracted_rows": str(HISTORICAL_CSV.relative_to(REPO_ROOT)),
            "extracted_sha256": row_sha,
        },
        "historical": [asdict(x) for x in refs],
        "synthetic_scenarios": synthetic,
        "safety": {
            "no_exit_intent": True,
            "no_order_placement": True,
            "ats_sole_stop_authority": True,
            "public_tape_stage1": "UNKNOWN",
        },
    }


def write_manifest(path: Path = MANIFEST_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = build_manifest()
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path
