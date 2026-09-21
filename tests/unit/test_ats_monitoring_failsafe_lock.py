"""Regression: monitoring failsafe must not nest-acquire monitoring_thread_lock.

Prod 2026-09-17: check_monitoring_failsafe held the non-reentrant Lock while calling
start_monitoring_loop (which acquires the same lock) → permanent deadlock; unified ATS
heartbeated but never ran auto-stop / enroll supervision again.
"""

from __future__ import annotations

import ast
import os
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ATS_PATH = Path(__file__).resolve().parents[2] / "backend" / "active_trade_supervisor.py"


def _calls_start_monitoring_under_lock(fn: ast.FunctionDef) -> bool:
    """True if any start_monitoring_loop() call sits inside `with monitoring_thread_lock`."""

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.in_lock = 0
            self.bad = False

        def visit_With(self, node: ast.With) -> None:
            enters = False
            for item in node.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Name) and ctx.id == "monitoring_thread_lock":
                    enters = True
            if enters:
                self.in_lock += 1
                self.generic_visit(node)
                self.in_lock -= 1
            else:
                self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "start_monitoring_loop" and self.in_lock > 0:
                self.bad = True
            self.generic_visit(node)

    v = Visitor()
    v.visit(fn)
    return v.bad


def test_check_monitoring_failsafe_source_does_not_nest_lock():
    tree = ast.parse(ATS_PATH.read_text())
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "check_monitoring_failsafe"
    )
    assert not _calls_start_monitoring_under_lock(fn)


@pytest.fixture(scope="module")
def ats_mod():
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    os.environ.setdefault("REC_POOL_USER_NUMBER", "0001")
    # Avoid argv collision if another ATS test already imported the module.
    if "backend.active_trade_supervisor" not in sys.modules:
        sys.argv = ["active_trade_supervisor.py", "unified"]
    import backend.active_trade_supervisor as ats  # noqa: E402

    return ats


def test_check_monitoring_failsafe_releases_lock_before_start(ats_mod, monkeypatch):
    ats = ats_mod
    held_during_start: list[bool] = []

    class _Alive:
        def is_alive(self) -> bool:
            return True

    def _start() -> None:
        # Non-blocking acquire: fails only if failsafe still holds the lock.
        acquired = ats.monitoring_thread_lock.acquire(blocking=False)
        held_during_start.append(not acquired)
        if acquired:
            ats.monitoring_thread = _Alive()  # type: ignore[assignment]
            ats.monitoring_thread_lock.release()

    monkeypatch.setattr(ats, "ATS_UNIFIED_POOL", True)
    monkeypatch.setattr(
        ats, "_count_active_trades_across_unified_pool_monitors", lambda: 1
    )
    monkeypatch.setattr(ats, "get_db_connection", lambda: MagicMock())
    monkeypatch.setattr(ats, "start_monitoring_loop", _start)
    monkeypatch.setattr(ats.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ats, "restart_active_trade_supervisor_process", MagicMock())

    with ats.monitoring_thread_lock:
        ats.monitoring_thread = None

    ats.check_monitoring_failsafe()

    assert held_during_start == [False], (
        "start_monitoring_loop ran while monitoring_thread_lock was still held"
    )
    assert isinstance(ats.monitoring_thread, _Alive)
