#!/usr/bin/env python3
"""CLI wrapper for backend.util.master_system_log.log_system_event (shell scripts)."""

from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, PROJECT_ROOT)


def main() -> int:
    p = argparse.ArgumentParser(description="Append one row to the master system event log.")
    p.add_argument("--category", required=True, help="RESTART|WS|DEPLOY|TRADING_HALT|MAINTENANCE|ANOMALY|MONITOR|BACKUP")
    p.add_argument("--message", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--severity", default="info", choices=["info", "warning", "critical"])
    p.add_argument("--detail-ref", default="", help="Supervisor script name or logs/ basename")
    p.add_argument("--metadata", default="", help="Optional JSON object")
    args = p.parse_args()

    meta = None
    if args.metadata.strip():
        try:
            meta = json.loads(args.metadata)
        except json.JSONDecodeError as e:
            print(f"error: invalid --metadata JSON: {e}", file=sys.stderr)
            return 1

    from backend.util.master_system_log import log_system_event

    log_system_event(
        category=args.category,
        message=args.message,
        source=args.source,
        severity=args.severity,
        detail_ref=args.detail_ref or None,
        metadata=meta,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
