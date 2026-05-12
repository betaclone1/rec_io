"""Unit tests for monitor loss_prevention value ``new`` (bootstrap sizing) and sim-trade tiers."""

from backend.core.time_based_loss_prevention import (
    apply_sim_trade_cycle_loss,
    cycle_loss_contribution_units,
    on_trade_closed_live_loss_throttle,
    replay_live_loss_throttle_from_trades_log,
    resolve_monitor_loss_prevention_value,
    tier_from_sim_loss_count,
)


def test_new_preserved_until_cycle_loss_even_with_win_streak_zero():
    # Win streak 0 + toggle on would normally be ``win_streak_one_contract``; ``new`` defers that.
    assert (
        resolve_monitor_loss_prevention_value(
            simulated_loss_prevention_cooldown_live=False,
            sim_loss_count=0,
            loss_prevention_toggle=True,
            win_streak=0,
            win_streak_threshold=22,
            current_loss_prevention="new",
            cycle_had_loss=False,
        )
        == "new"
    )


def test_new_preserved_when_cycle_had_loss_none():
    assert (
        resolve_monitor_loss_prevention_value(
            simulated_loss_prevention_cooldown_live=False,
            sim_loss_count=0,
            loss_prevention_toggle=True,
            win_streak=5,
            win_streak_threshold=22,
            current_loss_prevention="new",
            cycle_had_loss=None,
        )
        == "new"
    )


def test_new_exits_to_win_streak_one_contract_after_loss_with_zero_streak():
    assert (
        resolve_monitor_loss_prevention_value(
            simulated_loss_prevention_cooldown_live=False,
            sim_loss_count=0,
            loss_prevention_toggle=True,
            win_streak=0,
            win_streak_threshold=22,
            current_loss_prevention="new",
            cycle_had_loss=True,
        )
        == "win_streak_one_contract"
    )


def test_new_exits_to_off_when_streak_above_threshold_after_loss():
    assert (
        resolve_monitor_loss_prevention_value(
            simulated_loss_prevention_cooldown_live=False,
            sim_loss_count=0,
            loss_prevention_toggle=True,
            win_streak=25,
            win_streak_threshold=22,
            current_loss_prevention="new",
            cycle_had_loss=True,
        )
        == "off"
    )


def test_toggle_off_clears_new():
    assert (
        resolve_monitor_loss_prevention_value(
            simulated_loss_prevention_cooldown_live=False,
            sim_loss_count=0,
            loss_prevention_toggle=False,
            win_streak=0,
            win_streak_threshold=22,
            current_loss_prevention="new",
            cycle_had_loss=False,
        )
        == "off"
    )


def test_simulated_trade_window_overrides_new_first_tier():
    assert (
        resolve_monitor_loss_prevention_value(
            simulated_loss_prevention_cooldown_live=True,
            sim_loss_count=1,
            loss_prevention_toggle=True,
            loss_prevention_method="time",
            win_streak=0,
            win_streak_threshold=22,
            current_loss_prevention="new",
            cycle_had_loss=False,
        )
        == "sim_loss_50"
    )


def test_live_trade_throttle_overrides_sim_tier():
    assert (
        resolve_monitor_loss_prevention_value(
            live_loss_prevention_cooldown_live=True,
            simulated_loss_prevention_cooldown_live=True,
            sim_loss_count=1,
            loss_prevention_toggle=True,
            loss_prevention_method="time",
            win_streak=0,
            win_streak_threshold=22,
            current_loss_prevention="sim_loss_50",
            cycle_had_loss=False,
        )
        == "live_loss_1c"
    )


def test_tier_from_count():
    assert tier_from_sim_loss_count(1) == "sim_loss_50"
    assert tier_from_sim_loss_count(2) == "sim_loss_25"
    assert tier_from_sim_loss_count(3) == "sim_loss_1c"
    assert tier_from_sim_loss_count(99) == "sim_loss_1c"


def test_cycle_contribution_uses_simulated_losses_only():
    assert cycle_loss_contribution_units(3, 1) == 3
    assert cycle_loss_contribution_units(0, 2) == 0
    assert cycle_loss_contribution_units(0, 0) == 0


