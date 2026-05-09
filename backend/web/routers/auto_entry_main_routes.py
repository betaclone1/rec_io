"""Auto-entry monitor_list reads/writes, read_api auto-stop accuracy proxy, trigger_open_trade."""

import asyncio
import logging
import uuid
from typing import Any, Dict

import requests
from fastapi import APIRouter, Request

from backend.core.config.database import get_postgresql_connection
from backend.core.port_config import get_port
from backend.core.tenant_context import (
    effective_tenant_context_for_sql_rewrite,
    resolved_tenant_user_no_for_app,
)
from backend.core.tenant_legacy_sql import legacy_users_monitor_list
from backend.web.read_api_proxy import read_api_forward_headers, read_api_query_with_session

_log = logging.getLogger("main_app")
_READ_API_BASE_URL = f"http://127.0.0.1:{get_port('read_api')}"

auto_entry_main_router = APIRouter()


@auto_entry_main_router.get("/api/get_auto_entry_settings")
async def get_auto_entry_settings(monitor_id: str = None):
    """Get auto entry and auto stop settings for a specific monitor from monitor_list table"""
    if not monitor_id:
        return {"status": "error", "message": "Monitor ID required"}

    try:
        from backend.core.auto_entry_settings_store import monitor_list_flip_columns_available

        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            has_flip = monitor_list_flip_columns_available(cursor)
            sel_flip = """
                       , flip_sell_prob, flip_sell_prob_mult, flip_sell_floor, flip_sell_floor_mult
            """
            ml = legacy_users_monitor_list(effective_tenant_context_for_sql_rewrite().user_no)
            q = (
                """
                SELECT min_probability, max_probability, min_differential, max_differential, min_time, max_time, allow_re_entry,
                       spike_alert_enabled, spike_alert_momentum_threshold,
                       spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                       current_probability, min_ttc_seconds, momentum_spike_enabled,
                       momentum_spike_threshold, verification_period_enabled, verification_period_seconds,
                       min_volume, win_streak_threshold, performance_based_allocation,
                       momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount, momentum_scalp_profit_target,
                       min_ask, max_ask, loss_prevention_toggle, max_price_spread, prob_adj,
                       min_cooldown_timer, max_cooldown_timer,
                       regime_monitor_enabled, regime_window, stop_loss_price, min_ask_range,
                       test_filter, time_in_force, order_type
            """
                + (sel_flip if has_flip else "")
                + """
                       , symbol_wide_loss_prevention, symbol_wide_cooldown_duration, symbol_wide_cooldown_start_time
            """
                + f"""
                FROM {ml} WHERE id = %s
            """
            )
            cursor.execute(q, (monitor_id,))
            result = cursor.fetchone()

            conn.close()

            if result:
                row = {
                    "min_probability": float(result[0]) if result[0] is not None else 95.00,
                    "max_probability": float(result[1]) if result[1] is not None else 100.00,
                    "min_differential": float(result[2]) if result[2] else 0.25,
                    "max_differential": float(result[3]) if result[3] is not None else None,
                    "min_time": result[4],
                    "max_time": result[5],
                    "allow_re_entry": result[6],
                    "spike_alert_enabled": result[7],
                    "spike_alert_momentum_threshold": result[8],
                    "spike_alert_cooldown_threshold": result[9],
                    "spike_alert_cooldown_minutes": result[10],
                    "current_probability": result[11],
                    "min_ttc_seconds": result[12],
                    "momentum_spike_enabled": result[13],
                    "momentum_spike_threshold": result[14],
                    "verification_period_enabled": result[15],
                    "verification_period_seconds": result[16],
                    "min_volume": result[17],
                    "win_streak_threshold": result[18],
                    "performance_based_allocation": result[19],
                    "momentum_scalp_entry_threshold": float(result[20]) if result[20] is not None else None,
                    "momentum_scalp_trailing_stop_amount": float(result[21]) if result[21] is not None else None,
                    "momentum_scalp_profit_target": float(result[22]) if result[22] is not None else None,
                    "min_ask": float(result[23]) if result[23] is not None else 0.0000,
                    "max_ask": float(result[24]) if result[24] is not None else 0.9800,
                    "loss_prevention_toggle": bool(result[25]) if result[25] is not None else True,
                    "max_price_spread": float(result[26]) if result[26] is not None else 0.0300,
                    "prob_adj": float(result[27]) if result[27] is not None else 5.00,
                    "min_cooldown_timer": result[28] if result[28] is not None else None,
                    "max_cooldown_timer": result[29] if result[29] is not None else None,
                    "regime_monitor_enabled": bool(result[30]) if result[30] is not None else False,
                    "regime_window": str(result[31]) if result[31] is not None else "30d",
                    "stop_loss_price": float(result[32]) if result[32] is not None else 0.0,
                    "min_ask_range": float(result[33]) if result[33] is not None else None,
                    "test_filter": bool(result[34]) if result[34] is not None else False,
                    "time_in_force": str(result[35]) if result[35] is not None else "fill_or_kill",
                    "order_type": str(result[36]) if result[36] is not None else "market",
                }
                if has_flip:
                    row["flip_sell_prob"] = bool(result[37]) if result[37] is not None else False
                    row["flip_sell_prob_mult"] = str(result[38]) if result[38] is not None else None
                    row["flip_sell_floor"] = bool(result[39]) if result[39] is not None else False
                    row["flip_sell_floor_mult"] = str(result[40]) if result[40] is not None else None
                    _sw_i = 41
                else:
                    row["flip_sell_prob"] = False
                    row["flip_sell_prob_mult"] = None
                    row["flip_sell_floor"] = False
                    row["flip_sell_floor_mult"] = None
                    _sw_i = 37
                row["symbol_wide_loss_prevention"] = (
                    bool(result[_sw_i]) if result[_sw_i] is not None else False
                )
                row["symbol_wide_cooldown_duration"] = (
                    int(result[_sw_i + 1]) if result[_sw_i + 1] is not None else 4
                )
                sw_start = result[_sw_i + 2]
                row["symbol_wide_cooldown_start_time"] = (
                    sw_start.isoformat() if hasattr(sw_start, "isoformat") else sw_start
                )
                return row
            else:
                return {"status": "error", "message": f"Monitor not found: {monitor_id}"}

    except Exception as e:
        _log.debug("[Auto Entry Settings] Error getting monitor settings: %s", e)
        return {"status": "error", "message": str(e)}


