"""Keys and upserts for live_data.strike_pipeline_health (exchange + market + symbol)."""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TABLE = "strike_pipeline_health"
MARKET_15M = "15m"
MARKET_HOURLY = "hourly"


def strike_pipeline_health_strict_mode_enabled() -> bool:
    """
    Master opt-in for fail-closed pipeline health behavior.

    When True:
      - Dashboard monitor tiles and /api/monitors/health use strike_pipeline_health
        to show degraded state.
      - Auto-entry, trade_executor, and auto-stop may block on missing/stale/unhealthy rows.
      - WS strike-table generator treats stale Kalshi market / spot ticks as unhealthy
        (same freshness checks as ``STRIKE_PIPELINE_FRESHNESS_STRICT``).

    Default False: monitors show healthy; trade initiation is not gated on this table.
    WS writers can keep populating rows for debugging without affecting operations.

    Set STRIKE_PIPELINE_HEALTH_STRICT_MODE=1 only when publishers are reliable.
    """
    raw = os.getenv("STRIKE_PIPELINE_HEALTH_STRICT_MODE")
    if raw is None:
        # Fail-closed by default for live trading safety.
        return True
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def pipeline_health_pending_reason(reason: str | None) -> bool:
    """True when health is unknown/unavailable — tile lights stay green (trade gates stay fail-closed)."""
    r = str(reason or "").strip().lower()
    if not r:
        return True
    return (
        r.startswith("pipeline_health_missing")
        or r.startswith("pipeline_gate_exception:")
        or r == "pipeline_health_pending"
    )


def display_pipeline_health(ok: bool, reason: str) -> dict:
    """
    Map gate result to monitor tile light fields.

    Optimistic when pending/unknown so dashboards do not flash red before real health arrives.
    """
    if ok:
        return {
            "healthy": True,
            "state": "healthy",
            "reason": reason or "ok",
            "age_sec": None,
        }
    if pipeline_health_pending_reason(reason):
        return {
            "healthy": True,
            "state": "healthy",
            "reason": f"pending:{reason}",
            "age_sec": None,
        }
    return {
        "healthy": False,
        "state": "degraded",
        "reason": reason or "degraded",
        "age_sec": None,
    }


def pipeline_spot_flatline_window_sec() -> int:
    """Freshness window for Redis live_state and PG spot fallbacks (ring / legacy 1s log)."""
    return int(os.getenv("PIPELINE_SPOT_FLATLINE_WINDOW_SEC", "120"))


def pipeline_spot_flatline_min_distinct() -> int:
    """Minimum distinct spot prices required in flatline window to consider stream healthy."""
    return int(os.getenv("PIPELINE_SPOT_FLATLINE_MIN_DISTINCT", "2"))


def pipeline_spot_ring_flatline_window_sec() -> int:
    """PG ring window for flatline checks (~1 tick/min CFB needs a longer window than 1s log)."""
    base = max(180, int(pipeline_spot_flatline_window_sec()))
    try:
        return max(base, int(os.getenv("PIPELINE_SPOT_RING_FLATLINE_WINDOW_SEC", str(base))))
    except (TypeError, ValueError):
        return base


def _rollback_conn(conn) -> None:
    try:
        if conn is not None:
            conn.rollback()
    except Exception:
        pass


def _spot_series_passes_gate_live_state(symbol: str) -> tuple[bool, str]:
    """Hot-path spot freshness when ticks live in Redis (CFB / live_state publish mode)."""
    try:
        from backend.core import live_state_cache
        from backend.core.live_state_config import live_state_cache_enabled

        if not live_state_cache_enabled():
            return False, "live_state_cache_off"
        env = live_state_cache.get_symbol(symbol)
        window_sec = max(5, int(pipeline_spot_flatline_window_sec()))
        age = live_state_cache.cache_age_sec(env)
        if age > float(window_sec):
            return False, f"live_state_symbol_stale:{age:.1f}s>{window_sec}s"
        data = live_state_cache.get_symbol_data(symbol)
        if not data:
            return False, "live_state_symbol_miss"
        price = data.get("price") or data.get("one_minute_avg")
        if price is None:
            return False, "live_state_symbol_no_price"
        return True, "ok"
    except Exception as e:
        return False, f"live_state_spot_gate_failed:{e}"


