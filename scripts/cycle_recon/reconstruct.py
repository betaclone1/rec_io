#!/usr/bin/env python3
"""
Local offline cycle reconstruction CLI.

Postgres trade log is the default source. CSV --trade-log is an optional override.

Example (PG):
  PYTHONPATH=. .venv/bin/python scripts/cycle_recon/reconstruct.py \\
    --user-no 0001 --range 7d --symbol BTC --offline

Example (CSV fixture):
  PYTHONPATH=. .venv/bin/python scripts/cycle_recon/reconstruct.py \\
    --trade-log tests/fixtures/cycle_recon/10058_full_09_05.csv \\
    --trade-id 55286 --trade-id 55388 --no-pg
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.cycle_recon.orchestrator import RunRequest, run_reconstruction


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline cycle reconstruction (local analysis only)")
    ap.add_argument("--start", help="Range start UTC ISO (prefer --start-et for Eastern wall)")
    ap.add_argument("--end", help="Range end UTC ISO")
    ap.add_argument("--start-et", help="Range start Eastern wall (YYYY-MM-DD[ HH:MM[:SS]])")
    ap.add_argument("--end-et", help="Range end Eastern wall")
    ap.add_argument(
        "--range",
        dest="range_preset",
        choices=["24h", "7d", "30d", "all"],
        help="Relative Eastern window ending now",
    )
    ap.add_argument("--ticker", action="append", default=[], help="Market ticker (repeatable)")
    ap.add_argument("--symbol", action="append", default=[], help="Filter symbols e.g. BTC (repeatable)")
    ap.add_argument("--user-no", help="Tenant slot for Postgres trade log (e.g. 0001)")
    ap.add_argument(
        "--no-pg",
        action="store_true",
        help="Do not read Postgres trade log (CSV tickers/range only)",
    )
    ap.add_argument("--trade-log", help="Optional CSV override (fixtures/dev)")
    ap.add_argument("--trade-id", action="append", default=[], help="Trade id within PG or --trade-log")
    ap.add_argument("--monitor", action="append", default=[], help="Filter monitors")
    ap.add_argument("--pre-entry-seconds", type=int, default=120)
    ap.add_argument("--post-close-seconds", type=int, default=30)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--output-dir", help="Run output root (default cycle_recon_runs)")
    ap.add_argument("--run-id", help="Optional run id")
    ap.add_argument("--force-refresh", action="store_true", help="Refetch public trades")
    ap.add_argument("--offline", action="store_true", help="Cache/archives only")
    ap.add_argument("--export-csv", action="store_true", help="Also write debug CSVs")
    ap.add_argument(
        "--standardized-sizes",
        default="1,5,10,25,50,100",
        help="Comma-separated contract sizes for VWAP metrics",
    )
    ap.add_argument(
        "--no-drive-copy",
        action="store_true",
        help="Do not copy missing packages from mounted Drive into local cache",
    )
    ap.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip canonical handoff archive creation (debug only; default is ON)",
    )
    args = ap.parse_args(argv)

    sizes = [float(x) for x in str(args.standardized_sizes).split(",") if x.strip()]
    use_pg = not args.no_pg and not args.trade_log
    if args.trade_log:
        use_pg = False

    user_no = args.user_no
    if not user_no:
        import os

        user_no = (os.environ.get("REC_USER_NO") or "").strip() or None
        schema = (os.environ.get("REC_USER_SCHEMA") or "").strip()
        if not user_no and schema.startswith("users_"):
            user_no = schema[6:]

    req = RunRequest(
        start=args.start,
        end=args.end,
        start_et=args.start_et,
        end_et=args.end_et,
        range_preset=args.range_preset,
        tickers=list(args.ticker or []),
        symbols=list(args.symbol or []),
        trade_log=args.trade_log,
        trade_ids=list(args.trade_id or []),
        monitors=list(args.monitor or []),
        user_no=user_no,
        use_pg=use_pg,
        pre_entry_seconds=args.pre_entry_seconds,
        post_close_seconds=args.post_close_seconds,
        workers=args.workers,
        output_dir=args.output_dir,
        force_refresh=args.force_refresh,
        offline=args.offline,
        export_csv=args.export_csv,
        standardized_sizes=sizes,
        copy_from_drive=not args.no_drive_copy,
        run_id=args.run_id,
        create_archive=not args.no_archive,
    )
    try:
        result = run_reconstruction(req)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    arch = result.get("handoff_archive") or (result.get("summary") or {}).get("handoff_archive")
    if arch and not arch.get("error"):
        print(
            "HANDOFF_ARCHIVE "
            f"path={arch.get('path')} format={arch.get('format')} "
            f"bytes={arch.get('bytes')} sha256={arch.get('sha256')} "
            f"compression_s={arch.get('compression_s')}",
            file=sys.stderr,
        )
    elif arch and arch.get("error"):
        print(f"HANDOFF_ARCHIVE_FAILED {arch.get('error')}", file=sys.stderr)

    print(
        json.dumps(
            {
                "run_dir": result["run_dir"],
                "summary": result["summary"],
                "handoff_archive": arch,
            },
            indent=2,
            default=str,
        )
    )
    statuses = (result.get("summary") or {}).get("statuses") or {}
    if statuses.get("INVALID") or statuses.get("MISSING"):
        return 1
    if arch and arch.get("error"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
