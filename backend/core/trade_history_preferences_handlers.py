"""HTTP handlers for trade history UI preferences (PostgreSQL + optional Redis fanout).

Served from **main_app** (same-origin session as the trade history tab) and optionally
from **read_api** for direct calls. Prefer browser → main for prefs to avoid proxy/cookie
subtleties between processes.
"""

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import HTTPException, Request

from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.core.trade_history_preferences_store import (
    load_trade_history_preferences,
    save_trade_history_preferences,
)


def trade_history_preferences_get() -> Dict[str, Any]:
    return load_trade_history_preferences()


def trade_history_preferences_merge_and_save(data: Dict[str, Any]) -> Dict[str, Any]:
    """Merge JSON body into stored prefs, persist, publish Redis event. Raises HTTPException on DB failure."""
    from backend.core.trading_redis_comms import (
        publish_preferences_event,
        use_trading_redis_comms,
    )

    preferences = load_trade_history_preferences()
    for key, value in data.items():
        if (
            key == "monitor_selection"
            and isinstance(value, dict)
            and len(value) == 0
        ):
            continue
        preferences[key] = value
    preferences["last_search_timestamp"] = time.time()
    if not save_trade_history_preferences(preferences):
        raise HTTPException(
            status_code=503,
            detail="failed to persist trade history preferences (database error)",
        )
    try:
        if use_trading_redis_comms():
            publish_preferences_event(
                "trade_history_preferences_updated",
                {"source": "trade_history"},
                tenant_user_no=resolved_tenant_user_no_for_app(),
            )
    except Exception:
        pass
    return {"status": "ok", "preferences": preferences}


async def trade_history_preferences_post(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return {"status": "error", "message": "expected JSON object"}
        return trade_history_preferences_merge_and_save(data)
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}
