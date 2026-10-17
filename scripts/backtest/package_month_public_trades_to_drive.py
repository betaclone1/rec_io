#!/usr/bin/env python3
"""
Bundle a month of KXBTC15M day public-trade CSVs into one .tar.xz under the
local backtesting month folder, then upload to Drive BACKTESTING_DATA.

Layout:
  backtesting_data/KXBTC15M/{YYYY}/{YYYY_MM_MON}/KXBTC15M_public_trades_{YYYY-MM}_et.tar.xz

Example:
  .venv/bin/python3 scripts/backtest/package_month_public_trades_to_drive.py --year 2026 --month 9
"""

from __future__ import annotations

import argparse
import calendar
import json
import subprocess
import sys
import tarfile
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.cycle_packager import month_folder, package_root

TRADES_DIR = _ROOT / "backend" / "data" / "historical_data" / "kalshi_public_trades"
SERIES = "KXBTC15M"


def month_days(year: int, month: int) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last + 1)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--series", default=SERIES)
    ap.add_argument("--skip-upload", action="store_true")
    ap.add_argument("--dry-run-upload", action="store_true")
    args = ap.parse_args()

    days = month_days(args.year, args.month)
    # Use mid-month for month_folder Eastern labeling
    mid = date(args.year, args.month, 15)
    from zoneinfo import ZoneInfo

    end_est = datetime(mid.year, mid.month, mid.day, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    year_s, month_s = month_folder(end_est)
    out_dir = package_root() / args.series / year_s / month_s
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{args.year}-{args.month:02d}"
    out_name = f"{args.series}_public_trades_{tag}_et.tar.xz"
    out_path = out_dir / out_name

    members: list[tuple[str, Path]] = []
    missing: list[str] = []
    for d in days:
        p = TRADES_DIR / f"{args.series}_public_trades_{d.isoformat()}_et.csv"
        if p.is_file() and p.stat().st_size > 0:
            members.append((p.name, p))
        else:
            missing.append(d.isoformat())

    for extra in (
        f"{args.series}_longshot_winners_{tag}_et.csv",
        f"{args.series}_longshot_summary_{tag}_et.csv",
    ):
        p = TRADES_DIR / extra
        if p.is_file():
            members.append((p.name, p))

    if not members:
        print("ERROR: no day CSVs found to package", flush=True)
        return 1

    manifest = {
        "series": args.series,
        "year": args.year,
        "month": args.month,
        "month_folder": month_s,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "day_csv_count": sum(1 for n, _ in members if n.startswith(f"{args.series}_public_trades_")),
        "missing_days": missing,
        "members": [
            {"name": n, "bytes": p.stat().st_size} for n, p in members
        ],
    }
    manifest_path = TRADES_DIR / f"{args.series}_public_trades_{tag}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    members.append((manifest_path.name, manifest_path))

    print(
        f"packaging {len(members)} members -> {out_path} "
        f"(missing_days={len(missing)})",
        flush=True,
    )
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    with tarfile.open(tmp, "w:xz", preset=6) as tar:
        for name, path in members:
            tar.add(path, arcname=name)
    tmp.replace(out_path)
    print(f"wrote {out_path} bytes={out_path.stat().st_size}", flush=True)

    if args.skip_upload:
        print("skip-upload", flush=True)
        return 0

    cmd = [
        "node",
        str(_ROOT / "scripts" / "gdrive" / "upload-backtesting-data.js"),
        "--file",
        str(out_path),
    ]
    if args.dry_run_upload:
        cmd.append("--dry-run")
    print("upload:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(_ROOT), check=False)
    if proc.returncode != 0:
        print(f"upload failed rc={proc.returncode}", flush=True)
        return proc.returncode
    print("DRIVE_UPLOAD_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
