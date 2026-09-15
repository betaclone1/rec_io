"""Cross-tenant enrollment of open High Water Scalp positions (SELECT-only)."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.high_water_scalp import is_high_water_scalp, remaining_contracts

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("open", "pending", "closing", "partial")
_MONITOR_KEY_RE = re.compile(r"^mon_(\d+)_(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class EnrolledPosition:
    tenant_slot: str
    trade_id: int
    status: str
    ticker: str
    side: str
    trade_strategy: str
    position: float
    close_filled_count: float
    remaining: float
    buy_price: Optional[float]
    stop_loss_offset: Optional[float]
    limit_close_price: Optional[float]
    paper_trade: bool
    market: Optional[str]
    monitor_key: Optional[str] = None
    monitor_id: Optional[int] = None
    stop_loss_price: Optional[float] = None
    position_risk_mode: str = "legacy"
    position_risk_policy: str = "hws_lvw_v1"
    position_risk_book_only_enabled: bool = False
    remaining_position_generation: int = 0

    def key(self) -> str:
        return f"{self.tenant_slot}:{self.trade_id}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _trades_table_pairs(cursor) -> List[Tuple[str, str, str]]:
    cursor.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema ~ '^users_[0-9]{4}$'
          AND table_name ~ '^trades_[0-9]{4}$'
          AND replace(table_schema, 'users_', '') = replace(table_name, 'trades_', '')
        ORDER BY table_schema, table_name
        """
    )
    out: List[Tuple[str, str, str]] = []
    for schema, table in cursor.fetchall() or ():
        slot = str(schema).replace("users_", "")
        out.append((slot, str(schema), str(table)))
    return out


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_monitor_id(monitor_key: Any) -> Optional[int]:
    if monitor_key is None:
        return None
    s = str(monitor_key).strip()
    m = _MONITOR_KEY_RE.match(s)
    if m:
        try:
            return int(m.group(2))
        except (TypeError, ValueError):
            return None
    if s.isdigit():
        try:
            return int(s)
        except (TypeError, ValueError):
            return None
    return None


