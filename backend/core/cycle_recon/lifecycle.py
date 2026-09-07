from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from backend.core.cycle_package import CyclePackage, _parse_ts
from backend.core.cycle_recon.book_engine import (
    ReconstructionResult,
    book_at_or_before_as_of,
)
from backend.core.cycle_recon.measurements import (
    DEFAULT_SIZES,
    PUBLIC_TRADE_WINDOWS_S,
    book_liquidity_snapshot,
    public_trade_window_stats,
    strike_buffer,
)
from backend.core.cycle_recon.time_util import to_et_display, to_iso_z
from backend.core.cycle_recon.trade_log import StrategyTradeRef

PRE_ENTRY_OFFSETS = (120, 90, 60, 30, 15, 10, 5, 1)


def _price_index(pkg: CyclePackage) -> Dict[datetime, Dict[str, Any]]:
    out: Dict[datetime, Dict[str, Any]] = {}
    for r in pkg.price_rows:
        if not r.get("timestamp"):
            continue
        ts = _parse_ts(r["timestamp"]).replace(microsecond=0)
        out[ts] = r
    return out


def _spot_at(prices: Dict[datetime, Dict[str, Any]], ts: datetime) -> Optional[float]:
    key = ts.replace(microsecond=0)
    row = prices.get(key)
    if not row:
        prev = [t for t in prices if t <= key]
        if not prev:
            return None
        row = prices[max(prev)]
    v = row.get("price") or row.get("avg_60s")
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _best_bid_for_side(liq: Dict[str, Any], side_yn: str, yes: Dict[str, str], no: Dict[str, str]) -> Optional[float]:
    """Scalar best bid on the owned outcome side."""
    from backend.core.cycle_recon.book_engine import _best_bid

    if side_yn == "yes":
        return _best_bid(yes)
    return _best_bid(no)


def build_lifecycle_rows(
    pkg: CyclePackage,
    recon: ReconstructionResult,
    *,
    trade: Optional[StrategyTradeRef] = None,
    public_trades: Optional[List[Dict[str, Any]]] = None,
    sizes: Sequence[float] = DEFAULT_SIZES,
    include_open_seconds: bool = True,
) -> List[Dict[str, Any]]:
    prices = _price_index(pkg)
    floor = float(pkg.floor_strike) if pkg.floor_strike is not None else None
    side = (trade.side if trade and trade.side else "Y")
    side_yn = "yes" if str(side).upper() in ("Y", "YES") else "no"
    size = None
    if trade and trade.row.get("position") not in (None, ""):
        try:
            size = float(trade.row["position"])
        except (TypeError, ValueError):
            size = None
    size_list = list(sizes)
    if size and size not in size_list:
        size_list = [size] + list(sizes)

    anchors: List[tuple[str, datetime]] = [("cycle_open", pkg.open_utc)]
    entry = trade.entry_utc if trade else None
    close = trade.close_utc if trade else None

    if entry is not None:
        for off in PRE_ENTRY_OFFSETS:
            anchors.append((f"pre_entry_{off}s", entry - timedelta(seconds=off)))
        anchors.append(("entry", entry))
        if close is not None and close > entry and include_open_seconds:
            t = entry.replace(microsecond=0) + timedelta(seconds=1)
            end = close.replace(microsecond=0)
            while t < end:
                anchors.append(("open_second", t))
                t += timedelta(seconds=1)
            anchors.append(("close", close))
    anchors.append(("expiration", pkg.close_utc))

    rows: List[Dict[str, Any]] = []
    seen = set()
    mfe = None
    mae = None
    entry_exec = None

    # Map sample seconds -> rolling for enrichment near lifecycle times
    rolling_by_sec = {
        _parse_ts(s.timestamp_utc).replace(microsecond=0): s.rolling for s in recon.samples_1s
    }

    for label, ts in anchors:
        key = (label if label != "open_second" else f"open_second:{to_iso_z(ts)}", to_iso_z(ts))
        if key in seen:
            continue
        seen.add(key)
        hit = book_at_or_before_as_of(recon.as_of_books, ts)
        if hit is None:
            continue
        idx, book_ts, yes, no = hit
        # Strict invariant
        if book_ts > ts:
            raise RuntimeError(
                f"lookahead violation: book_ts={book_ts.isoformat()} > observation={ts.isoformat()} label={label}"
            )
        age_ms = (ts - book_ts).total_seconds() * 1000.0
        if age_ms < -1e-6:
            raise RuntimeError(f"negative book_age_ms={age_ms} at {label}")
        age_ms = max(0.0, age_ms)

        stale = age_ms >= 2000.0
        if stale and label not in ("cycle_open", "expiration", "entry", "close") and not label.startswith("pre_entry"):
            if label == "open_second":
                continue

        liq = book_liquidity_snapshot(yes, no, side=side_yn, sizes=size_list)
        spot = _spot_at(prices, ts)
        buf = strike_buffer(spot, floor)
        yes_ask = liq.get("best_ask")
        best_bid = _best_bid_for_side(liq, side_yn, yes, no)

        if entry is not None and ts >= entry and yes_ask is not None:
            if entry_exec is None and label == "entry":
                entry_exec = float(yes_ask)
            if entry_exec is not None:
                chg = float(yes_ask) - float(entry_exec)
                mfe = chg if mfe is None else max(mfe, chg)
                mae = chg if mae is None else min(mae, chg)

        pub = {}
        pub_post = {}
        if public_trades is not None:
            obs_ts = ts.timestamp()
            for w in PUBLIC_TRADE_WINDOWS_S:
                pub[f"public_{w}s"] = public_trade_window_stats(
                    public_trades,
                    center_ts=obs_ts,
                    window_s=float(w),
                    mode="trailing",
                )
            # Explicit post-event descriptive windows (not decision features)
            if label in ("entry", "close") or label.startswith("open_second"):
                for w in (5, 15, 30, 60):
                    pub_post[f"post_event_{w}s"] = public_trade_window_stats(
                        public_trades,
                        center_ts=obs_ts,
                        window_s=float(w),
                        mode="post",
                    )

        actual_vwap = None
        actual_liq = None
        if size:
            for k, v in liq["entry_vwap_by_size"].items():
                if abs(float(k) - float(size)) < 1e-9:
                    actual_vwap = v
                    break
            for k, v in liq["liquidation_vwap_by_size"].items():
                if abs(float(k) - float(size)) < 1e-9:
                    actual_liq = v
                    break

        qstate = "DEGRADED" if stale else "COMPLETE"
        roll = rolling_by_sec.get(ts.replace(microsecond=0)) or {}

        rows.append(
            {
                "ticker": pkg.market_ticker,
                "observation": label,
                "timestamp_utc": to_iso_z(ts),
                "timestamp_et": to_et_display(ts),
                "book_timestamp_utc": to_iso_z(book_ts),
                "book_age_ms": age_ms,
                "stale": stale,
                "quality_state": qstate,
                "seconds_since_cycle_open": (ts - pkg.open_utc).total_seconds(),
                "ttc_seconds": max(0.0, (pkg.close_utc - ts).total_seconds()),
                "seconds_relative_to_entry": (ts - entry).total_seconds() if entry else None,
                "position_state": _position_state(label, entry, close, ts),
                "side": side_yn,
                "spot": spot,
                "floor_strike": floor,
                "buffer_dollars": buf["buffer_dollars"],
                "buffer_pct": buf["buffer_pct"],
                "yes_ask": yes_ask,
                "best_ask": yes_ask,
                "best_bid": best_bid,
                "liquidity": liq,
                "entry_vwap_actual_size": actual_vwap,
                "liquidation_vwap_actual_size": actual_liq,
                "mfe_ask_delta": mfe,
                "mae_ask_delta": mae,
                "public_trade_windows": pub,
                "post_event_public_trade_windows": pub_post,
                "rolling_book_activity": roll,
                "trade_id": trade.trade_id if trade else None,
                "trade_identity": trade.identity_key if trade else None,
                "source_event_index": idx,
                "whole_cent_ask_ladder": liq.get("whole_cent_ask_ladder"),
            }
        )
    return rows


