from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from backend.core.cycle_hot_tables import parse_cycle_ticker_end_est, series_from_ticker
from backend.core.cycle_packager import month_folder, package_path_for_ticker, package_root
from backend.core.cycle_recon.hashing import sha256_bytes, sha256_file
from backend.core.cycle_recon.time_util import to_iso_z

DEFAULT_DRIVE_BACKTESTING = Path(
    "/Users/ericwais1/Library/CloudStorage/GoogleDrive-eric@rec-io.com/"
    "My Drive/DATA/HISTORICAL_DATA/BACKTESTING_DATA"
)

KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
MARKETS_TRADES_PATH = "/markets/trades"


@dataclass
class ArchiveLocateResult:
    ticker: str
    path: Optional[Path]
    source: Optional[str]  # local | drive_copy | drive_mount | missing
    sha256: Optional[str]
    bytes: Optional[int]
    reason: Optional[str] = None


def default_package_roots() -> List[Path]:
    roots: List[Path] = []
    env = (os.environ.get("CYCLE_PACKAGE_ROOT") or os.environ.get("BTC15M_CYCLE_PACKAGE_ROOT") or "").strip()
    if env:
        roots.append(Path(env).expanduser().resolve())
    try:
        roots.append(Path(package_root()).resolve())
    except Exception:
        roots.append(
            Path(__file__).resolve().parents[2]
            / "data"
            / "historical_data"
            / "backtesting_data"
        )
    out: List[Path] = []
    seen = set()
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def relative_package_path(ticker: str) -> Optional[Path]:
    """Return SERIES/YYYY/YYYY_MM_MON/TICKER.tar.xz relative path."""
    end = parse_cycle_ticker_end_est(ticker)
    series = series_from_ticker(ticker)
    if end is None or series is None:
        return None
    year, month = month_folder(end)
    return Path(series) / year / month / f"{str(ticker).strip()}.tar.xz"


def locate_package(
    ticker: str,
    *,
    local_roots: Optional[List[Path]] = None,
    drive_root: Optional[Path] = None,
    copy_from_drive: bool = True,
) -> ArchiveLocateResult:
    """
    Find a sealed .tar.xz for ticker. Prefer local cache; optionally copy from mounted Drive.
    Never mutates Drive content.
    """
    t = str(ticker).strip()

    try:
        p = package_path_for_ticker(t)
        if p is not None and p.is_file():
            digest = sha256_file(p)
            return ArchiveLocateResult(
                ticker=t, path=p, source="local", sha256=digest, bytes=p.stat().st_size
            )
    except Exception:
        pass

    rel = relative_package_path(t)
    if rel is None:
        return ArchiveLocateResult(
            ticker=t, path=None, source="missing", sha256=None, bytes=None, reason="BAD_TICKER"
        )

    roots = local_roots or default_package_roots()
    for root in roots:
        candidate = root / rel
        if candidate.is_file():
            digest = sha256_file(candidate)
            return ArchiveLocateResult(
                ticker=t,
                path=candidate,
                source="local",
                sha256=digest,
                bytes=candidate.stat().st_size,
            )

    drive = drive_root if drive_root is not None else DEFAULT_DRIVE_BACKTESTING
    if drive.is_dir():
        src = drive / rel
        if src.is_file():
            if not copy_from_drive:
                digest = sha256_file(src)
                return ArchiveLocateResult(
                    ticker=t,
                    path=src,
                    source="drive_mount",
                    sha256=digest,
                    bytes=src.stat().st_size,
                )
            dest_root = roots[0]
            dest = dest_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            tmp = dest.with_suffix(dest.suffix + ".partial")
            tmp.write_bytes(data)
            tmp.replace(dest)
            digest = sha256_file(dest)
            return ArchiveLocateResult(
                ticker=t,
                path=dest,
                source="drive_copy",
                sha256=digest,
                bytes=dest.stat().st_size,
            )

    return ArchiveLocateResult(
        ticker=t,
        path=None,
        source="missing",
        sha256=None,
        bytes=None,
        reason="ARCHIVE_NOT_FOUND",
    )


@dataclass
class PublicTradesFetchResult:
    ticker: str
    trades: List[Dict[str, Any]]
    cache_path: Path
    cache_hit: bool
    complete: bool
    pages: int
    meta: Dict[str, Any]


