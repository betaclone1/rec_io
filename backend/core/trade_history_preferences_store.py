"""Tenant trade history UI preferences (PostgreSQL `users.trade_history_preferences_*`).

Used by main_app and read_api for /api/get|set_trade_history_preferences (browser should hit main).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

import psycopg2
from psycopg2.extras import Json

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_context import resolved_tenant_user_no_for_app

logger = logging.getLogger(__name__)


def get_trade_history_preferences_postgresql() -> Dict[str, Any]:
    """Get trade history preferences from PostgreSQL."""
    try:
        conn = get_postgresql_connection()
        un = resolved_tenant_user_no_for_app()
        pref_table = f"users.trade_history_preferences_{un}"
        with conn.cursor() as cursor:
            select_full = f"""
                SELECT date_filter, start_date, end_date, win_filter, loss_filter,
                       contract_9am, contract_10am, contract_11am, contract_12am,
                       contract_1pm, contract_2pm, contract_3pm, contract_4pm,
                       contract_5pm, contract_6pm, contract_7pm, contract_8pm,
                       contract_9pm, contract_10pm, contract_11pm,
                       symbol_btc, symbol_eth, symbol_spy, symbol_ndx, symbol_usd_eur,
                       strategy_hourly_htc, strategy_momentum_scalp, strategy_test,
                       day_sunday, day_monday, day_tuesday, day_wednesday, day_thursday, day_friday, day_saturday,
                       analysis_interval, sort_key, sort_asc, page_size, last_search_timestamp, chart_view, pct_mode,
                       live_filter, paper_filter, include_test_trades,
                       COALESCE(strategy_selection, '{{}}'::jsonb),
                       COALESCE(symbol_selection, '{{}}'::jsonb),
                       COALESCE(monitor_selection, '{{}}'::jsonb)
                FROM {pref_table} WHERE id = 1
            """
            # Full query minus monitor_selection only (when that column is not migrated yet).
            select_with_strategy = f"""
                SELECT date_filter, start_date, end_date, win_filter, loss_filter,
                       contract_9am, contract_10am, contract_11am, contract_12am,
                       contract_1pm, contract_2pm, contract_3pm, contract_4pm,
                       contract_5pm, contract_6pm, contract_7pm, contract_8pm,
                       contract_9pm, contract_10pm, contract_11pm,
                       symbol_btc, symbol_eth, symbol_spy, symbol_ndx, symbol_usd_eur,
                       strategy_hourly_htc, strategy_momentum_scalp, strategy_test,
                       day_sunday, day_monday, day_tuesday, day_wednesday, day_thursday, day_friday, day_saturday,
                       analysis_interval, sort_key, sort_asc, page_size, last_search_timestamp, chart_view, pct_mode,
                       live_filter, paper_filter, include_test_trades,
                       COALESCE(strategy_selection, '{{}}'::jsonb),
                       COALESCE(symbol_selection, '{{}}'::jsonb)
                FROM {pref_table} WHERE id = 1
            """
            select_strategy_only = f"""
                SELECT date_filter, start_date, end_date, win_filter, loss_filter,
                       contract_9am, contract_10am, contract_11am, contract_12am,
                       contract_1pm, contract_2pm, contract_3pm, contract_4pm,
                       contract_5pm, contract_6pm, contract_7pm, contract_8pm,
                       contract_9pm, contract_10pm, contract_11pm,
                       symbol_btc, symbol_eth, symbol_spy, symbol_ndx, symbol_usd_eur,
                       strategy_hourly_htc, strategy_momentum_scalp, strategy_test,
                       day_sunday, day_monday, day_tuesday, day_wednesday, day_thursday, day_friday, day_saturday,
                       analysis_interval, sort_key, sort_asc, page_size, last_search_timestamp, chart_view, pct_mode,
                       live_filter, paper_filter, include_test_trades,
                       COALESCE(strategy_selection, '{{}}'::jsonb)
                FROM {pref_table} WHERE id = 1
            """
            select_without_strategy = f"""
                SELECT date_filter, start_date, end_date, win_filter, loss_filter,
                       contract_9am, contract_10am, contract_11am, contract_12am,
                       contract_1pm, contract_2pm, contract_3pm, contract_4pm,
                       contract_5pm, contract_6pm, contract_7pm, contract_8pm,
                       contract_9pm, contract_10pm, contract_11pm,
                       symbol_btc, symbol_eth, symbol_spy, symbol_ndx, symbol_usd_eur,
                       strategy_hourly_htc, strategy_momentum_scalp, strategy_test,
                       day_sunday, day_monday, day_tuesday, day_wednesday, day_thursday, day_friday, day_saturday,
                       analysis_interval, sort_key, sort_asc, page_size, last_search_timestamp, chart_view, pct_mode,
                       live_filter, paper_filter, include_test_trades
                FROM {pref_table} WHERE id = 1
            """
            result = None
            has_strategy_col = False
            has_symbol_col = False
            has_monitor_col = False
            try:
                cursor.execute(select_full)
                result = cursor.fetchone()
                has_strategy_col = result is not None and len(result) > 45
                has_symbol_col = result is not None and len(result) > 46
                has_monitor_col = result is not None and len(result) > 47
            except psycopg2.ProgrammingError:
                # Failed statement aborts the transaction; must rollback before a fallback SELECT.
                conn.rollback()
                try:
                    cursor.execute(select_with_strategy)
                    result = cursor.fetchone()
                    has_strategy_col = result is not None and len(result) > 45
                    has_symbol_col = result is not None and len(result) > 46
                    has_monitor_col = False
                except psycopg2.ProgrammingError:
                    conn.rollback()
                    try:
                        cursor.execute(select_strategy_only)
                        result = cursor.fetchone()
                        has_strategy_col = result is not None and len(result) > 45
                        has_symbol_col = False
                        has_monitor_col = False
                    except psycopg2.ProgrammingError:
                        conn.rollback()
                        cursor.execute(select_without_strategy)
                        result = cursor.fetchone()
                        has_strategy_col = False
                        has_symbol_col = False
                        has_monitor_col = False
            conn.close()

            if result:
                return {
                    "date_filter": result[0],
                    "start_date": result[1],
                    "end_date": result[2],
                    "win_filter": result[3],
                    "loss_filter": result[4],
                    "contract_9am": result[5],
                    "contract_10am": result[6],
                    "contract_11am": result[7],
                    "contract_12am": result[8],
                    "contract_1pm": result[9],
                    "contract_2pm": result[10],
                    "contract_3pm": result[11],
                    "contract_4pm": result[12],
                    "contract_5pm": result[13],
                    "contract_6pm": result[14],
                    "contract_7pm": result[15],
                    "contract_8pm": result[16],
                    "contract_9pm": result[17],
                    "contract_10pm": result[18],
                    "contract_11pm": result[19],
                    "symbol_btc": result[20],
                    "symbol_eth": result[21],
                    "symbol_spy": result[22],
                    "symbol_ndx": result[23],
                    "symbol_usd_eur": result[24],
                    "strategy_hourly_htc": result[25],
                    "strategy_momentum_scalp": result[26],
                    "strategy_test": result[27],
                    "day_sunday": result[28],
                    "day_monday": result[29],
                    "day_tuesday": result[30],
                    "day_wednesday": result[31],
                    "day_thursday": result[32],
                    "day_friday": result[33],
                    "day_saturday": result[34],
                    "analysis_interval": result[35],
                    "sort_key": result[36],
                    "sort_asc": result[37],
                    "page_size": result[38],
                    "last_search_timestamp": result[39],
                    "chart_view": result[40],
                    "pct_mode": result[41],
                    "live_filter": result[42] if len(result) > 42 else True,
                    "paper_filter": result[43] if len(result) > 43 else False,
                    "include_test_trades": result[44] if len(result) > 44 else False,
                    "strategy_selection": result[45] if has_strategy_col else {},
                    "symbol_selection": result[46] if has_symbol_col else {},
                    "monitor_selection": result[47] if has_monitor_col else {},
                }
            return {
                "date_filter": "TODAY",
                "start_date": None,
                "end_date": None,
                "win_filter": True,
                "loss_filter": True,
                "contract_9am": True,
                "contract_10am": True,
                "contract_11am": True,
                "contract_12am": True,
                "contract_1pm": True,
                "contract_2pm": True,
                "contract_3pm": True,
                "contract_4pm": True,
                "contract_5pm": True,
                "contract_6pm": True,
                "contract_7pm": True,
                "contract_8pm": True,
                "contract_9pm": True,
                "contract_10pm": True,
                "contract_11pm": True,
                "symbol_btc": True,
                "symbol_eth": True,
                "symbol_spy": True,
                "symbol_ndx": True,
                "symbol_usd_eur": True,
                "strategy_hourly_htc": True,
                "strategy_momentum_scalp": True,
                "strategy_test": True,
                "day_sunday": True,
                "day_monday": True,
                "day_tuesday": True,
                "day_wednesday": True,
                "day_thursday": True,
                "day_friday": True,
                "day_saturday": True,
                "analysis_interval": "daily",
                "sort_key": None,
                "sort_asc": True,
                "page_size": 50,
                "last_search_timestamp": int(time.time()),
                "chart_view": "pnl",
                "live_filter": True,
                "paper_filter": False,
                "include_test_trades": False,
                "strategy_selection": {},
                "symbol_selection": {},
                "monitor_selection": {},
            }
    except Exception as e:
        logger.warning("[PostgreSQL Error] Failed to get trade history preferences: %s", e)
        return {
            "date_filter": "TODAY",
            "start_date": None,
            "end_date": None,
            "win_filter": True,
            "loss_filter": True,
            "contract_9am": True,
            "contract_10am": True,
            "contract_11am": True,
            "contract_12am": True,
            "contract_1pm": True,
            "contract_2pm": True,
            "contract_3pm": True,
            "contract_4pm": True,
            "contract_5pm": True,
            "contract_6pm": True,
            "contract_7pm": True,
            "contract_8pm": True,
            "contract_9pm": True,
            "contract_10pm": True,
            "contract_11pm": True,
            "symbol_btc": True,
            "symbol_eth": True,
            "symbol_spy": True,
            "symbol_ndx": True,
            "symbol_usd_eur": True,
            "strategy_hourly_htc": True,
            "strategy_momentum_scalp": True,
            "strategy_test": True,
            "analysis_interval": "daily",
            "sort_key": None,
            "sort_asc": True,
            "page_size": 50,
            "last_search_timestamp": int(time.time()),
            "chart_view": "pnl",
            "live_filter": True,
            "paper_filter": False,
            "include_test_trades": False,
            "strategy_selection": {},
            "symbol_selection": {},
            "monitor_selection": {},
        }


def update_trade_history_preferences_postgresql(**kwargs: Any) -> bool:
    """Update trade history preferences in PostgreSQL using UPSERT. Returns False on failure."""
    conn = None
    try:
        conn = get_postgresql_connection()
        if not conn:
            logger.warning("trade_history_preferences: no DB connection")
            return False
        un = resolved_tenant_user_no_for_app()
        pref_table = f"users.trade_history_preferences_{un}"
        with conn.cursor() as cursor:
            cursor.execute(f"DELETE FROM {pref_table} WHERE id > 1")

            columns = list(kwargs.keys())
            values = list(kwargs.values())
            placeholders = ["%s"] * len(values)

            columns.append("updated_at")
            placeholders.append("CURRENT_TIMESTAMP")

            query = f"""
                INSERT INTO {pref_table} (id, {', '.join(columns)})
                VALUES (1, {', '.join(placeholders)})
                ON CONFLICT (id) DO UPDATE SET
                {', '.join([f"{col} = EXCLUDED.{col}" for col in columns])}
            """

            cursor.execute(query, values)
            conn.commit()
            logger.debug("[PostgreSQL] Updated trade history preferences: %s", kwargs)
        return True
    except Exception as e:
        logger.warning("[PostgreSQL Error] Failed to update trade history preferences: %s", e)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def load_trade_history_preferences() -> Dict[str, Any]:
    """Load trade history preferences from PostgreSQL."""
    try:
        return get_trade_history_preferences_postgresql()
    except Exception as e:
        logger.debug("[Trade History Preferences Load Error] %s", e)
        return {
            "date_filter": "TODAY",
            "start_date": None,
            "end_date": None,
            "win_filter": True,
            "loss_filter": True,
            "contract_9am": True,
            "contract_10am": True,
            "contract_11am": True,
            "contract_12am": True,
            "contract_1pm": True,
            "contract_2pm": True,
            "contract_3pm": True,
            "contract_4pm": True,
            "contract_5pm": True,
            "contract_6pm": True,
            "contract_7pm": True,
            "contract_8pm": True,
            "contract_9pm": True,
            "contract_10pm": True,
            "contract_11pm": True,
            "symbol_btc": True,
            "symbol_eth": True,
            "symbol_spy": True,
            "symbol_ndx": True,
            "symbol_usd_eur": True,
            "strategy_hourly_htc": True,
            "strategy_momentum_scalp": True,
            "strategy_test": True,
            "analysis_interval": "daily",
            "sort_key": None,
            "sort_asc": True,
            "page_size": 50,
            "last_search_timestamp": time.time(),
            "pct_mode": False,
            "live_filter": True,
            "paper_filter": False,
            "include_test_trades": False,
            "strategy_selection": {},
            "symbol_selection": {},
            "monitor_selection": {},
        }


def save_trade_history_preferences(preferences: Dict[str, Any]) -> bool:
    """Save trade history preferences to PostgreSQL. Returns False if the DB write failed."""
    try:
        update_data: Dict[str, Any] = {}
        if "date_filter" in preferences:
            update_data["date_filter"] = str(preferences["date_filter"])
        if "start_date" in preferences:
            update_data["start_date"] = preferences["start_date"]
        if "end_date" in preferences:
            update_data["end_date"] = preferences["end_date"]
        if "win_filter" in preferences:
            update_data["win_filter"] = bool(preferences["win_filter"])
        if "loss_filter" in preferences:
            update_data["loss_filter"] = bool(preferences["loss_filter"])
        if "live_filter" in preferences:
            update_data["live_filter"] = bool(preferences["live_filter"])
        if "paper_filter" in preferences:
            update_data["paper_filter"] = bool(preferences["paper_filter"])
        if "include_test_trades" in preferences:
            update_data["include_test_trades"] = bool(preferences["include_test_trades"])

        contract_fields = [
            "contract_9am",
            "contract_10am",
            "contract_11am",
            "contract_12am",
            "contract_1pm",
            "contract_2pm",
            "contract_3pm",
            "contract_4pm",
            "contract_5pm",
            "contract_6pm",
            "contract_7pm",
            "contract_8pm",
            "contract_9pm",
            "contract_10pm",
            "contract_11pm",
        ]
        for field in contract_fields:
            if field in preferences:
                update_data[field] = bool(preferences[field])

        symbol_fields = [
            "symbol_btc",
            "symbol_eth",
            "symbol_spy",
            "symbol_ndx",
            "symbol_usd_eur",
        ]
        for field in symbol_fields:
            if field in preferences:
                update_data[field] = bool(preferences[field])

        strategy_fields = [
            "strategy_hourly_htc",
            "strategy_momentum_scalp",
            "strategy_test",
        ]
        for field in strategy_fields:
            if field in preferences:
                update_data[field] = bool(preferences[field])
        if "strategy_selection" in preferences and isinstance(
            preferences["strategy_selection"], dict
        ):
            update_data["strategy_selection"] = Json(preferences["strategy_selection"])
        if "symbol_selection" in preferences and isinstance(
            preferences["symbol_selection"], dict
        ):
            update_data["symbol_selection"] = Json(preferences["symbol_selection"])
        # Omit empty map so UPSERT does not reference monitor_selection until the column exists
        # (migration 20260416_1500). Non-empty maps always include at least one monitor key.
        if "monitor_selection" in preferences and isinstance(
            preferences["monitor_selection"], dict
        ) and len(preferences["monitor_selection"]) > 0:
            update_data["monitor_selection"] = Json(preferences["monitor_selection"])

        day_fields = [
            "day_sunday",
            "day_monday",
            "day_tuesday",
            "day_wednesday",
            "day_thursday",
            "day_friday",
            "day_saturday",
        ]
        for field in day_fields:
            if field in preferences:
                update_data[field] = bool(preferences[field])

        if "analysis_interval" in preferences:
            update_data["analysis_interval"] = str(preferences["analysis_interval"])

        if "chart_view" in preferences:
            update_data["chart_view"] = str(preferences["chart_view"])

        if "pct_mode" in preferences:
            update_data["pct_mode"] = bool(preferences["pct_mode"])

        if "sort_key" in preferences:
            update_data["sort_key"] = preferences["sort_key"]
        if "sort_asc" in preferences:
            update_data["sort_asc"] = bool(preferences["sort_asc"])
        if "page_size" in preferences:
            update_data["page_size"] = int(preferences["page_size"])
        if "last_search_timestamp" in preferences:
            update_data["last_search_timestamp"] = int(preferences["last_search_timestamp"])

        if not update_data:
            return True
        ok = update_trade_history_preferences_postgresql(**update_data)
        if ok:
            logger.debug(
                "[Trade History Preferences] Updated PostgreSQL: %s", list(update_data.keys())
            )
        return ok
    except Exception as e:
        logger.warning("[Trade History Preferences Save Error] %s", e)
        return False
