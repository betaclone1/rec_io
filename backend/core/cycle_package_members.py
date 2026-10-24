"""
Cycle package member helpers: classification, volume path, quality, market enrich, export.

Sealed archives are always ``variant=full``. External SKUs are derived after the fact
by omitting ``PROPRIETARY_MEMBERS``.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger("cycle_package_members")

_UTC = timezone.utc

# Model / internal — strip for external (sellable) SKU.
PROPRIETARY_MEMBERS: Tuple[str, ...] = (
    "strike_table.csv",
    "metrics_ring.csv",
)

# Always retained in full + external variants (venue capture + underlying + QA).
SHAREABLE_CORE_MEMBERS: Tuple[str, ...] = (
    "meta.json",
    "market_meta.json",
    "snapshot.csv",
    "deltas.csv",
    "price_ring.csv",
    "public_trades.csv",
    "volume_path.csv",
    "quality.json",
)

_MARKET_META_API_KEYS = (
    "open_time",
    "close_time",
    "created_time",
    "expiration_time",
    "open_interest_fp",
    "open_interest",
    "volume_fp",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "yes_bid_dollars",
    "yes_ask_dollars",
    "no_bid_dollars",
    "no_ask_dollars",
    "last_price",
    "last_price_dollars",
    "status",
    "title",
    "event_ticker",
    "settlement_ts",
    "settled_time",
    "result",
)


def _parse_ts(raw: Any) -> Optional[datetime]:
    s = str(raw or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def enrich_market_meta_from_api(
    market_meta: Dict[str, Any],
    *,
    attempts: int = 12,
) -> None:
    """Merge selected Kalshi market fields into ``market_meta`` (in place).

    Retries on transient API failures. Venue settlement/floor are required for
    seal — keep trying rather than leaving NULLs after one 429.
    """
    import time

    mt = str(market_meta.get("market_ticker") or "").strip()
    if not mt:
        return
    try:
        from backend.core.kalshi_event_market_fetch import (
            fetch_market_payload,
            normalize_market_result_field,
        )
    except Exception as e:
        logger.debug("market enrich import failed: %s", e)
        return

    last_err: Optional[BaseException] = None
    market: Any = None
    for i in range(max(1, int(attempts))):
        try:
            market = fetch_market_payload(mt)
            if isinstance(market, dict):
                break
            last_err = RuntimeError(f"non-dict market payload: {type(market)}")
        except Exception as e:
            last_err = e
            market = None
        time.sleep(min(60.0, 1.0 * (2 ** min(i, 5))))
    if not isinstance(market, dict):
        logger.warning(
            "market enrich fetch failed %s after %s attempts: %s",
            mt,
            attempts,
            last_err,
        )
        return
    market_meta["venue_market_source"] = "kalshi_api"
    # Floor strike is required for seal; fill from venue when hot meta is still NULL.
    if market_meta.get("floor_strike") in (None, ""):
        from backend.core.kalshi_market_normalize import exact_decimal_text

        exact_fs = exact_decimal_text(market.get("floor_strike"))
        if exact_fs is not None:
            market_meta["floor_strike"] = exact_fs
            market_meta["floor_strike_source"] = "kalshi_api"
    for k in _MARKET_META_API_KEYS:
        if k not in market:
            continue
        v = market.get(k)
        if v in (None, ""):
            continue
        # Prefer existing volume_fp / market_result from hot tables when set.
        if k == "volume_fp" and market_meta.get("volume_fp") not in (None, ""):
            continue
        if k == "result":
            nr = normalize_market_result_field(v)
            if nr and not market_meta.get("market_result"):
                market_meta["market_result"] = nr
            continue
        market_meta[k] = v


def volume_path_csv_bytes(
    trades: Sequence[Dict[str, Any]],
    *,
    open_utc: Optional[datetime],
    close_utc: Optional[datetime],
) -> Tuple[bytes, int]:
    """
    Cumulative public-tape volume path.

    Emits one row per distinct trade second (and open/close anchors) with
    ``cum_count_fp`` / ``cum_trades``. OI is not fabricated — only seal-time OI
    lives on ``market_meta`` when the venue provides it.
    """
    events: List[Tuple[datetime, float]] = []
    for r in trades:
        ts = _parse_ts(r.get("created_time") or r.get("ts"))
        if ts is None:
            continue
        try:
            qty = float(r.get("count_fp") or r.get("count") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty < 0:
            qty = 0.0
        events.append((ts, qty))
    events.sort(key=lambda x: x[0])

    # Collapse to per-second increments then running cum.
    per_sec: Dict[datetime, float] = {}
    trade_counts: Dict[datetime, int] = {}
    for ts, qty in events:
        sec = ts.replace(microsecond=0)
        per_sec[sec] = per_sec.get(sec, 0.0) + qty
        trade_counts[sec] = trade_counts.get(sec, 0) + 1

    seconds = sorted(per_sec.keys())
    if open_utc is not None:
        o = open_utc.astimezone(_UTC).replace(microsecond=0)
        if o not in per_sec:
            seconds = [o] + seconds
    if close_utc is not None:
        c = close_utc.astimezone(_UTC).replace(microsecond=0)
        if c not in per_sec:
            seconds = seconds + [c]
    # unique preserve order
    seen: Set[datetime] = set()
    ordered: List[datetime] = []
    for s in seconds:
        if s in seen:
            continue
        seen.add(s)
        ordered.append(s)
    ordered.sort()

    buf = io.StringIO()
    w = csv.DictWriter(
        buf,
        fieldnames=["timestamp", "cum_count_fp", "cum_trades", "sec_count_fp", "sec_trades"],
    )
    w.writeheader()
    cum = 0.0
    cum_n = 0
    rows_out = 0
    for sec in ordered:
        inc = float(per_sec.get(sec, 0.0))
        n = int(trade_counts.get(sec, 0))
        cum += inc
        cum_n += n
        w.writerow(
            {
                "timestamp": sec.isoformat().replace("+00:00", "Z"),
                "cum_count_fp": f"{cum:.6f}".rstrip("0").rstrip(".")
                if cum
                else "0",
                "cum_trades": str(cum_n),
                "sec_count_fp": f"{inc:.6f}".rstrip("0").rstrip(".") if inc else "0",
                "sec_trades": str(n),
            }
        )
        rows_out += 1
    if rows_out == 0:
        w.writerow(
            {
                "timestamp": "",
                "cum_count_fp": "0",
                "cum_trades": "0",
                "sec_count_fp": "0",
                "sec_trades": "0",
            }
        )
        # header-only meaningful empty: still 0 data rows for gate
        text = buf.getvalue()
        # rewrite as header only
        return ("timestamp,cum_count_fp,cum_trades,sec_count_fp,sec_trades\n").encode(
            "utf-8"
        ), 0
    return buf.getvalue().encode("utf-8"), rows_out


def build_quality_report(
    *,
    row_counts: Dict[str, int],
    market_meta: Dict[str, Any],
    deltas: Sequence[Dict[str, Any]],
    price_rows: Sequence[Dict[str, Any]],
    open_utc: Optional[datetime],
    close_utc: Optional[datetime],
) -> Dict[str, Any]:
    """Lightweight capture QA — not a market-risk judgment."""
    notes: List[str] = []
    status = "COMPLETE"

    def _n(key: str) -> int:
        return int(row_counts.get(key, 0) or 0)

    checks = {
        "snapshot_rows": _n("snapshot.csv"),
        "deltas_rows": _n("deltas.csv"),
        "price_ring_rows": _n("price_ring.csv"),
        "strike_table_rows": _n("strike_table.csv"),
        "metrics_ring_rows": _n("metrics_ring.csv"),
        "public_trades_rows": _n("public_trades.csv"),
        "volume_path_rows": _n("volume_path.csv"),
    }

    # Expected ~900s for a 15m cycle price ring
    expected_secs = 900
    if open_utc and close_utc:
        expected_secs = max(
            1, int((close_utc.astimezone(_UTC) - open_utc.astimezone(_UTC)).total_seconds())
        )
    price_missing = max(0, expected_secs - checks["price_ring_rows"])
    if price_missing > 30:
        status = "DEGRADED"
        notes.append(f"price_ring short by ~{price_missing}s vs cycle window")

    seq_jumps = 0
    last_seq: Optional[int] = None
    for d in deltas:
        try:
            seq = int(d.get("seq"))
        except (TypeError, ValueError):
            continue
        if last_seq is not None and seq > last_seq + 1:
            seq_jumps += 1
        last_seq = seq
    if seq_jumps > 0:
        status = "DEGRADED"
        notes.append(f"delta seq jumps={seq_jumps}")

    if not market_meta.get("floor_strike"):
        status = "DEGRADED"
        notes.append("floor_strike missing")
    if not market_meta.get("market_result"):
        status = "DEGRADED"
        notes.append("market_result missing")

    return {
        "status": status,
        "checks": checks,
        "gaps": {
            "price_ring_missing_seconds_est": price_missing,
            "delta_seq_jumps": seq_jumps,
        },
        "notes": notes,
    }


def member_classification() -> Dict[str, List[str]]:
    return {
        "proprietary": list(PROPRIETARY_MEMBERS),
        "shareable_core": list(SHAREABLE_CORE_MEMBERS),
    }


def export_external_variant(
    src: Path | str,
    *,
    dest: Optional[Path | str] = None,
) -> Path:
    """
    Write an ``external`` SKU next to ``src`` (or ``dest``) by omitting proprietary members.

    Output name: ``{stem}.external.tar.xz`` when ``dest`` is None.
    """
    src_p = Path(src).expanduser().resolve()
    if not src_p.is_file():
        raise FileNotFoundError(src_p)
    dest_p = (
        Path(dest).expanduser().resolve()
        if dest
        else src_p.with_name(src_p.name.replace(".tar.xz", "") + ".external.tar.xz")
    )
    proprietary = set(PROPRIETARY_MEMBERS)

    with tarfile.open(src_p, "r:xz") as tin:
        members_data: Dict[str, bytes] = {}
        for info in tin.getmembers():
            if not info.isfile():
                continue
            name = Path(info.name).name
            if name in proprietary:
                continue
            f = tin.extractfile(info)
            if f is None:
                continue
            members_data[name] = f.read()

    meta = json.loads(members_data.get("meta.json", b"{}").decode("utf-8") or "{}")
    meta["variant"] = "external"
    meta["proprietary_members"] = list(PROPRIETARY_MEMBERS)
    meta["derived_from"] = src_p.name
    meta["exported_at_utc"] = (
        datetime.now(_UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )
    # Drop proprietary table stats if present
    tables = meta.get("tables")
    if isinstance(tables, dict):
        for k in PROPRIETARY_MEMBERS:
            tables.pop(k, None)
    members_data["meta.json"] = (
        json.dumps(meta, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    dest_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_p.with_suffix(dest_p.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    with tarfile.open(tmp, "w:xz", preset=6) as tout:
        for name, data in members_data.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = int(datetime.now(_UTC).timestamp())
            tout.addfile(info, io.BytesIO(data))
    tmp.replace(dest_p)
    return dest_p
