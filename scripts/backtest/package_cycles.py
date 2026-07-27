#!/usr/bin/env python3
"""CLI: package due cycle hot tables (or one ticker).

  .venv/bin/python scripts/backtest/package_cycles.py
  .venv/bin/python scripts/backtest/package_cycles.py --ticker KXBTC15M-...
  .venv/bin/python scripts/backtest/package_cycles.py --force --no-drop
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Package cycle hot tables")
    p.add_argument("--ticker", help="Package a single market ticker")
    p.add_argument("--force", action="store_true", help="Ignore grace / overwrite")
    p.add_argument(
        "--no-drop",
        action="store_true",
        help="Keep PG tables after packaging",
    )
    args = p.parse_args()

    from backend.core.cycle_packager import (
        package_due_cycles,
        package_root,
        package_ticker,
    )

    print(f"package_root={package_root()}")
    drop_after = not args.no_drop
    if args.ticker:
        path = package_ticker(args.ticker, drop_after=drop_after, force=args.force)
        print(path or "skipped/failed")
        return 0 if path else 1
    done = package_due_cycles(drop_after=drop_after, force=args.force)
    for path in done:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
