"""
Apply unified auto entry / auto stop fields to tenant ``users.monitor_list_<slot>``.
Used by main_app HTTP and by monitor_manager Redis stream consumer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.core.tenant_context import TenantContext
from backend.core.kalshi_execution_settings import (
    normalize_execution_order_type,
    normalize_kalshi_time_in_force,
)

_log = logging.getLogger(__name__)

# Aligns with trade_manager.update_win_streak_for_cycle: when toggle is on,
# loss_prevention is 'off' iff win_streak >= threshold, else 'one_contract'.


def loss_prevention_value_for_streak(
    win_streak: int, loss_prevention_toggle_on: bool, win_streak_threshold: int
) -> str:
    if not loss_prevention_toggle_on:
        return "off"
    if int(win_streak or 0) >= int(win_streak_threshold):
        return "off"
    return "one_contract"


def trigger_regime_reconcile_after_auto_entry_save(
    monitor_id: str,
    *,
    user_number: Optional[str] = None,
    source: str = "set_auto_entry_settings",
) -> None:
    try:
        import requests
        from backend.core.port_config import get_port
        from backend.trading_mode import _norm_slot

        try:
            un = _norm_slot(user_number or "0001")
        except ValueError:
            un = "0001"

        monitor_manager_port = get_port("monitor_manager")
        requests.post(
            f"http://localhost:{monitor_manager_port}/api/regime/reconcile",
            json={
                "monitor_id": int(monitor_id),
                "user_number": un,
                "full_sweep": False,
                "force_immediate": True,
                "source": source,
            },
            timeout=3,
        )
    except Exception as exc:
        _log.debug("[auto_entry_settings_store] regime reconcile skipped/failed: %s", exc)


def _cursor_tenant_context(cursor):
    ctx = getattr(cursor, "tenant_context", None)
    if ctx is not None:
        return ctx
    from backend.core.tenant_context import worker_tenant_context_cached

    return worker_tenant_context_cached()


def monitor_list_flip_columns_available(
    cursor,
    table_name: Optional[str] = None,
    *,
    tenant_context: Optional[TenantContext] = None,
) -> bool:
    """True when flip_sell_* migration has been applied (avoids broken SELECT/UPDATE on older DBs)."""
    ctx = tenant_context if tenant_context is not None else _cursor_tenant_context(cursor)
    tn = table_name or f"monitor_list_{ctx.user_no}"
    cursor.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = 'flip_sell_prob'
        LIMIT 1
        """,
        (ctx.pg_schema, tn),
    )
    return cursor.fetchone() is not None


