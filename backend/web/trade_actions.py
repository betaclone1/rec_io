from typing import Any, Dict

import requests

from backend.core.config.database import get_postgresql_connection
from backend.core.exchange_ids import normalize_exchange
from backend.core.tenant_context import effective_tenant_context_for_sql_rewrite, resolved_tenant_user_no_for_app
from backend.core.tenant_legacy_sql import legacy_users_monitor_list
from backend.core.time_eastern import now_est
from backend.core.port_config import get_port
from backend.util.paths import get_host


async def trigger_open_trade_payload(data: Dict[str, Any], logger) -> Dict[str, Any]:
    """Behavior-preserving extraction of main_app /api/trigger_open_trade."""
    try:
        strike = data.get("strike")
        side = data.get("side")
        ticker = data.get("ticker")
        buy_price = data.get("buy_price")
        prob = data.get("prob")
        symbol_open = data.get("symbol_open")
        momentum = data.get("momentum")
        contract = data.get("contract")
        symbol = data.get("symbol")
        position = data.get("position")
        trade_strategy = data.get("trade_strategy")
        paper_trade = data.get("paper_trade", False)

        logger.debug(
            "[TRIGGER OPEN TRADE] Received request: strike=%s, side=%s, ticker=%s, buy_price=%s, prob=%s, symbol_open=%s, momentum=%s, paper_trade=%s",
            strike,
            side,
            ticker,
            buy_price,
            prob,
            symbol_open,
            momentum,
            paper_trade,
        )

        trade_manager_port = get_port("trade_manager")
        trade_manager_host = get_host()
        trade_manager_url = f"http://{trade_manager_host}:{trade_manager_port}/trades"

        import uuid

        ticket_id = f"TICKET-{uuid.uuid4().hex[:9]}-{int(now_est().timestamp() * 1000)}"
        now = now_est()
        eastern_date = now.strftime("%Y-%m-%d")
        eastern_time = now.strftime("%H:%M:%S")

        converted_side = side
        if side == "yes":
            converted_side = "Y"
        elif side == "no":
            converted_side = "N"

        monitor = data.get("monitor")
        if not monitor:
            logger.debug("[TRIGGER OPEN TRADE] Error: No monitor specified in trade data")
            return {"status": "error", "message": "Monitor must be specified"}

        monitor_id = monitor.split("_")[-1] if monitor and "_" in monitor else None
        if not monitor_id:
            logger.debug("[TRIGGER OPEN TRADE] Error: Invalid monitor format: %s", monitor)
            return {"status": "error", "message": "Invalid monitor format"}

        bankroll_allotment_total = None
        conn = None
        try:
            conn = get_postgresql_connection()
            with conn.cursor() as cursor:
                ml = legacy_users_monitor_list(effective_tenant_context_for_sql_rewrite().user_no)
                cursor.execute(
                    f"SELECT bankroll_allotment_total FROM {ml} WHERE id = %s",
                    (monitor_id,),
                )
                result = cursor.fetchone()
                if result:
                    bankroll_allotment_total = result[0]
                    logger.debug(
                        "[TRIGGER OPEN TRADE] Bankroll allotment loaded from monitor %s: %s",
                        monitor_id,
                        bankroll_allotment_total,
                    )
                else:
                    logger.debug("[TRIGGER OPEN TRADE] No monitor configuration found for monitor %s", monitor_id)
                    return {"status": "error", "message": "Monitor configuration not found"}
        except Exception as e:
            logger.debug("[TRIGGER OPEN TRADE] Error loading bankroll allotment from monitor %s: %s", monitor_id, e)
            return {"status": "error", "message": f"Failed to load monitor configuration: {e}"}
        finally:
            if conn:
                conn.close()

        position_val = position or 1
        trade_data = {
            "ticket_id": ticket_id,
            "status": "pending",
            "date": eastern_date,
            "time": eastern_time,
            "symbol": symbol or "BTC",
            "exchange": normalize_exchange(data.get("exchange", data.get("market"))),
            "trade_strategy": trade_strategy or "Hourly HTC",
            "contract": contract or "BTC Market",
            "strike": strike,
            "side": converted_side,
            "ticker": ticker,
            "buy_price": buy_price,
            "position": position_val,
            "count_fp": f"{float(position_val):.2f}",
            "symbol_open": symbol_open,
            "symbol_close": None,
            "momentum": momentum,
            "prob": prob,
            "diff": data.get("diff"),
            "win_loss": None,
            "entry_method": data.get("entry_method", "manual"),
            "monitor": monitor,
            "bankroll_allotment_total": bankroll_allotment_total,
            "paper_trade": paper_trade,
        }

        response = requests.post(trade_manager_url, json=trade_data, timeout=10)
        if response.status_code == 201:
            result = response.json()
            logger.debug("[TRIGGER OPEN TRADE] Trade initiated successfully: %s", result)
            return {
                "status": "success",
                "message": "Trade initiated successfully",
                "trade_data": result,
            }

        logger.debug("[TRIGGER OPEN TRADE] Trade initiation failed: %s - %s", response.status_code, response.text)
        return {
            "status": "error",
            "message": f"Trade initiation failed: {response.status_code}",
            "details": response.text,
        }
    except Exception as e:
        logger.debug("[TRIGGER OPEN TRADE] Error: %s", e)
        return {"status": "error", "message": str(e)}
