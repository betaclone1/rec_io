#!/usr/bin/env python3
"""
Prune rotated supervisor logs in the local logs/ directory.

Goal:
- Keep the current live log file (*.out.log / *.err.log) for each service.
- Keep only the most recent N numeric rotations (e.g. .out.log.1 .. .out.log.N).
- Delete any older numeric rotations (e.g. .out.log.6 if N=5), to reduce disk usage.

This operates purely on filenames and does not depend on supervisor or logrotate.
It is safe to run on a running system; it never touches the active *.log file.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


MAX_BACKUPS = 5


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "logs"

    if not log_dir.is_dir():
        print(f"logs directory not found at {log_dir}")
        return

    # Match names like:
    #   service.out.log
    #   service.out.log.1
    #   service.err.log
    #   service.err.log.10
    pattern = re.compile(r"^(?P<base>.+\.(?:out|err)\.log)(?:\.(?P<idx>\d+))?$")

    groups: dict[str, list[tuple[int, Path]]] = defaultdict(list)

    for path in log_dir.iterdir():
        if not path.is_file():
            continue
        m = pattern.match(path.name)
        if not m:
            continue
        base = m.group("base")
        idx_str = m.group("idx")
        idx = int(idx_str) if idx_str is not None else 0
        groups[base].append((idx, path))

    to_delete: list[Path] = []

    for base, entries in groups.items():
        # Keep the active file (idx == 0) always
        backups = sorted((e for e in entries if e[0] > 0), key=lambda e: e[0])
        if len(backups) <= MAX_BACKUPS:
            continue

        # Keep only the newest MAX_BACKUPS indices; delete the rest
        # Example: indices [1,2,3,4,5,6,7] with MAX_BACKUPS=5 → delete 1,2
        for idx, path in backups[:-MAX_BACKUPS]:
            to_delete.append(path)

    unique_to_delete = sorted(set(to_delete))
    print(f"Found {len(unique_to_delete)} old rotated log files to delete (max_backups={MAX_BACKUPS}).")

    for path in unique_to_delete:
        try:
            print(f"Removing {path}")
            path.unlink()
        except FileNotFoundError:
            # If something else removed it between listing and unlink, ignore.
            continue


if __name__ == "__main__":
    main()

