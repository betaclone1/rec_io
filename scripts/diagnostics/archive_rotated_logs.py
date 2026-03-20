#!/usr/bin/env python3
"""
Archive rotated supervisor logs out of the root logs/ directory.

Goal:
- Keep the root logs/ directory focused on current live logs
  (<service>.out.log / <service>.err.log).
- Move all numeric rotations (<service>.out.log.N / <service>.err.log.N)
  into logs/archive/ and compress them.

This is safe to run while the system is live: supervisor only writes to the
base *.log files; the rotated *.log.N files are read-only history.
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path
import re


def archive_rotated_logs() -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "logs"
    if not log_dir.is_dir():
        print(f"logs directory not found at {log_dir}")
        return

    archive_dir = log_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    pattern = re.compile(
        r"^(?P<base>.+\.(?:out|err)\.log)\.(?P<idx>\d+)$"
    )

    moved = 0

    for path in log_dir.iterdir():
        if not path.is_file():
            continue
        m = pattern.match(path.name)
        if not m:
            continue

        target = archive_dir / f"{path.name}.gz"

        # If already archived, skip
        if target.exists():
            continue

        try:
            with path.open("rb") as src, gzip.open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
            moved += 1
            print(f"Archived {path.name} -> {target.name}")
        except FileNotFoundError:
            continue

    print(f"Archived {moved} rotated log files into {archive_dir}")


def main() -> None:
    archive_rotated_logs()


if __name__ == "__main__":
    main()

