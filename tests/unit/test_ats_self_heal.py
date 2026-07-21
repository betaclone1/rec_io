"""Unit tests for ATS self-heal helpers (ghost classification + enroll progress)."""

from __future__ import annotations

import ast
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import backend.core.ats_enrollment_redis as enroll


ATS_PATH = Path(__file__).resolve().parents[2] / "backend" / "active_trade_supervisor.py"


def _load_ats_helpers():
    tree = ast.parse(ATS_PATH.read_text())
    wanted = {
        "_is_terminal_trade_status",
        "_TERMINAL_TRADE_STATUSES",
    }
    nodes = [
        item
        for item in tree.body
        if (isinstance(item, ast.FunctionDef) and item.name in wanted)
        or (isinstance(item, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in wanted for t in item.targets
        ))
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    ns: dict = {"Optional": type(None)}
    # Optional typing for annotations
    from typing import Optional

    ns["Optional"] = Optional
    exec(compile(module, str(ATS_PATH), "exec"), ns)
    return ns


def test_terminal_trade_status_classification():
    ns = _load_ats_helpers()
    is_term = ns["_is_terminal_trade_status"]
    assert is_term("closed") is True
    assert is_term("EXPIRED") is True
    assert is_term("error") is True
    assert is_term("deleted") is True
    assert is_term("active") is False
    assert is_term("pending") is False
    assert is_term("open") is False
    assert is_term(None) is False


def test_subscriber_progress_advances():
    enroll.mark_subscriber_progress()
    age1 = enroll.subscriber_progress_age_sec()
    assert age1 < 1.0
    time.sleep(0.05)
    age2 = enroll.subscriber_progress_age_sec()
    assert age2 >= age1


def test_enroll_loop_marks_progress_when_idle():
    stop = __import__("threading").Event()
    messages = {"n": 0}

    class FakePubSub:
        def subscribe(self, *channels):
            return None

        def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
            messages["n"] += 1
            if messages["n"] >= 3:
                stop.set()
            return None

        def unsubscribe(self, *channels):
            return None

        def close(self):
            return None

    class FakeRedis:
        def pubsub(self):
            return FakePubSub()

    with patch.object(enroll, "redis_client_optional", return_value=FakeRedis()):
        with patch.object(enroll, "_SUBSCRIBER_GET_MESSAGE_TIMEOUT_SEC", 0.01):
            enroll.start_enroll_subscriber_loop(
                handler=MagicMock(),
                tm_notify_handler=MagicMock(),
                stop_event=stop,
            )
    assert enroll.subscriber_progress_age_sec() < 2.0
    assert messages["n"] >= 3
