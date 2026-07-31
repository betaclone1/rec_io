"""Resolve Kalshi order ids associated with a trade row (multi-leg aware)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Sequence


def _normalize_order_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _as_id_list(value: Any) -> List[str]:
    """Coerce TEXT[] / list / scalar-ish values into a de-duplicated id list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_items: Sequence[Any] = value
    elif isinstance(value, str):
        # psycopg may return array literals rarely; treat plain string as one id.
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("{") and stripped.endswith("}"):
            inner = stripped[1:-1].strip()
            if not inner:
                return []
            raw_items = [part.strip().strip('"') for part in inner.split(",")]
        else:
            raw_items = [stripped]
    else:
        raw_items = [value]

    out: List[str] = []
    seen: set[str] = set()
    for item in raw_items:
        oid = _normalize_order_id(item)
        if oid is None or oid in seen:
            continue
        seen.add(oid)
        out.append(oid)
    return out


def trade_associated_order_ids(trade: Mapping[str, Any] | None) -> Dict[str, List[str]]:
    """
    Return open/close/all Kalshi order ids for a trade.

    Prefer order_ids_open / order_ids_close when non-empty; fall back to scalar
    order_id_open / order_id_close for pre-migration rows. Blanks ignored; first-seen order kept.
    """
    row: Mapping[str, Any] = trade or {}
    open_ids = _as_id_list(row.get("order_ids_open"))
    if not open_ids:
        open_ids = _as_id_list(row.get("order_id_open"))

    close_ids = _as_id_list(row.get("order_ids_close"))
    if not close_ids:
        close_ids = _as_id_list(row.get("order_id_close"))

    all_ids: List[str] = []
    seen: set[str] = set()
    for oid in (*open_ids, *close_ids):
        if oid in seen:
            continue
        seen.add(oid)
        all_ids.append(oid)

    return {"open": open_ids, "close": close_ids, "all": all_ids}


def last_filled_order_id(trade: Mapping[str, Any] | None, *, phase: str = "open") -> str | None:
    """Last append-only filled id for a phase, else the scalar pointer if set."""
    resolved = trade_associated_order_ids(trade)
    ids = resolved["open"] if phase == "open" else resolved["close"]
    if ids:
        return ids[-1]
    return None


def sql_append_order_id_if_absent(column: str) -> str:
    """
    SQL fragment: append %s to TEXT[] column when not already present.
    Caller binds (order_id, order_id) for the two %s placeholders in this fragment,
    plus any other SET/WHERE params.
    """
    if column not in ("order_ids_open", "order_ids_close"):
        raise ValueError(f"Unsupported order-id array column: {column}")
    return (
        f"{column} = CASE "
        f"WHEN NOT (COALESCE({column}, '{{}}'::text[]) @> ARRAY[%s]::text[]) "
        f"THEN array_append(COALESCE({column}, '{{}}'::text[]), %s) "
        f"ELSE COALESCE({column}, '{{}}'::text[]) END"
    )


def merge_order_id_into_trade_dict(
    trade: MutableMapping[str, Any],
    order_id: str,
    *,
    phase: str = "open",
) -> None:
    """In-memory append helper for tests / callers that mutate a trade dict."""
    oid = _normalize_order_id(order_id)
    if oid is None:
        return
    key = "order_ids_open" if phase == "open" else "order_ids_close"
    current = _as_id_list(trade.get(key))
    if oid not in current:
        current.append(oid)
    trade[key] = current
    scalar = "order_id_open" if phase == "open" else "order_id_close"
    trade[scalar] = oid
