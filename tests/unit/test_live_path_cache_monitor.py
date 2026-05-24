from backend.core.live_path_cache_monitor import (
    PATCH_SCOPE_ACTIVE_TRADES_UI,
    PATCH_SCOPE_TRADE_LOG,
    LivePathMonitorSpec,
    SOURCE_STRIKE_LADDER,
    _strike_ladder_probability,
    _strike_ladder_row_for_monitor,
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


def test_strike_ladder_row_for_monitor_uses_market_probability():
    row = {
        "ticker": "KXBTCD-TEST-T100",
        "strike": 100.0,
        "buffer": 12.5,
        "buffer_pct": 0.02,
        "probability_15m": 88.5,
        "yes_ask_dollars": 0.12,
        "no_ask_dollars": 0.89,
        "active_side": "yes",
    }
    out = _strike_ladder_row_for_monitor(row, market="15m")
    assert out["ticker"] == "KXBTCD-TEST-T100"
    assert out["probability"] == 88.5
    assert out["fair_price"] is None
    assert _strike_ladder_probability(row, market="hourly") is None


def test_strike_ladder_spec_ticker_filter(monkeypatch):
    from backend.core import live_path_cache_monitor as lpcm

    def fake_rows(exchange, market, symbol):
        return [
            {"ticker": "AAA", "strike": 1, "probability": 10},
            {"ticker": "BBB", "strike": 2, "probability": 20},
        ]

    monkeypatch.setattr(lpcm.lsc, "get_strike_ladder_rows", fake_rows)
    spec = LivePathMonitorSpec(
        source=SOURCE_STRIKE_LADDER,
        exchange="kalshi",
        market="15m",
        symbol="BTC",
        ticker="bbb",
    )
    rows = lpcm._strike_ladder_rows_for_monitor(spec)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "BBB"