def _spot_series_passes_gate_ring(conn, symbol: str) -> tuple[bool, str]:
    """CFB PG ring fallback when Redis live_state is stale or unavailable."""
    from backend.core.live_price_ring_90m import _utc_wall_str

    sym = str(symbol or "").strip().upper()
    table = f"live_data.live_price_ring_90m_{sym.lower()}"
    window_sec = max(60, int(pipeline_spot_ring_flatline_window_sec()))
    min_distinct = max(1, int(pipeline_spot_flatline_min_distinct()))
    # Same ISO-8601 UTC (…mmmZ) format as ring writers — required for TEXT lexicographic compares.
    cutoff = _utc_wall_str(datetime.now(ZoneInfo("UTC")) - timedelta(seconds=window_sec))
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*)::bigint,
                    COUNT(DISTINCT price::text)::bigint
                FROM {table}
                WHERE timestamp >= %s
                """,
                (cutoff,),
            )
            row = cur.fetchone()
        if not row:
            return False, "spot_ring_missing"
        sample_count = int(row[0] or 0)
        distinct_count = int(row[1] or 0)
        if sample_count < 1:
            return False, "spot_ring_samples_empty"
        if sample_count < min_distinct:
            return False, f"spot_ring_samples_insufficient:{sample_count}<{min_distinct}"
        if distinct_count < min_distinct:
            return False, f"spot_ring_flatline:{distinct_count}<{min_distinct}_in_{window_sec}s"
        return True, "ok"
    except Exception as e:
        _rollback_conn(conn)
        return False, f"spot_ring_gate_failed:{e}"


def _spot_series_passes_gate_live_price_log(conn, symbol: str) -> tuple[bool, str]:
    """Legacy Coinbase 1s log (optional when table still exists)."""
    sym = str(symbol or "").strip().upper()
    table = f"live_data.live_price_log_1s_{sym.lower()}"
    window_sec = max(5, int(pipeline_spot_flatline_window_sec()))
    min_distinct = max(1, int(pipeline_spot_flatline_min_distinct()))
    cutoff = (datetime.now(ZoneInfo("America/New_York")) - timedelta(seconds=window_sec)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*)::bigint,
                    COUNT(DISTINCT price::text)::bigint
                FROM {table}
                WHERE timestamp >= %s
                """,
                (cutoff,),
            )
            row = cur.fetchone()
        if not row:
            return False, "spot_log_missing"
        sample_count = int(row[0] or 0)
        distinct_count = int(row[1] or 0)
        if sample_count < min_distinct:
            return False, f"spot_samples_insufficient:{sample_count}<{min_distinct}"
        if distinct_count < min_distinct:
            return False, f"spot_flatline:{distinct_count}<{min_distinct}_in_{window_sec}s"
        return True, "ok"
    except Exception as e:
        _rollback_conn(conn)
        return False, f"spot_log_gate_failed:{e}"


def _spot_series_passes_gate(conn, symbol: str) -> tuple[bool, str]:
    sym = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2,10}", sym):
        return False, "invalid_symbol_for_spot_gate"
    ls_ok, ls_rsn = _spot_series_passes_gate_live_state(sym)
    if ls_ok:
        return True, ls_rsn
    if conn is not None:
        ring_ok, ring_rsn = _spot_series_passes_gate_ring(conn, sym)
        if ring_ok:
            return True, ring_rsn
        log_ok, log_rsn = _spot_series_passes_gate_live_price_log(conn, sym)
        if log_ok:
            return True, log_rsn
        return False, f"{ls_rsn};{ring_rsn};{log_rsn}"
    return False, ls_rsn


def pipeline_health_writer_dead_sec() -> int:
    """
    Upper bound on age of pipeline_health_checked_at before we assume the strike-table
    publisher died (distinct from quiet Kalshi markets).
    """
    return int(os.getenv("PIPELINE_HEALTH_WRITER_DEAD_SEC", "900"))


