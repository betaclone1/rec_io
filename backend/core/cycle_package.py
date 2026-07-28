"""
Load sealed cycle packages (``.tar.xz``) and reconstruct market state over time.

Package members (schema_version 2):
  meta.json, market_meta.json, snapshot.csv, deltas.csv,
  strike_table.csv, price_ring.csv, metrics_ring.csv
"""

from __future__ import annotations

import csv
import io
import json
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_UTC = timezone.utc


def _parse_ts(raw: str) -> datetime:
    s = str(raw or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def _dec(v: Any) -> Decimal:
    return Decimal(str(v).strip())


def _apply_delta(
    yes: Dict[str, str], no: Dict[str, str], side: str, price: Any, delta: Any
) -> None:
    side_l = str(side).strip().lower()
    book = yes if side_l == "yes" else no
    px = str(_dec(price).quantize(Decimal("0.000001")))
    cur = _dec(book.get(px, "0"))
    new_sz = cur + _dec(delta)
    if new_sz <= 0:
        book.pop(px, None)
    else:
        book[px] = str(new_sz.quantize(Decimal("0.01")))


def asks_from_book(yes: Dict[str, str], no: Dict[str, str]) -> Tuple[Optional[float], Optional[float]]:
    """Same touch derivation as live strike pricing (``touch_dollars_from_orderbook_snapshot``)."""
    from backend.core.orderbook_strike_prices import touch_dollars_from_orderbook_snapshot

    touch = touch_dollars_from_orderbook_snapshot({"yes": yes, "no": no, "valid": True})
    if not touch:
        return None, None

    def _f(key: str) -> Optional[float]:
        v = touch.get(key)
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return _f("yes_ask_dollars"), _f("no_ask_dollars")


@dataclass
class CyclePackage:
    path: Path
    meta: Dict[str, Any]
    market_meta: Dict[str, Any]
    snapshots: List[Dict[str, Any]]
    deltas: List[Dict[str, Any]]
    strike_rows: List[Dict[str, Any]]
    price_rows: List[Dict[str, Any]]
    metrics_rows: List[Dict[str, Any]]

    @property
    def market_ticker(self) -> str:
        return str(self.meta.get("market_ticker") or self.path.name.replace(".tar.xz", ""))

    @property
    def open_utc(self) -> datetime:
        return _parse_ts(self.meta["cycle_open_utc"])

    @property
    def close_utc(self) -> datetime:
        return _parse_ts(self.meta["cycle_close_utc"])

    @property
    def floor_strike(self) -> Optional[Decimal]:
        raw = self.market_meta.get("floor_strike")
        if raw in (None, ""):
            raw = self.meta.get("floor_strike")
        if raw in (None, ""):
            return None
        try:
            return _dec(raw)
        except (InvalidOperation, ValueError):
            return None

    @property
    def market_result(self) -> Optional[str]:
        v = self.market_meta.get("market_result") or self.meta.get("market_result")
        return str(v).strip().lower() if v not in (None, "") else None


@dataclass
class BookState:
    timestamp: datetime
    yes: Dict[str, str] = field(default_factory=dict)
    no: Dict[str, str] = field(default_factory=dict)

    @property
    def yes_ask(self) -> Optional[float]:
        return asks_from_book(self.yes, self.no)[0]

    @property
    def no_ask(self) -> Optional[float]:
        return asks_from_book(self.yes, self.no)[1]


@dataclass
class CycleTick:
    """One reconstructed decision instant for this package's market ticker."""

    timestamp: datetime
    ttc_seconds: int
    spot: Optional[float]
    avg_60s: Optional[float]
    yes_ask: Optional[float]
    no_ask: Optional[float]
    probability_15m: Optional[float]
    yes_prob_15m: Optional[float]
    no_prob_15m: Optional[float]
    fair_price: Optional[float]
    floor_strike: Optional[Decimal]
    metrics: Dict[str, Any] = field(default_factory=dict)
    # End-of-second book levels (string price -> size), for paper-style fill walks.
    yes_book: Dict[str, str] = field(default_factory=dict)
    no_book: Dict[str, str] = field(default_factory=dict)


def load_cycle_package(path: Path | str) -> CyclePackage:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(p)
    members: Dict[str, bytes] = {}
    with tarfile.open(p, "r:xz") as tar:
        for info in tar.getmembers():
            if not info.isfile():
                continue
            f = tar.extractfile(info)
            if f is None:
                continue
            members[Path(info.name).name] = f.read()

    def _json(name: str) -> Dict[str, Any]:
        raw = members.get(name)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _csv(name: str) -> List[Dict[str, Any]]:
        raw = members.get(name)
        if not raw:
            return []
        text = raw.decode("utf-8")
        return list(csv.DictReader(io.StringIO(text)))

    snaps = _csv("snapshot.csv")
    for s in snaps:
        if isinstance(s.get("yes"), str):
            s["yes"] = json.loads(s["yes"] or "{}")
        if isinstance(s.get("no"), str):
            s["no"] = json.loads(s["no"] or "{}")

    return CyclePackage(
        path=p,
        meta=_json("meta.json"),
        market_meta=_json("market_meta.json"),
        snapshots=snaps,
        deltas=_csv("deltas.csv"),
        strike_rows=_csv("strike_table.csv"),
        price_rows=_csv("price_ring.csv"),
        metrics_rows=_csv("metrics_ring.csv"),
    )


def _index_by_second(rows: List[Dict[str, Any]], ts_key: str = "timestamp") -> Dict[datetime, Dict[str, Any]]:
    out: Dict[datetime, Dict[str, Any]] = {}
    for r in rows:
        if not r.get(ts_key):
            continue
        ts = _parse_ts(r[ts_key]).replace(microsecond=0)
        out[ts] = r
    return out


def iter_book_states(pkg: CyclePackage) -> Iterator[BookState]:
    """
    Yield book state once per UTC second after the opening snapshot.

    Starts from the first non-empty snapshot; applies deltas in ``received_at`` order.
    When the clock advances to a new second, emits the book as of the end of the prior
    second (all deltas for that second already applied).
    """
    start: Optional[Dict[str, Any]] = None
    for s in pkg.snapshots:
        yes0 = s.get("yes") or {}
        no0 = s.get("no") or {}
        if yes0 or no0:
            start = s
            break
    if start is None:
        return

    yes = dict(start.get("yes") or {})
    no = dict(start.get("no") or {})
    current_era = str(start.get("seq") or "")
    current_second = _parse_ts(start["received_at"]).replace(microsecond=0)

    for d in pkg.deltas:
        era = str(d.get("snapshot_seq") or "")
        if era and current_era and era != current_era:
            matched = next((s for s in pkg.snapshots if str(s.get("seq")) == era), None)
            if matched is not None:
                my = matched.get("yes") or {}
                mn = matched.get("no") or {}
                # Closing empty snapshot clears the book; non-empty resets to that snap.
                if my or mn:
                    yes = dict(my)
                    no = dict(mn)
                else:
                    yes = {}
                    no = {}
                current_era = era
        ts = _parse_ts(d["received_at"]).replace(microsecond=0)
        while current_second < ts:
            yield BookState(timestamp=current_second, yes=dict(yes), no=dict(no))
            current_second += timedelta(seconds=1)
        _apply_delta(yes, no, d.get("side", ""), d.get("price"), d.get("delta"))

    yield BookState(timestamp=current_second, yes=dict(yes), no=dict(no))


def iter_cycle_ticks(pkg: CyclePackage) -> Iterator[CycleTick]:
    """
    1 Hz decision ticks for the package window.

    Prefers strike_table timestamps; fills asks from reconstructed book at that second;
    spot from price_ring; metrics when present.
    """
    prices = _index_by_second(pkg.price_rows)
    metrics = _index_by_second(pkg.metrics_rows)
    strikes = _index_by_second(pkg.strike_rows)

    books: Dict[datetime, BookState] = {}
    last_book: Optional[BookState] = None
    for b in iter_book_states(pkg):
        books[b.timestamp] = b
        last_book = b

    # Timeline: union of strike + price seconds inside [open, close]
    seconds = sorted(set(strikes) | set(prices))
    if not seconds:
        seconds = sorted(books.keys())

    floor = pkg.floor_strike
    close = pkg.close_utc

    def book_at(ts: datetime) -> Optional[BookState]:
        if ts in books:
            return books[ts]
        # nearest previous
        prev = [t for t in books if t <= ts]
        if not prev:
            return last_book
        return books[max(prev)]

    for ts in seconds:
        if ts < pkg.open_utc.replace(microsecond=0) or ts > close.replace(microsecond=0):
            # allow slight overrun on strike; still compute
            pass
        ttc = max(0, int((close - ts).total_seconds()))
        st = strikes.get(ts) or {}
        pr = prices.get(ts) or {}
        met = metrics.get(ts) or {}
        bk = book_at(ts)
        yes_ask = bk.yes_ask if bk else None
        no_ask = bk.no_ask if bk else None

        def _f(row: Dict[str, Any], key: str) -> Optional[float]:
            v = row.get(key)
            if v in (None, ""):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        yield CycleTick(
            timestamp=ts,
            ttc_seconds=ttc,
            spot=_f(pr, "price"),
            avg_60s=_f(pr, "avg_60s"),
            yes_ask=yes_ask,
            no_ask=no_ask,
            probability_15m=_f(st, "probability_15m"),
            yes_prob_15m=_f(st, "yes_prob_15m"),
            no_prob_15m=_f(st, "no_prob_15m"),
            fair_price=_f(st, "fair_price"),
            floor_strike=floor,
            metrics={k: v for k, v in met.items() if k != "timestamp"},
            yes_book=dict(bk.yes) if bk else {},
            no_book=dict(bk.no) if bk else {},
        )
