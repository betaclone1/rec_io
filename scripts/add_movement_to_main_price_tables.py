#!/usr/bin/env python3
"""
Add movement and movement_percentile to main historical_data.*_price_history tables
(not the MOVEMENT TEST clone). Ensures columns exist, backfills movement (missing only),
then generates movement profiles and assigns movement_percentile.
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

# Run from backend/util/analytics for imports
analytics_dir = os.path.join(os.path.dirname(__file__), '..', 'backend', 'util', 'analytics')
sys.path.insert(0, analytics_dir)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    from movement_generator_pg import (
        get_postgresql_connection,
        ensure_movement_columns,
        get_symbols_from_db,
        fill_missing_movement_in_db,
    )
    from symbol_profiler import SymbolProfiler

    symbols = get_symbols_from_db()
    if not symbols:
        logger.error("No historical_data.*_price_history tables found")
        sys.exit(1)
    logger.info("Symbols: %s", symbols)

    conn = get_postgresql_connection()
    if not conn:
        sys.exit(1)
    for symbol in symbols:
        try:
            ensure_movement_columns(conn, symbol)
            logger.info("Ensured movement + movement_percentile columns for %s", symbol)
        except Exception as e:
            logger.error("Failed to ensure columns for %s: %s", symbol, e)
    conn.close()

    for symbol in symbols:
        try:
            logger.info("Backfilling movement for %s...", symbol)
            fill_missing_movement_in_db(symbol)
        except Exception as e:
            logger.error("Failed to backfill movement for %s: %s", symbol, e)

    today = datetime.now().strftime("%Y%m%d")
    for symbol in symbols:
        try:
            logger.info("Generating movement profile for %s...", symbol)
            profiler = SymbolProfiler(symbol.lower())
            profiler.movement_profile_table = f"analytics.{symbol.lower()}_movement_profile_{today}"
            profiler.generate_movement_profile()
        except Exception as e:
            logger.error("Failed to generate movement profile for %s: %s", symbol, e)

    for symbol in symbols:
        try:
            logger.info("Assigning movement percentiles for %s...", symbol)
            profiler = SymbolProfiler(symbol.lower())
            profiler.assign_movement_percentiles()
        except Exception as e:
            logger.error("Failed to assign movement percentiles for %s: %s", symbol, e)

    logger.info("Done. Main tables now have movement and movement_percentile.")


if __name__ == "__main__":
    main()
