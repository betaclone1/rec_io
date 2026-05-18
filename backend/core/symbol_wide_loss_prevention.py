"""Symbol-wide loss prevention state sync and effective-state resolution."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from psycopg2 import sql

from backend.core.system_settings_store import _settings_table_ident

_log = logging.getLogger(__name__)

SYMBOL_WIDE_SUFFIX = "_symbol_wide"
MARKET_WIDE_LP_BASE = "live_loss_market_wide_1c"
_MONITOR_LIST_RE = re.compile(r"(?:^|[.])monitor_list_(\d{4})$", re.IGNORECASE)
_SIZING_STATES = {
    "one_contract",
    "win_streak_one_contract",
    "symbol_one_contract",
    "sim_loss_50",
    "sim_loss_25",
    "sim_loss_1c",
    "live_loss_1c",
    "live_loss_market_wide_1c",
}
_STATE_SEVERITY = {
    "off": 0,
    "sim_loss_25": 1,
    "sim_loss_50": 2,
    "sim_loss_1c": 3,
    "live_loss_1c": 4,
    "one_contract": 4,
    "win_streak_one_contract": 4,
    "symbol_one_contract": 4,
    # Strictest: wins ties vs same-tier live / symbol-wide live states.
    "live_loss_market_wide_1c": 5,
}


def _sql_sim_cooldown_live_expr(prefix: str = "") -> str:
    p = prefix
    return f"""(
        COALESCE({p}loss_prevention_toggle, FALSE) IS TRUE
        AND COALESCE(NULLIF({p}loss_prevention_method, ''), 'win_streak') = 'time'
        AND COALESCE({p}simulated_trade_loss_prevention, FALSE) IS TRUE
        AND {p}simulated_loss_prevention_cooldown_start_time IS NOT NULL
        AND COALESCE({p}loss_prevention_duration, 0) > 0
        AND (
            {p}simulated_loss_prevention_cooldown_start_time
            + (COALESCE({p}loss_prevention_duration, 0) || ' hours')::interval
        ) > NOW()
    )"""


def _sql_live_cooldown_live_expr(prefix: str = "") -> str:
    p = prefix
    return f"""(
        COALESCE({p}loss_prevention_toggle, FALSE) IS TRUE
        AND COALESCE(NULLIF({p}loss_prevention_method, ''), 'win_streak') = 'time'
        AND {p}live_loss_prevention_cooldown_start_time IS NOT NULL
        AND COALESCE({p}loss_prevention_duration, 0) > 0
        AND (
            {p}live_loss_prevention_cooldown_start_time
            + (COALESCE({p}loss_prevention_duration, 0) || ' hours')::interval
        ) > NOW()
    )"""


def _sql_local_loss_prevention_state_expr(prefix: str = "") -> str:
    p = prefix
    return f"""(
        CASE
            WHEN COALESCE({p}loss_prevention_toggle, FALSE) IS NOT TRUE THEN 'off'
            WHEN COALESCE(NULLIF({p}loss_prevention_method, ''), 'win_streak') = 'time'
             AND {_sql_live_cooldown_live_expr(p)} THEN 'live_loss_1c'
            WHEN COALESCE(NULLIF({p}loss_prevention_method, ''), 'win_streak') = 'time'
             AND {_sql_sim_cooldown_live_expr(p)} THEN
                CASE
                    WHEN COALESCE({p}loss_prevention_cooldown_loss_count, 0) >= 3 THEN 'sim_loss_1c'
                    WHEN COALESCE({p}loss_prevention_cooldown_loss_count, 0) = 2 THEN 'sim_loss_25'
                    WHEN COALESCE({p}loss_prevention_cooldown_loss_count, 0) >= 1 THEN 'sim_loss_50'
                    ELSE 'off'
                END
            WHEN COALESCE(NULLIF({p}loss_prevention_method, ''), 'win_streak') <> 'time'
             AND COALESCE({p}win_streak, 0) < COALESCE({p}win_streak_threshold, 22)
             THEN 'win_streak_one_contract'
            ELSE 'off'
        END
    )"""


def _sql_loss_prevention_severity_expr(state_sql: str) -> str:
    normalized = f"LOWER(REPLACE(COALESCE(({state_sql})::text, ''), '-', '_'))"
    base = f"""(
        CASE
            WHEN RIGHT({normalized}, {len(SYMBOL_WIDE_SUFFIX)}) = '{SYMBOL_WIDE_SUFFIX}'
                THEN LEFT({normalized}, GREATEST(LENGTH({normalized}) - {len(SYMBOL_WIDE_SUFFIX)}, 0))
            WHEN {normalized} IN ('', 'none', 'null') THEN 'off'
            ELSE {normalized}
        END
    )"""
    return f"""(
        CASE
            WHEN {base} = 'live_loss_market_wide_1c' THEN 5
            WHEN {base} IN ('live_loss_1c', 'one_contract', 'win_streak_one_contract', 'symbol_one_contract') THEN 4
            WHEN {base} = 'sim_loss_1c' THEN 3
            WHEN {base} = 'sim_loss_50' THEN 2
            WHEN {base} = 'sim_loss_25' THEN 1
            ELSE 0
        END
    )"""


def normalize_loss_prevention_state_for_sizing(value: Any) -> str:
    """Strip origin markers before applying existing sizing rules."""
    state = str(value or "").strip().lower().replace("-", "_")
    if state.endswith(SYMBOL_WIDE_SUFFIX):
        state = state[: -len(SYMBOL_WIDE_SUFFIX)]
    if state in ("", "none", "null"):
        return "off"
    return state


def loss_prevention_state_severity(value: Any) -> int:
    return _STATE_SEVERITY.get(normalize_loss_prevention_state_for_sizing(value), 0)


def more_serious_loss_prevention_state(local_value: Any, symbol_wide_value: Any) -> str:
    """Return the stricter local-vs-symbol-wide LP state.

    Ties prefer the current local value unless that value is already a symbol-wide
    projection, preserving attribution for persisted follower rows.
    """
    symbol_state = symbol_wide_loss_prevention_state(symbol_wide_value)
    if is_symbol_wide_loss_prevention_state(local_value):
        return symbol_state

    local_state = normalize_loss_prevention_state_for_sizing(local_value)
    local_severity = loss_prevention_state_severity(local_state)
    symbol_severity = loss_prevention_state_severity(symbol_state)
    if symbol_severity > local_severity:
        return symbol_state
    if (
        symbol_severity == local_severity
        and symbol_severity > 0
        and is_symbol_wide_loss_prevention_state(local_value)
    ):
        return symbol_state
    return local_state


def is_symbol_wide_loss_prevention_state(value: Any) -> bool:
    return str(value or "").strip().lower().replace("-", "_").endswith(SYMBOL_WIDE_SUFFIX)


def symbol_wide_loss_prevention_state(value: Any) -> str:
    """Persist non-off symbol-wide states with an origin suffix."""
    state = normalize_loss_prevention_state_for_sizing(value)
    if state == "off":
        return "off"
    return f"{state}{SYMBOL_WIDE_SUFFIX}"


def is_loss_prevention_sizing_state(value: Any) -> bool:
    return normalize_loss_prevention_state_for_sizing(value) in _SIZING_STATES


def _monitor_list_slot(monitor_list_qualified: str) -> Optional[str]:
    match = _MONITOR_LIST_RE.search(str(monitor_list_qualified or "").strip())
    return match.group(1) if match else None


def read_market_wide_loss_prevention_settings(
    cursor,
    user_slot: str,
) -> Tuple[bool, Optional[int], Optional[int]]:
    """Return (market_wide_loss_prevention, hero_monitor_id, stop_loss_count_threshold)."""
    u = str(user_slot or "").strip()
    if not re.fullmatch(r"\d{4}", u):
        return False, None, None
    try:
        ident = _settings_table_ident(u)
        cursor.execute(
            sql.SQL(
                """
                SELECT COALESCE(market_wide_loss_prevention, TRUE),
                       hero_monitor_id,
                       stop_loss_count_threshold
                FROM {}
                WHERE id = 1
                """
            ).format(ident)
        )
        row = cursor.fetchone()
        if not row:
            return True, None, None
        enabled = bool(row[0]) if row[0] is not None else True
        hero = int(row[1]) if row[1] is not None else None
        th = int(row[2]) if row[2] is not None else None
        return enabled, hero, th
    except Exception as exc:
        _log.debug("market-wide LP settings read failed for slot=%s: %s", u, exc)
        return True, None, None


def compute_market_wide_loss_prevention_state(
    cursor,
    monitor_list_qualified: str,
) -> str:
    """Return 'off' or suffixed market-wide LP state for symbol_wide monitors."""
    slot = _monitor_list_slot(monitor_list_qualified)
    if not slot:
        return "off"
    enabled, hero_id, threshold = read_market_wide_loss_prevention_settings(cursor, slot)
    if not enabled or hero_id is None or threshold is None or int(threshold) < 1:
        return "off"
    ml = str(monitor_list_qualified or "").strip()
    if not re.match(r"^(?:users|users_\d{4})\.monitor_list_\d{4}$", ml, re.I):
        return "off"
    try:
        cursor.execute(
            f"""
            SELECT COALESCE(loss_prevention_toggle, FALSE),
                   COALESCE(loss_prevention_cooldown_loss_count, 0)
            FROM {ml}
            WHERE id = %s
            """,
            (int(hero_id),),
        )
        row = cursor.fetchone()
    except Exception as exc:
        _log.debug("market-wide LP hero read failed id=%s: %s", hero_id, exc)
        return "off"
    if not row or not bool(row[0]):
        return "off"
    if int(row[1] or 0) >= int(threshold):
        return symbol_wide_loss_prevention_state(MARKET_WIDE_LP_BASE)
    return "off"


def _market_wide_extra_recipient_sql(
    global_hero_id: Optional[int],
    symbol_publisher_ids: list[int],
) -> Tuple[str, Tuple[Any, ...]]:
    """OR-clauses for monitors that receive market-wide LP without symbol_wide follower flag."""
    clauses: list[str] = []
    params: list[Any] = []
    seen: set[int] = set()

    def _add(mid: Optional[int]) -> None:
        if mid is None:
            return
        try:
            i = int(mid)
        except (TypeError, ValueError):
            return
        if i in seen:
            return
        seen.add(i)
        clauses.append("(id = %s AND COALESCE(loss_prevention_toggle, FALSE) IS TRUE)")
        params.append(i)

    _add(global_hero_id)
    for pid in symbol_publisher_ids:
        _add(pid)
    if not clauses:
        return "", ()
    return " OR " + " OR ".join(clauses), tuple(params)


def sync_market_wide_loss_prevention_followers(cursor, monitor_list_qualified: str) -> int:
    """Project market-wide LP into symbol_wide followers, global MW hero, and symbol LP publishers."""
    ml = str(monitor_list_qualified or "").strip()
    if not re.match(r"^(?:users|users_\d{4})\.monitor_list_\d{4}$", ml, re.I):
        _log.debug("market-wide LP sync skipped: invalid monitor_list %r", monitor_list_qualified)
        return 0
    mw = compute_market_wide_loss_prevention_state(cursor, ml)
    mw_base = normalize_loss_prevention_state_for_sizing(mw)
    mw_severity = loss_prevention_state_severity(mw)
    updated = 0
    slot_mw = _monitor_list_slot(ml)
    hero_id_for_row: Optional[int] = None
    symbol_publishers: list[int] = []
    if slot_mw == "0001":
        try:
            symbol_publishers = [int(x) for x in configured_symbol_wide_monitor_ids(cursor, ml)]
        except (TypeError, ValueError):
            symbol_publishers = []
    if slot_mw:
        _en_h, hero_id_for_row, _th_h = read_market_wide_loss_prevention_settings(cursor, slot_mw)
        if hero_id_for_row is not None:
            try:
                hero_id_for_row = int(hero_id_for_row)
            except (TypeError, ValueError):
                hero_id_for_row = None
    extra_or_sql, extra_params = _market_wide_extra_recipient_sql(
        hero_id_for_row, symbol_publishers
    )
    if mw_base != "off":
        local_state_expr = _sql_local_loss_prevention_state_expr()
        local_severity_expr = _sql_loss_prevention_severity_expr(local_state_expr)
        try:
            cursor.execute(
                f"""
                UPDATE {ml}
                SET loss_prevention_state = (
                    CASE
                        WHEN {local_severity_expr} >= %s THEN {local_state_expr}
                        ELSE %s
                    END
                ),
                updated_at = CURRENT_TIMESTAMP
                WHERE (
                    (
                        COALESCE(symbol_wide_loss_prevention, FALSE) IS TRUE
                        AND COALESCE(loss_prevention_toggle, FALSE) IS TRUE
                    )
                    {extra_or_sql}
                )
                  AND loss_prevention_state IS DISTINCT FROM (
                    CASE
                        WHEN {local_severity_expr} >= %s THEN {local_state_expr}
                        ELSE %s
                    END
                  )
                """,
                (mw_severity, mw) + extra_params + (mw_severity, mw),
            )
            updated += int(getattr(cursor, "rowcount", 0) or 0)
        except Exception as exc:
            _log.debug("market-wide LP follower active sync failed: %s", exc)
        return updated

    try:
        extra_scan_sql, scan_params = _market_wide_extra_recipient_sql(
            hero_id_for_row, symbol_publishers
        )
        cursor.execute(
            f"""
            SELECT id, loss_prevention_state
            FROM {ml}
            WHERE (
                (
                    COALESCE(symbol_wide_loss_prevention, FALSE) IS TRUE
                    AND COALESCE(loss_prevention_toggle, FALSE) IS TRUE
                )
                {extra_scan_sql}
            )
            """,
            scan_params,
        )
        rows = cursor.fetchall() or []
    except Exception as exc:
        _log.debug("market-wide LP follower clear scan failed: %s", exc)
        return 0
    for mid, st in rows:
        base = normalize_loss_prevention_state_for_sizing(st)
        if base == MARKET_WIDE_LP_BASE and is_symbol_wide_loss_prevention_state(st):
            if project_symbol_wide_loss_prevention_to_monitor(cursor, ml, str(mid)):
                updated += 1
    return updated


def try_sync_market_wide_after_hero_recompute(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> None:
    """When the configured global hero monitor is recomputed, refresh market-wide follower rows."""
    slot = _monitor_list_slot(monitor_list_qualified)
    if not slot:
        return
    _enabled, hero_id, _th = read_market_wide_loss_prevention_settings(cursor, slot)
    if hero_id is None:
        return
    if str(hero_id).strip() != str(monitor_id).strip():
        return
    try:
        sync_market_wide_loss_prevention_followers(cursor, monitor_list_qualified)
    except Exception as exc:
        _log.debug("market-wide LP sync after hero recompute failed: %s", exc)


def _fetch_monitor_lp_row(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> Optional[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT id,
               name,
               symbol,
               loss_prevention_state,
               COALESCE(loss_prevention_duration, 4),
               simulated_loss_prevention_cooldown_start_time,
               original_loss_prevention_cooldown_start_time,
               COALESCE(loss_prevention_cooldown_loss_count, 0),
               live_loss_prevention_cooldown_start_time,
               COALESCE(loss_prevention_toggle, FALSE),
               COALESCE(symbol_wide_loss_prevention, FALSE),
               {_sql_local_loss_prevention_state_expr()} AS computed_local_loss_prevention_state
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "symbol": row[2],
        "loss_prevention_state": row[3],
        "loss_prevention_duration": row[4],
        "simulated_loss_prevention_cooldown_start_time": row[5],
        "original_loss_prevention_cooldown_start_time": row[6],
        "loss_prevention_cooldown_loss_count": row[7],
        "live_loss_prevention_cooldown_start_time": row[8],
        "loss_prevention_toggle": row[9],
        "symbol_wide_loss_prevention": row[10],
        "computed_local_loss_prevention_state": row[11],
    }


def is_symbol_wide_loss_prevention_publisher(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> bool:
    """True when this monitor publishes LP for its symbol via live_symbol_status.monitor_follow."""
    slot = _monitor_list_slot(monitor_list_qualified)
    if slot != "0001":
        return False
    mid = str(monitor_id or "").strip()
    if not mid:
        return False
    ml = str(monitor_list_qualified or "").strip()
    if not re.match(r"^(?:users|users_\d{4})\.monitor_list_\d{4}$", ml, re.I):
        return False
    try:
        cursor.execute(
            f"""
            SELECT 1
            FROM live_data.live_symbol_status AS lss
            JOIN {ml} AS m
              ON UPPER(m.symbol) = UPPER(lss.symbol)
             AND BTRIM(COALESCE(m.name, '')) = BTRIM(COALESCE(lss.monitor_follow, ''))
            WHERE m.id = %s
              AND BTRIM(COALESCE(lss.monitor_follow, '')) <> ''
            LIMIT 1
            """,
            (mid,),
        )
        return cursor.fetchone() is not None
    except Exception as exc:
        _log.debug("symbol-wide LP publisher check failed id=%s: %s", mid, exc)
        return False


def configured_symbol_wide_monitor_ids(
    cursor,
    monitor_list_qualified: str,
) -> list[str]:
    """Return user_0001 hero monitor ids referenced by live_symbol_status.monitor_follow."""
    slot = _monitor_list_slot(monitor_list_qualified)
    if slot != "0001":
        return []

    try:
        cursor.execute(
            f"""
            SELECT DISTINCT m.id
            FROM live_data.live_symbol_status AS lss
            JOIN {monitor_list_qualified} AS m
              ON UPPER(m.symbol) = UPPER(lss.symbol)
             AND BTRIM(COALESCE(m.name, '')) = BTRIM(COALESCE(lss.monitor_follow, ''))
            WHERE BTRIM(COALESCE(lss.monitor_follow, '')) <> ''
            ORDER BY m.id
            """
        )
        return [str(row[0]) for row in (cursor.fetchall() or [])]
    except Exception as exc:
        _log.debug("symbol-wide LP configured monitor lookup failed: %s", exc)
        return []


def _symbol_wide_monitor_tables(cursor) -> list[str]:
    cursor.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.columns
        WHERE (table_schema = 'users' OR table_schema ~ '^users_[0-9]{4}$')
          AND table_name LIKE 'monitor_list_%'
          AND column_name IN (
            'id',
            'symbol',
            'loss_prevention_state',
            'loss_prevention_toggle',
            'loss_prevention_method',
            'symbol_wide_loss_prevention',
            'simulated_trade_loss_prevention',
            'loss_prevention_duration',
            'simulated_loss_prevention_cooldown_start_time',
            'live_loss_prevention_cooldown_start_time',
            'loss_prevention_cooldown_loss_count',
            'win_streak',
            'win_streak_threshold',
            'updated_at'
          )
        GROUP BY table_schema, table_name
        HAVING COUNT(DISTINCT column_name) = 14
        ORDER BY table_name
        """
    )
    return [f"{schema}.{table}" for schema, table in (cursor.fetchall() or [])]


