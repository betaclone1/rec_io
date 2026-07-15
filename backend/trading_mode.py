"""
Global trading mode: live (real balance + live execution) vs paper (simulated balance).

State is stored in the same JSON file as legacy account mode (Kalshi env is always prod).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from psycopg2 import sql as psql

from backend.core.config.database import get_system_postgresql_connection
from backend.core.tenant_provision import fetch_active_master_user_nos
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


def paper_mode_from_client_query(client_trading_mode: Optional[str]) -> Optional[bool]:
    """
    When the UI sends ``trading_mode=paper|live`` on API requests, honor it for **reads** so each
    tenant sees charts/PnL for the mode they selected, independent of the global on-disk toggle
    (which remains the execution default for workers that do not receive the query param).

    Returns ``None`` if the client did not send a recognized value (caller should use global
    :func:`is_paper_trading`).
    """
    if client_trading_mode is None:
        return None
    m = str(client_trading_mode).strip().lower()
    if m == "paper":
        return True
    if m == "live":
        return False
    return None


def use_paper_for_request(client_trading_mode: Optional[str]) -> bool:
    """Effective paper vs live for read paths (dashboard, read_api, proxies)."""
    explicit = paper_mode_from_client_query(client_trading_mode)
    if explicit is not None:
        return explicit
    return is_paper_trading()


def _active_tenant_slots(cur) -> List[str]:
    """Four-digit slots for active rows in system.master_users."""
    return list(fetch_active_master_user_nos(cur))


def _monitor_list_sql_identifiers(slot: str) -> Tuple[psql.Identifier, psql.Identifier]:
    u = _norm_slot(slot)
    return psql.Identifier(f"users_{u}"), psql.Identifier(f"monitor_list_{u}")


def _snapshot_active_monitor_paper_flags() -> Dict[str, Dict[str, bool]]:
    """
    Per-tenant map: slot -> { monitor_id (str) -> paper_trade } for active monitors.
    Uses system DB connection so all tenants are visible (not request-bound TenantConnection).
    """
    out: Dict[str, Dict[str, bool]] = {}
    conn = get_system_postgresql_connection()
    if not conn:
        return out
    try:
        with conn.cursor() as cur:
            for slot in _active_tenant_slots(cur):
                sch, tbl = _monitor_list_sql_identifiers(slot)
                cur.execute(
                    psql.SQL(
                        "SELECT id::text, COALESCE(paper_trade, false) FROM {}.{} WHERE status = 'active'"
                    ).format(sch, tbl)
                )
                per: Dict[str, bool] = {}
                for mid, pt in cur.fetchall() or []:
                    per[str(mid)] = bool(pt)
                if per:
                    out[slot] = per
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def _apply_monitor_paper_flags_for_slot(slot: str, flags: Dict[str, bool]) -> None:
    """Restore paper_trade for one tenant's monitors (system connection)."""
    if not flags:
        return
    conn = get_system_postgresql_connection()
    if not conn:
        return
    sch, tbl = _monitor_list_sql_identifiers(slot)
    try:
        with conn.cursor() as cur:
            for mid, pt in flags.items():
                try:
                    mid_int = int(mid)
                except (TypeError, ValueError):
                    continue
                cur.execute(
                    psql.SQL(
                        "UPDATE {}.{} SET paper_trade = %s, updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = %s AND status = 'active'"
                    ).format(sch, tbl),
                    (pt, mid_int),
                )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _apply_monitor_paper_flags_merged(snap: Any) -> None:
    """
    Restore from state file. Supports:
    - New: { slot: { mid: bool } }
    - Legacy flat: { mid: bool } (only ever matched ``monitor_list_<slot>``); apply to the default slot if active.
    """
    if not isinstance(snap, dict) or not snap:
        return
    if all(isinstance(v, dict) for v in snap.values()):
        for slot, flags in snap.items():
            if not isinstance(flags, dict):
                continue
            try:
                u = _norm_slot(str(slot))
            except ValueError:
                continue
            flat = {str(k): bool(v) for k, v in flags.items()}
            _apply_monitor_paper_flags_for_slot(u, flat)
        return
    flat = {str(k): bool(v) for k, v in snap.items() if not isinstance(v, dict)}
    if not flat:
        return
    conn = get_system_postgresql_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            slots = set(_active_tenant_slots(cur))
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if "0001" in slots:
        _apply_monitor_paper_flags_for_slot("0001", flat)


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
        conn = get_system_postgresql_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    for slot in _active_tenant_slots(cur):
                        sch, tbl = _monitor_list_sql_identifiers(slot)
                        cur.execute(
                            psql.SQL(
                                "UPDATE {}.{} SET paper_trade = true, updated_at = CURRENT_TIMESTAMP "
                                "WHERE status = 'active'"
                            ).format(sch, tbl)
                        )
                conn.commit()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        return "paper", None

    # live
    snap = state.get("paper_monitor_snapshot")
    if not isinstance(snap, dict):
        snap = {}
    state["paper_monitor_snapshot"] = None
    state["trading_mode"] = "live"
    _save_state(state)
    _apply_monitor_paper_flags_merged(snap)
    return "live", None


