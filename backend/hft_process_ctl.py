"""Start/stop the HFT engine subprocess with singleton guarantees."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from backend.hft_engine import HFT_LOCK_KEY
from backend.util.paths import get_project_root

logger = logging.getLogger("hft_process_ctl")

_PGREP_PATTERN = "backend.hft_engine"
_START_WAIT_SEC = 2.5
_STOP_TERM_WAIT_SEC = 6.0

_op_lock = threading.Lock()


def _redis_cmd():
    from backend.core.live_state_cache import redis_client_optional
    return redis_client_optional()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pgrep_hft_pids() -> List[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", _PGREP_PATTERN],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    pids: List[int] = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return sorted(set(pids))


def _lock_holder_pid(r) -> Optional[int]:
    if not r:
        return None
    raw = r.get(HFT_LOCK_KEY)
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _clear_lock(r) -> None:
    if r:
        try:
            r.delete(HFT_LOCK_KEY)
        except Exception:
            pass


def find_hft_engine_pids(r=None) -> List[int]:
    """All live PIDs for backend.hft_engine (lock holder + pgrep, deduped)."""
    if r is None:
        r = _redis_cmd()
    pids: List[int] = []
    lock_pid = _lock_holder_pid(r)
    if lock_pid is not None and _pid_alive(lock_pid):
        pids.append(lock_pid)
    for pid in _pgrep_hft_pids():
        if pid not in pids and _pid_alive(pid):
            pids.append(pid)
    return sorted(pids)


def hft_process_status(r=None) -> Dict[str, Any]:
    pids = find_hft_engine_pids(r)
    running = len(pids) > 0
    return {
        "running": running,
        "pid": pids[0] if pids else None,
        "pids": pids,
        "multiple": len(pids) > 1,
    }


def _spawn_hft_engine(user_no: str) -> None:
    root = get_project_root()
    env = os.environ.copy()
    env.setdefault("REC_USER_NO", user_no)
    env.setdefault("REC_PROJECT_ROOT", root)
    env.setdefault("PYTHONPATH", root)
    log_path = os.path.join(root, "logs", "hft_engine_ctl.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_fh = open(log_path, "a", encoding="utf-8")
    try:
        subprocess.Popen(
            [sys.executable, "-m", "backend.hft_engine"],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log_fh.close()


def _terminate_pids(pids: List[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + _STOP_TERM_WAIT_SEC
    while time.monotonic() < deadline:
        alive = [p for p in pids if _pid_alive(p)]
        if not alive:
            return
        time.sleep(0.2)
    for pid in pids:
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def start_hft_engine(*, user_no: Optional[str] = None) -> Dict[str, Any]:
    """Start the engine if none is running; never spawn a second instance."""
    user_no = (user_no or os.getenv("REC_USER_NO", "0001")).strip()
    r = _redis_cmd()

    with _op_lock:
        pids = find_hft_engine_pids(r)
        if len(pids) > 1:
            logger.warning("Multiple HFT engine PIDs %s — stopping extras", pids)
            _terminate_pids(pids)
            _clear_lock(r)
            time.sleep(0.5)
            pids = find_hft_engine_pids(r)
        if pids:
            return {
                "status": "ok",
                "action": "start",
                "started": False,
                "reason": "already_running",
                "process": hft_process_status(r),
            }

        lock_pid = _lock_holder_pid(r)
        if lock_pid is not None and not _pid_alive(lock_pid):
            _clear_lock(r)

        try:
            _spawn_hft_engine(user_no)
        except Exception as exc:
            logger.exception("Failed to spawn HFT engine")
            return {
                "status": "error",
                "action": "start",
                "message": str(exc),
                "process": hft_process_status(r),
            }

        deadline = time.monotonic() + _START_WAIT_SEC
        while time.monotonic() < deadline:
            pids = find_hft_engine_pids(r)
            if pids:
                proc = hft_process_status(r)
                proc["started"] = True
                return {
                    "status": "ok",
                    "action": "start",
                    "started": True,
                    "process": proc,
                }
            time.sleep(0.15)

        return {
            "status": "error",
            "action": "start",
            "message": "Engine did not appear within timeout (check logs/hft_engine.log)",
            "process": hft_process_status(r),
        }


def stop_hft_engine() -> Dict[str, Any]:
    """Stop all HFT engine processes and clear the singleton lock."""
    r = _redis_cmd()

    with _op_lock:
        pids = find_hft_engine_pids(r)
        if not pids:
            _clear_lock(r)
            return {
                "status": "ok",
                "action": "stop",
                "stopped": False,
                "reason": "not_running",
                "process": hft_process_status(r),
            }

        _terminate_pids(pids)
        _clear_lock(r)
        time.sleep(0.2)
        remaining = find_hft_engine_pids(r)
        if remaining:
            return {
                "status": "error",
                "action": "stop",
                "message": f"Could not stop engine (remaining PIDs: {remaining})",
                "process": hft_process_status(r),
            }

        return {
            "status": "ok",
            "action": "stop",
            "stopped": True,
            "process": hft_process_status(r),
        }
