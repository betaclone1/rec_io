#!/usr/bin/env python3
"""One-shot recompute of performance rollup tables for one or more slots (closed/settled trades → UPSERT)."""

from __future__ import annotations

import argparse
import os
import sys

# Repo root on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.core.performance_rollups import recompute_performance_rollups_for_slot  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill users_<slot>.performance_{total,monitors}_<slot>")
    p.add_argument(
        "slots",
        nargs="*",
        default=["0001"],
        help="Four-digit slot(s), default 0001",
    )
    args = p.parse_args()
    for s in args.slots:
        print(recompute_performance_rollups_for_slot(s))


if __name__ == "__main__":
    main()