def _norm_slot(user_number: str) -> str:
    u = str(user_number).strip().zfill(4)
    if len(u) != 4 or not u.isdigit():
        raise ValueError(f"invalid user number: {user_number!r}")
    return u


def account_balance_table_for_user(
    user_number: str,
    *,
    client_trading_mode: Optional[str] = None,
    force_live: bool = False,
) -> str:
    """Live vs paper balance history table (per four-digit slot).

    Uses tenant schema ``users_<slot>`` (not legacy ``users``), so raw psycopg2 connections
    (e.g. monitor_manager) resolve the correct relation after ``users`` → ``users_0001`` rename.

    Pass ``client_trading_mode`` from HTTP query (``paper`` / ``live``) so dashboards match the
    user's UI toggle even when another tenant changed the global on-disk mode.

    ``force_live=True``: always the real Kalshi-backed ``account_balance_<slot>`` table. Use for
    ``kalshi_account_sync`` REST/WS writes so global ``trading_mode=paper`` does not redirect live
    API payloads into ``account_balance_paper_*`` (which would overwrite simulated paper history).
    """
    u = _norm_slot(user_number)
    if force_live:
        base = "account_balance"
    else:
        paper = use_paper_for_request(client_trading_mode)
        base = "account_balance_paper" if paper else "account_balance"
    return f"users_{u}.{base}_{u}"


def subaccounts_table_for_user(
    user_number: str,
    *,
    client_trading_mode: Optional[str] = None,
    force_live: bool = False,
) -> str:
    u = _norm_slot(user_number)
    if force_live:
        return f"users_{u}.subaccounts_{u}"
    if use_paper_for_request(client_trading_mode):
        return f"users_{u}.subaccounts_paper_{u}"
    return f"users_{u}.subaccounts_{u}"


def transfers_table_for_user(
    user_number: str,
    *,
    client_trading_mode: Optional[str] = None,
    force_live: bool = False,
) -> str:
    """Live vs paper transfer log (per four-digit slot)."""
    u = _norm_slot(user_number)
    if force_live:
        return f"users_{u}.transfers_{u}"
    if use_paper_for_request(client_trading_mode):
        return f"users_{u}.transfers_paper_{u}"
    return f"users_{u}.transfers_{u}"


def credits_history_table_for_user(user_number: str) -> str:
    """Kalshi credit history log (per four-digit slot).

    Live-only Kalshi data (no paper variant); populated by
    ``kalshi_account_sync_ws.sync_credit_history``.
    """
    u = _norm_slot(user_number)
    return f"users_{u}.credits_history_{u}"


def subaccount_balance_table_fqn(user_number: str, subaccount_number: int) -> str:
    """Live per-subaccount balance history (Kalshi GET /portfolio/balance?subaccount=N)."""
    u = _norm_slot(user_number)
    n = int(subaccount_number)
    return f"users_{u}.subaccount_balance_{u}_{n}"


def paper_account_balance_fqn(user_number: str) -> str:
    """Always paper balance table for this slot (ignores global trading_mode)."""
    u = _norm_slot(user_number)
    return f"users_{u}.account_balance_paper_{u}"


def paper_subaccounts_fqn(user_number: str) -> str:
    """Always paper subaccounts table for this slot."""
    u = _norm_slot(user_number)
    return f"users_{u}.subaccounts_paper_{u}"


def monitor_list_fqn(user_number: str) -> str:
    u = _norm_slot(user_number)
    return f"users_{u}.monitor_list_{u}"


def strategy_list_fqn(user_number: str) -> str:
    u = _norm_slot(user_number)
    return f"users_{u}.strategy_list_{u}"


def trades_table_fqn(user_number: str) -> str:
    u = _norm_slot(user_number)
    return f"users_{u}.trades_{u}"


def sql_ident_qualified_table(fqn: str) -> psql.Composed:
    """psycopg2.sql Identifier pair for schema.table (e.g. users_0001.account_balance_0001)."""
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
