from backend.core.live_path_cache_monitor import (
    PATCH_SCOPE_ACTIVE_TRADES_UI,
    PATCH_SCOPE_TRADE_LOG,
    active_trades_ui_live_patch_fields,
    live_patch_fields_for_scope,
    trade_log_live_patch_fields,
)


def test_active_trades_ui_patch_includes_monitor_and_trade_monitor_field_names():
    rec = {
        "current_close_price": 0.12,
        "current_pnl": "1.23",
        "current_probability": 97.9487,
    }
    out = active_trades_ui_live_patch_fields(rec)
    assert out["pnl"] == "1.23"
    assert out["sell"] == 0.88
    assert out["sell_price"] == 0.88
    assert out["prob"] == 97.9487
    assert out["current_probability"] == 97.9487


def test_trade_log_patch_omits_prob():
    rec = {"current_close_price": 0.5, "current_pnl": "0.00", "current_probability": 50.0}
    out = trade_log_live_patch_fields(rec)
    assert "prob" not in out
    assert "current_probability" not in out
    assert out["sell_price"] == 0.5


def test_live_patch_fields_for_scope_routing():
    rec = {"current_probability": 42.0, "current_pnl": "0.00"}
    ui = live_patch_fields_for_scope(PATCH_SCOPE_ACTIVE_TRADES_UI, rec)
    log = live_patch_fields_for_scope(PATCH_SCOPE_TRADE_LOG, rec)
    assert ui["current_probability"] == 42.0
    assert "current_probability" not in log
