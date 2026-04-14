"""Shared helpers for system.version_control release strings (patch bump, read latest)."""

from __future__ import annotations

import re
from typing import Any, Optional


def normalize_version_label(s: str) -> str:
    """Strip leading 'v' / whitespace."""
    return s.strip().lstrip("vV").strip()


def bump_patch(version: str) -> str:
    v = normalize_version_label(version)
    parts = v.split(".")
    if not parts:
        raise ValueError("empty version")
    last = parts[-1]
    m = re.match(r"^(\d+)(.*)$", last)
    if not m:
        raise ValueError(f"last segment not numeric: {version!r}")
    n = int(m.group(1)) + 1
    suffix = m.group(2)
    parts[-1] = f"{n}{suffix}"
    return ".".join(parts)


def fetch_latest_version(cursor: Any) -> Optional[str]:
    cursor.execute("SELECT version FROM system.version_control ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if not row or not row[0]:
        return None
    return str(row[0]).strip()
