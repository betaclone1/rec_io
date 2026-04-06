# Kalshi API environment: prod only (demo removed).
account_mode_state = {"mode": "prod"}

import os
import json
from backend.util.paths import get_data_dir


def _state_path():
    return os.path.join(get_data_dir(), "account_mode_state.json")


def get_account_mode():
    """Always returns prod. Migrates legacy demo → prod in the state file without dropping other keys."""
    try:
        with open(_state_path()) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return "prod"
        if data.get("mode") == "demo":
            data["mode"] = "prod"
            os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
            with open(_state_path(), "w") as wf:
                json.dump(data, wf, indent=2)
        return "prod"
    except Exception:
        return "prod"


def set_account_mode(mode):
    """Persist prod only; preserves trading_mode and other keys in the same JSON file."""
    path = _state_path()
    try:
        with open(path) as f:
            data = json.load(f)
            if not isinstance(data, dict):
                data = {}
    except Exception:
        data = {}
    data["mode"] = "prod"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
