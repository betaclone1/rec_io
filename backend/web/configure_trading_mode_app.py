"""Wire trading_mode_router hooks to realtime broadcast and bankroll ripple."""

import asyncio
import logging

from backend.web import main_realtime
from backend.web.trading_mode_routes import configure_trading_mode_hooks

_log = logging.getLogger("main_app")


async def ripple_bankroll_to_monitors():
    """After balance source changes, recompute monitor allotments via monitor_manager."""

    def _run():
        try:
            from backend.kalshi_account_sync_ws import notify_monitor_manager

            notify_monitor_manager(False)
        except Exception as e:
            _log.warning("ripple_bankroll_to_monitors: %s", e)

    await asyncio.to_thread(_run)


def wire_trading_mode_for_main_app() -> None:
    configure_trading_mode_hooks(
        broadcast_trading_mode=main_realtime.broadcast_trading_mode,
        ripple_bankroll_to_monitors=ripple_bankroll_to_monitors,
    )
