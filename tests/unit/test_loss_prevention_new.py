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
    assert tier_from_sim_loss_count(0) == "off"
    assert tier_from_sim_loss_count(1) == "sim_loss_50"
    assert tier_from_sim_loss_count(2) == "sim_loss_25"
    assert tier_from_sim_loss_count(3) == "sim_loss_1c"
    assert tier_from_sim_loss_count(99) == "sim_loss_1c"


def test_resolve_sim_cooldown_with_zero_master_tally_is_off_not_sim_loss_50():
    assert (
        resolve_monitor_loss_prevention_value(
            live_loss_prevention_cooldown_live=False,
            simulated_loss_prevention_cooldown_live=True,
            sim_loss_count=0,
            loss_prevention_toggle=True,
            loss_prevention_method="time",
            win_streak=0,
            win_streak_threshold=22,
            current_loss_prevention="sim_loss_50",
            cycle_had_loss=False,
        )
        == "off"
    )


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
    refreshed = []
    monkeypatch.setattr(
        lp,
        "refresh_loss_prevention_tally_from_trades",
        lambda *a, **kw: (refreshed.append(kw) or True),
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
    assert len(cursor.executed) == 2
    assert recomputed == [("users.monitor_list_0001", "99015")]
    assert refreshed and refreshed[0].get("monitor_id") == "99015"


def test_live_loss_replay_counts_all_trades_log_rows(monkeypatch):
    from backend.core import time_based_loss_prevention as lp

    monkeypatch.setattr(
        lp,
        "refresh_loss_prevention_tally_from_trades",
        lambda *a, **kw: True,
    )
    cursor = _LiveLossCursor([(4.0,)])

    assert (
        replay_live_loss_throttle_from_trades_log(
            cursor,
            "users.trades_0001",
            "users.monitor_list_0001",
            "0001",
            "99015",
        )
        is True
    )

    assert "users.monitor_list_0001" in cursor.executed[0][0]
    assert cursor.executed[0][1] == ("99015",)


def test_replay_live_uses_log_rebuild_ignores_anchor_floor(monkeypatch):
    from datetime import datetime

    from backend.core import time_based_loss_prevention as lp
    from backend.core.time_based_loss_prevention import EST, replay_live_loss_throttle_from_trades_log

    floor = datetime(2026, 5, 14, 8, 45, 0, tzinfo=EST)
    calls = []

    def fake_rebuild(cur, **kw):
        calls.append(kw)
        return True

    monkeypatch.setattr(lp, "rebuild_monitor_time_lp_from_trade_logs_on_restart", fake_rebuild)

    class _C:
        def __init__(self):
            self.executed = []

        def execute(self, query, params=None):
            self.executed.append((query, params))

        def fetchone(self):
            return (4.0,)

    cur = _C()
    assert (
        replay_live_loss_throttle_from_trades_log(
            cur,
            "users.trades_0001",
            "users.monitor_list_0001",
            "0001",
            "99015",
            duration_hours=5,
            loss_anchor_floor_est=floor,
        )
        is True
    )
    assert len(calls) == 1
    assert calls[0].get("monitor_id") == "99015"


def test_expire_live_trade_cooldown_issues_two_updates():
    """Live window end: clear live only if sim still in window; else full episode reset."""
    from backend.core.time_based_loss_prevention import _expire_live_trade_cooldown_if_needed

    class _Cursor:
        def __init__(self):
            self.executed: list = []

        def execute(self, query, params=None):
            self.executed.append((query, params))

    cur = _Cursor()
    _expire_live_trade_cooldown_if_needed(cur, "users.monitor_list_0001", "7")
    assert len(cur.executed) == 2
    q0, p0 = cur.executed[0]
    q1, p1 = cur.executed[1]
    assert p0 == p1 == ("7",)
    assert "SET live_loss_prevention_cooldown_start_time = NULL" in q0
    assert "simulated_loss_prevention_cooldown_start_time" in q0
    assert "loss_prevention_cooldown_loss_count = 0" not in q0
    assert "SET live_loss_prevention_cooldown_start_time = NULL" in q1
    assert "loss_prevention_cooldown_loss_count = 0" in q1
    assert "original_loss_prevention_cooldown_start_time = NULL" in q1
    assert "simulated_loss_prevention_cooldown_start_time = NULL" in q1


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
    refreshed = []
    monkeypatch.setattr(
        lp,
        "refresh_loss_prevention_tally_from_trades",
        lambda *a, **kw: (refreshed.append(kw) or True),
    )

    cursor = _LiveLossCursor(
        [
            (True, "time", True),
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

    assert refreshed and refreshed[0].get("monitor_id") == "10002"
    assert len(cursor.executed) == 1


def test_lp_episode_segments_when_gap_exceeds_duration():
    from backend.core.time_based_loss_prevention import _segment_closed_loss_rows_by_cooldown_gap

    dur_h = 5.0
    base = 1_000_000.0
    rows = [
        ("live", "2026-05-14", 1.0, "A", base),
        ("sim", "2026-05-14", 1.0, "A", base + 60.0),
        ("live", "2026-05-15", 1.0, "B", base + (6 * 3600.0)),
    ]
    eps = _segment_closed_loss_rows_by_cooldown_gap(rows, dur_h)
    assert len(eps) == 2
    assert len(eps[0]) == 2
    assert len(eps[1]) == 1


def test_lp_dedupe_excludes_sim_when_live_shares_cycle_ticker():
    from backend.core.time_based_loss_prevention import _deduped_loss_count_in_episode

    ep = [
        ("live", "2026-05-14", 1.0, "KX", 1.0),
        ("sim", "2026-05-14", 1.0, "KX", 2.0),
        ("sim", "2026-05-14", 2.0, "KY", 3.0),
    ]
    assert _deduped_loss_count_in_episode(ep) == 2
