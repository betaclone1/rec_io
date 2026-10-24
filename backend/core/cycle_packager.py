"""
Hourly packager: closed cycle hot tables → xz tar under backtesting_data.

Layout (per series):
  backend/data/historical_data/backtesting_data/{SERIES}/{YYYY}/{YYYY_MM_MON}/{TICKER}.tar.xz

Each archive contains (schema_version 4):
  meta.json              (variant=full, proprietary_members listed)
  market_meta.json       (floor/result + venue fields at seal)
  snapshot.csv / deltas.csv
  strike_table.csv       (PROPRIETARY — model probs / fair)
  price_ring.csv         (underlying index; shareable)
  metrics_ring.csv       (PROPRIETARY — momentum/vol profile)
  public_trades.csv      (Kalshi public tape)
  volume_path.csv        (cum tape volume vs time)
  quality.json           (capture QA footer)

External SKU: derive after the fact via
``backend.core.cycle_package_members.export_external_variant``.

Drops PG tables only after a successful write + quality gate + member verification.
Incomplete cycles stay in PG and are retried on every packager wake (and within
the same wake via multi-pass). Never abandon a cycle because of transient API
delay, 429, or empty live OB capture when tape + settlement are still pending
or recoverable from Kalshi.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from backend.core.cycle_hot_tables import (
    _SCHEMA,
    _qualified,
    all_table_names,
    cycle_window_utc,
    drop_cycle_tables,
    list_hot_cycle_tickers_in_db,
    market_meta_table_name,
    parse_cycle_ticker_end_est,
    series_from_ticker,
)
from backend.core.cycle_package_members import (
    PROPRIETARY_MEMBERS,
    build_quality_report,
    enrich_market_meta_from_api,
    member_classification,
    volume_path_csv_bytes,
)

logger = logging.getLogger("cycle_packager")

_UTC = timezone.utc
_EST = ZoneInfo("America/New_York")

# Legacy: v2 no public_trades; v3 +public_trades; v4 +volume_path +quality +meta tags.
PACKAGE_SCHEMA_VERSION = 4

_PUBLIC_TRADES_PREFERRED_COLS = (
    "trade_id",
    "ticker",
    "created_time",
    "taker_side",
    "taker_outcome_side",
    "taker_book_side",
    "yes_price",
    "no_price",
    "yes_price_dollars",
    "no_price_dollars",
    "count",
    "count_fp",
    "is_block_trade",
    "ts",
)

_MONTH_ABBR = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


def package_root() -> Path:
    """``backend/data/historical_data/backtesting_data`` under project root."""
    env = (
        os.getenv("CYCLE_PACKAGE_ROOT")
        or os.getenv("BTC15M_CYCLE_PACKAGE_ROOT")
        or ""
    ).strip()
    if env:
        return Path(env).expanduser().resolve()
    repo = Path(__file__).resolve().parents[2]
    return repo / "backend" / "data" / "historical_data" / "backtesting_data"


def month_folder(end_est: datetime) -> Tuple[str, str]:
    """Return ``(year_str, YYYY_MM_MON)`` from cycle end Eastern time.

    Example: ``("2026", "2026_07_JUL")``.
    """
    year = f"{end_est.year:04d}"
    month = f"{year}_{end_est.month:02d}_{_MONTH_ABBR[end_est.month - 1]}"
    return year, month


def package_dir_for_ticker(market_ticker: str) -> Optional[Path]:
    end = parse_cycle_ticker_end_est(market_ticker)
    series = series_from_ticker(market_ticker)
    if end is None or series is None:
        return None
    year, month = month_folder(end)
    return package_root() / series / year / month


def package_path_for_ticker(market_ticker: str) -> Optional[Path]:
    d = package_dir_for_ticker(market_ticker)
    if d is None:
        return None
    return d / f"{str(market_ticker).strip()}.tar.xz"


def _grace_sec() -> float:
    try:
        raw = (
            os.getenv("CYCLE_PACKAGE_GRACE_SEC")
            or os.getenv("BTC15M_CYCLE_PACKAGE_GRACE_SEC")
            or "300"
        )
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 300.0


def _due_max_passes() -> int:
    """How many seal attempts per wake for tickers that deferred (API lag / 429)."""
    try:
        raw = (
            os.getenv("CYCLE_PACKAGE_MAX_PASSES")
            or os.getenv("BTC15M_CYCLE_PACKAGE_MAX_PASSES")
            or "8"
        )
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 8


def _due_pass_pause_sec() -> float:
    try:
        raw = (
            os.getenv("CYCLE_PACKAGE_PASS_PAUSE_SEC")
            or os.getenv("BTC15M_CYCLE_PACKAGE_PASS_PAUSE_SEC")
            or "20"
        )
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 20.0


def _system_conn():
    from backend.core.config.database import get_system_postgresql_connection

    return get_system_postgresql_connection()


def _copy_table_csv(cur, table: str) -> bytes:
    buf = io.StringIO()
    cur.copy_expert(
        f"COPY {_qualified(table)} TO STDOUT WITH (FORMAT csv, HEADER true)",
        buf,
    )
    return buf.getvalue().encode("utf-8")


def _table_row_count(cur, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {_qualified(table)}")
    return int(cur.fetchone()[0])


def _jsonable_floor_strike(v: Any) -> Optional[str]:
    """Exact API decimal text for packages — never float/int round."""
    from backend.core.kalshi_market_normalize import exact_decimal_text

    return exact_decimal_text(v)


def _read_market_meta_row(cur, market_ticker: str) -> Dict[str, Any]:
    tbl = market_meta_table_name(market_ticker)
    cur.execute(
        f"""
        SELECT market_ticker, floor_strike, volume_fp, market_result, updated_at
        FROM {_qualified(tbl)}
        WHERE market_ticker = %s
        LIMIT 1
        """,
        (str(market_ticker).strip().upper(),),
    )
    row = cur.fetchone()
    if not row:
        return {
            "market_ticker": str(market_ticker).strip(),
            "floor_strike": None,
            "volume_fp": None,
            "market_result": None,
            "updated_at": None,
        }
    return {
        "market_ticker": row[0],
        "floor_strike": _jsonable_floor_strike(row[1]),
        "volume_fp": row[2],
        "market_result": row[3],
        "updated_at": row[4],
    }


def _enrich_market_result_from_redis(market_meta: Dict[str, Any]) -> None:
    """Fill market_result from Kalshi WS settled registry when still NULL (same source)."""
    if market_meta.get("market_result"):
        return
    mt = str(market_meta.get("market_ticker") or "").strip()
    if not mt:
        return
    try:
        import redis as redis_mod

        from backend.core.market_watchdog.config import load_config

        cfg = load_config(exchange="kalshi", market_interval="all")
        url = os.getenv("REDIS_URL", "").strip()
        if url:
            r = redis_mod.from_url(url, decode_responses=True)
        else:
            r = redis_mod.Redis(
                host=os.getenv("REDIS_HOST", "127.0.0.1"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=True,
            )
        raw = r.get(cfg.settled_redis_key)
        if not raw:
            return
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict) and data.get(mt):
            market_meta["market_result"] = str(data[mt]).strip().lower()
            market_meta["market_result_source"] = f"redis:{cfg.settled_redis_key}"
    except Exception as e:
        logger.debug("settled redis lookup failed %s: %s", mt, e)


def public_trades_to_csv_bytes(trades: List[Dict[str, Any]]) -> bytes:
    """Serialize Kalshi public Trade objects to CSV bytes (UTF-8)."""
    if not trades:
        header = ",".join(_PUBLIC_TRADES_PREFERRED_COLS) + "\n"
        return header.encode("utf-8")
    keys: List[str] = []
    seen: set[str] = set()
    for k in _PUBLIC_TRADES_PREFERRED_COLS:
        if any(k in r for r in trades):
            keys.append(k)
            seen.add(k)
    for r in trades:
        for k in r.keys():
            if k not in seen:
                keys.append(k)
                seen.add(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    w.writeheader()
    for r in sorted(
        trades,
        key=lambda row: (
            str(row.get("created_time") or ""),
            str(row.get("trade_id") or ""),
        ),
    ):
        w.writerow({k: r.get(k, "") for k in keys})
    return buf.getvalue().encode("utf-8")


def fetch_public_trades_csv_for_package(
    market_ticker: str,
    *,
    force_refresh: bool = True,
    attempts: int = 8,
) -> Tuple[Optional[bytes], int, Optional[str], List[Dict[str, Any]]]:
    """
    Fetch Kalshi public tape for ``market_ticker``.

    Returns ``(csv_bytes, row_count, error, trades)``.
    Retries transient API failures. On exhaustion returns
    ``(None, 0, reason, [])`` — caller must not seal a substitute; leave hot
    tables and retry on the next pass. Never invent tape rows.
    """
    import time

    from backend.core.cycle_recon.sources import fetch_public_trades

    last_err: Optional[str] = None
    for i in range(max(1, int(attempts))):
        try:
            res = fetch_public_trades(
                market_ticker,
                force_refresh=force_refresh,
                offline=False,
            )
        except Exception as e:
            last_err = f"public_trades fetch error: {e}"
            logger.warning(
                "public_trades attempt %s/%s failed %s: %s",
                i + 1,
                attempts,
                market_ticker,
                e,
            )
            time.sleep(min(60.0, 2.0 * (2 ** min(i, 4))))
            continue
        if not res.complete:
            last_err = "public_trades fetch incomplete"
            logger.warning(
                "public_trades incomplete attempt %s/%s %s",
                i + 1,
                attempts,
                market_ticker,
            )
            time.sleep(min(60.0, 2.0 * (2 ** min(i, 4))))
            continue
        trades = list(res.trades or [])
        raw = public_trades_to_csv_bytes(trades)
        return raw, len(trades), None, trades
    return None, 0, last_err or "public_trades fetch failed", []


def quality_gate(
    *,
    row_counts: Dict[str, int],
    market_meta: Dict[str, Any],
    force: bool = False,
    require_public_trades: bool = True,
    require_v4_members: bool = False,
) -> Tuple[bool, str]:
    """
    Hard seal requirements (API-recoverable / settlement truth):

    - ``floor_strike`` and ``market_result`` from venue
    - ``public_trades.csv`` member present (tape may be empty but fetch must succeed)
    - v4: ``volume_path.csv`` + ``quality.json`` members present

    Live-capture gaps (empty deltas / strike / price_ring) are recorded in
    ``quality.json`` as DEGRADED — they must **not** permanently block seal.
    Otherwise transient capture holes + rate limits leave months of tape unusable.
    Incomplete *API* fields still fail the gate so the next packager pass retries.
    """
    if force:
        return True, "force"
    if market_meta.get("floor_strike") is None:
        return False, "floor_strike missing"
    if not market_meta.get("market_result"):
        return False, "market_result missing"
    if require_public_trades and "public_trades.csv" not in row_counts:
        return False, "public_trades missing"
    if require_v4_members:
        if "volume_path.csv" not in row_counts:
            return False, "volume_path missing"
        if "quality.json" not in row_counts:
            return False, "quality.json missing"
    return True, "ok"


def _existing_package_complete(
    *,
    names: set[str],
    meta_obj: Dict[str, Any],
    market_meta: Dict[str, Any],
) -> Tuple[bool, str]:
    """Validate an on-disk package; older schema versions keep their original gate."""
    tables = meta_obj.get("tables") or {}
    counts = {k: int((v or {}).get("rows") or 0) for k, v in tables.items()}
    try:
        sv = int(meta_obj.get("schema_version") or 0)
    except (TypeError, ValueError):
        sv = 0
    require_pt = sv >= 3
    require_v4 = sv >= 4
    if require_pt and "public_trades.csv" not in names:
        return False, "public_trades member missing"
    if require_v4 and "volume_path.csv" not in names:
        return False, "volume_path member missing"
    if require_v4 and "quality.json" not in names:
        return False, "quality.json member missing"
    return quality_gate(
        row_counts=counts,
        market_meta=market_meta,
        force=False,
        require_public_trades=require_pt,
        require_v4_members=require_v4,
    )


def is_cycle_ready_to_package(
    market_ticker: str,
    *,
    now: Optional[datetime] = None,
    grace_sec: Optional[float] = None,
) -> bool:
    win = cycle_window_utc(market_ticker)
    if win is None:
        return False
    _, close_u = win
    now_u = now or datetime.now(_UTC)
    if now_u.tzinfo is None:
        now_u = now_u.replace(tzinfo=_UTC)
    else:
        now_u = now_u.astimezone(_UTC)
    g = _grace_sec() if grace_sec is None else grace_sec
    return now_u >= (close_u + timedelta(seconds=g))


def package_ticker(
    market_ticker: str,
    *,
    drop_after: bool = True,
    force: bool = False,
) -> Optional[Path]:
    """
    Export one ticker's hot tables to ``.tar.xz``. Returns path on success.

    Skips if a *complete* package already exists (unless ``force``).
    Drops PG tables only after quality gate + verify when ``drop_after``.
    """
    mt = str(market_ticker).strip()
    out = package_path_for_ticker(mt)
    if out is None:
        logger.warning("cannot resolve package path for %s", mt)
        return None
    if out.exists() and not force:
        # Do not drop hot tables based on a prior incomplete artifact.
        try:
            with tarfile.open(out, "r:xz") as tar:
                names = set(tar.getnames())
                meta_f = tar.extractfile("meta.json")
                meta_obj = json.loads(meta_f.read().decode()) if meta_f else {}
                mm_f = tar.extractfile("market_meta.json") if "market_meta.json" in names else None
                mm = json.loads(mm_f.read().decode()) if mm_f else {}
            ok, reason = _existing_package_complete(
                names=names, meta_obj=meta_obj, market_meta=mm
            )
            if ok:
                logger.info("complete package already exists %s — skipping", out)
                if drop_after:
                    drop_cycle_tables(mt)
                return out
            logger.warning(
                "existing package incomplete (%s) %s — will rebuild when data ready",
                reason,
                out,
            )
        except Exception as e:
            logger.warning("could not validate existing package %s: %s", out, e)

    if not force and not is_cycle_ready_to_package(mt):
        logger.debug("cycle not ready %s", mt)
        return None

    snap, deltas, strike, price, metrics, _meta_tbl = all_table_names(mt)
    table_csv = (
        (snap, "snapshot.csv"),
        (deltas, "deltas.csv"),
        (strike, "strike_table.csv"),
        (price, "price_ring.csv"),
        (metrics, "metrics_ring.csv"),
    )
    conn = _system_conn()
    if conn is None:
        logger.error("no PG connection for package %s", mt)
        return None

    end_est = parse_cycle_ticker_end_est(mt)
    win = cycle_window_utc(mt)
    series = series_from_ticker(mt) or mt.split("-", 1)[0]
    open_utc = win[0] if win else None
    close_utc = win[1] if win else None
    meta: Dict[str, Any] = {
        "market_ticker": mt,
        "series": series,
        "schema": _SCHEMA,
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "variant": "full",
        "proprietary_members": list(PROPRIETARY_MEMBERS),
        "member_classification": member_classification(),
        "packaged_at_utc": datetime.now(_UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "cycle_open_utc": open_utc.isoformat().replace("+00:00", "Z") if open_utc else None,
        "cycle_close_utc": close_utc.isoformat().replace("+00:00", "Z")
        if close_utc
        else None,
        "cycle_close_est": end_est.isoformat() if end_est else None,
        "tables": {},
    }

    try:
        members: Dict[str, bytes] = {}
        with conn.cursor() as cur:
            for table, csv_name in table_csv:
                try:
                    raw = _copy_table_csv(cur, table)
                    n = _table_row_count(cur, table)
                except Exception as e:
                    conn.rollback()
                    logger.warning("COPY failed %s.%s: %s", _SCHEMA, table, e)
                    raw = b""
                    n = 0
                members[csv_name] = raw
                meta["tables"][csv_name] = {"rows": n, "bytes": len(raw)}

            try:
                market_meta = _read_market_meta_row(cur, mt)
            except Exception as e:
                conn.rollback()
                logger.warning("market_meta read failed %s: %s", mt, e)
                market_meta = {
                    "market_ticker": mt,
                    "floor_strike": None,
                    "volume_fp": None,
                    "market_result": None,
                    "updated_at": None,
                }

        _enrich_market_result_from_redis(market_meta)
        enrich_market_meta_from_api(market_meta)

        # Public tape is not in PG hot tables — fetch at seal time (authoritative API).
        pt_bytes, pt_rows, pt_err, trades = fetch_public_trades_csv_for_package(
            mt, force_refresh=True
        )
        if pt_bytes is None:
            logger.warning(
                "defer package %s — public_trades unavailable (will retry): %s",
                mt,
                pt_err or "unknown",
            )
            return None
        members["public_trades.csv"] = pt_bytes
        meta["tables"]["public_trades.csv"] = {"rows": pt_rows, "bytes": len(pt_bytes)}

        vol_bytes, vol_rows = volume_path_csv_bytes(
            trades, open_utc=open_utc, close_utc=close_utc
        )
        members["volume_path.csv"] = vol_bytes
        meta["tables"]["volume_path.csv"] = {"rows": vol_rows, "bytes": len(vol_bytes)}

        delta_rows = list(
            csv.DictReader(io.StringIO(members["deltas.csv"].decode("utf-8", errors="replace")))
        )
        price_rows = list(
            csv.DictReader(
                io.StringIO(members["price_ring.csv"].decode("utf-8", errors="replace"))
            )
        )
        row_counts = {k: int(v["rows"]) for k, v in meta["tables"].items()}
        quality = build_quality_report(
            row_counts=row_counts,
            market_meta=market_meta,
            deltas=delta_rows,
            price_rows=price_rows,
            open_utc=open_utc,
            close_utc=close_utc,
        )
        # Live OB/strike holes are capture gaps — seal tape+settlement anyway,
        # but mark DEGRADED so operators can see what was missing.
        if int(row_counts.get("deltas.csv", 0) or 0) <= 0:
            quality["status"] = "DEGRADED"
            notes = list(quality.get("notes") or [])
            notes.append("deltas empty (live capture gap; sealed without OB)")
            quality["notes"] = notes
        if int(row_counts.get("strike_table.csv", 0) or 0) <= 0:
            quality["status"] = "DEGRADED"
            notes = list(quality.get("notes") or [])
            notes.append("strike_table empty (live capture gap)")
            quality["notes"] = notes
        if int(row_counts.get("price_ring.csv", 0) or 0) <= 0:
            quality["status"] = "DEGRADED"
            notes = list(quality.get("notes") or [])
            notes.append("price_ring empty (live capture gap)")
            quality["notes"] = notes
        q_bytes = (json.dumps(quality, indent=2, sort_keys=True) + "\n").encode("utf-8")
        members["quality.json"] = q_bytes
        meta["tables"]["quality.json"] = {
            "rows": 1 if quality else 0,
            "bytes": len(q_bytes),
            "status": quality.get("status"),
        }
        row_counts = {k: int(v["rows"]) for k, v in meta["tables"].items()}

        ok, reason = quality_gate(
            row_counts=row_counts,
            market_meta=market_meta,
            force=force,
            require_public_trades=True,
            require_v4_members=True,
        )
        if not ok:
            logger.warning(
                "defer package %s — quality gate failed (will retry): %s (counts=%s meta=%s)",
                mt,
                reason,
                row_counts,
                {
                    "floor_strike": market_meta.get("floor_strike"),
                    "market_result": market_meta.get("market_result"),
                },
            )
            return None

        meta["floor_strike"] = market_meta.get("floor_strike")
        meta["market_result"] = market_meta.get("market_result")
        meta["quality_status"] = quality.get("status")
        members["market_meta.json"] = (
            json.dumps(market_meta, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        members["meta.json"] = (
            json.dumps(meta, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out.with_suffix(out.suffix + ".tmp")
        if tmp_path.exists():
            tmp_path.unlink()

        with tarfile.open(tmp_path, "w:xz", preset=6) as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mtime = int(datetime.now(_UTC).timestamp())
                tar.addfile(info, io.BytesIO(data))

        with tarfile.open(tmp_path, "r:xz") as tar:
            got = set(tar.getnames())
        expected = set(members.keys())
        if got != expected:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"package member mismatch got={got} expected={expected}")

        tmp_path.replace(out)
        logger.info(
            "packaged %s -> %s (%.1f KB)",
            mt,
            out,
            out.stat().st_size / 1024.0,
        )

        if drop_after:
            drop_cycle_tables(mt, conn)
        return out
    except Exception as e:
        logger.exception("package failed %s: %s", mt, e)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def package_due_cycles(
    *,
    drop_after: bool = True,
    force: bool = False,
    max_passes: Optional[int] = None,
    pass_pause_sec: Optional[float] = None,
) -> List[Path]:
    """
    Package every DB-resident enabled 15m cycle past close+grace.

    Deferred seals (missing settlement, public_trades 429, etc.) stay pending and
    are retried within this call for ``max_passes`` rounds — never dropped from the
    backlog. Hot tables remain until a successful seal.
    """
    passes = _due_max_passes() if max_passes is None else max(1, int(max_passes))
    pause = _due_pass_pause_sec() if pass_pause_sec is None else max(0.0, float(pass_pause_sec))
    pending = [
        mt
        for mt in list_hot_cycle_tickers_in_db()
        if force or is_cycle_ready_to_package(mt)
    ]
    done: List[Path] = []
    done_tickers: set[str] = set()

    for pass_i in range(passes):
        if not pending:
            break
        still: List[str] = []
        sealed_this_pass = 0
        for mt in pending:
            path = package_ticker(mt, drop_after=drop_after, force=force)
            if path is not None:
                key = str(mt).strip().upper()
                if key not in done_tickers:
                    done_tickers.add(key)
                    done.append(path)
                sealed_this_pass += 1
            else:
                still.append(mt)
        logger.info(
            "package_due_cycles pass %s/%s: sealed=%s deferred=%s",
            pass_i + 1,
            passes,
            sealed_this_pass,
            len(still),
        )
        pending = still
        if pending and pass_i + 1 < passes and pause > 0:
            logger.info(
                "deferring %s cycle(s) — sleeping %.0fs before retry pass",
                len(pending),
                pause,
            )
            time.sleep(pause)

    if pending:
        logger.warning(
            "package_due_cycles still deferred after %s pass(es): %s — will retry next wake",
            passes,
            pending,
        )

    if done:
        try:
            from backend.core.cycle_gdrive_upload import (
                upload_cycle_packages_best_effort,
            )

            upload_cycle_packages_best_effort(done)
        except Exception as e:
            logger.exception("gdrive post-package hook failed: %s", e)
    return done