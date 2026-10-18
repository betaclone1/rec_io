"""Per-subaccount drawdown controls and scoped emergency halt."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.core.subaccount_drawdown import get_subaccount_drawdown_controls
from backend.monitor_manager import MonitorManager


def test_get_subaccount_drawdown_controls_reads_row():
    cur = MagicMock()
    cur.fetchone.return_value = (True, Decimal("40.00"))
    halt, pct = get_subaccount_drawdown_controls(
        cur, "users_0001.subaccounts_0001", subaccount_id=2
    )
    assert halt is True
    assert pct == Decimal("40.00")
    assert cur.execute.called


def test_get_subaccount_drawdown_controls_defaults_when_missing():
    cur = MagicMock()
    cur.fetchone.return_value = None
    halt, pct = get_subaccount_drawdown_controls(
        cur, "users_0001.subaccounts_0001", subaccount_id=9
    )
    assert halt is True
    assert pct == Decimal("50.00")


@patch.object(MonitorManager, "update_monitor_bankroll_allotments", return_value={"status": "success"})
@patch.object(MonitorManager, "apply_drawdown_emergency_monitor_halt")
def test_handle_bankroll_update_scopes_halt_to_subaccounts(mock_halt, _allot):
    mock_halt.return_value = {"status": "success"}
    mm = MonitorManager.__new__(MonitorManager)
    mm.log_event = MagicMock()
    out = mm.handle_bankroll_update(
        True, drawdown_halt_subaccounts=[1, 2]
    )
    assert out.get("status") == "success" or "bankroll" in str(out).lower() or mock_halt.call_count == 2
    assert mock_halt.call_count == 2
    called_ids = [c.kwargs.get("subaccount_id") for c in mock_halt.call_args_list]
    assert called_ids == [1, 2]


@patch.object(MonitorManager, "update_monitor_bankroll_allotments", return_value={"status": "success"})
@patch.object(MonitorManager, "apply_drawdown_emergency_monitor_halt")
def test_handle_bankroll_update_legacy_all_monitors_when_no_sa_list(mock_halt, _allot):
    mock_halt.return_value = {"status": "success"}
    mm = MonitorManager.__new__(MonitorManager)
    mm.log_event = MagicMock()
    mm.handle_bankroll_update(True, drawdown_halt_subaccounts=None)
    mock_halt.assert_called_once_with()
