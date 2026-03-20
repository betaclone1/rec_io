#!/usr/bin/env python3
"""
Purge logs for services that are no longer managed by supervisor.

Rules:
- Discover the current set of supervised program names from supervisorctl.
- In logs/, consider files matching: <service>.(out|err).log[.N]
- If <service> is NOT in the active supervisor program list AND
  the file is older than a cutoff (default: 14 days),
  delete it (including its rotated segments).

This is intended as a housekeeping tool for development / local environments
to get rid of logs from old monitors, retired services, etc., without touching
the active services' logs.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Set


CUTOFF_DAYS = 14


def get_active_services() -> Set[str]:
    """Return the set of program names currently known to supervisor."""
    try:
        result = subprocess.run(
            ["supervisorctl", "-c", "backend/supervisord.conf", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("supervisorctl not found; cannot determine active services.")
        return set()

    active = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith(("error:", "unix:/")):
            continue
        # Format: <name>  STATE  pid ...
        parts = line.split()
        if parts:
            active.add(parts[0])
    return active


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "logs"

    if not log_dir.is_dir():
        print(f"logs directory not found at {log_dir}")
        return

    active_services = get_active_services()
    if not active_services:
        print("No active services detected from supervisorctl; aborting purge.")
        return

    cutoff = datetime.now() - timedelta(days=CUTOFF_DAYS)
    pattern = re.compile(
        r"^(?P<service>.+)\.(?P<stream>out|err)\.log(?:\.(?P<idx>\d+))?$"
    )

    to_delete = []

    for path in log_dir.iterdir():
        if not path.is_file():
            continue
        m = pattern.match(path.name)
        if not m:
            continue
        service = m.group("service")
        if service in active_services:
            continue

        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime > cutoff:
            continue

        to_delete.append(path)

    # Group by service so we can report clearly
    by_service = {}
    for p in to_delete:
        m = pattern.match(p.name)
        if not m:
            continue
        svc = m.group("service")
        by_service.setdefault(svc, []).append(p)

    if not to_delete:
        print(
            f"No inactive-service logs older than {CUTOFF_DAYS} days found to delete."
        )
        return

    print(
        f"Purging logs for {len(by_service)} inactive services "
        f"(files older than {CUTOFF_DAYS} days)."
    )

    for svc, files in sorted(by_service.items()):
        print(f"- {svc}: {len(files)} files")
        for p in sorted(files):
            try:
                print(f"  removing {p.name}")
                p.unlink()
            except FileNotFoundError:
                continue


if __name__ == "__main__":
    main()

