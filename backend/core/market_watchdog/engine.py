"""Market watchdog ingest entry (supervisor: ``market_watchdog_ws.py``)."""

from __future__ import annotations

import argparse
import asyncio
import logging

from backend.core.market_watchdog.config import load_config
from backend.core.market_watchdog.venues.kalshi import auth
from backend.core.market_watchdog.venues.kalshi.ws_ingest import run_ingest

log = logging.getLogger("market_watchdog.engine")


def main() -> None:
    parser = argparse.ArgumentParser(description="Kalshi market WebSocket ingest")
    parser.add_argument("--exchange", default="kalshi")
    parser.add_argument(
        "--market",
        choices=("all", "15m", "hourly"),
        default="all",
        help="all = sandbox default (15m + hourly in one process)",
    )
    args = parser.parse_args()
    auth.load_kalshi_credentials_from_disk()
    cfg = load_config(exchange=args.exchange, market_interval=args.market)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [kalshi_market_ws_master] %(message)s",
    )
    try:
        asyncio.run(run_ingest(cfg))
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
