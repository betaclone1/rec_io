from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from backend.core.cycle_package import load_cycle_package, _parse_ts
from backend.core.cycle_recon.book_engine import collect_lifecycle_targets, reconstruct_book
from backend.core.cycle_recon.lifecycle import PRE_ENTRY_OFFSETS, build_lifecycle_rows, samples_to_timeseries_rows
from backend.core.cycle_recon.measurements import aggregate_whole_cent, book_liquidity_snapshot
from backend.core.cycle_recon.package_writer import PackageBuilder, default_runs_root
from backend.core.cycle_recon.sources import fetch_public_trades, locate_package
from backend.core.cycle_recon.time_util import (
    et_date_str,
    parse_et_wall,
    parse_utc,
    range_preset_et_bounds,
    to_iso_z,
)
from backend.core.cycle_recon.trade_log import StrategyTradeRef, find_trade_refs, select_strategy_trades
from backend.core.cycle_recon.trade_log_pg import (
    find_trade_refs_pg,
    list_distinct_tickers_pg,
    select_strategy_trades_pg,
)
from backend.core.cycle_recon.version import GENERATOR_VERSION, SCHEMA_VERSION

log = logging.getLogger("cycle_recon")


@dataclass
class RunRequest:
    start: Optional[str] = None  # UTC ISO (backend canonical)
    end: Optional[str] = None
    start_et: Optional[str] = None  # Eastern wall from UI; converted to UTC
    end_et: Optional[str] = None
    range_preset: Optional[str] = None  # 24h | 7d | 30d | all
    tickers: List[str] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)
    trade_log: Optional[str] = None  # optional CSV override (dev/legacy)
    trade_ids: List[str] = field(default_factory=list)
    monitors: List[str] = field(default_factory=list)
    user_no: Optional[str] = None  # tenant slot for Postgres trade log
    use_pg: bool = True
    pre_entry_seconds: int = 120
    post_close_seconds: int = 30
    workers: int = 2
    output_dir: Optional[str] = None
    force_refresh: bool = False
    offline: bool = False
    export_csv: bool = False
    standardized_sizes: List[float] = field(default_factory=lambda: [1, 5, 10, 25, 50, 100])
    copy_from_drive: bool = True
    run_id: Optional[str] = None
    create_archive: bool = True


def resolve_time_bounds(req: RunRequest) -> tuple[Optional[datetime], Optional[datetime]]:
    """Resolve request time window to aware UTC datetimes (Eastern UI → UTC)."""
    if req.range_preset:
        return range_preset_et_bounds(req.range_preset)
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    if req.start_et:
        start = parse_et_wall(req.start_et)
    elif req.start:
        start = parse_utc(req.start)
    if req.end_et:
        end = parse_et_wall(req.end_et)
    elif req.end:
        end = parse_utc(req.end)
    return start, end