def test_parse_ts_epoch_matches_utc_instant():
    from datetime import datetime, timezone
    from decimal import Decimal

    from backend.core.time_based_loss_prevention import EST, _parse_ts

    utc = datetime(2026, 5, 9, 18, 30, tzinfo=timezone.utc)
    want = utc.astimezone(EST)
    assert _parse_ts(utc.timestamp()) == want
    assert _parse_ts(Decimal(str(utc.timestamp()))) == want


class _LiveLossCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows.pop(0)


def test_live_loss_throttle_counts_paper_and_test_trades_log_rows(monkeypatch):
    from backend.core import time_based_loss_prevention as lp

    recomputed = []
    monkeypatch.setattr(
        lp,
        "recompute_monitor_loss_prevention",
        lambda cursor, monitor_list, monitor_id: recomputed.append((monitor_list, monitor_id)),
    )

    cursor = _LiveLossCursor(
        [
            ("mon_0001_99015", "L", 1_779_000_000),
            (True, "time"),
            None,
        ]
    )

    assert (
        on_trade_closed_live_loss_throttle(
            cursor,
            "users.trades_0001",
            "users.monitor_list_0001",
            "0001",
            39432,
        )
        is True
    )

    first_query = cursor.executed[0][0]
    assert "paper_trade" not in first_query
    assert "test_filter" not in first_query
    update_query, update_params = cursor.executed[2]
    assert "original_loss_prevention_cooldown_start_time = COALESCE" in update_query
    assert "loss_prevention_cooldown_loss_count = COALESCE(loss_prevention_cooldown_loss_count, 0) + 1" in update_query
    assert update_params[-1] == "99015"
    assert recomputed == [("users.monitor_list_0001", "99015")]


def test_live_loss_replay_counts_all_trades_log_rows():
    cursor = _LiveLossCursor([(1_779_000_000, 1_779_003_600, 2)])

    assert (
        replay_live_loss_throttle_from_trades_log(
            cursor,
            "users.trades_0001",
            "users.monitor_list_0001",
            "0001",
            "99015",
            duration_hours=72,
        )
        is True
    )

    replay_query = cursor.executed[0][0]
    assert "paper_trade" not in replay_query
    assert "test_filter" not in replay_query
    assert "COUNT(*)" in replay_query
    update_query, update_params = cursor.executed[-1]
    assert "original_loss_prevention_cooldown_start_time = LEAST" in update_query
    assert "loss_prevention_cooldown_loss_count = COALESCE(loss_prevention_cooldown_loss_count, 0) + %s" in update_query
    assert update_params[-2] == 2
    assert update_params[-1] == "99015"


def test_sim_loss_during_live_throttle_extends_live_cooldown_and_count(monkeypatch):
    from datetime import datetime

    from backend.core import time_based_loss_prevention as lp

    monkeypatch.setattr(lp, "ensure_sim_trade_ledger_table", lambda cursor, tenant_slot: None)
    monkeypatch.setattr(
        lp,
        "_expire_simulated_trade_state_if_needed",
        lambda cursor, monitor_list, monitor_id, now_est: False,
    )
    monkeypatch.setattr(lp, "_cycle_contribution", lambda *args: (2, None))
    monkeypatch.setattr(lp, "recompute_monitor_loss_prevention", lambda *args: None)

    cursor = _LiveLossCursor(
        [
            (True, "time", True),
            (0,),
            ("2026-05-12 10:00:15-04:00", "2026-05-12 11:00:15-04:00", 2),
        ]
    )

    assert (
        apply_sim_trade_cycle_loss(
            cursor,
            monitor_list_qualified="users.monitor_list_0001",
            trades_qualified="users.trades_0001",
            trades_simulated_qualified="users.trades_simulated_0001",
            ledger_qualified="users.sim_trade_lp_cycle_ledger_0001",
            tenant_slot="0001",
            monitor_key="mon_0001_10002",
            cycle_date="2026-05-12",
            weekly_cycle="59.2",
            loss_anchor_ts=datetime(2026, 5, 12, 11, 30, 14),
        )
        is True
    )

    update_query, update_params = cursor.executed[-1]
    assert "live_loss_prevention_cooldown_start_time = CASE" in update_query
    assert "loss_prevention_cooldown_loss_count = loss_prevention_cooldown_loss_count + %s" in update_query
    assert update_params[1] == 2
    assert update_params[-1] == "10002"
