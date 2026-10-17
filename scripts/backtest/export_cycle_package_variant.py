#!/usr/bin/env python3
"""Derive an external (non-proprietary) cycle package from a sealed full archive.

Omits strike_table.csv and metrics_ring.csv; rewrites meta.json with
variant=external. Full seals stay authoritative on disk / Drive.

Examples:
  python3 scripts/backtest/export_cycle_package_variant.py path/to/TICKER.tar.xz
  python3 scripts/backtest/export_cycle_package_variant.py --dir backtesting_data/KXBTC15M/2026/2026_10_OCT
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.cycle_package_members import (  # noqa: E402
    PROPRIETARY_MEMBERS,
    export_external_variant,
)


def _iter_packages(paths: list[Path], directory: Path | None) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        p = p.expanduser().resolve()
        if p.is_file() and p.name.endswith(".tar.xz") and ".external." not in p.name:
            out.append(p)
    if directory is not None:
        d = directory.expanduser().resolve()
        if not d.is_dir():
            raise SystemExit(f"not a directory: {d}")
        for p in sorted(d.rglob("*.tar.xz")):
            if ".external." in p.name:
                continue
            out.append(p.resolve())
    # de-dupe preserve order
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    return uniq


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "packages",
        nargs="*",
        type=Path,
        help="Full .tar.xz package path(s)",
    )
    ap.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="Recursively export every full package under this directory",
    )
    ap.add_argument(
        "--dest-dir",
        type=Path,
        default=None,
        help="Write external packages here (default: next to each source)",
    )
    args = ap.parse_args()
    pkgs = _iter_packages(list(args.packages or []), args.dir)
    if not pkgs:
        ap.error("provide package path(s) and/or --dir")
    print(
        f"exporting external variant (omit {', '.join(PROPRIETARY_MEMBERS)}) "
        f"for {len(pkgs)} package(s)"
    )
    for src in pkgs:
        if args.dest_dir is not None:
            dest = args.dest_dir.expanduser().resolve() / (
                src.name.replace(".tar.xz", "") + ".external.tar.xz"
            )
        else:
            dest = None
        out = export_external_variant(src, dest=dest)
        print(f"  {src.name} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
