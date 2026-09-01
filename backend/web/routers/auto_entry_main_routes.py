"""Auto-entry monitor_list reads/writes, read_api auto-stop accuracy proxy, trigger_open_trade."""

import asyncio
import logging
import uuid
from typing import Any, Dict

import requests
from fastapi import APIRouter, Request

from backend.core.config.database import get_postgresql_connection
from backend.core.time_eastern import timestamptz_wire_iso_et
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
            tenant_user_no = effective_tenant_context_for_sql_rewrite().user_no
            ml = legacy_users_monitor_list(tenant_user_no)
            q = (
                """
                SELECT min_probability, max_probability, min_differential, max_differential, min_time, max_time, allow_re_entry,
                       spike_alert_enabled, spike_alert_momentum_threshold,
                       spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                       current_probability, min_ttc_seconds, momentum_spike_enabled,
                       momentum_spike_threshold, entry_verification_period_enabled, entry_verification_period_seconds,
                       min_volume, win_streak_threshold, performance_based_allocation,
                       momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount, momentum_scalp_profit_target,
                       min_ask, max_ask, loss_prevention_toggle, max_price_spread, prob_adj,
                       min_cooldown_timer, max_cooldown_timer,
                       regime_monitor_enabled, regime_window, stop_loss_price, min_ask_range,
                       test_filter, reverse, time_in_force, order_type, min_fill_price,
                       name, symbol
            """
                + (sel_flip if has_flip else "")
                + """
                       , simulated_trade_loss_prevention, loss_prevention_duration, simulated_loss_prevention_cooldown_start_time,
                         COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak'),
                         COALESCE(symbol_wide_loss_prevention, FALSE),
                         min_slippage, min_movement, max_movement, limit_close_price, limit_close_offset,
                         stop_loss_offset, min_buffer_pct, stop_verification_period_enabled,
                         stop_verification_period_seconds, weekend_adjustment, monitor_dupe_pairing
            """
                + f"""
                FROM {ml} WHERE id = %s
            """
            )
            cursor.execute(q, (monitor_id,))
            result = cursor.fetchone()

            if result:
                monitor_name = str(result[39] or "").strip()
                monitor_symbol = str(result[40] or "").strip().upper()
                symbol_wide_hero = False
                symbol_wide_monitor_follow = None
                symbol_wide_monitor_follow_id = None
                if str(tenant_user_no or "").zfill(4) == "0001" and monitor_name and monitor_symbol:
                    cursor.execute(
                        """
                        SELECT monitor_follow, monitor_follow_id
                        FROM live_data.live_symbol_status
                        WHERE UPPER(symbol) = %s
                        LIMIT 1
                        """,
                        (monitor_symbol,),
                    )
                    follow_row = cursor.fetchone()
                    if follow_row:
                        symbol_wide_monitor_follow = follow_row[0]
                        symbol_wide_monitor_follow_id = follow_row[1]
                        symbol_wide_hero = (
                            str(symbol_wide_monitor_follow or "").strip() == monitor_name
                        )

                def _f(v):
                    return float(v) if v is not None else None

                def _b(v):
                    return bool(v) if v is not None else None

                def _s(v):
                    return str(v) if v is not None else None

                # Pass-through from monitor_list only — never invent UI/strategy defaults.
                row = {
                    "min_probability": _f(result[0]),
                    "max_probability": _f(result[1]),
                    "min_differential": _f(result[2]),
                    "max_differential": _f(result[3]),
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
                    "entry_verification_period_enabled": result[15],
                    "entry_verification_period_seconds": result[16],
                    "min_volume": result[17],
                    "win_streak_threshold": result[18],
                    "performance_based_allocation": result[19],
                    "momentum_scalp_entry_threshold": _f(result[20]),
                    "momentum_scalp_trailing_stop_amount": _f(result[21]),
                    "momentum_scalp_profit_target": _f(result[22]),
                    "min_ask": _f(result[23]),
                    "max_ask": _f(result[24]),
                    "loss_prevention_toggle": _b(result[25]),
                    "max_price_spread": _f(result[26]),
                    "prob_adj": _f(result[27]),
                    "min_cooldown_timer": result[28],
                    "max_cooldown_timer": result[29],
                    "regime_monitor_enabled": _b(result[30]),
                    "regime_window": _s(result[31]),
                    "stop_loss_price": _f(result[32]),
                    "min_ask_range": _f(result[33]),
                    "test_filter": _b(result[34]),
                    "reverse": _b(result[35]),
                    "time_in_force": _s(result[36]),
                    "order_type": _s(result[37]),
                    "min_fill_price": _f(result[38]),
                    "name": monitor_name,
                    "symbol": monitor_symbol,
                }
                if has_flip:
                    row["flip_sell_prob"] = _b(result[41])
                    row["flip_sell_prob_mult"] = _s(result[42])
                    row["flip_sell_floor"] = _b(result[43])
                    row["flip_sell_floor_mult"] = _s(result[44])
                    _sw_i = 45
                else:
                    row["flip_sell_prob"] = None
                    row["flip_sell_prob_mult"] = None
                    row["flip_sell_floor"] = None
                    row["flip_sell_floor_mult"] = None
                    _sw_i = 41
                st_on = _b(result[_sw_i])
                st_dur = int(result[_sw_i + 1]) if result[_sw_i + 1] is not None else None
                st_start = result[_sw_i + 2]
                lp_method = _s(result[_sw_i + 3])
                symbol_wide_on = _b(result[_sw_i + 4])
                row["min_slippage"] = _f(result[_sw_i + 5])
                row["min_movement"] = _f(result[_sw_i + 6])
                row["max_movement"] = _f(result[_sw_i + 7])
                row["limit_close_price"] = _f(result[_sw_i + 8])
                row["limit_close_offset"] = _f(result[_sw_i + 9])
                row["stop_loss_offset"] = _f(result[_sw_i + 10])
                row["min_buffer_pct"] = _f(result[_sw_i + 11])
                row["stop_verification_period_enabled"] = _b(result[_sw_i + 12])
                svs = result[_sw_i + 13]
                row["stop_verification_period_seconds"] = int(svs) if svs is not None else None
                row["weekend_adjustment"] = _s(result[_sw_i + 14]) or "none"
                raw_pairs = result[_sw_i + 15]
                row["monitor_dupe_pairing"] = (
                    [int(x) for x in raw_pairs if x is not None] if raw_pairs else []
                )
                st_start_iso = (
                    timestamptz_wire_iso_et(st_start)
                    if hasattr(st_start, "isoformat")
                    else st_start
                )
                row["symbol_wide_loss_prevention"] = symbol_wide_on
                row["symbol_wide_loss_prevention_hero"] = symbol_wide_hero
                row["symbol_wide_monitor_follow"] = symbol_wide_monitor_follow
                row["symbol_wide_monitor_follow_id"] = symbol_wide_monitor_follow_id
                row["loss_prevention_method"] = lp_method
                row["loss_prevention_duration"] = st_dur
                row["simulated_trade_cooldown_duration"] = st_dur
                row["simulated_loss_prevention_cooldown_start_time"] = st_start_iso
                row["simulated_trade_cooldown_start_time"] = st_start_iso
                row["simulated_trade_loss_prevention"] = st_on
                row["symbol_wide_cooldown_duration"] = st_dur
                row["symbol_wide_cooldown_start_time"] = st_start_iso
                conn.close()
                return row
            else:
                conn.close()
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
        result: Dict[str, Any] = {"status": "error", "message": "not applied"}
        try:
            with conn.cursor() as cursor:
                result = apply_auto_entry_settings(cursor, str(monitor_id), data)
            if result.get("status") == "ok":
                conn.commit()
            else:
                conn.rollback()
        finally:
            conn.close()

        if result.get("status") == "ok":
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
        return result

    except Exception as e:
        _log.debug("[Auto Entry Settings] Error updating strategy: %s", e)
        return {"status": "error", "message": str(e)}


@auto_entry_main_router.post("/api/trigger_open_trade")
async def trigger_open_trade(request: Request):
    """Thin delegate to extracted trade action handler."""
    from backend.web.trade_actions import trigger_open_trade_payload

    data = await request.json()
    return await trigger_open_trade_payload(data, _log)
