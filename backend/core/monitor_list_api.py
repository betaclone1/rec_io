"""
Payload builder for GET /api/monitors.

Keeps monitor-list SQL, symbol-wide cooldown projection, and row formatting out of main_app.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

from backend.core.config.database import get_postgresql_connection
from backend.core.time_based_loss_prevention import (
    _sql_live_loss_prevention_cooldown_live_expr,
    _sql_sim_cooldown_live_expr,
)
from backend.core.symbol_wide_loss_prevention import (
    _sql_local_loss_prevention_state_expr,
    is_symbol_wide_loss_prevention_state,
    more_serious_loss_prevention_state,
    normalize_loss_prevention_state_for_sizing,
    symbol_wide_loss_prevention_state,
)
from backend.core.strike_pipeline_health import (
    evaluate_pipeline_gate_conn,
    strike_pipeline_health_strict_mode_enabled,
)
from backend.core.time_eastern import EST, now_est, timestamptz_wire_iso_et
from backend.trading_mode import is_paper_trading

_log = logging.getLogger(__name__)


def _monitor_list_select_sql(user_number: str) -> str:
    return f"""
                SELECT
                    ml.id,
                    ml.name,
                    ml.symbol,
                    ml.strategy,
                    ml.auto_trade,
                    ml.auto_trade_status,
                    ml.trades,
                    ml.win_loss,
                    ml.ret_pct,
                    ml.pnl,
                    ml.bankroll_allotment_pct,
                    ml.status,
                    ml.dashboard_order,
                    ml.win_streak,
                    ml.loss_prevention_state,
                    {_sql_local_loss_prevention_state_expr("ml.")} AS computed_local_loss_prevention_state,
                    COALESCE(ml.loss_prevention_toggle, FALSE),
                    COALESCE(NULLIF(ml.loss_prevention_method, ''), 'win_streak'),
                    ml.created,
                    ml.cooldown_timer,
                    ml.current_contract,
                    ml.current_weekly_cycle,
                    ml.current_performance_modifier,
                    ml.current_max_pct_exposure,
                    ml.performance_based_allocation,
                    ml.paper_trade,
                    ml.test_filter,
                    ml.regime_monitor_enabled,
                    ml.regime_window,
                    ml.market,
                    ml.simulated_trade_loss_prevention,
                    ml.loss_prevention_duration,
                    ml.simulated_loss_prevention_cooldown_start_time,
                    ml.original_loss_prevention_cooldown_start_time,
                    ml.loss_prevention_cooldown_loss_count,
                    ml.live_loss_prevention_cooldown_start_time,
                    {_sql_sim_cooldown_live_expr("ml.")} AS simulated_loss_prevention_cooldown_live,
                    {_sql_live_loss_prevention_cooldown_live_expr("ml.")} AS live_loss_prevention_cooldown_live,
                    COALESCE(ml.symbol_wide_loss_prevention, FALSE),
                    lss.loss_prevention_state AS symbol_wide_loss_prevention_state,
                    lss.loss_prevention_duration AS symbol_wide_loss_prevention_duration,
                    lss.simulated_loss_prevention_cooldown_start_time AS symbol_wide_simulated_loss_prevention_cooldown_start_time,
                    lss.original_loss_prevention_cooldown_start_time AS symbol_wide_original_loss_prevention_cooldown_start_time,
                    lss.loss_prevention_cooldown_loss_count AS symbol_wide_loss_prevention_cooldown_loss_count,
                    lss.live_loss_prevention_cooldown_start_time AS symbol_wide_live_loss_prevention_cooldown_start_time,
                    lss.monitor_follow,
                    lss.monitor_follow_id,
                    lss.loss_prevention_updated_at
                FROM users.monitor_list_{user_number} AS ml
                LEFT JOIN live_data.live_symbol_status AS lss
                  ON UPPER(lss.symbol) = UPPER(ml.symbol)
                WHERE ml.status != 'ARCHIVED'
                ORDER BY ml.dashboard_order, ml.id
            """


def get_monitors_api_payload(user_number: str) -> Dict[str, Any]:
    """Return the JSON-serializable dict for GET /api/monitors (includes NEW_MONITOR row)."""
    conn = get_postgresql_connection()
    if not conn:
        _log.error(
            "get_monitors: database connection unavailable "
            "(check main_app logs for 'Failed to open tenant PostgreSQL connection')"
        )
        return {
            "status": "error",
            "message": "Database connection failed",
        }

    with conn.cursor() as cursor:
        cursor.execute(_monitor_list_select_sql(user_number))
        results: List[Any] = cursor.fetchall()

        strict_pipeline_health = strike_pipeline_health_strict_mode_enabled()
        # Per (symbol, market): hourly monitors must not inherit 15m pipeline failures (and vice versa).
        health_by_symbol_market: Dict[Tuple[str, str], Dict[str, Any]] = {}
        if strict_pipeline_health:
            sym_mkt_pairs = sorted(
                {
                    (str(r[2]).upper(), str(r[29] or "").strip().lower())
                    for r in results
                    if r[2] and (str(r[29] or "").strip().lower() in ("15m", "hourly"))
                }
            )
            for sym, mkt in sym_mkt_pairs:
                try:
                    ok, rsn = evaluate_pipeline_gate_conn(
                        conn, exchange="kalshi", market=mkt, symbol=sym
                    )
                except Exception as exc:
                    # Never fail GET /api/monitors because pipeline-health or spot-gate SQL errored
                    # (tenant search_path, missing table/column, permissions, etc.).
                    _log.exception(
                        "monitor_list pipeline_gate_conn failed sym=%s mkt=%s: %s",
                        sym,
                        mkt,
                        exc,
                    )
                    ok, rsn = False, f"pipeline_gate_exception:{exc}"
                health_by_symbol_market[(sym, mkt)] = {
                    "healthy": ok,
                    "state": "healthy" if ok else "degraded",
                    "reason": "ok" if ok else rsn,
                    "age_sec": None,
                }

    conn.close()

    monitors: List[Dict[str, Any]] = []
    for row in results:
        (
            monitor_id,
            name,
            symbol,
            strategy,
            auto_trade,
            auto_trade_status,
            trades,
            win_loss,
            ret_pct,
            pnl,
            bankroll_allotment_pct,
            status,
            dashboard_order,
            win_streak,
            loss_prevention_state,
            computed_local_loss_prevention_state,
            loss_prevention_toggle,
            loss_prevention_method,
            created,
            cooldown_timer,
            current_contract,
            current_weekly_cycle,
            current_performance_modifier,
            current_max_pct_exposure,
            performance_based_allocation,
            paper_trade,
            test_filter,
            regime_monitor_enabled,
            regime_window,
            market,
            simulated_trade_loss_prevention,
            loss_prevention_duration,
            simulated_loss_prevention_cooldown_start_time,
            original_loss_prevention_cooldown_start_time,
            loss_prevention_cooldown_loss_count,
            live_loss_prevention_cooldown_start_time,
            simulated_loss_prevention_cooldown_live,
            live_loss_prevention_cooldown_live,
            symbol_wide_loss_prevention,
            symbol_wide_loss_prevention_raw_state,
            symbol_wide_loss_prevention_duration,
            symbol_wide_simulated_loss_prevention_cooldown_start_time,
            symbol_wide_original_loss_prevention_cooldown_start_time,
            symbol_wide_loss_prevention_cooldown_loss_count,
            symbol_wide_live_loss_prevention_cooldown_start_time,
            symbol_wide_monitor_follow,
            symbol_wide_monitor_follow_id,
            symbol_wide_loss_prevention_updated_at,
        ) = row

        local_loss_prevention_state = (
            computed_local_loss_prevention_state
            if is_symbol_wide_loss_prevention_state(loss_prevention_state)
            else loss_prevention_state
        )
        symbol_state_out = symbol_wide_loss_prevention_state(symbol_wide_loss_prevention_raw_state)
        effective_state_out = more_serious_loss_prevention_state(
            local_loss_prevention_state,
            symbol_state_out,
        )
        effective_base_state = normalize_loss_prevention_state_for_sizing(effective_state_out)
        symbol_base_state = normalize_loss_prevention_state_for_sizing(symbol_state_out)
        symbol_wide_active = (
            bool(symbol_wide_loss_prevention)
            and symbol_base_state != "off"
            and effective_state_out == symbol_state_out
        )
        if symbol_wide_active:
            loss_prevention_out = effective_state_out
            effective_loss_prevention_duration = (
                symbol_wide_loss_prevention_duration or loss_prevention_duration
            )
            effective_simulated_loss_prevention_cooldown_start_time = (
                symbol_wide_simulated_loss_prevention_cooldown_start_time
            )
            effective_original_loss_prevention_cooldown_start_time = (
                symbol_wide_original_loss_prevention_cooldown_start_time
            )
            effective_loss_prevention_cooldown_loss_count = (
                symbol_wide_loss_prevention_cooldown_loss_count or 0
            )
            effective_live_loss_prevention_cooldown_start_time = (
                symbol_wide_live_loss_prevention_cooldown_start_time
            )
            effective_simulated_loss_prevention_cooldown_live = symbol_base_state.startswith("sim_loss_")
            effective_live_loss_prevention_cooldown_live = symbol_base_state == "live_loss_1c"
        elif bool(symbol_wide_loss_prevention) and effective_base_state != "off":
            loss_prevention_out = effective_state_out
            effective_loss_prevention_duration = loss_prevention_duration
            effective_simulated_loss_prevention_cooldown_start_time = (
                simulated_loss_prevention_cooldown_start_time
            )
            effective_original_loss_prevention_cooldown_start_time = (
                original_loss_prevention_cooldown_start_time
            )
            effective_loss_prevention_cooldown_loss_count = loss_prevention_cooldown_loss_count or 0
            effective_live_loss_prevention_cooldown_start_time = (
                live_loss_prevention_cooldown_start_time
            )
            effective_simulated_loss_prevention_cooldown_live = effective_base_state.startswith("sim_loss_")
            effective_live_loss_prevention_cooldown_live = effective_base_state == "live_loss_1c"
        else:
            loss_prevention_out = local_loss_prevention_state
            effective_loss_prevention_duration = loss_prevention_duration
            effective_simulated_loss_prevention_cooldown_start_time = (
                simulated_loss_prevention_cooldown_start_time
            )
            effective_original_loss_prevention_cooldown_start_time = (
                original_loss_prevention_cooldown_start_time
            )
            effective_loss_prevention_cooldown_loss_count = loss_prevention_cooldown_loss_count or 0
            effective_live_loss_prevention_cooldown_start_time = (
                live_loss_prevention_cooldown_start_time
            )
            effective_simulated_loss_prevention_cooldown_live = bool(
                simulated_loss_prevention_cooldown_live
            )
            effective_live_loss_prevention_cooldown_live = bool(live_loss_prevention_cooldown_live)
        sw_live = (
            bool(effective_simulated_loss_prevention_cooldown_live)
            or bool(effective_live_loss_prevention_cooldown_live)
        )

        uptime_str = "0d 0h 0m"
        if created:
            now = now_est()
            if isinstance(created, str):
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            else:
                created_dt = created

            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=EST)
            else:
                created_dt = created_dt.astimezone(EST)

            diff = now - created_dt
            days = diff.days
            hours = diff.seconds // 3600
            minutes = (diff.seconds % 3600) // 60
            uptime_str = f"{days}d {hours}h {minutes}m"

        formatted_monitor: Dict[str, Any] = {
            "id": f"mon_{user_number}_{monitor_id}",
            "symbol": symbol,
            "strategy": strategy,
            "status": status,
            "autoTrade": auto_trade,
            "trades": trades,
            "winRate": f"{win_loss}%" if win_loss is not None else "0%",
            "return": f"{ret_pct}%" if ret_pct is not None else "0%",
            "pnl": f"${round(float(pnl)):,}" if pnl is not None else "$0",
            "uptime": uptime_str,
            "name": name,
            "bankroll_allotment": bankroll_allotment_pct,
            "auto_trade_status": auto_trade_status,
            "dashboard_order": dashboard_order or 0,
            "win_streak": win_streak or 0,
            "loss_prevention": loss_prevention_out,
            "loss_prevention_state": loss_prevention_out,
            "local_loss_prevention_state": local_loss_prevention_state,
            "loss_prevention_toggle": bool(loss_prevention_toggle),
            "loss_prevention_method": str(loss_prevention_method or "win_streak"),
            "cooldown_timer": cooldown_timer or 0,
            "current_contract": current_contract,
            "current_weekly_cycle": current_weekly_cycle,
            "current_performance_modifier": current_performance_modifier,
            "current_max_pct_exposure": current_max_pct_exposure,
            "performance_based_allocation": performance_based_allocation,
            "paper_trade": (
                True
                if (is_paper_trading() and status == "active")
                else bool((paper_trade or False) or (test_filter or False))
            ),
            "test_filter": bool(test_filter) if test_filter is not None else False,
            "regime_monitor_enabled": regime_monitor_enabled or False,
            "regime_window": regime_window or "30d",
            "market": (market or "").strip().lower() if market else None,
            "symbol_wide_loss_prevention": bool(symbol_wide_loss_prevention),
            "symbol_wide_loss_prevention_state": symbol_state_out,
            "symbol_wide_loss_prevention_active": symbol_wide_active,
            "symbol_wide_monitor_follow": symbol_wide_monitor_follow,
            "symbol_wide_monitor_follow_id": symbol_wide_monitor_follow_id,
            "symbol_wide_loss_prevention_updated_at": (
                timestamptz_wire_iso_et(symbol_wide_loss_prevention_updated_at)
                if hasattr(symbol_wide_loss_prevention_updated_at, "isoformat")
                else symbol_wide_loss_prevention_updated_at
            ),
            "loss_prevention_duration": int(effective_loss_prevention_duration)
            if effective_loss_prevention_duration is not None
            else 4,
            # Backward-compatible duration alias for clients that have not yet renamed.
            "simulated_trade_cooldown_duration": int(effective_loss_prevention_duration)
            if effective_loss_prevention_duration is not None
            else 4,
            "simulated_loss_prevention_cooldown_start_time": (
                timestamptz_wire_iso_et(effective_simulated_loss_prevention_cooldown_start_time)
                if hasattr(effective_simulated_loss_prevention_cooldown_start_time, "isoformat")
                else effective_simulated_loss_prevention_cooldown_start_time
            ),
            "simulated_trade_cooldown_start_time": (
                timestamptz_wire_iso_et(effective_simulated_loss_prevention_cooldown_start_time)
                if hasattr(effective_simulated_loss_prevention_cooldown_start_time, "isoformat")
                else effective_simulated_loss_prevention_cooldown_start_time
            ),
            "original_loss_prevention_cooldown_start_time": (
                timestamptz_wire_iso_et(effective_original_loss_prevention_cooldown_start_time)
                if hasattr(effective_original_loss_prevention_cooldown_start_time, "isoformat")
                else effective_original_loss_prevention_cooldown_start_time
            ),
            "original_simulated_trade_cooldown_start_time": (
                timestamptz_wire_iso_et(effective_original_loss_prevention_cooldown_start_time)
                if hasattr(effective_original_loss_prevention_cooldown_start_time, "isoformat")
                else effective_original_loss_prevention_cooldown_start_time
            ),
            "loss_prevention_cooldown_loss_count": int(effective_loss_prevention_cooldown_loss_count or 0),
            "simulated_trade_cooldown_loss_count": int(effective_loss_prevention_cooldown_loss_count or 0),
            "live_loss_prevention_cooldown_start_time": (
                timestamptz_wire_iso_et(effective_live_loss_prevention_cooldown_start_time)
                if hasattr(effective_live_loss_prevention_cooldown_start_time, "isoformat")
                else effective_live_loss_prevention_cooldown_start_time
            ),
            "live_trade_cooldown_start_time": (
                timestamptz_wire_iso_et(effective_live_loss_prevention_cooldown_start_time)
                if hasattr(effective_live_loss_prevention_cooldown_start_time, "isoformat")
                else effective_live_loss_prevention_cooldown_start_time
            ),
            "simulated_loss_prevention_cooldown_live": bool(effective_simulated_loss_prevention_cooldown_live),
            "live_loss_prevention_cooldown_live": bool(effective_live_loss_prevention_cooldown_live),
            "simulated_trade_cooldown_live": bool(effective_simulated_loss_prevention_cooldown_live),
            "live_trade_cooldown_live": bool(effective_live_loss_prevention_cooldown_live),
            # Backward-compatible aliases (same values as simulated_trade_*)
            "simulated_trade_loss_prevention": bool(simulated_trade_loss_prevention)
            if simulated_trade_loss_prevention is not None
            else False,
            "symbol_wide_cooldown_duration": int(effective_loss_prevention_duration)
            if effective_loss_prevention_duration is not None
            else 4,
            "symbol_wide_cooldown_start_time": (
                timestamptz_wire_iso_et(effective_simulated_loss_prevention_cooldown_start_time)
                if hasattr(effective_simulated_loss_prevention_cooldown_start_time, "isoformat")
                else effective_simulated_loss_prevention_cooldown_start_time
            ),
            "symbol_wide_cooldown_live": symbol_wide_active or sw_live,
        }

        monitor_market = formatted_monitor.get("market")
        monitor_symbol = str(symbol or "").upper()
        if monitor_market in ("15m", "hourly"):
            if not strict_pipeline_health:
                formatted_monitor["monitor_healthy"] = True
                formatted_monitor["monitor_health_state"] = "healthy"
                formatted_monitor["monitor_health_reason"] = "strict_mode_off"
                formatted_monitor["monitor_health_age_sec"] = 0.0
            else:
                h = health_by_symbol_market.get((monitor_symbol, monitor_market))
                if h:
                    formatted_monitor["monitor_healthy"] = bool(h["healthy"])
                    formatted_monitor["monitor_health_state"] = h["state"]
                    formatted_monitor["monitor_health_reason"] = h["reason"]
                    formatted_monitor["monitor_health_age_sec"] = h["age_sec"]
                else:
                    formatted_monitor["monitor_healthy"] = False
                    formatted_monitor["monitor_health_state"] = "degraded"
                    formatted_monitor["monitor_health_reason"] = "pipeline_health_missing"
                    formatted_monitor["monitor_health_age_sec"] = None
        else:
            formatted_monitor["monitor_healthy"] = True
            formatted_monitor["monitor_health_state"] = "healthy"
            formatted_monitor["monitor_health_reason"] = "not_ws_gated_market"
            formatted_monitor["monitor_health_age_sec"] = 0.0
        monitors.append(formatted_monitor)

    monitors.append(
        {
            "id": "NEW_MONITOR",
            "symbol": "+",
            "strategy": "NEW MONITOR",
            "status": "new",
            "autoTrade": False,
            "trades": "",
            "winRate": "",
            "return": "",
            "pnl": "",
            "uptime": "",
            "name": "NEW_MONITOR",
            "bankroll_allotment": 0,
            "auto_trade_status": "inactive",
        }
    )

    return {
        "status": "ok",
        "user_id": f"user_{user_number}",
        "count": len(monitors) - 1,
        "monitors": monitors,
        "global_paper_mode": is_paper_trading(),
    }
