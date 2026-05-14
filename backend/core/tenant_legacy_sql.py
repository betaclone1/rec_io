"""
Legacy SQL table tokens ``users.<base>_<slot>`` and unified pool ``active_trades_*_<slot>``.

Callers must pass the monitor owner slot (e.g. ``ctx_user()``), an explicit four-digit
``tenant_user_no``, or :func:`backend.core.tenant_context.effective_tenant_context_for_sql_rewrite`
``.user_no`` for the worker process. Do not embed a literal tenant suffix in source.
"""

from __future__ import annotations

from backend.trading_mode import _norm_slot


def legacy_users_monitor_list(tenant_slot: str) -> str:
    return f"users.monitor_list_{_norm_slot(tenant_slot)}"


def legacy_users_trades(tenant_slot: str) -> str:
    return f"users.trades_{_norm_slot(tenant_slot)}"


def legacy_users_trades_simulated(tenant_slot: str) -> str:
    return f"users.trades_simulated_{_norm_slot(tenant_slot)}"


def legacy_users_sim_trade_lp_cycle_ledger(tenant_slot: str) -> str:
    return f"users.sim_trade_lp_cycle_ledger_{_norm_slot(tenant_slot)}"


def legacy_users_orders(tenant_slot: str) -> str:
    return f"users.orders_{_norm_slot(tenant_slot)}"


def legacy_users_fills(tenant_slot: str) -> str:
    return f"users.fills_{_norm_slot(tenant_slot)}"


def legacy_active_trades_pool_15m(worker_slot: str) -> str:
    return f"active_trades_15m_{_norm_slot(worker_slot)}"


def legacy_active_trades_pool_hourly(worker_slot: str) -> str:
    return f"active_trades_hourly_{_norm_slot(worker_slot)}"
