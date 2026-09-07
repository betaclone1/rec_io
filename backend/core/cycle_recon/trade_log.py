from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from backend.core.cycle_recon.hashing import sha256_file, short_hash
from backend.core.cycle_recon.time_util import (
    combine_trade_log_close_utc,
    combine_trade_log_open_utc,
)


@dataclass
class StrategyTradeRef:
    """Source-scoped trade identity (IDs are never globally unique)."""

    source_path: str
    source_sha256: str
    source_namespace: str  # e.g. csv:mon_0001_10058
    trade_id: str
    ticker: str
    monitor: Optional[str]
    side: Optional[str]
    date: Optional[str]
    entry_utc: datetime
    close_utc: Optional[datetime]
    row: Dict[str, Any] = field(default_factory=dict)

    @property
    def identity_key(self) -> str:
        return (
            f"{self.source_namespace}|id={self.trade_id}|ticker={self.ticker}"
            f"|sha={short_hash(self.source_sha256)}"
        )


def _norm_side(raw: Any) -> Optional[str]:
    if raw in (None, ""):
        return None
    s = str(raw).strip().upper()
    if s in ("Y", "YES"):
        return "Y"
    if s in ("N", "NO"):
        return "N"
    return s


def load_trade_log_csv(path: Path | str) -> tuple[List[Dict[str, Any]], str]:
    p = Path(path).expanduser().resolve()
    digest = sha256_file(p)
    with p.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]
    return rows, digest


def select_strategy_trades(
    path: Path | str,
    *,
    trade_ids: Optional[Sequence[str]] = None,
    monitors: Optional[Sequence[str]] = None,
    tickers: Optional[Sequence[str]] = None,
) -> List[StrategyTradeRef]:
    """
    Load and filter strategy trades from a CSV shaped like tenant trades_* exports.

    Trade IDs are source-scoped: matching uses this file's rows only.
    """
    p = Path(path).expanduser().resolve()
    rows, digest = load_trade_log_csv(p)
    id_set: Optional[Set[str]] = {str(x).strip() for x in trade_ids} if trade_ids else None
    mon_set: Optional[Set[str]] = {str(x).strip() for x in monitors} if monitors else None
    tick_set: Optional[Set[str]] = {str(x).strip() for x in tickers} if tickers else None

    # Infer namespace from dominant monitor when present
    monitors_seen = [str(r.get("monitor") or "").strip() for r in rows if r.get("monitor")]
    mon_mode = monitors_seen[0] if monitors_seen else "unknown"
    namespace = f"csv:{mon_mode}:{p.name}"

    out: List[StrategyTradeRef] = []
    for r in rows:
        tid = str(r.get("id") or "").strip()
        ticker = str(r.get("ticker") or "").strip()
        monitor = str(r.get("monitor") or "").strip() or None
        if id_set is not None and tid not in id_set:
            continue
        if mon_set is not None and (monitor or "") not in mon_set:
            continue
        if tick_set is not None and ticker not in tick_set:
            continue
        if not ticker:
            continue
        entry = combine_trade_log_open_utc(
            str(r.get("date") or ""),
            str(r.get("time") or ""),
            str(r.get("created_at") or "") or None,
        )
        close = combine_trade_log_close_utc(
            str(r.get("date") or ""),
            str(r.get("closed_at") or "") or None,
            str(r.get("updated_at") or "") or None,
        )
        out.append(
            StrategyTradeRef(
                source_path=str(p),
                source_sha256=digest,
                source_namespace=namespace,
                trade_id=tid,
                ticker=ticker,
                monitor=monitor,
                side=_norm_side(r.get("side")),
                date=str(r.get("date") or "") or None,
                entry_utc=entry,
                close_utc=close,
                row=r,
            )
        )
    return out


def find_trade_refs(
    path: Path | str,
    trade_ids: Sequence[str],
) -> tuple[List[StrategyTradeRef], List[str]]:
    """Return (found refs, missing ids) for explicit trade IDs in a CSV."""
    wanted = [str(x).strip() for x in trade_ids]
    found = select_strategy_trades(path, trade_ids=wanted)
    have = {t.trade_id for t in found}
    missing = [i for i in wanted if i not in have]
    return found, missing