def _symbol_wide_live_state_for_symbol(cursor, symbol: str) -> str:
    cursor.execute(
        """
        SELECT loss_prevention_state
        FROM live_data.live_symbol_status
        WHERE UPPER(symbol) = %s
        LIMIT 1
        """,
        (str(symbol or "").strip().upper(),),
    )
    row = cursor.fetchone()
    return symbol_wide_loss_prevention_state(row[0]) if row else "off"


def project_symbol_wide_loss_prevention_to_monitor(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> bool:
    """Project the current symbol-wide state into one follower monitor row."""
    cursor.execute(
        f"""
        SELECT symbol,
               COALESCE(symbol_wide_loss_prevention, FALSE),
               COALESCE(loss_prevention_toggle, FALSE),
               loss_prevention_state,
               {_sql_local_loss_prevention_state_expr()} AS computed_local_loss_prevention_state
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return False

    symbol, follows_symbol_wide, lp_enabled, current_state, local_state = row
    if not (bool(follows_symbol_wide) and bool(lp_enabled)):
        return False

    symbol_state = _symbol_wide_live_state_for_symbol(cursor, str(symbol or ""))
    symbol_base_state = normalize_loss_prevention_state_for_sizing(symbol_state)
    if symbol_base_state != "off":
        projected_state = more_serious_loss_prevention_state(local_state, symbol_state)
        cursor.execute(
            f"""
            UPDATE {monitor_list_qualified}
            SET loss_prevention_state = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND loss_prevention_state IS DISTINCT FROM %s
            """,
            (projected_state, monitor_id, projected_state),
        )
        return bool(getattr(cursor, "rowcount", 0) or 0)

    if not is_symbol_wide_loss_prevention_state(current_state):
        return False

    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET loss_prevention_state = {_sql_local_loss_prevention_state_expr()},
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (monitor_id,),
    )
    return bool(getattr(cursor, "rowcount", 0) or 0)


def sync_symbol_wide_loss_prevention_followers(cursor, symbol: str) -> int:
    """Push live_symbol_status LP state into all follower monitor rows for a symbol."""
    symbol_key = str(symbol or "").strip().upper()
    if not symbol_key:
        return 0

    symbol_state = _symbol_wide_live_state_for_symbol(cursor, symbol_key)
    symbol_base_state = normalize_loss_prevention_state_for_sizing(symbol_state)
    symbol_severity = loss_prevention_state_severity(symbol_state)
    is_active = symbol_base_state != "off"

    updated = 0
    try:
        tables = _symbol_wide_monitor_tables(cursor)
    except Exception as exc:
        _log.debug("symbol-wide LP follower table lookup failed: %s", exc)
        return 0

    for table in tables:
        try:
            if is_active:
                local_state_expr = _sql_local_loss_prevention_state_expr()
                local_severity_expr = _sql_loss_prevention_severity_expr(local_state_expr)
                cursor.execute(
                    f"""
                    UPDATE {table}
                    SET loss_prevention_state = (
                            CASE
                                WHEN {local_severity_expr} >= %s THEN {local_state_expr}
                                ELSE %s
                            END
                        ),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE UPPER(symbol) = %s
                      AND COALESCE(symbol_wide_loss_prevention, FALSE) IS TRUE
                      AND COALESCE(loss_prevention_toggle, FALSE) IS TRUE
                      AND loss_prevention_state IS DISTINCT FROM (
                            CASE
                                WHEN {local_severity_expr} >= %s THEN {local_state_expr}
                                ELSE %s
                            END
                        )
                    """,
                    (symbol_severity, symbol_state, symbol_key, symbol_severity, symbol_state),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {table}
                    SET loss_prevention_state = {_sql_local_loss_prevention_state_expr()},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE UPPER(symbol) = %s
                      AND COALESCE(symbol_wide_loss_prevention, FALSE) IS TRUE
                      AND RIGHT(
                        LOWER(REPLACE(COALESCE(loss_prevention_state, ''), '-', '_')),
                        %s
                      ) = %s
                      AND LOWER(REPLACE(TRIM(COALESCE(loss_prevention_state, '')), '-', '_'))
                          NOT LIKE 'live_loss_market_wide_1c%%'
                    """,
                    (symbol_key, len(SYMBOL_WIDE_SUFFIX), SYMBOL_WIDE_SUFFIX),
                )
            updated += int(getattr(cursor, "rowcount", 0) or 0)
            try:
                sync_market_wide_loss_prevention_followers(cursor, table)
            except Exception as exc:
                _log.debug("market-wide LP re-sync after symbol-wide fanout failed table=%s: %s", table, exc)
        except Exception as exc:
            _log.debug("symbol-wide LP follower projection failed for table=%s: %s", table, exc)
    return updated


def sync_symbol_wide_loss_prevention_from_monitor(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> bool:
    """Copy a user_0001 hero monitor's LP fields into live_symbol_status.

    The row to update is selected by the manually configured
    live_symbol_status.monitor_follow name. ``monitor_follow_id`` is a derived
    cache and is refreshed on every successful sync. Directly updating
    live_symbol_status lets the existing DB trigger publish fanout.
    """
    slot = _monitor_list_slot(monitor_list_qualified)
    if slot != "0001":
        return False

    try:
        monitor = _fetch_monitor_lp_row(cursor, monitor_list_qualified, str(monitor_id))
    except Exception as exc:
        _log.debug("symbol-wide LP sync skipped; monitor row unavailable: %s", exc)
        return False

    if not monitor:
        return False

    monitor_name = str(monitor.get("name") or "").strip()
    symbol = str(monitor.get("symbol") or "").strip().upper()
    if not monitor_name or not symbol:
        return False

    live_state = symbol_wide_loss_prevention_state(monitor.get("loss_prevention_state"))
    try:
        cursor.execute(
            """
            UPDATE live_data.live_symbol_status
            SET monitor_follow_id = %s,
                loss_prevention_state = %s,
                loss_prevention_duration = %s,
                simulated_loss_prevention_cooldown_start_time = %s,
                original_loss_prevention_cooldown_start_time = %s,
                loss_prevention_cooldown_loss_count = %s,
                live_loss_prevention_cooldown_start_time = %s,
                loss_prevention_updated_at = CURRENT_TIMESTAMP
            WHERE UPPER(symbol) = %s
              AND BTRIM(COALESCE(monitor_follow, '')) = %s
            RETURNING symbol
            """,
            (
                int(monitor["id"]),
                live_state,
                int(monitor.get("loss_prevention_duration") or 4),
                monitor.get("simulated_loss_prevention_cooldown_start_time"),
                monitor.get("original_loss_prevention_cooldown_start_time"),
                int(monitor.get("loss_prevention_cooldown_loss_count") or 0),
                monitor.get("live_loss_prevention_cooldown_start_time"),
                symbol,
                monitor_name,
            ),
        )
        updated = cursor.fetchone() is not None
        if not updated:
            _log.debug(
                "symbol-wide LP sync found no live_symbol_status follower for symbol=%s monitor=%s",
                symbol,
                monitor_name,
            )
        else:
            sync_symbol_wide_loss_prevention_followers(cursor, symbol)
        return updated
    except Exception as exc:
        _log.debug(
            "symbol-wide LP sync failed for symbol=%s monitor=%s: %s",
            symbol,
            monitor_name,
            exc,
        )
        return False


def resolve_effective_loss_prevention_state(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> str:
    """Resolve LP state: local, optional per-symbol LSS merge, then optional global market-wide merge."""
    try:
        monitor = _fetch_monitor_lp_row(cursor, monitor_list_qualified, str(monitor_id))
    except Exception as exc:
        _log.debug("effective LP read failed for monitor=%s: %s", monitor_id, exc)
        return "off"

    if not monitor:
        return "off"

    if not bool(monitor.get("loss_prevention_toggle")):
        return "off"

    raw_local_state = monitor.get("loss_prevention_state")
    local_state = normalize_loss_prevention_state_for_sizing(
        monitor.get("computed_local_loss_prevention_state")
        if is_symbol_wide_loss_prevention_state(raw_local_state)
        else raw_local_state
    )

    slot = _monitor_list_slot(monitor_list_qualified)
    mw_hero_id: Optional[int] = None
    if slot:
        _mw_en, mw_hero_raw, _mw_th = read_market_wide_loss_prevention_settings(cursor, slot)
        if mw_hero_raw is not None:
            try:
                mw_hero_id = int(mw_hero_raw)
            except (TypeError, ValueError):
                mw_hero_id = None
    is_global_mw_hero = mw_hero_id is not None and str(mw_hero_id) == str(monitor.get("id"))
    is_symbol_lp_publisher = is_symbol_wide_loss_prevention_publisher(
        cursor, monitor_list_qualified, str(monitor.get("id"))
    )

    two_way = local_state
    if bool(monitor.get("symbol_wide_loss_prevention")):
        symbol = str(monitor.get("symbol") or "").strip().upper()
        if symbol:
            try:
                cursor.execute(
                    """
                    SELECT loss_prevention_state
                    FROM live_data.live_symbol_status
                    WHERE UPPER(symbol) = %s
                    LIMIT 1
                    """,
                    (symbol,),
                )
                row = cursor.fetchone()
            except Exception as exc:
                _log.debug("symbol-wide LP state read failed for symbol=%s: %s", symbol, exc)
                row = None
            if row:
                symbol_state = row[0]
                if normalize_loss_prevention_state_for_sizing(symbol_state) != "off":
                    two_way = more_serious_loss_prevention_state(local_state, symbol_state)

    mw = compute_market_wide_loss_prevention_state(cursor, monitor_list_qualified)
    if normalize_loss_prevention_state_for_sizing(mw) == "off":
        return two_way
    if (
        bool(monitor.get("symbol_wide_loss_prevention"))
        or is_global_mw_hero
        or is_symbol_lp_publisher
    ):
        return more_serious_loss_prevention_state(two_way, mw)
    return two_way
