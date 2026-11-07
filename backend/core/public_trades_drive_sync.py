"""Hourly public-trades + market-results archive → Google Drive.

Background-only: Kalshi public REST + local CSV / tar.xz + Drive upload.
Does not touch Redis, monitors, tenant DML, or the live ingest path.
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import subprocess
import sys
import tarfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from backend.core.cycle_gdrive_upload import (
    gdrive_upload_enabled,
    resolve_gdrive_oauth_paths,
    upload_cycle_packages,
)
from backend.core.cycle_packager import month_folder, package_root

log = logging.getLogger("public_trades_drive_sync")

EST = ZoneInfo("America/New_York")

DEFAULT_SERIES: tuple[str, ...] = (
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXGOLD15M",
    "KXSILVER15M",
    "KXWTI15M",
)

_REPO = Path(__file__).resolve().parents[2]
TRADES_DIR = _REPO / "backend" / "data" / "historical_data" / "kalshi_public_trades"


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return default


def et_today() -> date:
    return datetime.now(EST).date()


def interval_sec() -> float:
    try:
        return max(300.0, float(_env_first("PUBLIC_TRADES_DRIVE_SYNC_INTERVAL_SEC", default="3600")))
    except (TypeError, ValueError):
        return 3600.0


def lookback_days() -> int:
    """Calendar days to refresh. Hourly prod stays at 1 (today only — low load)."""
    try:
        return max(1, int(_env_first("PUBLIC_TRADES_DRIVE_SYNC_LOOKBACK_DAYS", default="1")))
    except (TypeError, ValueError):
        return 1


def pull_workers() -> int:
    """Per-day Kalshi pull concurrency. Keep low on prod."""
    try:
        return max(1, min(4, int(_env_first("PUBLIC_TRADES_DRIVE_SYNC_WORKERS", default="2"))))
    except (TypeError, ValueError):
        return 2


def sync_enabled() -> bool:
    raw = _env_first("PUBLIC_TRADES_DRIVE_SYNC", default="").lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    # Auto-on when Drive OAuth is present (same pattern as cycle packages).
    return gdrive_upload_enabled()


def series_list(override: Optional[Sequence[str]] = None) -> list[str]:
    if override:
        return [str(s).strip().upper() for s in override if str(s).strip()]
    raw = _env_first("PUBLIC_TRADES_DRIVE_SYNC_SERIES", default="")
    if raw:
        return [p.strip().upper() for p in raw.split(",") if p.strip()]
    return list(DEFAULT_SERIES)


def _python() -> str:
    venv = _REPO / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _run(argv: list[str], *, label: str) -> int:
    log.info("RUN %s: %s", label, " ".join(argv))
    t0 = time.time()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO)
    proc = subprocess.run(argv, cwd=str(_REPO), env=env)
    log.info("DONE %s rc=%s elapsed=%.1fs", label, proc.returncode, time.time() - t0)
    return int(proc.returncode)


def day_csv_path(series: str, day: date) -> Path:
    return TRADES_DIR / f"{series}_public_trades_{day.isoformat()}_et.csv"


def month_archive_path(series: str, year: int, month: int) -> Path:
    mid = datetime(year, month, 15, 12, 0, tzinfo=EST)
    year_s, month_s = month_folder(mid)
    out_dir = package_root() / series / year_s / month_s
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{year}-{month:02d}"
    return out_dir / f"{series}_public_trades_{tag}_et.tar.xz"


def _month_days(year: int, month: int) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last + 1)]


def pull_day(series: str, day: date, *, force: bool, workers: int) -> int:
    argv = [
        _python(),
        "scripts/backtest/pull_kxbtc15m_public_trades_day_csv.py",
        "--date",
        day.isoformat(),
        "--series",
        series,
        "--workers",
        str(workers),
    ]
    if force:
        argv.append("--force-refresh")
    return _run(argv, label=f"trades:{series}:{day.isoformat()}{'F' if force else ''}")


def refresh_market_results(series: str, months: Iterable[tuple[int, int]]) -> list[str]:
    failed: list[str] = []
    rc = _run(
        [
            _python(),
            "scripts/backtest/fetch_kxbtc15m_market_results_bulk.py",
            "--series",
            series,
        ],
        label=f"results_bulk:{series}",
    )
    if rc != 0:
        failed.append(f"results_bulk:{series}:rc={rc}")
    for y, m in sorted(set(months)):
        rc = _run(
            [
                _python(),
                "scripts/backtest/export_month_market_results.py",
                "--series",
                series,
                "--year",
                str(y),
                "--month",
                str(m),
            ],
            label=f"results_month:{series}:{y}-{m:02d}",
        )
        if rc != 0:
            failed.append(f"results_month:{series}:{y}-{m:02d}:rc={rc}")
    return failed


def package_month(series: str, year: int, month: int) -> Optional[Path]:
    """Build (or rebuild) the month tar.xz. Returns path or None if nothing to pack."""
    days = _month_days(year, month)
    tag = f"{year}-{month:02d}"
    members: list[tuple[str, Path]] = []
    missing: list[str] = []
    for d in days:
        p = day_csv_path(series, d)
        if p.is_file() and p.stat().st_size > 0:
            members.append((p.name, p))
        else:
            missing.append(d.isoformat())

    for extra in (
        f"{series}_market_results_{tag}_et.csv",
        f"{series}_longshot_winners_{tag}_et.csv",
        f"{series}_longshot_summary_{tag}_et.csv",
    ):
        p = TRADES_DIR / extra
        if p.is_file() and p.stat().st_size > 0:
            members.append((extra, p))

    if not members:
        log.warning("package skip %s %s: no members", series, tag)
        return None

    out_path = month_archive_path(series, year, month)
    manifest = {
        "series": series,
        "year": year,
        "month": month,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "day_csv_count": sum(
            1 for n, _ in members if n.startswith(f"{series}_public_trades_")
        ),
        "missing_days": missing,
        "members": [{"name": n, "bytes": p.stat().st_size} for n, p in members],
    }
    manifest_path = TRADES_DIR / f"{series}_public_trades_{tag}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    members.append((manifest_path.name, manifest_path))

    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    log.info(
        "packaging %s -> %s members=%s missing_days=%s",
        tag,
        out_path,
        len(members),
        len(missing),
    )
    with tarfile.open(tmp, "w:xz", preset=6) as tar:
        for name, path in members:
            tar.add(path, arcname=name)
    tmp.replace(out_path)
    log.info("wrote %s bytes=%s", out_path, out_path.stat().st_size)
    return out_path


def catchup_and_package(
    series: Sequence[str],
    *,
    lookback: int,
    workers: int,
    force_recent_days: int = 1,
    package_months: Optional[Sequence[tuple[int, int]]] = None,
    skip_trades: bool = False,
    skip_results: bool = False,
    skip_package: bool = False,
) -> tuple[list[Path], list[str]]:
    """
    Low-load hourly path (serial): refresh today, light market-result update,
    re-package current month (plus previous month on the 1st).

    Intentionally not parallel — prod only needs the newest cycles each hour.
    Bulk historical seeds use a separate parallel local script.
    """
    TRADES_DIR.mkdir(parents=True, exist_ok=True)
    today = et_today()
    end = today
    start = end - timedelta(days=lookback)
    failed: list[str] = []
    archives: list[Path] = []
    months: set[tuple[int, int]] = {(end.year, end.month)}
    if end.day == 1:
        prev = end - timedelta(days=1)
        months.add((prev.year, prev.month))
    d = start
    while d <= end:
        months.add((d.year, d.month))
        d += timedelta(days=1)
    if package_months:
        months.update(package_months)

    force_cut = end - timedelta(days=max(0, force_recent_days - 1))

    if not skip_trades:
        for ser in series:
            d = start
            while d <= end:
                exists = day_csv_path(ser, d).is_file()
                force = d >= force_cut
                if force or not exists:
                    rc = pull_day(ser, d, force=force, workers=workers)
                    if rc != 0:
                        failed.append(f"trades:{ser}:{d.isoformat()}:rc={rc}")
                d += timedelta(days=1)

    if not skip_results:
        for ser in series:
            failed.extend(refresh_market_results(ser, months))

    if not skip_package:
        for ser in series:
            for y, m in sorted(months):
                path = package_month(ser, y, m)
                if path is not None:
                    archives.append(path)

    return archives, failed


def upload_archives(paths: Sequence[Path], *, dry_run: bool = False) -> bool:
    if not paths:
        log.info("upload: nothing to upload")
        return True
    if dry_run:
        for p in paths:
            log.info("DRY_RUN upload %s", p)
        return True
    if not gdrive_upload_enabled():
        client, token = resolve_gdrive_oauth_paths()
        log.error(
            "Drive upload disabled or missing OAuth (client=%s token=%s)",
            client,
            token,
        )
        return False
    return upload_cycle_packages(paths)


def local_months_with_day_csvs(series: Sequence[str]) -> list[tuple[str, int, int]]:
    """Scan trades dir for day CSVs; return (series, year, month) present on disk."""
    found: set[tuple[str, int, int]] = set()
    for ser in series:
        prefix = f"{ser}_public_trades_"
        for p in TRADES_DIR.glob(f"{prefix}*_et.csv"):
            # {series}_public_trades_YYYY-MM-DD_et.csv
            name = p.name
            if not name.startswith(prefix) or not name.endswith("_et.csv"):
                continue
            mid = name[len(prefix) : -len("_et.csv")]
            if len(mid) != 10 or mid[4] != "-" or mid[7] != "-":
                continue
            try:
                d = date.fromisoformat(mid)
            except ValueError:
                continue
            if p.stat().st_size <= 0:
                continue
            found.add((ser, d.year, d.month))
    return sorted(found)


def package_all_local_months(series: Sequence[str]) -> list[Path]:
    archives: list[Path] = []
    for ser, y, m in local_months_with_day_csvs(series):
        path = package_month(ser, y, m)
        if path is not None:
            archives.append(path)
    return archives


def score_cycles_enabled() -> bool:
    raw = _env_first("PUBLIC_TRADES_DRIVE_SYNC_SKIP_SCORE", default="").lower()
    return raw not in ("1", "true", "yes", "on")


def run_once(
    *,
    series: Optional[Sequence[str]] = None,
    lookback: Optional[int] = None,
    workers: Optional[int] = None,
    dry_run_upload: bool = False,
    skip_trades: bool = False,
    skip_results: bool = False,
    skip_package: bool = False,
    skip_upload: bool = False,
    skip_score: bool = False,
    backfill_local_months: bool = False,
) -> int:
    ser = series_list(series)
    lb = lookback if lookback is not None else lookback_days()
    wk = workers if workers is not None else pull_workers()
    do_score = (not skip_score) and score_cycles_enabled()
    log.info(
        "wake start series=%s lookback=%s workers=%s backfill_local=%s "
        "score=%s trades_dir=%s package_root=%s",
        ser,
        lb,
        wk,
        backfill_local_months,
        do_score,
        TRADES_DIR,
        package_root(),
    )
    if backfill_local_months:
        archives = [] if skip_package else package_all_local_months(ser)
        failed: list[str] = []
        if not skip_results:
            months = {(y, m) for _, y, m in local_months_with_day_csvs(ser)}
            for s in ser:
                failed.extend(refresh_market_results(s, months))
            if not skip_package:
                archives = package_all_local_months(ser)
    else:
        archives, failed = catchup_and_package(
            ser,
            lookback=lb,
            workers=wk,
            skip_trades=skip_trades,
            skip_results=skip_results,
            skip_package=skip_package,
        )
    scored = 0
    if do_score:
        from backend.core.tail_backtest_cycles import score_lookback_for_sync

        try:
            scored, score_failed = score_lookback_for_sync(
                ser, lookback_days=lb, root=TRADES_DIR
            )
            failed.extend(score_failed)
            log.info("tail_backtest_cycles upserted=%s", scored)
        except Exception as e:
            log.exception("tail_backtest_cycles scoring failed")
            failed.append(f"score:fatal:{e}")
    ok = True
    if not skip_upload:
        ok = upload_archives(archives, dry_run=dry_run_upload)
    if failed:
        log.warning("failures=%s", failed)
    log.info(
        "wake done archives=%s scored=%s upload_ok=%s failures=%s",
        len(archives),
        scored,
        ok,
        len(failed),
    )
    if failed or not ok:
        return 1
    return 0
