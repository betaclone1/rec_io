"""
Payload builder for GET /api/monitors.

Keeps monitor-list SQL, symbol-wide cooldown projection, and row formatting out of main_app.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from backend.core.config.database import get_postgresql_connection
from backend.core.strike_pipeline_health import (
    evaluate_symbol_pipeline_gate_conn,
    strike_pipeline_health_strict_mode_enabled,
)
from backend.core.time_eastern import EST, now_est
from backend.trading_mode import is_paper_trading

_log = logging.getLogger(__name__)


def _monitor_list_select_sql(user_number: str) -> str:
    return f"""
                SELECT
                    id,
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
                    loss_prevention,
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
                    symbol_wide_loss_prevention,
                    symbol_wide_cooldown_duration,
                    symbol_wide_cooldown_start_time,
                    (
                        COALESCE(symbol_wide_loss_prevention, FALSE)
                        AND symbol_wide_cooldown_start_time IS NOT NULL
                        AND COALESCE(symbol_wide_cooldown_duration, 0) > 0
                        AND (
                            symbol_wide_cooldown_start_time
                            + (
                                COALESCE(symbol_wide_cooldown_duration, 0) || ' hours'
                            )::interval
                        ) > NOW()
                    ) AS symbol_wide_cooldown_live
                FROM users.monitor_list_{user_number}
                WHERE status != 'ARCHIVED'
                ORDER BY dashboard_order, id
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
        health_by_symbol: Dict[str, Any] = {}
        if strict_pipeline_health:
            symbols = sorted(
                {
                    str(r[2]).upper()
                    for r in results
                    if r[2] and ((str(r[27] or "").strip().lower()) in ("15m", "hourly"))
                }
            )
            for sym in symbols:
                ok, rsn = evaluate_symbol_pipeline_gate_conn(conn, exchange="kalshi", symbol=sym)
                health_by_symbol[sym] = {
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
            loss_prevention,
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
            symbol_wide_loss_prevention,
            symbol_wide_cooldown_duration,
            symbol_wide_cooldown_start_time,
            symbol_wide_cooldown_live,
        ) = row

        sw_live = bool(symbol_wide_cooldown_live)
        loss_prevention_out = "symbol_one_contract" if sw_live else loss_prevention

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
            "symbol_wide_loss_prevention": bool(symbol_wide_loss_prevention)
            if symbol_wide_loss_prevention is not None
            else False,
            "symbol_wide_cooldown_duration": int(symbol_wide_cooldown_duration)
            if symbol_wide_cooldown_duration is not None
            else 4,
            "symbol_wide_cooldown_start_time": (
                symbol_wide_cooldown_start_time.isoformat()
                if hasattr(symbol_wide_cooldown_start_time, "isoformat")
                else symbol_wide_cooldown_start_time
            ),
            "symbol_wide_cooldown_live": sw_live,
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
                h = health_by_symbol.get(monitor_symbol)
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
