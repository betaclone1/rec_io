#!/usr/bin/env python3
"""Production Kalshi crypto 15m orderbook live publisher.

Owns Redis ``trade_monitor:orderbook_levels:v1:*`` for non-lean 15m markets.
Watchdog must set ``REC_KALSHI_OB_LIVE_OWNER=1`` (default) and skip those OB subs.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from backend.core.kalshi_ob_live import owned_15m_symbols, run_ob_live


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    symbols = owned_15m_symbols()
    logging.getLogger("kalshi_ob_live").info("entrypoint symbols=%s", symbols)
    try:
        asyncio.run(run_ob_live(symbols))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
