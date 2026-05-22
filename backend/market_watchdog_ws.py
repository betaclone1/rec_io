#!/usr/bin/env python3
"""
Global market ingest (supervisor entry).

``--exchange`` selects the venue under ``backend.core.market_watchdog.venues``.
"""

from backend.core.market_watchdog.engine import main

if __name__ == "__main__":
    main()