def apply_auto_entry_settings(
    cursor,
    monitor_id: str,
    data: Dict[str, Any],
    *,
    tenant_context: Optional[TenantContext] = None,
) -> Dict[str, Any]:
    """
    Build UPDATE from ``data``, execute, return {"status":"ok", ...partial row} or error dict.
    Caller owns transaction (commit/rollback/close).

    Pass ``tenant_context`` when the cursor is a raw psycopg2 cursor (e.g. monitor_manager);
    it cannot carry a ``tenant_context`` attribute. When omitted, uses the cursor's bound
    tenant (e.g. :class:`TenantRewritingCursor`) or the worker default.
    """
    ctx = tenant_context if tenant_context is not None else _cursor_tenant_context(cursor)
    ml = ctx.qualify_raw_table(f"monitor_list_{ctx.user_no}")
    cursor.execute(
        f"""
        SELECT id FROM {ml} WHERE id = %s
        """,
        (monitor_id,),
    )
    if not cursor.fetchone():
        return {"status": "error", "message": f"Monitor not found: {monitor_id}"}

    has_flip_cols = monitor_list_flip_columns_available(cursor, tenant_context=ctx)

    update_fields = []
    update_values = []

    if "regime_monitor_enabled" in data:
        reg_enabled = data["regime_monitor_enabled"]
        if isinstance(reg_enabled, str):
            reg_enabled = reg_enabled.lower() in ("true", "1", "yes")
        update_fields.append("regime_monitor_enabled = %s")
        update_values.append(bool(reg_enabled))

    if "regime_window" in data:
        regime_window = data["regime_window"]
        if regime_window is not None:
            regime_window = str(regime_window).strip()
            allowed = {"30d", "7d", "1d", "12h"}
            if regime_window not in allowed:
                return {
                    "status": "error",
                    "message": f"Invalid regime_window: {regime_window}. Allowed: {sorted(list(allowed))}",
                }
            update_fields.append("regime_window = %s")
            update_values.append(regime_window)

    if "min_probability" in data:
        update_fields.append("min_probability = %s")
        update_values.append(float(data["min_probability"]))
    if "max_probability" in data:
        update_fields.append("max_probability = %s")
        update_values.append(float(data["max_probability"]))
    if "min_differential" in data:
        update_fields.append("min_differential = %s")
        update_values.append(float(data["min_differential"]))
    if "max_differential" in data:
        update_fields.append("max_differential = %s")
        update_values.append(
            float(data["max_differential"]) if data["max_differential"] is not None else None
        )
    if "min_volume" in data:
        update_fields.append("min_volume = %s")
        update_values.append(int(data["min_volume"]))
    if "min_time" in data:
        update_fields.append("min_time = %s")
        update_values.append(int(data["min_time"]))
    if "max_time" in data:
        update_fields.append("max_time = %s")
        update_values.append(int(data["max_time"]))
    if "allow_re_entry" in data:
        update_fields.append("allow_re_entry = %s")
        update_values.append(bool(data["allow_re_entry"]))
    if "win_streak_threshold" in data:
        update_fields.append("win_streak_threshold = %s")
        update_values.append(int(data["win_streak_threshold"]))
    if "spike_alert_enabled" in data:
        update_fields.append("spike_alert_enabled = %s")
        update_values.append(bool(data["spike_alert_enabled"]))
    if "spike_alert_momentum_threshold" in data:
        update_fields.append("spike_alert_momentum_threshold = %s")
        update_values.append(int(data["spike_alert_momentum_threshold"]))
    if "spike_alert_cooldown_threshold" in data:
        update_fields.append("spike_alert_cooldown_threshold = %s")
        update_values.append(int(data["spike_alert_cooldown_threshold"]))
    if "spike_alert_cooldown_minutes" in data:
        update_fields.append("spike_alert_cooldown_minutes = %s")
        update_values.append(int(data["spike_alert_cooldown_minutes"]))

    if "current_probability" in data:
        update_fields.append("current_probability = %s")
        update_values.append(int(data["current_probability"]))
    if "min_ttc_seconds" in data:
        update_fields.append("min_ttc_seconds = %s")
        update_values.append(int(data["min_ttc_seconds"]))
    if "momentum_spike_enabled" in data:
        update_fields.append("momentum_spike_enabled = %s")
        update_values.append(bool(data["momentum_spike_enabled"]))
    if "momentum_spike_threshold" in data:
        update_fields.append("momentum_spike_threshold = %s")
        update_values.append(int(data["momentum_spike_threshold"]))
    if "verification_period_enabled" in data:
        update_fields.append("verification_period_enabled = %s")
        update_values.append(bool(data["verification_period_enabled"]))
    if "verification_period_seconds" in data:
        update_fields.append("verification_period_seconds = %s")
        update_values.append(int(data["verification_period_seconds"]))
    if "performance_based_allocation" in data:
        update_fields.append("performance_based_allocation = %s")
        update_values.append(bool(data["performance_based_allocation"]))

    if "momentum_scalp_entry_threshold" in data:
        update_fields.append("momentum_scalp_entry_threshold = %s")
        update_values.append(float(data["momentum_scalp_entry_threshold"]))
    if "momentum_scalp_trailing_stop_amount" in data:
        update_fields.append("momentum_scalp_trailing_stop_amount = %s")
        update_values.append(float(data["momentum_scalp_trailing_stop_amount"]))
    if "momentum_scalp_profit_target" in data:
        update_fields.append("momentum_scalp_profit_target = %s")
        update_values.append(float(data["momentum_scalp_profit_target"]))
    if "min_ask" in data:
        update_fields.append("min_ask = %s")
        update_values.append(float(data["min_ask"]))
    if "max_ask" in data:
        update_fields.append("max_ask = %s")
        update_values.append(float(data["max_ask"]))
    if "symbol_wide_loss_prevention" in data:
        sw_raw = data["symbol_wide_loss_prevention"]
        if isinstance(sw_raw, str):
            sw_raw = sw_raw.lower() in ("true", "1", "yes")
        sw_b = bool(sw_raw)
        update_fields.append("symbol_wide_loss_prevention = %s")
        update_values.append(sw_b)
        if sw_b:
            eff_dur = None
            if "symbol_wide_cooldown_duration" in data:
                eff_dur = int(data["symbol_wide_cooldown_duration"])
            else:
                cursor.execute(
                    f"SELECT COALESCE(symbol_wide_cooldown_duration, 0) FROM {ml} WHERE id = %s",
                    (monitor_id,),
                )
                dr = cursor.fetchone()
                eff_dur = int(dr[0]) if dr and dr[0] is not None else 0
            if eff_dur < 1:
                return {
                    "status": "error",
                    "message": "symbol_wide_cooldown_duration must be at least 1 hour when symbol-wide loss prevention is enabled",
                }

    if "symbol_wide_cooldown_duration" in data:
        hrs = int(data["symbol_wide_cooldown_duration"])
        if hrs < 1:
            return {
                "status": "error",
                "message": "symbol_wide_cooldown_duration must be at least 1",
            }
        update_fields.append("symbol_wide_cooldown_duration = %s")
        update_values.append(hrs)

    if "loss_prevention_toggle" in data:
        lp_tog = bool(data["loss_prevention_toggle"])
        update_fields.append("loss_prevention_toggle = %s")
        update_values.append(lp_tog)
    if "max_price_spread" in data:
        update_fields.append("max_price_spread = %s")
        update_values.append(float(data["max_price_spread"]))
    if "prob_adj" in data:
        update_fields.append("prob_adj = %s")
        update_values.append(float(data["prob_adj"]))
    if "min_cooldown_timer" in data:
        update_fields.append("min_cooldown_timer = %s")
        update_values.append(
            int(data["min_cooldown_timer"]) if data["min_cooldown_timer"] is not None else None
        )
    if "max_cooldown_timer" in data:
        update_fields.append("max_cooldown_timer = %s")
        update_values.append(
            int(data["max_cooldown_timer"]) if data["max_cooldown_timer"] is not None else None
        )
    if "stop_loss_price" in data:
        slp = float(data["stop_loss_price"])
        if slp < 0 or round(slp, 4) > 0.99:
            return {
                "status": "error",
                "message": "stop_loss_price must be between 0.0000 and 0.9900 (0 disables)",
            }
        update_fields.append("stop_loss_price = %s")
        update_values.append(round(slp, 4))

    if "min_ask_range" in data:
        mar = data["min_ask_range"]
        if mar is None:
            update_fields.append("min_ask_range = %s")
            update_values.append(None)
        else:
            marf = float(mar)
            if marf < 0 or marf > 1.0:
                return {
                    "status": "error",
                    "message": "min_ask_range must be between 0 and 1.0 (null or 0 disables)",
                }
            update_fields.append("min_ask_range = %s")
            update_values.append(round(marf, 4))

    if "test_filter" in data:
        tf = data["test_filter"]
        if isinstance(tf, str):
            tf = tf.lower() in ("true", "1", "yes")
        tf = bool(tf)
        update_fields.append("test_filter = %s")
        update_values.append(tf)
        if tf:
            update_fields.append("paper_trade = %s")
            update_values.append(True)

    if "time_in_force" in data:
        tif = normalize_kalshi_time_in_force(data["time_in_force"])
        if not tif:
            return {"status": "error", "message": "invalid_time_in_force"}
        update_fields.append("time_in_force = %s")
        update_values.append(tif)
    if "order_type" in data:
        ot = normalize_execution_order_type(data["order_type"])
        if not ot:
            return {"status": "error", "message": "invalid_order_type_policy"}
        update_fields.append("order_type = %s")
        update_values.append(ot)

    flip_cur = None
    if has_flip_cols and any(
        k in data
        for k in (
            "flip_sell_prob",
            "flip_sell_floor",
            "flip_sell_prob_mult",
            "flip_sell_floor_mult",
        )
    ):
        cursor.execute(
            f"""
            SELECT flip_sell_prob, flip_sell_prob_mult, flip_sell_floor, flip_sell_floor_mult
            FROM {ml} WHERE id = %s
            """,
            (monitor_id,),
        )
        flip_cur = cursor.fetchone()

    def _flip_bool_payload(v):
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return bool(v)

    if flip_cur is not None:
        old_fp, old_fpm, old_ff, old_ffm = flip_cur
        old_fp = bool(old_fp) if old_fp is not None else False
        old_ff = bool(old_ff) if old_ff is not None else False
    else:
        old_fp, old_fpm, old_ff, old_ffm = (False, None, False, None)

    if has_flip_cols:
        if "flip_sell_prob" in data:
            new_fp = _flip_bool_payload(data["flip_sell_prob"])
            update_fields.append("flip_sell_prob = %s")
            update_values.append(new_fp)
            if new_fp and not old_fp and old_fpm is None and "flip_sell_prob_mult" not in data:
                update_fields.append("flip_sell_prob_mult = %s")
                update_values.append("1x")

        if "flip_sell_prob_mult" in data:
            m = data["flip_sell_prob_mult"]
            update_fields.append("flip_sell_prob_mult = %s")
            update_values.append(
                str(m).strip() if m is not None and str(m).strip() != "" else None
            )

        if "flip_sell_floor" in data:
            new_ff = _flip_bool_payload(data["flip_sell_floor"])
            update_fields.append("flip_sell_floor = %s")
            update_values.append(new_ff)
            if new_ff and not old_ff and old_ffm is None and "flip_sell_floor_mult" not in data:
                update_fields.append("flip_sell_floor_mult = %s")
                update_values.append("1x")

        if "flip_sell_floor_mult" in data:
            m = data["flip_sell_floor_mult"]
            update_fields.append("flip_sell_floor_mult = %s")
            update_values.append(
                str(m).strip() if m is not None and str(m).strip() != "" else None
            )

    # loss_prevention is derived in sync_symbol_wide_after_monitor_settings_save via
    # recompute_monitor_loss_prevention (symbol-wide window overrides win-streak LP).

    if not update_fields:
        return {"status": "error", "message": "No valid fields to update"}

    query = f"UPDATE {ml} SET {', '.join(update_fields)} WHERE id = %s"
    update_values.append(monitor_id)
    cursor.execute(query, update_values)

    trades_tbl = ctx.qualify_raw_table(f"trades_{ctx.user_no}")
    # Local import avoids circular import: symbol_wide_loss_prevention imports
    # loss_prevention_value_for_streak from this module.
    from backend.core.symbol_wide_loss_prevention import (
        sync_symbol_wide_after_monitor_settings_save,
    )

    sync_symbol_wide_after_monitor_settings_save(cursor, ml, trades_tbl, monitor_id)

    sel_base = """
        SELECT min_probability, min_differential, min_time, max_time, allow_re_entry,
               spike_alert_enabled, spike_alert_momentum_threshold,
               spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
               current_probability, min_ttc_seconds, momentum_spike_enabled,
               momentum_spike_threshold, verification_period_enabled, verification_period_seconds,
               min_volume, win_streak_threshold, performance_based_allocation,
               momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount, momentum_scalp_profit_target,
               regime_monitor_enabled, regime_window, stop_loss_price,
               time_in_force, order_type
    """
    sel_flip = """
               , flip_sell_prob, flip_sell_prob_mult, flip_sell_floor, flip_sell_floor_mult
    """
    cursor.execute(
        (sel_base + (sel_flip if has_flip_cols else "") + f"""
        FROM {ml} WHERE id = %s
        """).replace("\n", " "),
        (monitor_id,),
    )
    updated_result = cursor.fetchone()
    if not updated_result:
        return {"status": "error", "message": "Failed to retrieve updated settings"}

    out = {
        "status": "ok",
        "min_probability": updated_result[0],
        "min_differential": float(updated_result[1]),
        "min_time": updated_result[2],
        "max_time": updated_result[3],
        "allow_re_entry": updated_result[4],
        "spike_alert_enabled": updated_result[5],
        "spike_alert_momentum_threshold": updated_result[6],
        "spike_alert_cooldown_threshold": updated_result[7],
        "spike_alert_cooldown_minutes": updated_result[8],
        "current_probability": updated_result[9],
        "min_ttc_seconds": updated_result[10],
        "momentum_spike_enabled": updated_result[11],
        "momentum_spike_threshold": updated_result[12],
        "verification_period_enabled": updated_result[13],
        "verification_period_seconds": updated_result[14],
        "min_volume": updated_result[15],
        "win_streak_threshold": updated_result[16],
        "performance_based_allocation": updated_result[17],
        "momentum_scalp_entry_threshold": float(updated_result[18]) if updated_result[18] is not None else None,
        "momentum_scalp_trailing_stop_amount": float(updated_result[19]) if updated_result[19] is not None else None,
        "momentum_scalp_profit_target": float(updated_result[20]) if updated_result[20] is not None else None,
        "regime_monitor_enabled": bool(updated_result[21]) if updated_result[21] is not None else False,
        "regime_window": str(updated_result[22]) if updated_result[22] is not None else "30d",
        "stop_loss_price": float(updated_result[23]) if updated_result[23] is not None else 0.0,
        "time_in_force": str(updated_result[24]) if updated_result[24] is not None else "fill_or_kill",
        "order_type": str(updated_result[25]) if updated_result[25] is not None else "market",
    }
    if has_flip_cols:
        out["flip_sell_prob"] = bool(updated_result[26]) if updated_result[26] is not None else False
        out["flip_sell_prob_mult"] = str(updated_result[27]) if updated_result[27] is not None else None
        out["flip_sell_floor"] = bool(updated_result[28]) if updated_result[28] is not None else False
        out["flip_sell_floor_mult"] = str(updated_result[29]) if updated_result[29] is not None else None
    else:
        out["flip_sell_prob"] = False
        out["flip_sell_prob_mult"] = None
        out["flip_sell_floor"] = False
        out["flip_sell_floor_mult"] = None
    return out
