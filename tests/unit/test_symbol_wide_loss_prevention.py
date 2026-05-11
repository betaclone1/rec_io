from backend.core.symbol_wide_loss_prevention import (
    configured_symbol_wide_monitor_ids,
    is_loss_prevention_sizing_state,
    normalize_loss_prevention_state_for_sizing,
    resolve_effective_loss_prevention_state,
    symbol_wide_loss_prevention_state,
    sync_symbol_wide_loss_prevention_from_monitor,
)


class FakeCursor:
    def __init__(
        self,
        *,
        monitor_row,
        live_state="off",
        update_returns=True,
        configured_ids=None,
    ):
        self.monitor_row = monitor_row
        self.live_state = live_state
        self.update_returns = update_returns
        self.configured_ids = configured_ids or []
        self.last = None
        self.update_params = None
        self.queries = []

    def execute(self, query, params=None):
        q = " ".join(str(query).split())
        self.queries.append(q)
        if q.startswith("SELECT id, name, symbol"):
            self.last = "monitor"
        elif q.startswith("SELECT loss_prevention_state FROM live_data.live_symbol_status"):
            self.last = "live_state"
        elif q.startswith("SELECT DISTINCT m.id FROM live_data.live_symbol_status"):
            self.last = "configured_ids"
        elif q.startswith("UPDATE live_data.live_symbol_status"):
            self.update_params = params
            self.last = "update"
        else:
            raise AssertionError(f"unexpected query: {q}")

    def fetchone(self):
        if self.last == "monitor":
            return self.monitor_row
        if self.last == "live_state":
            return (self.live_state,)
        if self.last == "update":
            return ("BTC",) if self.update_returns else None
        return None

    def fetchall(self):
        if self.last == "configured_ids":
            return [(value,) for value in self.configured_ids]
        return []


def _monitor_row(*, local_state="off", symbol_wide=True):
    return (
        10001,
        "BTC Hourly Hero",
        "BTC",
        local_state,
        4,
        "2026-05-11T10:00:00Z",
        "2026-05-11T09:00:00Z",
        3,
        None,
        True,
        symbol_wide,
    )


def test_symbol_wide_suffix_marks_non_off_states_only():
    assert symbol_wide_loss_prevention_state("sim_loss_1c") == "sim_loss_1c_symbol_wide"
    assert symbol_wide_loss_prevention_state("live_loss_1c") == "live_loss_1c_symbol_wide"
    assert symbol_wide_loss_prevention_state("off") == "off"
    assert symbol_wide_loss_prevention_state("none") == "off"


def test_suffixed_states_normalize_to_existing_sizing_rules():
    assert normalize_loss_prevention_state_for_sizing("sim_loss_25_symbol_wide") == "sim_loss_25"
    assert is_loss_prevention_sizing_state("live_loss_1c_symbol_wide")


def test_effective_state_uses_symbol_wide_when_enabled_and_non_off():
    cur = FakeCursor(
        monitor_row=_monitor_row(local_state="off", symbol_wide=True),
        live_state="sim_loss_1c_symbol_wide",
    )
    assert (
        resolve_effective_loss_prevention_state(cur, "users.monitor_list_0002", "20001")
        == "sim_loss_1c_symbol_wide"
    )


def test_effective_state_falls_back_to_local_when_symbol_wide_off():
    cur = FakeCursor(
        monitor_row=_monitor_row(local_state="live_loss_1c", symbol_wide=True),
        live_state="off",
    )
    assert (
        resolve_effective_loss_prevention_state(cur, "users.monitor_list_0002", "20001")
        == "live_loss_1c"
    )


def test_hero_sync_writes_suffixed_state_to_live_symbol_status():
    cur = FakeCursor(monitor_row=_monitor_row(local_state="sim_loss_1c"))
    assert sync_symbol_wide_loss_prevention_from_monitor(cur, "users.monitor_list_0001", "10001")
    assert cur.update_params[1] == "sim_loss_1c_symbol_wide"
    assert cur.update_params[5] == 3


def test_hero_sync_uses_monitor_follow_name_as_authority():
    cur = FakeCursor(monitor_row=_monitor_row(local_state="live_loss_1c"))
    assert sync_symbol_wide_loss_prevention_from_monitor(cur, "users.monitor_list_0001", "10001")
    update_query = next(q for q in cur.queries if q.startswith("UPDATE live_data.live_symbol_status"))
    assert "monitor_follow_id = %s OR" not in update_query
    assert "BTRIM(COALESCE(monitor_follow, '')) = %s" in update_query
    assert cur.update_params[-1] == "BTC Hourly Hero"


def test_configured_symbol_wide_monitor_ids_reads_follow_names_without_sim_flag():
    cur = FakeCursor(monitor_row=_monitor_row(), configured_ids=[10001, 10002])
    assert configured_symbol_wide_monitor_ids(cur, "users.monitor_list_0001") == ["10001", "10002"]
    query = cur.queries[-1]
    assert "live_data.live_symbol_status" in query
    assert "simulated_trade_loss_prevention" not in query