@auto_entry_main_router.get("/api/monitor_auto_stop_accuracy")
async def get_monitor_auto_stop_accuracy(request: Request, monitor_id: str = None):
    """Proxy: delegate auto-stop accuracy aggregates to read_api service."""
    try:
        params: Dict[str, Any] = {}
        if monitor_id:
            params["monitor_id"] = monitor_id
        params = read_api_query_with_session(request, params)

        def _do_accuracy() -> Any:
            resp = requests.get(
                f"{_READ_API_BASE_URL}/api/monitor_auto_stop_accuracy",
                params=params,
                headers=read_api_forward_headers(request),
                timeout=5,
            )
            resp.raise_for_status()
            return resp.json()

        return await asyncio.to_thread(_do_accuracy)
    except Exception as e:
        _log.warning("[read_api proxy] Error getting monitor_auto_stop_accuracy from read_api: %s", e)
        return {"status": "error", "message": "read_api proxy failed for /api/monitor_auto_stop_accuracy"}


@auto_entry_main_router.post("/api/set_auto_entry_settings")
async def set_auto_entry_settings(request: Request):
    data = await request.json()

    monitor_id = data.get("monitor_id")
    if not monitor_id:
        return {"status": "error", "message": "Monitor ID required"}

    try:
        from backend.core.auto_entry_settings_store import (
            apply_auto_entry_settings,
            trigger_regime_reconcile_after_auto_entry_save,
        )
        from backend.core.trading_redis_comms import (
            publish_auto_entry_settings_job,
            redis_client_optional,
            use_trading_redis_comms,
            wait_auto_entry_settings_ack,
        )

        if use_trading_redis_comms() and redis_client_optional():
            cid = str(uuid.uuid4())
            if publish_auto_entry_settings_job(
                str(monitor_id),
                data,
                cid,
                user_number=resolved_tenant_user_no_for_app(),
            ):
                ack = wait_auto_entry_settings_ack(cid)
                if ack is not None:
                    return ack
            _log.debug(
                "[Auto Entry Settings] Redis path unavailable or timed out; applying in main"
            )

        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                result = apply_auto_entry_settings(cursor, str(monitor_id), data)
            if result.get("status") == "ok":
                conn.commit()
                trigger_regime_reconcile_after_auto_entry_save(
                    str(monitor_id),
                    user_number=resolved_tenant_user_no_for_app(),
                    source="set_auto_entry_settings",
                )
                _log.debug(
                    "[Auto Entry & Auto Stop Settings] Updated monitor %s: %s",
                    monitor_id,
                    list(data.keys()),
                )
            else:
                conn.rollback()
            return result
        finally:
            conn.close()

    except Exception as e:
        _log.debug("[Auto Entry Settings] Error updating strategy: %s", e)
        return {"status": "error", "message": str(e)}


@auto_entry_main_router.post("/api/trigger_open_trade")
async def trigger_open_trade(request: Request):
    """Thin delegate to extracted trade action handler."""
    from backend.web.trade_actions import trigger_open_trade_payload

    data = await request.json()
    return await trigger_open_trade_payload(data, _log)
