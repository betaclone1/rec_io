"""
MAIN APPLICATION - UNIVERSAL CENTRALIZED PORT SYSTEM
Uses the single centralized port configuration system.
"""

import os
import sys
from functools import partial

import uvicorn
from fastapi import FastAPI

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

from backend.core.port_config import get_port, unified_active_trade_supervisor_service_name
from backend.web.main_app_lifespan import main_app_lifespan
from backend.web.main_app_logging import get_main_app_logger
from backend.web.main_app_middleware import install_main_app_middleware
from backend.web.routers.register_main_app_routers import register_main_app_routers

MAIN_APP_PORT = get_port("main_app")
# Aggregate /api/active_trades is served by pool ATS (8034), not legacy key active_trade_supervisor (6000).
ACTIVE_TRADE_SUPERVISOR_PORT = get_port(unified_active_trade_supervisor_service_name())

_main_logger = get_main_app_logger()
_main_logger.info("Using centralized port %s (ATS port %s)", MAIN_APP_PORT, ACTIVE_TRADE_SUPERVISOR_PORT)

app = FastAPI(
    title="Trading System Main App",
    lifespan=partial(main_app_lifespan, main_app_port=MAIN_APP_PORT),
)

install_main_app_middleware(app, MAIN_APP_PORT)
register_main_app_routers(app)

if __name__ == "__main__":
    _main_logger.debug(f"[MAIN] 🚀 Launching app on centralized port {MAIN_APP_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=MAIN_APP_PORT)
