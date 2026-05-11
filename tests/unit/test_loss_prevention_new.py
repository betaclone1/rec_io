"""Unit tests for monitor loss_prevention value ``new`` (bootstrap sizing) and sim-trade tiers."""

from backend.core.time_based_loss_prevention import (
    cycle_loss_contribution_units,
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