def pipeline_catastrophic_transport_sec() -> int:
    """
    Upper bound on age of ws_transport_ok_at (RFC WS ping/pong or successful recv) before
    we treat the Kalshi market WS path as dead. Large by design (minutes), not seconds.
    """
    return int(os.getenv("PIPELINE_CATASTROPHIC_TRANSPORT_SEC", "600"))


def default_hourly_eval_staleness_sec() -> int:
    """Deprecated name: use pipeline_health_writer_dead_sec()."""
    return pipeline_health_writer_dead_sec()


def default_max_age_15m_sec() -> int:
    """Legacy metadata; optional dashboard-only freshness (not trade gates)."""
    return int(os.getenv("STRIKE_PIPELINE_MAX_STALENESS_SEC", "30"))


def default_max_age_hourly_market_sec() -> int:
    """Stored on health rows as pipeline_health_max_age_sec metadata."""
    return pipeline_health_writer_dead_sec()


def floor_strike_vs_spot_check_enabled() -> bool:
    """When False, skip floor_strike vs spot sanity checks (emergency override). Default on."""
    return os.getenv("FLOOR_STRIKE_VS_SPOT_CHECK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def floor_strike_vs_spot_max_drift_pct() -> float:
    """
    Max allowed percent difference between a Kalshi ``floor_strike`` (or anchor strike)
    and the live symbol spot. Above this, data is treated as corrupt: strike updates are
    skipped and ``strike_pipeline_health`` is marked unhealthy (strict mode gates trading).
    """
    try:
        return float(os.getenv("FLOOR_STRIKE_VS_SPOT_MAX_DRIFT_PCT", "10"))
    except (TypeError, ValueError):
        return 10.0


def floor_strike_vs_spot_check(
    floor_strike_val: object,
    spot: float | None,
) -> tuple[bool, str, float | None]:
    """
    Return (ok, reason, drift_pct). Missing or invalid spot skips the check (ok True).
    ``drift_pct`` is ``|floor - spot| / spot * 100`` when comparable.
    """
    if not floor_strike_vs_spot_check_enabled():
        return True, "check_disabled", None
    if spot is None or float(spot) <= 0:
        return True, "no_spot_baseline", None
    try:
        fs = float(floor_strike_val)
    except (TypeError, ValueError):
        return True, "unparseable_floor_skip", None
    drift = abs(fs - float(spot)) / float(spot) * 100.0
    cap = floor_strike_vs_spot_max_drift_pct()
    if drift > cap:
        return False, f"floor_strike_vs_spot_drift_{drift:.2f}_pct_gt_{cap}", drift
    return True, "ok", drift


def upsert_strike_pipeline_health(
    conn,
    *,
    exchange: str,
    market: str,
    symbol: str,
    healthy: bool,
    reason: str,
    max_age_sec: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO live_data.{TABLE}
                (exchange, market, symbol, pipeline_healthy, pipeline_health_reason,
                 pipeline_health_checked_at, pipeline_health_max_age_sec, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), %s, NOW())
            ON CONFLICT (exchange, market, symbol) DO UPDATE SET
                pipeline_healthy = EXCLUDED.pipeline_healthy,
                pipeline_health_reason = EXCLUDED.pipeline_health_reason,
                pipeline_health_checked_at = EXCLUDED.pipeline_health_checked_at,
                pipeline_health_max_age_sec = EXCLUDED.pipeline_health_max_age_sec,
                updated_at = NOW()
            """,
            (
                exchange.strip().lower(),
                market.strip().lower(),
                symbol.strip().upper(),
                bool(healthy),
                reason,
                max(5, int(max_age_sec)),
            ),
        )
    conn.commit()


def row_passes_trade_gate(
    row: tuple | None,
    *,
    writer_dead_sec: int | None = None,
    transport_dead_sec: int | None = None,
) -> tuple[bool, str]:
    """
    Evaluate a fetched health row for trade / auto-stop gates.

    row: (pipeline_healthy, pipeline_health_reason, checked_age_sec, transport_age_sec)
         transport_age_sec is NULL in SQL when ws_transport_ok_at is NULL.
    """
    wdead = int(writer_dead_sec if writer_dead_sec is not None else pipeline_health_writer_dead_sec())
    tdead = int(transport_dead_sec if transport_dead_sec is not None else pipeline_catastrophic_transport_sec())
    if not row:
        return False, "missing_health_row"
    is_healthy = bool(row[0])
    reason = str(row[1] or "")
    checked_age = float(row[2]) if row[2] is not None else float("inf")
    transport_age = row[3]
    if not is_healthy:
        return False, f"pipeline_unhealthy:{reason or 'unknown'}"
    if checked_age > float(wdead):
        return False, f"writer_stale:{checked_age:.1f}s>{wdead}s"
    if transport_age is None:
        return False, "transport_never_observed"
    if float(transport_age) > float(tdead):
        return False, f"transport_stale:{float(transport_age):.1f}s>{tdead}s"
    return True, "ok"


def evaluate_pipeline_gate_conn(
    conn,
    *,
    exchange: str = "kalshi",
    market: str,
    symbol: str,
) -> tuple[bool, str]:
    """
    Trade / auto-stop gate: writer-alive + WS transport freshness.
    When STRIKE_PIPELINE_HEALTH_STRICT_MODE is off, returns (True, 'ok') without querying.
    """
    if not strike_pipeline_health_strict_mode_enabled():
        return True, "ok"
    ex = (exchange or "kalshi").strip().lower()
    mkt = (market or "").strip().lower()
    sym = (symbol or "").strip().upper()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                pipeline_healthy,
                pipeline_health_reason,
                EXTRACT(EPOCH FROM (NOW() - pipeline_health_checked_at)),
                EXTRACT(EPOCH FROM (NOW() - ws_transport_ok_at))
            FROM live_data.strike_pipeline_health
            WHERE LOWER(TRIM(exchange::text)) = %s
              AND LOWER(TRIM(market::text)) = %s
              AND UPPER(TRIM(symbol::text)) = %s
            LIMIT 1
            """,
            (ex, mkt, sym),
        )
        row = cur.fetchone()
    ok, reason = row_passes_trade_gate(row)
    if not ok:
        return ok, reason
    return _spot_series_passes_gate(conn, sym)


