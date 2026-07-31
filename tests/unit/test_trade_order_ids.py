from __future__ import annotations

from backend.core.trade_order_ids import (
    last_filled_order_id,
    merge_order_id_into_trade_dict,
    sql_append_order_id_if_absent,
    trade_associated_order_ids,
)


def test_trade_associated_order_ids_prefers_arrays() -> None:
    resolved = trade_associated_order_ids(
        {
            "order_id_open": "scalar-open-stale",
            "order_id_close": "scalar-close-stale",
            "order_ids_open": ["open-a", "open-b", "open-a"],
            "order_ids_close": ["close-a", ""],
        }
    )
    assert resolved == {
        "open": ["open-a", "open-b"],
        "close": ["close-a"],
        "all": ["open-a", "open-b", "close-a"],
    }


def test_trade_associated_order_ids_falls_back_to_scalars() -> None:
    resolved = trade_associated_order_ids(
        {
            "order_id_open": " open-only ",
            "order_id_close": None,
            "order_ids_open": [],
            "order_ids_close": None,
        }
    )
    assert resolved == {
        "open": ["open-only"],
        "close": [],
        "all": ["open-only"],
    }


def test_last_filled_order_id_and_merge() -> None:
    trade: dict = {"order_ids_open": ["a"], "order_id_open": "a"}
    assert last_filled_order_id(trade, phase="open") == "a"
    merge_order_id_into_trade_dict(trade, "b", phase="open")
    assert trade["order_ids_open"] == ["a", "b"]
    assert trade["order_id_open"] == "b"
    assert last_filled_order_id(trade, phase="open") == "b"


def test_sql_append_order_id_if_absent_fragment() -> None:
    frag = sql_append_order_id_if_absent("order_ids_open")
    assert "array_append" in frag
    assert "order_ids_open" in frag
    assert frag.count("%s") == 2
