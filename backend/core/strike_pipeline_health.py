"""Keys and upserts for live_data.strike_pipeline_health (exchange + market + symbol)."""

from __future__ import annotations

import os

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

    Default False: monitors show healthy; trade initiation is not gated on this table.
    WS writers can keep populating rows for debugging without affecting operations.

    Set STRIKE_PIPELINE_HEALTH_STRICT_MODE=1 only when publishers are reliable.
    """
    return os.getenv("STRIKE_PIPELINE_HEALTH_STRICT_MODE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


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
    return row_passes_trade_gate(row)
