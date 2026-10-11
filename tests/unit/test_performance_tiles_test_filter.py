from backend.core.performance_rollups import (
    _dashboard_tile_aggregate_all_modes,
    _monitor_tiles_numeric_payloads_from_join,
)

_ROW = {
    "all_td_trades_n_live": 1,
    "all_td_trades_n_paper": 1,
    "all_td_trades_n_test": 8,
    "all_td_pnl_live": 4.0,
    "all_td_pnl_paper": 6.0,
    "all_td_pnl_test": 100.0,
    "all_td_ret_pct_live": 2.0,
    "all_td_ret_pct_paper": -1.0,
    "all_td_ret_pct_test": 50.0,
    "all_td_win_rate_live": 1.0,
    "all_td_win_rate_paper": 0.0,
    "all_td_win_rate_test": 1.0,
}


def test_aggregate_excludes_test_for_non_test_filter_monitor():
    pnl, n, wr, ret = _dashboard_tile_aggregate_all_modes(_ROW, "all_td_", include_test=False)
    assert (pnl, n, wr, ret) == (10.0, 2, 0.5, 1.0)


def test_aggregate_includes_test_for_test_filter_monitor():
    pnl, n, wr, ret = _dashboard_tile_aggregate_all_modes(_ROW, "all_td_", include_test=True)
    assert (pnl, n, ret) == (110.0, 10, 51.0)
    assert wr == 0.9


def test_join_payload_uses_monitor_test_filter():
    colnames = ["ml_id", "ml_test_filter", *_ROW.keys()]
    rows = [
        (1, False, *_ROW.values()),
        (2, True, *_ROW.values()),
    ]
    tiles = {t["id"]: t for t in _monitor_tiles_numeric_payloads_from_join(colnames, rows, "0001", "all", "td")}
    assert tiles["mon_0001_1"]["trades"] == 2
    assert tiles["mon_0001_2"]["trades"] == 10
