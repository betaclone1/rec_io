"""
Hourly packager: closed cycle hot tables → xz tar under backtesting_data.

Layout (per series):
  backend/data/historical_data/backtesting_data/{SERIES}/{YYYY}/{YYYY_MM_MON}/{TICKER}.tar.xz

Each archive contains:
  meta.json
  market_meta.json   (floor_strike, market_result, …)
  snapshot.csv
  deltas.csv
  strike_table.csv
  price_ring.csv
  metrics_ring.csv

Drops PG tables only after a successful write + quality gate + member verification.
Incomplete cycles are left in PG for the next pass (no silent empty packages).
"""

from __future__ import annotations

import io
import json
import logging
import os
import tarfile
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

logger = logging.getLogger("cycle_packager")

_UTC = timezone.utc
_EST = ZoneInfo("America/New_York")

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


def quality_gate(
    *,
    row_counts: Dict[str, int],
    market_meta: Dict[str, Any],
    force: bool = False,
) -> Tuple[bool, str]:
    """
    Require a usable cycle package. Incomplete captures stay in PG for retry.

    ``force`` bypasses the gate (ops / rebuild only).
    """
    if force:
        return True, "force"
    deltas = int(row_counts.get("deltas.csv", 0))
    price = int(row_counts.get("price_ring.csv", 0))
    strike = int(row_counts.get("strike_table.csv", 0))
    if deltas <= 0:
        return False, "deltas empty"
    if price <= 0:
        return False, "price_ring empty"
    if strike <= 0:
        return False, "strike_table empty"
    if market_meta.get("floor_strike") is None:
        return False, "floor_strike missing"
    if not market_meta.get("market_result"):
        return False, "market_result missing"
    return True, "ok"


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
                tables = meta_obj.get("tables") or {}
                counts = {k: int((v or {}).get("rows") or 0) for k, v in tables.items()}
                mm_f = tar.extractfile("market_meta.json") if "market_meta.json" in names else None
                mm = json.loads(mm_f.read().decode()) if mm_f else {}
            ok, reason = quality_gate(row_counts=counts, market_meta=mm, force=False)
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
    meta: Dict[str, Any] = {
        "market_ticker": mt,
        "series": series,
        "schema": _SCHEMA,
        "schema_version": 2,
        "packaged_at_utc": datetime.now(_UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "cycle_open_utc": win[0].isoformat().replace("+00:00", "Z") if win else None,
        "cycle_close_utc": win[1].isoformat().replace("+00:00", "Z") if win else None,
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

        row_counts = {k: int(v["rows"]) for k, v in meta["tables"].items()}
        ok, reason = quality_gate(
            row_counts=row_counts, market_meta=market_meta, force=force
        )
        if not ok:
            logger.warning(
                "skip package %s — quality gate failed: %s (counts=%s meta=%s)",
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
) -> List[Path]:
    """Package every DB-resident enabled 15m cycle past close+grace that passes the gate."""
    tickers = list_hot_cycle_tickers_in_db()
    done: List[Path] = []
    for mt in tickers:
        if not force and not is_cycle_ready_to_package(mt):
            continue
        path = package_ticker(mt, drop_after=drop_after, force=force)
        if path is not None:
            done.append(path)
    if done:
        try:
            from backend.core.cycle_gdrive_upload import (
                upload_cycle_packages_best_effort,
            )

            upload_cycle_packages_best_effort(done)
        except Exception as e:
            logger.exception("gdrive post-package hook failed: %s", e)
    return done