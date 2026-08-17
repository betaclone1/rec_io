"""Orphan-log cleanup must not treat pool worker suffixes as monitor ids."""

from backend.core.aes_btc15m_exp_scalp_cutout import supervisor_log_numeric_monitor_id


def test_numeric_monitor_log_id():
    assert (
        supervisor_log_numeric_monitor_id(
            "auto_entry_supervisor_0001_10046.out.log", "0001"
        )
        == "10046"
    )
    assert (
        supervisor_log_numeric_monitor_id(
            "active_trade_supervisor_0001_10056.err.log", "0001"
        )
        == "10056"
    )


def test_cutout_and_unified_pool_logs_are_not_monitor_ids():
    assert (
        supervisor_log_numeric_monitor_id(
            "auto_entry_supervisor_0001_btc15m_exp_scalp.out.log", "0001"
        )
        is None
    )
    assert (
        supervisor_log_numeric_monitor_id(
            "active_trade_supervisor_0001_btc15m_exp_scalp.err.log", "0001"
        )
        is None
    )
    assert supervisor_log_numeric_monitor_id("auto_entry_supervisor_0001.out.log", "0001") is None
