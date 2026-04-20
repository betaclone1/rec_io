"""Shared backtest constants (project root must be on ``sys.path``)."""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.port_config import default_pool_user_number
from backend.core.tenant_legacy_sql import legacy_users_monitor_list, legacy_users_trades

TRADES_TABLE = legacy_users_trades(default_pool_user_number())
MONITOR_LIST_TABLE = legacy_users_monitor_list(default_pool_user_number())