def resolve_markets(req: RunRequest) -> tuple[List[str], List[StrategyTradeRef], Dict[str, Any]]:
    """
    Resolve tickers + strategy trades.

    Default source is the tenant Postgres trade log (``users_NNNN.trades_NNNN`` ∪ archives).
    CSV ``trade_log`` remains an explicit override for fixtures/dev.

    When no explicit ``tickers`` are provided, expand to **all** markets for the
    selected symbol(s) in the time window (trade-log distinct tickers ∪ sealed
    archives overlapping the window).
    """
    notes: Dict[str, Any] = {
        "missing_trade_ids": [],
        "source": None,
        "time_bounds_utc": {},
        "date_filter_et": {},
        "ticker_mode": None,
    }
    trades: List[StrategyTradeRef] = []

    start, end = resolve_time_bounds(req)
    notes["time_bounds_utc"] = {
        "start": to_iso_z(start) if start else None,
        "end": to_iso_z(end) if end else None,
        "range_preset": req.range_preset,
    }
    min_date_et = et_date_str(start) if start else None
    max_date_et = et_date_str(end) if end else None
    notes["date_filter_et"] = {"min_date": min_date_et, "max_date": max_date_et}

    explicit_tickers: Set[str] = {
        str(t).strip() for t in (req.tickers or []) if str(t).strip()
    }
    tickers: Set[str] = set(explicit_tickers)
    expand_window = not explicit_tickers

    if req.trade_log:
        notes["source"] = "csv"
        if req.trade_ids:
            trades, missing = find_trade_refs(req.trade_log, req.trade_ids)
            notes["missing_trade_ids"] = missing
            for tr in trades:
                tickers.add(tr.ticker)
            notes["ticker_mode"] = "trade_ids"
        elif explicit_tickers:
            trades = select_strategy_trades(
                req.trade_log,
                monitors=req.monitors or None,
                tickers=list(explicit_tickers),
            )
            notes["ticker_mode"] = "explicit"
        else:
            trades = select_strategy_trades(
                req.trade_log,
                monitors=req.monitors or None,
                tickers=None,
            )
            for tr in trades:
                tickers.add(tr.ticker)
            notes["ticker_mode"] = "window_csv"
    elif req.use_pg:
        user_no = (req.user_no or "").strip()
        if not user_no:
            raise ValueError("Postgres trade log requires user_no (tenant slot)")
        notes["source"] = f"pg:users_{user_no}"
        if req.trade_ids:
            trades, missing = find_trade_refs_pg(user_no, req.trade_ids)
            notes["missing_trade_ids"] = missing
            for tr in trades:
                tickers.add(tr.ticker)
            notes["ticker_mode"] = "trade_ids"
        elif explicit_tickers:
            notes["ticker_mode"] = "explicit"
            trades = select_strategy_trades_pg(
                user_no,
                monitors=req.monitors or None,
                tickers=list(explicit_tickers),
                symbols=req.symbols or None,
                min_date_et=min_date_et,
                max_date_et=max_date_et,
                limit=20000,
            )
        else:
            # Full window: every ticker for symbol(s) in range (PG ∪ sealed archives)
            notes["ticker_mode"] = "window_all"
            pg_tickers = list_distinct_tickers_pg(
                user_no,
                min_date_et=min_date_et,
                max_date_et=max_date_et,
                symbols=req.symbols or None,
                monitors=req.monitors or None,
            )
            tickers |= set(pg_tickers)
            notes["pg_distinct_tickers"] = len(pg_tickers)
            if start and end:
                arch = _tickers_in_range(start, end, symbols=req.symbols or None)
                tickers |= set(arch)
                notes["archive_tickers_in_range"] = len(arch)

            if tickers:
                trades = select_strategy_trades_pg(
                    user_no,
                    monitors=req.monitors or None,
                    tickers=sorted(tickers),
                    symbols=req.symbols or None,
                    min_date_et=min_date_et,
                    max_date_et=max_date_et,
                    limit=20000,
                )
            else:
                trades = select_strategy_trades_pg(
                    user_no,
                    monitors=req.monitors or None,
                    symbols=req.symbols or None,
                    min_date_et=min_date_et,
                    max_date_et=max_date_et,
                    limit=20000,
                )
                for tr in trades:
                    tickers.add(tr.ticker)

    for tr in trades:
        tickers.add(tr.ticker)

    if expand_window and start and end and not tickers:
        tickers |= set(_tickers_in_range(start, end, symbols=req.symbols or None))
        notes["ticker_mode"] = notes.get("ticker_mode") or "window_archives_only"

    return sorted(tickers), trades, notes


def _tickers_in_range(
    start: datetime,
    end: datetime,
    *,
    symbols: Optional[Sequence[str]] = None,
) -> List[str]:
    """Heuristic: list sealed packages under local backtesting_data whose meta overlaps range."""
    from backend.core.cycle_recon.sources import default_package_roots

    sym_set = {str(s).strip().upper() for s in (symbols or []) if str(s).strip()} or None
    found: List[str] = []
    for root in default_package_roots():
        for p in root.glob("**/KX*.tar.xz"):
            name = p.name.replace(".tar.xz", "")
            if sym_set is not None:
                # e.g. KXBTC15M… → BTC; skip if no symbol token matches
                upper = name.upper()
                if not any(sym in upper for sym in sym_set):
                    continue
            try:
                from backend.core.cycle_hot_tables import cycle_window_utc

                win = cycle_window_utc(name)
                if not win:
                    continue
                open_u, close_u = win
            except Exception:
                continue
            if close_u < start or open_u > end:
                continue
            found.append(name)
    return found


