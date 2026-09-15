#!/usr/bin/env python3
"""CLI for Stage 1 position_risk observe tools (local only)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def cmd_write_fixtures(_: argparse.Namespace) -> int:
    from backend.core.position_risk.fixture_manifest import FIXTURE_ROOT, write_manifest
    from backend.core.position_risk.synthetic_scenarios import write_synthetic_fixtures

    write_synthetic_fixtures(FIXTURE_ROOT / "synthetic")
    path = write_manifest()
    print(json.dumps({"manifest": str(path)}, indent=2))
    return 0


def cmd_replay_synthetic(args: argparse.Namespace) -> int:
    from backend.core.position_risk.metrics import LatencyTracker
    from backend.core.position_risk.replay import replay_frames
    from backend.core.position_risk.synthetic_scenarios import load_synthetic_fixture

    path = Path(args.path)
    name, frames = load_synthetic_fixture(path)
    tracker = LatencyTracker()
    result = replay_frames(frames, ticker=name, tracker=tracker)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_replay_historical(args: argparse.Namespace) -> int:
    from backend.core.position_risk.fixture_manifest import build_manifest
    from backend.core.position_risk.historical_replay import replay_historical_package

    man = build_manifest()
    tid = int(args.trade_id)
    ref = next((h for h in man["historical"] if h["trade_id"] == tid), None)
    if not ref:
        print(json.dumps({"error": "trade_id not in manifest", "trade_id": tid}))
        return 1
    if not ref.get("l2_package_path"):
        print(
            json.dumps(
                {
                    "error": "UNRESOLVED — no local L2 package",
                    "trade_id": tid,
                    "status": ref.get("status"),
                    "notes": ref.get("notes"),
                },
                indent=2,
            )
        )
        return 2
    floor = None
    try:
        buy = float(ref["buy_price"])
        # HWS scalp typical floor analysis: stop_loss_price often ~0.10 owned;
        # CSV may lack stop_loss_price — leave None rather than invent.
        floor = None
    except Exception:
        buy = 1.0
    result = replay_historical_package(
        package_path=Path(ref["l2_package_path"]),
        side=ref["side"],
        size=float(ref["position"]),
        floor_owned=floor,
        date=ref["date"],
        time=ref["time"],
        closed_at=ref["closed_at"],
    )
    result["historical_ref"] = {
        "trade_id": tid,
        "role": ref["role"],
        "status": ref["status"],
        "l2_sha256": ref.get("l2_package_sha256"),
        "tape": "UNKNOWN",
        "notes": ref.get("notes"),
    }
    out = Path(args.out) if args.out else None
    text = json.dumps(result, indent=2, default=str)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(json.dumps({"wrote": str(out), "n_frames": result.get("n_frames")}))
    else:
        print(text)
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    path = Path(os.getenv("REC_POSITION_RISK_STATUS_PATH", "backend/data/position_risk/status.json"))
    if not path.is_file():
        print(json.dumps({"error": "status file missing", "path": str(path)}))
        return 1
    print(path.read_text())
    return 0


def cmd_enroll_scan(_: argparse.Namespace) -> int:
    from backend.core.config.database import get_system_postgresql_connection
    from backend.core.position_risk.enroll import fetch_open_hws_positions

    conn = get_system_postgresql_connection()
    try:
        rows = fetch_open_hws_positions(conn)
    finally:
        conn.close()
    print(json.dumps([r.to_dict() for r in rows], indent=2, default=str))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="position_risk Stage 1 local tools")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("write-fixtures", help="Write synthetic JSON + manifest.json")
    s.set_defaults(func=cmd_write_fixtures)

    s = sub.add_parser("replay-synthetic")
    s.add_argument("--path", required=True)
    s.set_defaults(func=cmd_replay_synthetic)

    s = sub.add_parser("replay-historical")
    s.add_argument("--trade-id", required=True, type=int)
    s.add_argument("--out", default="")
    s.set_defaults(func=cmd_replay_historical)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("enroll-scan")
    s.set_defaults(func=cmd_enroll_scan)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