def evaluate_symbol_pipeline_gate_conn(
    conn,
    *,
    exchange: str = "kalshi",
    symbol: str,
) -> tuple[bool, str]:
    """
    Symbol-level gate for monitor health: if a symbol's spot feed is degraded, every monitor
    using that symbol (hourly and 15m) must be degraded.

    Rule:
      1) strict mode off -> pass
      2) require at least one strike_pipeline_health row for symbol
      3) every present market row must pass row_passes_trade_gate
      4) spot flatline/freshness gate must pass
    """
    if not strike_pipeline_health_strict_mode_enabled():
        return True, "ok"
    ex = (exchange or "kalshi").strip().lower()
    sym = (symbol or "").strip().upper()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                market,
                pipeline_healthy,
                pipeline_health_reason,
                EXTRACT(EPOCH FROM (NOW() - pipeline_health_checked_at)),
                EXTRACT(EPOCH FROM (NOW() - ws_transport_ok_at))
            FROM live_data.strike_pipeline_health
            WHERE LOWER(TRIM(exchange::text)) = %s
              AND UPPER(TRIM(symbol::text)) = %s
            """,
            (ex, sym),
        )
        rows = cur.fetchall()
    if not rows:
        return False, "pipeline_health_missing_symbol"
    for market, ph, pr, cage, tage in rows:
        ok, rsn = row_passes_trade_gate((ph, pr, cage, tage))
        if not ok:
            return False, f"market_{str(market).strip().lower()}:{rsn}"
    return _spot_series_passes_gate(conn, sym)


# ---------------------------------------------------------------------------
# Prolonged outage → System Event Log (master_events / system.event_log)
# ---------------------------------------------------------------------------
#
# Confirmed-unhealthy already waits degrade_confirm_sec (~30s) before the
# dashboard light goes red. Brief Kalshi floor_strike TBD blips at 15m rollover
# usually clear before that. Emit a master event only after confirmed unhealthy
# lasts STRIKE_PIPELINE_PROLONGED_OUTAGE_SEC (default 90s), plus one recovery.

_DEFAULT_PROLONGED_OUTAGE_SEC = 90

_prolonged_lock = threading.Lock()
_prolonged_state: dict[tuple[str, str, str], dict[str, Any]] = {}


def prolonged_outage_event_sec() -> int:
    """Seconds of continuous confirmed-unhealthy before a System Event Log warning."""
    raw = os.getenv("STRIKE_PIPELINE_PROLONGED_OUTAGE_SEC")
    if raw is None or str(raw).strip() == "":
        return _DEFAULT_PROLONGED_OUTAGE_SEC
    try:
        return max(30, int(str(raw).strip()))
    except ValueError:
        return _DEFAULT_PROLONGED_OUTAGE_SEC


def reset_prolonged_outage_event_state() -> None:
    """Clear in-memory outage timers (tests / process restart)."""
    with _prolonged_lock:
        _prolonged_state.clear()


def note_pipeline_health_for_system_event(
    *,
    exchange: str,
    market: str,
    symbol: str,
    healthy: bool,
    reason: str,
    now_mono: float | None = None,
) -> None:
    """
    Emit System Event Log entries for prolonged strike-pipeline outages and recovery.

    Call when confirmed pipeline health is written (after degrade confirm masking).
    Fail-open: never raises to callers.
    """
    ex = str(exchange or "").strip().lower() or "kalshi"
    mk = str(market or "").strip().lower()
    sym = str(symbol or "").strip().upper()
    if not mk or not sym:
        return

    key = (ex, mk, sym)
    now = float(now_mono if now_mono is not None else time.monotonic())
    threshold = float(prolonged_outage_event_sec())
    reason_s = str(reason or "").strip() or "unknown"

    emit_outage: tuple[float, str] | None = None
    emit_recovery: tuple[float, str] | None = None

    with _prolonged_lock:
        st = _prolonged_state.get(key)
        if healthy:
            if st and st.get("event_emitted") and st.get("unhealthy_since") is not None:
                elapsed = now - float(st["unhealthy_since"])
                emit_recovery = (elapsed, str(st.get("reason") or reason_s))
            _prolonged_state.pop(key, None)
        else:
            if st is None or st.get("unhealthy_since") is None:
                st = {
                    "unhealthy_since": now,
                    "event_emitted": False,
                    "reason": reason_s,
                }
                _prolonged_state[key] = st
            else:
                st["reason"] = reason_s
            elapsed = now - float(st["unhealthy_since"])
            if (not st.get("event_emitted")) and elapsed >= threshold:
                st["event_emitted"] = True
                emit_outage = (elapsed, reason_s)

    if emit_outage is None and emit_recovery is None:
        return

    try:
        from backend.util.master_system_log import log_system_event
    except Exception:
        return

    detail_ref = f"strike_table_generator_ws_{mk}"
    source = "strike_pipeline"

    if emit_outage is not None:
        elapsed, rsn = emit_outage
        try:
            log_system_event(
                category="ANOMALY",
                severity="warning",
                source=source,
                message=(
                    f"{ex} {mk} {sym} strike pipeline prolonged outage "
                    f"({elapsed:.0f}s): {rsn}"
                ),
                detail_ref=detail_ref,
                metadata={
                    "exchange": ex,
                    "market": mk,
                    "symbol": sym,
                    "elapsed_sec": round(elapsed, 1),
                    "reason": rsn,
                    "event": "prolonged_outage",
                },
            )
        except Exception:
            pass

    if emit_recovery is not None:
        elapsed, prior = emit_recovery
        try:
            log_system_event(
                category="ANOMALY",
                severity="info",
                source=source,
                message=(
                    f"{ex} {mk} {sym} strike pipeline recovered after "
                    f"{elapsed:.0f}s outage (was: {prior})"
                ),
                detail_ref=detail_ref,
                metadata={
                    "exchange": ex,
                    "market": mk,
                    "symbol": sym,
                    "elapsed_sec": round(elapsed, 1),
                    "prior_reason": prior,
                    "event": "outage_recovered",
                },
            )
        except Exception:
            pass