def process_market(
    ticker: str,
    *,
    req: RunRequest,
    trades_for_ticker: List[StrategyTradeRef],
    builder: Optional[PackageBuilder] = None,
) -> Dict[str, Any]:
    """
    Reconstruct one market. When ``builder`` is provided, stream large tables
    directly to parquet and release per-market state before return.
    """
    t0 = time.time()
    locate = locate_package(ticker, copy_from_drive=req.copy_from_drive)
    if locate.path is None:
        row = {
            "ticker": ticker,
            "status": "MISSING",
            "reason_codes": [locate.reason or "ARCHIVE_NOT_FOUND"],
            "archive": asdict(locate),
        }
        if builder is not None:
            builder.stream("markets").append(row)
        return {
            "ticker": ticker,
            "status": "MISSING",
            "reason_codes": [locate.reason or "ARCHIVE_NOT_FOUND"],
            "archive": asdict(locate),
            "elapsed_s": time.time() - t0,
            "market_row": row,
            "tables": {},
            "row_counts": {},
            "intervals": [],
            "quality_evidence": {},
        }

    pkg = load_cycle_package(locate.path)

    # Collect exact lifecycle as-of targets (no end-of-second lookahead)
    targets = []
    for tr in trades_for_ticker:
        targets.extend(
            collect_lifecycle_targets(
                pkg,
                entry=tr.entry_utc,
                close=tr.close_utc,
                pre_entry_offsets=PRE_ENTRY_OFFSETS,
                include_open_seconds=True,
            )
        )
    if not trades_for_ticker:
        targets = collect_lifecycle_targets(pkg, entry=None, close=None, include_open_seconds=False)

    event_stream = builder.stream("book_events") if builder is not None else None

    def _sink(row: Dict[str, Any]) -> None:
        if event_stream is not None:
            event_stream.append(row)

    recon = reconstruct_book(
        pkg,
        as_of_targets=targets,
        event_sink=_sink if event_stream is not None else None,
        collect_events=event_stream is None,
    )
    if event_stream is None:
        # fallback path for tests without builder
        pass

    pub_meta: Dict[str, Any] = {}
    public_rows: List[Dict[str, Any]] = []
    try:
        pub = fetch_public_trades(
            ticker,
            force_refresh=req.force_refresh,
            offline=req.offline,
        )
        pub_meta = {
            "cache_hit": pub.cache_hit,
            "complete": pub.complete,
            "pages": pub.pages,
            **pub.meta,
            "cache_path": str(pub.cache_path),
        }
        for tr in pub.trades:
            row = dict(tr)
            ct = row.get("created_time") or row.get("utc_timecode")
            if ct:
                try:
                    row["_ts"] = parse_utc(ct).timestamp()
                    row["timestamp_utc"] = to_iso_z(parse_utc(ct))
                except Exception:
                    pass
            if row.get("taker_side") or row.get("taker_outcome_side"):
                row["aggressor"] = row.get("taker_side") or row.get("taker_outcome_side")
            else:
                row["aggressor"] = "UNKNOWN"
            public_rows.append(row)
        if not pub.complete:
            recon.reason_codes.append("API_INCOMPLETE")
            if recon.quality_state == "COMPLETE":
                recon.quality_state = "DEGRADED"
    except Exception as e:
        pub_meta = {"error": str(e)}
        recon.reason_codes.append("API_CACHE_MISS_OFFLINE" if req.offline else "API_FETCH_FAILED")
        if recon.quality_state == "COMPLETE":
            recon.quality_state = "DEGRADED"

    symbol_rows = []
    for r in pkg.price_rows:
        if not r.get("timestamp"):
            continue
        ts = _parse_ts(r["timestamp"])
        symbol_rows.append(
            {
                "ticker": ticker,
                "timestamp_utc": to_iso_z(ts),
                "price": r.get("price"),
                "avg_60s": r.get("avg_60s"),
                **{k: v for k, v in r.items() if k not in ("timestamp", "price", "avg_60s")},
            }
        )

    side = "yes"
    if trades_for_ticker:
        side = "yes" if (trades_for_ticker[0].side or "Y").upper() in ("Y", "YES") else "no"

    ts_rows = samples_to_timeseries_rows(
        pkg, recon.samples_1s, side=side, sizes=req.standardized_sizes
    )

    ladder_rows: List[Dict[str, Any]] = []
    lifecycle_rows: List[Dict[str, Any]] = []
    if trades_for_ticker:
        for tr in trades_for_ticker:
            life = build_lifecycle_rows(
                pkg,
                recon,
                trade=tr,
                public_trades=public_rows,
                sizes=req.standardized_sizes,
                include_open_seconds=True,
            )
            lifecycle_rows.extend(life)
            entry_rows = [r for r in life if r.get("observation") == "entry"]
            if entry_rows:
                er = entry_rows[0]
                liq = er.get("liquidity") or {}
                for px, sz in (liq.get("whole_cent_ask_ladder") or {}).items():
                    ladder_rows.append(
                        {
                            "ticker": ticker,
                            "trade_id": tr.trade_id,
                            "trade_identity": tr.identity_key,
                            "observation": "entry",
                            "timestamp_utc": er["timestamp_utc"],
                            "side": er["side"],
                            "price_cent": px,
                            "size": sz,
                            "ladder_kind": "whole_cent_ask",
                        }
                    )
                for lvl in (liq.get("raw_ask_ladder") or [])[:40]:
                    ladder_rows.append(
                        {
                            "ticker": ticker,
                            "trade_id": tr.trade_id,
                            "trade_identity": tr.identity_key,
                            "observation": "entry",
                            "timestamp_utc": er["timestamp_utc"],
                            "side": er["side"],
                            "price_cent": lvl.get("price"),
                            "size": lvl.get("size"),
                            "ladder_kind": "raw_ask",
                        }
                    )
    else:
        lifecycle_rows = build_lifecycle_rows(
            pkg,
            recon,
            trade=None,
            public_trades=public_rows,
            sizes=req.standardized_sizes,
            include_open_seconds=False,
        )
        if recon.samples_1s:
            mid = recon.samples_1s[len(recon.samples_1s) // 2]
            liq = book_liquidity_snapshot(mid.yes, mid.no, side=side, sizes=req.standardized_sizes)
            for px, sz in (liq.get("whole_cent_ask_ladder") or {}).items():
                ladder_rows.append(
                    {
                        "ticker": ticker,
                        "trade_id": None,
                        "observation": "cycle_mid",
                        "timestamp_utc": mid.timestamp_utc,
                        "side": side,
                        "price_cent": px,
                        "size": sz,
                        "ladder_kind": "whole_cent_ask",
                    }
                )

    strategy_rows = []
    for tr in trades_for_ticker:
        strategy_rows.append(
            {
                "trade_identity": tr.identity_key,
                "source_path": tr.source_path,
                "source_sha256": tr.source_sha256,
                "source_namespace": tr.source_namespace,
                "trade_id": tr.trade_id,
                "ticker": tr.ticker,
                "monitor": tr.monitor,
                "side": tr.side,
                "date": tr.date,
                "entry_utc": to_iso_z(tr.entry_utc),
                "close_utc": to_iso_z(tr.close_utc) if tr.close_utc else None,
                **{
                    k: tr.row.get(k)
                    for k in (
                        "status",
                        "trade_strategy",
                        "contract",
                        "strike",
                        "prob",
                        "diff",
                        "buy_price",
                        "position",
                        "sell_price",
                        "closed_at",
                        "fees",
                        "pnl",
                        "symbol_open",
                        "symbol_close",
                        "win_loss",
                        "close_method",
                        "ret_pct",
                        "roi_pct",
                        "market_result",
                        "initial_price",
                        "slippage",
                        "initial_proj_price",
                        "limit_close_price",
                        "paper_trade",
                    )
                },
            }
        )

    snap_rows = recon.snapshot_level_rows
    event_count = int(recon.meta.get("event_count") or 0)
    if event_stream is None:
        event_rows = recon.event_rows
        event_count = len(event_rows)
    else:
        event_rows = []

    market_row = {
        "ticker": ticker,
        "status": recon.quality_state,
        "reason_codes": recon.reason_codes,
        "archive_path": str(locate.path),
        "archive_source": locate.source,
        "archive_sha256": locate.sha256,
        "archive_bytes": locate.bytes,
        "cycle_open_utc": recon.meta.get("cycle_open_utc"),
        "cycle_close_utc": recon.meta.get("cycle_close_utc"),
        "floor_strike": recon.meta.get("floor_strike"),
        "market_result": recon.meta.get("market_result"),
        "delta_count": recon.meta.get("delta_count"),
        "snapshot_count": recon.meta.get("snapshot_count"),
        "event_count": event_count,
        "sample_1s_count": recon.meta.get("sample_1s_count"),
        "public_trades_meta": pub_meta,
        "intervals": [asdict(i) for i in recon.intervals],
        "quality_evidence": recon.quality_evidence,
    }

    row_counts = {
        "strategy_trades": len(strategy_rows),
        "book_timeseries": len(ts_rows),
        "whole_cent_ladder": len(ladder_rows),
        "public_trades": len(public_rows),
        "symbol_timeseries": len(symbol_rows),
        "trade_lifecycle": len(lifecycle_rows),
        "initial_book_snapshots": len(snap_rows),
        "book_events": event_count,
    }

    if builder is not None:
        builder.stream("strategy_trades").extend(strategy_rows)
        builder.stream("book_timeseries").extend(ts_rows)
        builder.stream("whole_cent_ladder").extend(ladder_rows)
        builder.stream("public_trades").extend(public_rows)
        builder.stream("symbol_timeseries").extend(symbol_rows)
        builder.stream("trade_lifecycle").extend(lifecycle_rows)
        builder.stream("initial_book_snapshots").extend(snap_rows)
        builder.stream("markets").append(market_row)
        if event_rows:
            builder.stream("book_events").extend(event_rows)
        # Release heavy in-memory structures
        del recon
        del public_rows
        del ts_rows
        del symbol_rows
        del lifecycle_rows
        del snap_rows
        del event_rows
        return {
            "ticker": ticker,
            "status": market_row["status"],
            "reason_codes": market_row["reason_codes"],
            "archive": asdict(locate),
            "elapsed_s": time.time() - t0,
            "market_row": market_row,
            "intervals": market_row["intervals"],
            "pub_meta": pub_meta,
            "quality_evidence": market_row["quality_evidence"],
            "row_counts": row_counts,
            "tables": {},
        }

    return {
        "ticker": ticker,
        "status": market_row["status"],
        "reason_codes": market_row["reason_codes"],
        "archive": asdict(locate),
        "elapsed_s": time.time() - t0,
        "market_row": market_row,
        "tables": {
            "strategy_trades": strategy_rows,
            "book_events": event_rows,
            "initial_book_snapshots": snap_rows,
            "book_timeseries": ts_rows,
            "whole_cent_ladder": ladder_rows,
            "public_trades": public_rows,
            "symbol_timeseries": symbol_rows,
            "trade_lifecycle": lifecycle_rows,
        },
        "intervals": market_row["intervals"],
        "pub_meta": pub_meta,
        "quality_evidence": market_row["quality_evidence"],
        "row_counts": row_counts,
    }


def run_reconstruction(req: RunRequest) -> Dict[str, Any]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    tickers, trades, resolve_notes = resolve_markets(req)
    if not tickers:
        raise ValueError(
            "No markets resolved (need tickers, Postgres trade log hits, CSV trade-log, or start/end range)"
        )

    run_id = req.run_id or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    out_root = Path(req.output_dir) if req.output_dir else default_runs_root()
    builder = PackageBuilder(out_root, run_id)

    trades_by_ticker: Dict[str, List[StrategyTradeRef]] = {}
    for tr in trades:
        trades_by_ticker.setdefault(tr.ticker, []).append(tr)

    # Force sequential default for memory target; workers>1 still sequential for large streams
    workers = max(1, min(int(req.workers or 1), 4))
    log.info("run %s markets=%s workers=%s (streaming parquet)", run_id, tickers, workers)

    quality_markets = []
    markets = []
    row_totals: Dict[str, int] = {}
    strategy_trade_count = 0

    # Always process one market at a time for <2GB peak (ignore parallel for heavy tables)
    for t in tickers:
        log.info("start %s", t)
        r = process_market(
            t,
            req=req,
            trades_for_ticker=trades_by_ticker.get(t, []),
            builder=builder,
        )
        log.info("done %s status=%s elapsed=%.2fs", t, r.get("status"), r.get("elapsed_s", 0))
        mr = r.get("market_row") or {
            "ticker": r["ticker"],
            "status": r.get("status"),
            "reason_codes": r.get("reason_codes"),
            "archive": r.get("archive"),
        }
        markets.append(mr)
        quality_markets.append(
            {
                "ticker": r["ticker"],
                "status": r.get("status"),
                "reason_codes": r.get("reason_codes"),
                "intervals": r.get("intervals") or [],
                "elapsed_s": r.get("elapsed_s"),
                "pub_meta": r.get("pub_meta"),
                "quality_evidence": r.get("quality_evidence") or mr.get("quality_evidence"),
            }
        )
        for k, v in (r.get("row_counts") or {}).items():
            row_totals[k] = row_totals.get(k, 0) + int(v)
        strategy_trade_count += int((r.get("row_counts") or {}).get("strategy_trades") or 0)

    # Ensure markets stream exists even if all missing
    if "markets" not in builder._streams and markets:
        builder.write_table("markets", markets, export_csv=req.export_csv)

    quality_report = {
        "schema_version": SCHEMA_VERSION,
        "markets": quality_markets,
        "resolve_notes": resolve_notes,
        "definitions": {
            "COMPLETE": "Required sources present; no material continuity/integrity failures",
            "DEGRADED": "Material gap/duplicate-seq/negative-depth/ooo/crossed; see intervals+evidence",
            "INVALID": "Reconstruction inconsistent; do not trust levels",
            "MISSING": "Sealed package or required source absent",
            "RESYNC": "Informational era change with recovered snapshot; does not alone degrade",
            "DELTA_DUPLICATE": "Same source seq observed more than once (not same-value updates)",
            "public_trade_windows": "Decision-time trailing [t-w,t]; post_event_* are separate",
        },
    }

    summary = {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "market_count": len(markets),
        "statuses": _count_status(markets),
        "strategy_trade_count": strategy_trade_count,
        "row_counts": {**row_totals, "markets": len(markets)},
        "resolve_notes": resolve_notes,
        "what_you_can_answer": [
            "exact entry book and whole-cent ladder (whole_cent_ladder + trade_lifecycle entry)",
            "executable entry/liquidation VWAP for recorded size (trade_lifecycle)",
            "60-120s pre-entry evolution (trade_lifecycle pre_entry_* + book_timeseries)",
            "entry-to-close lifecycle and holding time (trade_lifecycle)",
            "BTC buffer path (trade_lifecycle / book_timeseries buffer_*)",
            "public prints trailing to observation (public_trade_windows); post_event_* separate",
            "exact gaps/staleness (quality_report intervals + book_age_ms/stale flags)",
            "replay without archive (book_events + initial_book_snapshots)",
        ],
        "unavailable_by_design": [
            "exchange-level BTC trades",
            "order IDs / queue position",
            "cancellation identity",
            "reliable aggressor when tape lacks taker fields (emitted as UNKNOWN)",
            "missing trigger timestamps not present in trade log",
        ],
    }

    readme = _readme_text(run_id, summary, quality_report)
    path = builder.finalize(
        request=asdict(req),
        quality_report=quality_report,
        summary=summary,
        readme=readme,
        status="complete",
    )

    archive_info = None
    if req.create_archive:
        from backend.core.cycle_recon.archive import (
            archive_result_dict,
            create_handoff_archive,
            patch_summary_with_archive,
        )

        t_arch = time.perf_counter()
        try:
            arch = create_handoff_archive(path)
            patch_summary_with_archive(path, arch)
            archive_info = archive_result_dict(arch)
            summary["handoff_archive"] = archive_info
            log.info(
                "handoff archive %s format=%s bytes=%s sha256=%s compression_s=%.3f",
                arch.archive_path,
                arch.format,
                arch.bytes,
                arch.sha256,
                arch.compression_s,
            )
        except Exception as e:
            log.error("handoff archive failed after %.2fs: %s", time.perf_counter() - t_arch, e)
            summary["handoff_archive"] = {"error": str(e), "verified": False}
            # Surface in returned summary; do not delete the run directory
            archive_info = summary["handoff_archive"]

    return {
        "run_dir": str(path),
        "summary": summary,
        "quality_report": quality_report,
        "handoff_archive": archive_info,
    }


def _count_status(markets: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for m in markets:
        s = str(m.get("status") or "UNKNOWN")
        out[s] = out.get(s, 0) + 1
    return out


def _readme_text(run_id: str, summary: Dict[str, Any], quality: Dict[str, Any]) -> str:
    lines = [
        f"# Cycle reconstruction package `{run_id}`",
        "",
        "Local offline analysis package. **Reconstruction facts only** — not strategy advice.",
        "",
        f"- schema: `{SCHEMA_VERSION}` generator: `{GENERATOR_VERSION}`",
        f"- markets: {summary.get('market_count')} statuses: {summary.get('statuses')}",
        "",
        "## Warnings",
        "",
        "- YES/NO are complementary views of **one** Kalshi book (asks derived from opposite bids).",
        "- Timestamps are UTC canonical; `*_et` fields are display-only.",
        "- Stale/gap intervals are marked; do not treat carried-forward books as live updates.",
        "- Aggressor/signed flow is `UNKNOWN` unless tape fields are reliable.",
        "",
        "## Quality",
        "",
        "```json",
        json_dumps_brief(quality),
        "```",
        "",
    ]
    return "\n".join(lines) + "\n"


def json_dumps_brief(obj: Any) -> str:
    import json

    return json.dumps(obj, indent=2, default=str)[:8000]