def _cache_dir() -> Path:
    env = (os.environ.get("CYCLE_RECON_CACHE") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (
        Path(__file__).resolve().parents[2]
        / "data"
        / "historical_data"
        / "cycle_recon_cache"
        / "kalshi_trades"
    )


def public_trades_cache_path(ticker: str, *, endpoint: str = "markets") -> Path:
    safe = str(ticker).strip().replace("/", "_")
    return _cache_dir() / endpoint / f"{safe}.json"


def fetch_public_trades(
    ticker: str,
    *,
    force_refresh: bool = False,
    offline: bool = False,
    min_ts: Optional[int] = None,
    max_ts: Optional[int] = None,
    limit: int = 1000,
    sleep_s: float = 0.05,
    timeout_s: float = 30.0,
) -> PublicTradesFetchResult:
    """
    Fully paginate Kalshi public markets/trades for one ticker.
    Caches raw JSON locally. Offline mode requires a complete cache.
    """
    cache_path = public_trades_cache_path(ticker)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.is_file() and not force_refresh:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        if raw.get("complete"):
            trades = list(raw.get("trades") or [])
            if min_ts is not None or max_ts is not None:
                trades = _filter_trades_ts(trades, min_ts, max_ts)
            return PublicTradesFetchResult(
                ticker=ticker,
                trades=trades,
                cache_path=cache_path,
                cache_hit=True,
                complete=True,
                pages=int(raw.get("pages") or 0),
                meta={
                    "fetched_at": raw.get("fetched_at"),
                    "sha256": raw.get("sha256"),
                    "endpoint": raw.get("endpoint"),
                    "raw_trade_count": len(raw.get("trades") or []),
                },
            )
        if offline:
            return PublicTradesFetchResult(
                ticker=ticker,
                trades=list(raw.get("trades") or []),
                cache_path=cache_path,
                cache_hit=True,
                complete=False,
                pages=int(raw.get("pages") or 0),
                meta={"reason": "API_CACHE_INCOMPLETE_OFFLINE", "fetched_at": raw.get("fetched_at")},
            )

    if offline:
        raise FileNotFoundError(f"offline cache miss for {ticker}: {cache_path}")

    trades: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    pages = 0
    while True:
        params: Dict[str, Any] = {"ticker": ticker, "limit": min(int(limit), 1000)}
        if cursor:
            params["cursor"] = cursor
        if min_ts is not None:
            params["min_ts"] = int(min_ts)
        if max_ts is not None:
            params["max_ts"] = int(max_ts)
        url = f"{KALSHI_BASE}{MARKETS_TRADES_PATH}?{urlencode(params)}"
        resp = _request_with_retry(url, timeout_s=timeout_s)
        pages += 1
        body = resp.json()
        batch = body.get("trades") or []
        if not isinstance(batch, list):
            batch = []
        trades.extend(batch)
        cursor = body.get("cursor") or None
        if not cursor or not batch:
            break
        if sleep_s > 0:
            time.sleep(sleep_s)

    payload = {
        "ticker": ticker,
        "endpoint": "markets/trades",
        "fetched_at": to_iso_z(datetime.now(timezone.utc)),
        "pages": pages,
        "complete": True,
        "trades": trades,
    }
    blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload["sha256"] = sha256_bytes(blob)
    tmp = cache_path.with_suffix(".partial.json")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(cache_path)

    return PublicTradesFetchResult(
        ticker=ticker,
        trades=trades,
        cache_path=cache_path,
        cache_hit=False,
        complete=True,
        pages=pages,
        meta={
            "fetched_at": payload["fetched_at"],
            "sha256": payload["sha256"],
            "endpoint": payload["endpoint"],
            "raw_trade_count": len(trades),
        },
    )


def _filter_trades_ts(
    trades: List[Dict[str, Any]], min_ts: Optional[int], max_ts: Optional[int]
) -> List[Dict[str, Any]]:
    out = []
    for t in trades:
        ts = t.get("ts")
        if ts is None and t.get("created_time"):
            from backend.core.cycle_recon.time_util import parse_utc

            try:
                ts = int(parse_utc(t["created_time"]).timestamp())
            except Exception:
                ts = None
        if ts is None:
            out.append(t)
            continue
        ts_i = int(ts)
        if min_ts is not None and ts_i < min_ts:
            continue
        if max_ts is not None and ts_i > max_ts:
            continue
        out.append(t)
    return out


def _request_with_retry(url: str, *, timeout_s: float, attempts: int = 5) -> requests.Response:
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            resp = requests.get(url, timeout=timeout_s)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(min(8.0, 0.5 * (2**i)))
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            last = e
            time.sleep(min(8.0, 0.5 * (2**i)))
    raise RuntimeError(f"Kalshi trades fetch failed for {url}: {last}")