def _table_has_column(cursor, schema: str, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        LIMIT 1
        """,
        (schema, table, column),
    )
    return cursor.fetchone() is not None


def fetch_open_hws_positions(
    conn,
    *,
    market_filter: Optional[Sequence[str]] = ("15m",),
) -> List[EnrolledPosition]:
    """SELECT-only discovery of open High Water Scalp rows across all tenant trade tables."""
    cur = conn.cursor()
    pairs = _trades_table_pairs(cur)
    rows: List[EnrolledPosition] = []
    markets = {str(m).strip().lower() for m in (market_filter or ()) if str(m).strip()}
    for slot, schema, table in pairs:
        ml = f"monitor_list_{slot}"
        has_ml = _table_has_column(cur, schema, ml, "id") if ml else False
        has_prm = has_ml and _table_has_column(cur, schema, ml, "position_risk_mode")
        has_trade_prm = _table_has_column(cur, schema, table, "position_risk_mode")
        has_slp_trade = _table_has_column(cur, schema, table, "stop_loss_price")

        select_cols = [
            "t.id",
            "t.status",
            "t.ticker",
            "t.side",
            "t.trade_strategy",
            "t.position",
            "COALESCE(t.close_filled_count, 0)",
            "t.buy_price",
            "t.stop_loss_offset",
            "t.limit_close_price",
            "t.paper_trade",
            "t.market",
            "t.monitor",
        ]
        if has_slp_trade:
            select_cols.append("t.stop_loss_price")
        else:
            select_cols.append("NULL::numeric AS stop_loss_price")

        # Live monitor settings win over stale trade snapshot (paper vs legacy authority).
        if has_prm and has_trade_prm:
            select_cols.extend(
                [
                    "COALESCE(m.position_risk_mode, t.position_risk_mode, 'legacy')",
                    "COALESCE(m.position_risk_policy, t.position_risk_policy, 'hws_lvw_v1')",
                    "COALESCE(m.position_risk_book_only_enabled, t.position_risk_book_only_enabled, FALSE)",
                ]
            )
        elif has_prm:
            select_cols.extend(
                [
                    "COALESCE(m.position_risk_mode, 'legacy')",
                    "COALESCE(m.position_risk_policy, 'hws_lvw_v1')",
                    "COALESCE(m.position_risk_book_only_enabled, FALSE)",
                ]
            )
        elif has_trade_prm:
            select_cols.extend(
                [
                    "COALESCE(t.position_risk_mode, 'legacy')",
                    "COALESCE(t.position_risk_policy, 'hws_lvw_v1')",
                    "COALESCE(t.position_risk_book_only_enabled, FALSE)",
                ]
            )
        else:
            select_cols.extend(
                [
                    "'legacy'::text",
                    "'hws_lvw_v1'::text",
                    "FALSE",
                ]
            )

        if has_ml:
            # Prefer monitor_list stop_loss_price when trade snapshot missing.
            select_cols.append("m.stop_loss_price AS monitor_stop_loss_price")
            if has_prm and not has_trade_prm:
                pass
            join_sql = f"""
                LEFT JOIN {schema}.{ml} m
                  ON m.id = CASE
                    WHEN t.monitor ~* '^mon_[0-9]+_[0-9]+$'
                      THEN NULLIF(substring(t.monitor from '_([0-9]+)$'), '')::int
                    WHEN t.monitor ~ '^[0-9]+$'
                      THEN t.monitor::int
                    ELSE NULL
                  END
            """
        else:
            select_cols.append("NULL::numeric AS monitor_stop_loss_price")
            join_sql = ""

        sql = f"""
            SELECT {", ".join(select_cols)}
            FROM {schema}.{table} t
            {join_sql}
            WHERE t.status = ANY(%s)
        """
        cur.execute(sql, (list(OPEN_STATUSES),))
        for r in cur.fetchall() or ():
            (
                trade_id,
                status,
                ticker,
                side,
                strategy,
                position,
                filled,
                buy_price,
                stop_off,
                lim_close,
                paper,
                market,
                monitor_key,
                stop_loss_price,
                prm,
                prp,
                prb,
                mon_slp,
            ) = r
            if not is_high_water_scalp(strategy):
                continue
            mkt = (str(market).strip().lower() if market is not None else "") or None
            if markets and mkt not in markets and mkt is not None:
                continue
            if markets and mkt is None:
                if "15M" not in str(ticker or "").upper():
                    continue
            pos_f = float(position or 0)
            filled_f = float(filled or 0)
            rem = float(remaining_contracts(pos_f, filled_f))
            if rem <= 0 and str(status).lower() not in ("pending",):
                continue
            pt = paper
            if isinstance(pt, str):
                pt = pt.lower() in ("true", "1", "yes", "t")
            else:
                pt = bool(pt)
            rem_use = rem if rem > 0 else pos_f
            # Generation bumps when remaining qty changes (integer contracts).
            rem_gen = int(round(rem_use))
            slp = _f(stop_loss_price)
            if slp is None:
                slp = _f(mon_slp)
            mid = _parse_monitor_id(monitor_key)
            book_only = prb
            if isinstance(book_only, str):
                book_only = book_only.lower() in ("true", "1", "yes", "t")
            else:
                book_only = bool(book_only)
            rows.append(
                EnrolledPosition(
                    tenant_slot=slot,
                    trade_id=int(trade_id),
                    status=str(status),
                    ticker=str(ticker or ""),
                    side=str(side or ""),
                    trade_strategy=str(strategy or ""),
                    position=pos_f,
                    close_filled_count=filled_f,
                    remaining=rem_use,
                    buy_price=_f(buy_price),
                    stop_loss_offset=_f(stop_off),
                    limit_close_price=_f(lim_close),
                    paper_trade=pt,
                    market=mkt,
                    monitor_key=str(monitor_key) if monitor_key is not None else None,
                    monitor_id=mid,
                    stop_loss_price=slp,
                    position_risk_mode=str(prm or "legacy").strip().lower() or "legacy",
                    position_risk_policy=str(prp or "hws_lvw_v1").strip() or "hws_lvw_v1",
                    position_risk_book_only_enabled=book_only,
                    remaining_position_generation=rem_gen,
                )
            )
    rows.sort(key=lambda p: (p.tenant_slot, p.trade_id))
    return rows