def _position_state(
    label: str,
    entry: Optional[datetime],
    close: Optional[datetime],
    ts: datetime,
) -> str:
    if label == "cycle_open":
        return "flat"
    if entry is None:
        return "unknown"
    if ts < entry:
        return "flat_pre_entry"
    if close is not None and ts >= close:
        return "flat_post_close"
    if label == "expiration" and (close is None or ts >= (close or ts)):
        return "expired_or_flat"
    return "open"


def samples_to_timeseries_rows(
    pkg: CyclePackage,
    samples: List[Any],
    *,
    side: str = "yes",
    sizes: Sequence[float] = (1, 5, 10, 25, 50, 100),
) -> List[Dict[str, Any]]:
    prices = _price_index(pkg)
    floor = float(pkg.floor_strike) if pkg.floor_strike is not None else None
    rows = []
    for s in samples:
        ts = _parse_ts(s.timestamp_utc)
        liq = book_liquidity_snapshot(s.yes, s.no, side=side, sizes=sizes)
        spot = _spot_at(prices, ts)
        buf = strike_buffer(spot, floor)
        # Flatten rolling windows onto row for parquet convenience
        flat_roll: Dict[str, Any] = {}
        for wkey, wval in (s.rolling or {}).items():
            if not isinstance(wval, dict):
                continue
            flat_roll[f"roll_{wkey}_update_event_count"] = wval.get("update_event_count")
            flat_roll[f"roll_{wkey}_update_quantity_abs"] = wval.get("update_quantity_abs")
            flat_roll[f"roll_{wkey}_quote_jump_count_yes_ask"] = wval.get("quote_jump_count_yes_ask")
            flat_roll[f"roll_{wkey}_yes_ask_change"] = wval.get("yes_ask_change")
        rows.append(
            {
                "ticker": pkg.market_ticker,
                "timestamp_utc": s.timestamp_utc,
                "timestamp_et": s.timestamp_et,
                "seconds_since_cycle_open": s.seconds_since_cycle_open,
                "ttc_seconds": s.ttc_seconds,
                "yes_ask": s.yes_ask,
                "no_ask": s.no_ask,
                "best_yes_bid": s.best_yes_bid,
                "best_no_bid": s.best_no_bid,
                "spread_yes": s.spread_yes,
                "midpoint_yes": s.midpoint_yes,
                "book_age_ms": s.book_age_ms,
                "stale": s.stale,
                "quality_state": s.quality_state,
                "quality_flags": s.quality_flags,
                "spot": spot,
                "buffer_dollars": buf["buffer_dollars"],
                "buffer_pct": buf["buffer_pct"],
                "cum_depth_cents": liq["cum_depth_cents"],
                "largest_shelf_price": liq["largest_shelf_price"],
                "largest_shelf_size": liq["largest_shelf_size"],
                "depth_concentration": liq["depth_concentration"],
                "empty_whole_cent_levels_15": liq["empty_whole_cent_levels_15"],
                "qty_to_move_cents": liq["qty_to_move_cents"],
                "entry_vwap_by_size": liq["entry_vwap_by_size"],
                "liquidation_vwap_by_size": liq["liquidation_vwap_by_size"],
                "rolling_book_activity": s.rolling,
                **flat_roll,
            }
        )
    return rows
