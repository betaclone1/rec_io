"""
Catalog and snapshots for the local Live Path Cache Monitor UI.

Unauthenticated debug tooling only — same contract as prior active-trades hot-path proof.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.core import live_state_cache as lsc
from backend.core import live_state_active_trades as ls_at
from backend.core import live_state_kalshi_portfolio as lskp
from backend.core.live_state_config import live_state_cache_enabled
from backend.trading_mode import _norm_slot

SOURCE_ACTIVE_TRADES = "active_trades"
SOURCE_MARKET = "market"
SOURCE_SYMBOL = "symbol"
SOURCE_STRIKE_LADDER = "strike_ladder"
SOURCE_KALSHI_POSITIONS = "kalshi_positions"
SOURCE_KALSHI_ORDERS = "kalshi_orders"
SOURCE_KALSHI_FILLS = "kalshi_fills"
SOURCE_REDIS_KEY = "redis_key"


@dataclass(frozen=True)
class LivePathSourceParam:
    name: str
    label: str
    required: bool = False
    default: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class LivePathRowColumn:
    field: str
    label: str
    numeric: bool = False


@dataclass(frozen=True)
class LivePathSourceDef:
    id: str
    label: str
    description: str
    redis_key_template: str
    live_kind: Optional[str]  # rec_io:live_state:updated kind filter
    params: Tuple[LivePathSourceParam, ...] = ()
    row_mode: bool = False  # table + patch stream (active_trades)
    row_id_field: str = "row_id"
    row_columns: Tuple[LivePathRowColumn, ...] = ()


def source_catalog() -> List[Dict[str, Any]]:
    defs = _all_sources()
    return [
        {
            "id": d.id,
            "label": d.label,
            "description": d.description,
            "redis_key_template": d.redis_key_template,
            "live_kind": d.live_kind,
            "row_mode": d.row_mode,
            "row_id_field": d.row_id_field,
            "row_columns": [
                {"field": c.field, "label": c.label, "numeric": c.numeric}
                for c in d.row_columns
            ],
            "params": [
                {
                    "name": p.name,
                    "label": p.label,
                    "required": p.required,
                    "default": p.default,
                    "placeholder": p.placeholder,
                }
                for p in d.params
            ],
        }
        for d in defs
    ]


def _all_sources() -> List[LivePathSourceDef]:
    _active_cols = (
        LivePathRowColumn("trade_id", "trade_id"),
        LivePathRowColumn("status", "status"),
        LivePathRowColumn("ticker", "ticker"),
        LivePathRowColumn("buy_price", "buy", numeric=True),
        LivePathRowColumn("sell_price", "sell", numeric=True),
        LivePathRowColumn("pnl", "pnl", numeric=True),
        LivePathRowColumn("current_probability", "prob", numeric=True),
    )
    return [
        LivePathSourceDef(
            id=SOURCE_ACTIVE_TRADES,
            label="Active trades (tenant pool)",
            description="Redis hash of open positions; WS sends row patches (sell, pnl).",
            redis_key_template="rec_io:live_state:v1:tenant:{user_no}:active_trades",
            live_kind="active_trades",
            row_mode=True,
            row_id_field="trade_id",
            row_columns=_active_cols,
            params=(
                LivePathSourceParam("user_no", "Tenant slot", True, "0001", "0001"),
            ),
        ),
        LivePathSourceDef(
            id=SOURCE_KALSHI_POSITIONS,
            label="Kalshi positions (hot)",
            description="Ephemeral open Kalshi market positions from portfolio WS.",
            redis_key_template="rec_io:live_state:v1:tenant:{user_no}:kalshi:positions",
            live_kind=lskp.KIND_POSITIONS,
            row_mode=True,
            row_id_field="row_id",
            row_columns=(
                LivePathRowColumn("ticker", "ticker"),
                LivePathRowColumn("position_fp", "position_fp"),
                LivePathRowColumn("position_cost_dollars", "position_cost_dollars"),
                LivePathRowColumn("realized_pnl_dollars", "realized_pnl_dollars"),
                LivePathRowColumn("last_updated_ts", "updated"),
            ),
            params=(LivePathSourceParam("user_no", "Tenant slot", True, "0001", "0001"),),
        ),
        LivePathSourceDef(
            id=SOURCE_KALSHI_ORDERS,
            label="Kalshi orders (hot)",
            description="Recent Kalshi orders from portfolio WS (bounded hash).",
            redis_key_template="rec_io:live_state:v1:tenant:{user_no}:kalshi:orders",
            live_kind=lskp.KIND_ORDERS,
            row_mode=True,
            row_id_field="row_id",
            row_columns=(
                LivePathRowColumn("order_id", "order_id"),
                LivePathRowColumn("ticker", "ticker"),
                LivePathRowColumn("status", "status"),
                LivePathRowColumn("orderbook_side", "orderbook_side"),
                LivePathRowColumn("outcome_side", "outcome_side"),
                LivePathRowColumn("initial_count", "initial_count", numeric=True),
                LivePathRowColumn("fill_count", "fill_count", numeric=True),
                LivePathRowColumn("remaining_count", "remaining_count", numeric=True),
                LivePathRowColumn("yes_price_dollars", "yes_px"),
            ),
            params=(LivePathSourceParam("user_no", "Tenant slot", True, "0001", "0001"),),
        ),
        LivePathSourceDef(
            id=SOURCE_KALSHI_FILLS,
            label="Kalshi fills (hot)",
            description="Recent Kalshi fills from portfolio WS (bounded hash).",
            redis_key_template="rec_io:live_state:v1:tenant:{user_no}:kalshi:fills",
            live_kind=lskp.KIND_FILLS,
            row_mode=True,
            row_id_field="row_id",
            row_columns=(
                LivePathRowColumn("trade_id", "trade_id"),
                LivePathRowColumn("ticker", "ticker"),
                LivePathRowColumn("order_id", "order_id"),
                LivePathRowColumn("orderbook_side", "orderbook_side"),
                LivePathRowColumn("outcome_side", "outcome_side"),
                LivePathRowColumn("count_fp", "count", numeric=True),
                LivePathRowColumn("yes_price_dollars", "yes_px"),
                LivePathRowColumn("created_time", "created"),
            ),
            params=(LivePathSourceParam("user_no", "Tenant slot", True, "0001", "0001"),),
        ),
        LivePathSourceDef(
            id=SOURCE_MARKET,
            label="Market ladder (Kalshi)",
            description="live_state market envelope; updates on rec_io:live_state:updated.",
            redis_key_template="rec_io:live_state:v1:market:{exchange}:{market}:{symbol}",
            live_kind="market",
            params=(
                LivePathSourceParam("exchange", "Exchange", False, "kalshi"),
                LivePathSourceParam("market", "Market", False, "15m"),
                LivePathSourceParam("symbol", "Symbol", True, "BTC"),
            ),
        ),
        LivePathSourceDef(
            id=SOURCE_SYMBOL,
            label="Symbol price",
            description="live_state symbol metrics envelope.",
            redis_key_template="rec_io:live_state:v1:symbol:{symbol}",
            live_kind="symbol",
            params=(LivePathSourceParam("symbol", "Symbol", True, "BTC"),),
        ),
        LivePathSourceDef(
            id=SOURCE_STRIKE_LADDER,
            label="Strike ladder",
            description="Generated strike table rows in live_state.",
            redis_key_template="rec_io:live_state:v1:strike_ladder:{exchange}:{market}:{symbol}",
            live_kind="strike_ladder",
            params=(
                LivePathSourceParam("exchange", "Exchange", False, "kalshi"),
                LivePathSourceParam("market", "Market", False, "15m"),
                LivePathSourceParam("symbol", "Symbol", True, "BTC"),
            ),
        ),
        LivePathSourceDef(
            id=SOURCE_REDIS_KEY,
            label="Raw Redis key",
            description="Read any string/hash key (JSON values decoded when possible).",
            redis_key_template="{redis_key}",
            live_kind=None,
            params=(
                LivePathSourceParam(
                    "redis_key",
                    "Full key",
                    True,
                    "",
                    "rec_io:live_state:v1:market:kalshi:15m:BTC",
                ),
            ),
        ),
    ]


def get_source_def(source_id: str) -> Optional[LivePathSourceDef]:
    sid = str(source_id or "").strip().lower()
    for d in _all_sources():
        if d.id == sid:
            return d
    return None


PATCH_SCOPE_TRADE_LOG = "trade_log"
PATCH_SCOPE_ACTIVE_TRADES_UI = "active_trades_ui"


@dataclass
class LivePathMonitorSpec:
    source: str
    user_no: str = "0001"
    exchange: str = "kalshi"
    market: str = "15m"
    symbol: str = "BTC"
    redis_key: str = ""
    # active_trades WS only: trade_log = sell/pnl (history); active_trades_ui adds live prob.
    patch_scope: str = PATCH_SCOPE_ACTIVE_TRADES_UI

    def subscription_key(self) -> str:
        if self.source == SOURCE_ACTIVE_TRADES:
            return f"{SOURCE_ACTIVE_TRADES}:{_norm_slot(self.user_no)}"
        if self.source in (SOURCE_KALSHI_POSITIONS, SOURCE_KALSHI_ORDERS, SOURCE_KALSHI_FILLS):
            return f"{self.source}:{_norm_slot(self.user_no)}"
        if self.source == SOURCE_REDIS_KEY:
            return f"{SOURCE_REDIS_KEY}:{self.redis_key.strip()}"
        return ":".join(
            [
                self.source,
                self.exchange.strip().lower(),
                self.market.strip().lower(),
                self.symbol.strip().upper(),
            ]
        )

    def resolved_redis_key(self) -> str:
        d = get_source_def(self.source)
        if not d:
            return ""
        if self.source == SOURCE_ACTIVE_TRADES:
            return ls_at.tenant_active_trades_key(self.user_no)
        if self.source == SOURCE_KALSHI_POSITIONS:
            return lskp.tenant_kalshi_positions_key(self.user_no)
        if self.source == SOURCE_KALSHI_ORDERS:
            return lskp.tenant_kalshi_orders_key(self.user_no)
        if self.source == SOURCE_KALSHI_FILLS:
            return lskp.tenant_kalshi_fills_key(self.user_no)
        if self.source == SOURCE_REDIS_KEY:
            return self.redis_key.strip()
        if self.source == SOURCE_MARKET:
            return lsc.market_key(self.exchange, self.market, self.symbol)
        if self.source == SOURCE_SYMBOL:
            return lsc.symbol_key(self.symbol)
        if self.source == SOURCE_STRIKE_LADDER:
            return lsc.strike_ladder_key(self.exchange, self.market, self.symbol)
        return ""

    def matches_live_state_message(self, obj: Dict[str, Any]) -> bool:
        if str(obj.get("type") or "") != "live_state_updated":
            return False
        d = get_source_def(self.source)
        if not d or not d.live_kind:
            return False
        if str(obj.get("kind") or "") != d.live_kind:
            return False
        msg_key = str(obj.get("key") or "")
        return msg_key == self.resolved_redis_key()


def parse_spec_from_query(
    *,
    source: str,
    user_no: str = "0001",
    exchange: str = "kalshi",
    market: str = "15m",
    symbol: str = "BTC",
    redis_key: str = "",
    patch_scope: str = PATCH_SCOPE_ACTIVE_TRADES_UI,
) -> LivePathMonitorSpec:
    scope = str(patch_scope or PATCH_SCOPE_ACTIVE_TRADES_UI).strip()
    if scope not in (PATCH_SCOPE_TRADE_LOG, PATCH_SCOPE_ACTIVE_TRADES_UI):
        scope = PATCH_SCOPE_ACTIVE_TRADES_UI
    return LivePathMonitorSpec(
        source=str(source or SOURCE_ACTIVE_TRADES).strip().lower(),
        user_no=_norm_slot(user_no) if user_no else "0001",
        exchange=str(exchange or "kalshi").strip().lower(),
        market=str(market or "15m").strip().lower(),
        symbol=str(symbol or "BTC").strip().upper(),
        redis_key=str(redis_key or "").strip(),
        patch_scope=scope,
    )


def validate_spec(spec: LivePathMonitorSpec) -> Optional[str]:
    d = get_source_def(spec.source)
    if not d:
        return f"unknown source: {spec.source}"
    for p in d.params:
        if not p.required:
            continue
        val = getattr(spec, p.name, None)
        if p.name == "redis_key":
            val = spec.redis_key
        if val is None or str(val).strip() == "":
            return f"missing required param: {p.name}"
    if spec.source == SOURCE_ACTIVE_TRADES:
        u = str(spec.user_no).strip()
        if not u.isdigit() or len(u) > 4:
            return "user_no must be a numeric tenant slot (e.g. 0001)"
    if spec.source in (SOURCE_KALSHI_POSITIONS, SOURCE_KALSHI_ORDERS, SOURCE_KALSHI_FILLS):
        u = str(spec.user_no).strip()
        if not u.isdigit() or len(u) > 4:
            return "user_no must be a numeric tenant slot (e.g. 0001)"
    return None


def _trade_row_for_monitor(rec: Dict[str, Any]) -> Dict[str, Any]:
    tid = rec.get("trade_id")
    if tid is None:
        return {}
    mcp = rec.get("current_close_price")
    sell = None
    if mcp is not None:
        try:
            sell = round(1.0 - float(mcp), 6)
        except (TypeError, ValueError):
            pass
    return {
        "trade_id": tid,
        "status": rec.get("status"),
        "ticker": rec.get("ticker"),
        "buy_price": rec.get("buy_price"),
        "sell_price": sell,
        "pnl": rec.get("current_pnl"),
        "current_probability": rec.get("current_probability"),
    }


def _sell_and_pnl_patch_fields(rec: dict) -> Dict[str, Any]:
    mcp = rec.get("current_close_price")
    sell = None
    if mcp is not None:
        try:
            sell = round(1.0 - float(mcp), 6)
        except (TypeError, ValueError):
            pass
    pnl = rec.get("current_pnl")
    out: Dict[str, Any] = {
        "pnl": str(pnl).strip() if pnl is not None else None,
    }
    if sell is not None:
        # trade monitor WS uses ``sell``; live path monitor row columns use ``sell_price``.
        out["sell"] = sell
        out["sell_price"] = sell
    return out


def trade_log_live_patch_fields(rec: dict) -> Dict[str, Any]:
    """Trade history / trades_* mirror — sell and pnl only (prob frozen at open)."""
    return _sell_and_pnl_patch_fields(rec)


def active_trades_ui_live_patch_fields(rec: dict) -> Dict[str, Any]:
    """Trade monitor active-trades panel — includes live prob for ATS / risk styling."""
    out = _sell_and_pnl_patch_fields(rec)
    prob = rec.get("current_probability")
    if prob is not None:
        try:
            prob_f = float(prob)
            # trade monitor WS uses ``prob``; live path monitor row columns use ``current_probability``.
            out["prob"] = prob_f
            out["current_probability"] = prob_f
        except (TypeError, ValueError):
            pass
    return out


def trade_live_patch_fields(rec: dict) -> Dict[str, Any]:
    """Alias for trade-log patches (backward compatible)."""
    return trade_log_live_patch_fields(rec)


def live_patch_fields_for_scope(scope: str, rec: dict) -> Dict[str, Any]:
    if str(scope or "").strip() == PATCH_SCOPE_TRADE_LOG:
        return trade_log_live_patch_fields(rec)
    return active_trades_ui_live_patch_fields(rec)


def _compact_market_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    markets = data.get("markets") if isinstance(data.get("markets"), list) else []
    rows = []
    for m in markets[:12]:
        if not isinstance(m, dict):
            continue
        rows.append(
            {
                "ticker": m.get("ticker") or m.get("market_ticker"),
                "floor_strike": m.get("floor_strike"),
                "yes_ask": m.get("yes_ask_dollars"),
                "no_ask": m.get("no_ask_dollars"),
                "status": m.get("status"),
            }
        )
    return {
        "event_ticker": data.get("event_ticker"),
        "market_count": len(markets),
        "markets_preview": rows,
    }


def _compact_symbol_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "price",
        "current_price",
        "momentum",
        "momentum_percentile",
        "volatility",
        "ttc_seconds",
    )
    return {k: data.get(k) for k in keys if k in data}


def _compact_ladder_summary(data: Any) -> Dict[str, Any]:
    rows = data if isinstance(data, list) else []
    preview = []
    for row in rows[:8]:
        if isinstance(row, dict):
            preview.append(
                {
                    "strike": row.get("strike"),
                    "probability": row.get("probability") or row.get("probability_15m"),
                    "yes_ask": row.get("yes_ask_dollars"),
                    "buffer": row.get("buffer"),
                }
            )
    return {"row_count": len(rows), "rows_preview": preview}


def build_snapshot(spec: LivePathMonitorSpec) -> Dict[str, Any]:
    err = validate_spec(spec)
    if err:
        return {"error": err}
    ts = time.time()
    key = spec.resolved_redis_key()
    base: Dict[str, Any] = {
        "source": spec.source,
        "subscription_key": spec.subscription_key(),
        "redis_key": key,
        "live_state_cache_enabled": live_state_cache_enabled(),
        "server_ts": ts,
    }
    if spec.source == SOURCE_ACTIVE_TRADES:
        enabled = ls_at.live_state_active_trades_enabled()
        records = ls_at.list_trades(spec.user_no) if enabled else []
        rows = []
        for rec in records:
            row = _trade_row_for_monitor(rec)
            if row:
                rows.append(row)
        base.update(
            {
                "active_trades_hot_path_enabled": enabled,
                "record_count": len(rows),
                "rows": rows,
                "records": records,
            }
        )
        return base
    if spec.source == SOURCE_KALSHI_POSITIONS:
        enabled = lskp.live_state_kalshi_portfolio_enabled()
        records = lskp.list_positions(spec.user_no) if enabled else []
        rows = [lskp.position_row_for_monitor(rec) for rec in records]
        base.update(
            {
                "kalshi_portfolio_hot_path_enabled": enabled,
                "record_count": len(rows),
                "rows": rows,
                "records": records,
            }
        )
        return base
    if spec.source == SOURCE_KALSHI_ORDERS:
        enabled = lskp.live_state_kalshi_portfolio_enabled()
        records = lskp.list_orders(spec.user_no) if enabled else []
        rows = [lskp.order_row_for_monitor(rec) for rec in records]
        base.update(
            {
                "kalshi_portfolio_hot_path_enabled": enabled,
                "record_count": len(rows),
                "rows": rows,
                "records": records,
            }
        )
        return base
    if spec.source == SOURCE_KALSHI_FILLS:
        enabled = lskp.live_state_kalshi_portfolio_enabled()
        records = lskp.list_fills(spec.user_no) if enabled else []
        rows = [lskp.fill_row_for_monitor(rec) for rec in records]
        base.update(
            {
                "kalshi_portfolio_hot_path_enabled": enabled,
                "record_count": len(rows),
                "rows": rows,
                "records": records,
            }
        )
        return base
    if spec.source == SOURCE_REDIS_KEY:
        return {**base, **_read_raw_redis_key(key)}
    env = _read_envelope_for_spec(spec)
    if env is None:
        base["envelope"] = None
        base["age_sec"] = None
        base["summary"] = None
        return base
    data = env.get("data")
    age = lsc.cache_age_sec(env)
    summary: Any = data
    if spec.source == SOURCE_MARKET and isinstance(data, dict):
        summary = _compact_market_summary(data)
    elif spec.source == SOURCE_SYMBOL and isinstance(data, dict):
        summary = _compact_symbol_summary(data)
    elif spec.source == SOURCE_STRIKE_LADDER:
        summary = _compact_ladder_summary(data)
    base["envelope"] = env
    base["age_sec"] = round(age, 3) if age != float("inf") else None
    base["summary"] = summary
    return base


def _read_envelope_for_spec(spec: LivePathMonitorSpec) -> Optional[Dict[str, Any]]:
    if spec.source == SOURCE_MARKET:
        return lsc.get_market(spec.exchange, spec.market, spec.symbol)
    if spec.source == SOURCE_SYMBOL:
        return lsc.get_symbol(spec.symbol)
    if spec.source == SOURCE_STRIKE_LADDER:
        return lsc.get_strike_ladder(spec.exchange, spec.market, spec.symbol)
    return None


def _read_raw_redis_key(key: str) -> Dict[str, Any]:
    r = lsc.redis_client_optional()
    if not r or not key:
        return {"error": "redis unavailable or empty key", "value": None, "redis_type": None}
    try:
        ktype = r.type(key)
        if ktype == "hash":
            raw = r.hgetall(key)
            decoded: Dict[str, Any] = {}
            for fk, fv in raw.items():
                try:
                    decoded[fk] = json.loads(fv)
                except Exception:
                    decoded[fk] = fv
            return {
                "redis_type": "hash",
                "field_count": len(decoded),
                "value": decoded,
            }
        if ktype == "string":
            raw = r.get(key)
            try:
                val: Any = json.loads(raw) if raw else None
            except Exception:
                val = raw
            return {"redis_type": "string", "value": val}
        return {"redis_type": ktype, "value": None, "error": f"unsupported type: {ktype}"}
    except Exception as exc:
        return {"error": str(exc), "value": None, "redis_type": None}


def build_cache_event_payload(spec: LivePathMonitorSpec, obj: Dict[str, Any]) -> Dict[str, Any]:
    snap = build_snapshot(spec)
    return {
        "type": "cache_event",
        "source": spec.source,
        "redis_key": spec.resolved_redis_key(),
        "live_state": {
            "kind": obj.get("kind"),
            "key": obj.get("key"),
            "detail": obj.get("detail"),
        },
        "age_sec": snap.get("age_sec"),
        "summary": snap.get("summary"),
        "record_count": snap.get("record_count"),
        "ts": time.time(),
    }


def build_cache_init_payload(spec: LivePathMonitorSpec) -> Dict[str, Any]:
    snap = build_snapshot(spec)
    d = get_source_def(spec.source)
    return {
        "type": "cache_init",
        "source": spec.source,
        "row_mode": bool(d and d.row_mode),
        "subscription_key": spec.subscription_key(),
        "snapshot": snap,
        "ts": time.time(),
    }
