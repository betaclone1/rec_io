"""
Filesystem session tokens: one ``auth_tokens.json`` (and ``device_tokens.json``) per
``data/users/user_NNNN/``. Scripts and workers use ``REC_USER_SCHEMA`` / ``--user-no`` instead.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from backend.util.paths import get_data_dir

_USER_DIR_RE = re.compile(r"^user_(\d{4})$")


def parse_auth_expiry_utc(iso_str: str) -> datetime:
    s = (iso_str or "").replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _users_root() -> str:
    return os.path.join(get_data_dir(), "users")


def token_file_for_user_no(user_no: str) -> str:
    return os.path.join(_users_root(), f"user_{user_no}", "auth_tokens.json")


def device_file_for_user_no(user_no: str) -> str:
    return os.path.join(_users_root(), f"user_{user_no}", "device_tokens.json")


def _iter_auth_token_paths() -> list[str]:
    root = _users_root()
    if not os.path.isdir(root):
        return []
    paths: list[str] = []
    for name in sorted(os.listdir(root)):
        if not _USER_DIR_RE.match(name):
            continue
        p = os.path.join(root, name, "auth_tokens.json")
        if os.path.isfile(p):
            paths.append(p)
    return paths


def _user_no_from_auth_path(path: str) -> Optional[str]:
    parent = os.path.basename(os.path.dirname(path))
    m = _USER_DIR_RE.match(parent)
    return m.group(1) if m else None


def find_valid_token(token: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    t = (token or "").strip()
    if not t:
        return None
    now = datetime.now(timezone.utc)
    for path in _iter_auth_token_paths():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict) or t not in data:
            continue
        rec = data[t]
        if not isinstance(rec, dict):
            continue
        try:
            exp = parse_auth_expiry_utc(str(rec.get("expires") or ""))
        except Exception:
            continue
        if now >= exp:
            continue
        slot = _user_no_from_auth_path(path)
        if not slot:
            continue
        return slot, rec
    return None


def save_token_for_user(user_no: str, token: str, record: Dict[str, Any]) -> None:
    path = token_file_for_user_no(user_no)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data: Dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
        except Exception:
            pass
    data[token] = record
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def delete_token_everywhere(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    for path in _iter_auth_token_paths():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict) or t not in data:
            continue
        del data[t]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    return False


def load_device_tokens(user_no: str) -> Dict[str, Any]:
    path = device_file_for_user_no(user_no)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_device_tokens(user_no: str, tokens: Dict[str, Any]) -> None:
    path = device_file_for_user_no(user_no)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def delete_device_token(user_no: str, device_id: str) -> None:
    if not device_id:
        return
    data = load_device_tokens(user_no)
    if device_id in data:
        del data[device_id]
        save_device_tokens(user_no, data)
