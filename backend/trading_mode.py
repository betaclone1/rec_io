"""
Global trading mode: live (real balance + live execution) vs paper (simulated balance).

State is stored in the same JSON file as legacy account mode (Kalshi env is always prod).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from psycopg2 import sql as psql

from backend.core.config.database import get_postgresql_connection
from backend.util.paths import get_data_dir

_STATE_BASENAME = "account_mode_state.json"


def _state_path() -> str:
    return os.path.join(get_data_dir(), _STATE_BASENAME)


def _load_state() -> Dict[str, Any]:
    path = _state_path()
    try:
        with open(path) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_state(data: Dict[str, Any]) -> None:
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_trading_mode() -> str:
    """Return 'live' or 'paper'. Default live."""
    mode = (_load_state().get("trading_mode") or "live").strip().lower()
    return "paper" if mode == "paper" else "live"


def is_paper_trading() -> bool:
    return get_trading_mode() == "paper"


def _snapshot_active_monitor_paper_flags() -> Dict[str, bool]:
    """Map monitor id (str) -> paper_trade bool for active monitors."""
    out: Dict[str, bool] = {}
    conn = get_postgresql_connection()
    if not conn:
        return out
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, COALESCE(paper_trade, false)
                FROM users.monitor_list_0001
                WHERE status = 'active'
                """
            )
            for mid, pt in cur.fetchall() or []:
                out[str(mid)] = bool(pt)
    finally:
        conn.close()
    return out


def _apply_monitor_paper_flags(flags: Dict[str, bool]) -> None:
    conn = get_postgresql_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            for mid, pt in flags.items():
                try:
                    mid_int = int(mid)
                except (TypeError, ValueError):
                    continue
                cur.execute(
                    """
                    UPDATE users.monitor_list_0001
                    SET paper_trade = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'active'
                    """,
                    (pt, mid_int),
                )
        conn.commit()
    finally:
        conn.close()


def set_trading_mode(mode: str) -> Tuple[str, Optional[str]]:
    """
    Set trading_mode to 'live' or 'paper'.
    On entering paper: snapshot active monitors' paper_trade, then set all active to paper_trade=true.
    On entering live: restore snapshot.
    Returns (normalized_mode, error_message).
    """
    m = (mode or "").strip().lower()
    if m not in ("live", "paper"):
        return "live", "Invalid trading_mode"
    state = _load_state()
    # Kalshi env: prod only (demo removed)
    state["mode"] = "prod"
    prev = (state.get("trading_mode") or "live").strip().lower()
    if prev not in ("live", "paper"):
        prev = "live"

    if m == prev:
        state["trading_mode"] = m
        _save_state(state)
        return m, None

    if m == "paper":
        snap = _snapshot_active_monitor_paper_flags()
        state["paper_monitor_snapshot"] = snap
        state["trading_mode"] = "paper"
        _save_state(state)
        conn = get_postgresql_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE users.monitor_list_0001
                        SET paper_trade = true, updated_at = CURRENT_TIMESTAMP
                        WHERE status = 'active'
                        """
                    )
                conn.commit()
            finally:
                conn.close()
        return "paper", None

    # live
    snap = state.get("paper_monitor_snapshot")
    if not isinstance(snap, dict):
        snap = {}
    state["paper_monitor_snapshot"] = None
    state["trading_mode"] = "live"
    _save_state(state)
    _apply_monitor_paper_flags({str(k): bool(v) for k, v in snap.items()})
    return "live", None


def account_balance_table_for_user(user_number: str) -> str:
    """Live vs paper balance history table (paper v1: user 0001 only)."""
    if str(user_number) == "0001" and get_trading_mode() == "paper":
        return "users.account_balance_paper_0001"
    return f"users.account_balance_{user_number}"


def subaccounts_table_for_user(user_number: str) -> str:
    if str(user_number) == "0001" and get_trading_mode() == "paper":
        return "users.subaccounts_paper_0001"
    return f"users.subaccounts_{user_number}"


def transfers_table_for_user(user_number: str) -> str:
    """Live vs paper transfer log (paper v1: user 0001 only)."""
    if str(user_number) == "0001" and get_trading_mode() == "paper":
        return "users.transfers_paper_0001"
    return f"users.transfers_{user_number}"


def sql_ident_qualified_table(fqn: str) -> psql.Composed:
    """psycopg2.sql Identifier pair for schema.table (e.g. users.account_balance_0001)."""
    parts = fqn.split(".")
    if len(parts) != 2:
        raise ValueError(f"expected schema.table, got {fqn!r}")
    return psql.SQL("{}.{}").format(psql.Identifier(parts[0]), psql.Identifier(parts[1]))


def migrate_legacy_state_file() -> None:
    """If old file had mode=demo, force prod; default trading_mode live."""
    state = _load_state()
    changed = False
    if state.get("mode") == "demo":
        state["mode"] = "prod"
        changed = True
    if "trading_mode" not in state:
        state["trading_mode"] = "live"
        changed = True
    if changed:
        _save_state(state)
