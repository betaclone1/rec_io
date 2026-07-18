"""Focused tests for Expiration Scalp's ATS stop-loss routing.

active_trade_supervisor performs process/DB startup at import time, so these tests
execute only the target function's AST rather than importing the daemon module.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import Mock


ATS_PATH = Path(__file__).resolve().parents[2] / "backend" / "active_trade_supervisor.py"


def _load_function(name: str, namespace: dict):
    tree = ast.parse(ATS_PATH.read_text())
    node = next(
        item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(ATS_PATH), "exec"), namespace)
    return namespace[name]


def test_expiration_scalp_routes_only_to_floor_without_other_gates():
    get_stop_loss_price = Mock(return_value=0.20)
    try_floor = Mock()
    check_scalp = _load_function(
        "check_auto_stop_conditions_expiration_scalp",
        {
            "get_stop_loss_price": get_stop_loss_price,
            "_try_stop_loss_ask_floor": try_floor,
        },
    )
    trades = [{"trade_id": 42, "status": "active"}]
    triggered = set()
    verification = {99: (1, 2)}

    check_scalp(trades, triggered, verification)

    get_stop_loss_price.assert_called_once_with()
    try_floor.assert_called_once_with(
        trades[0],
        0.20,
        triggered,
        verification,
        0,
        0,
        check_probability_divergence=False,
    )


def test_expiration_scalp_checks_each_active_trade_against_same_floor():
    try_floor = Mock()
    check_scalp = _load_function(
        "check_auto_stop_conditions_expiration_scalp",
        {
            "get_stop_loss_price": Mock(return_value=0.35),
            "_try_stop_loss_ask_floor": try_floor,
        },
    )
    trades = [{"trade_id": 1}, {"trade_id": 2}]

    check_scalp(trades, set(), {})

    assert try_floor.call_count == 2
    assert [call.args[1] for call in try_floor.call_args_list] == [0.35, 0.35]
