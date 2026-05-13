from backend.core.symbol_wide_loss_prevention import (
    configured_symbol_wide_monitor_ids,
    is_loss_prevention_sizing_state,
    loss_prevention_state_severity,
    more_serious_loss_prevention_state,
    normalize_loss_prevention_state_for_sizing,
    project_symbol_wide_loss_prevention_to_monitor,
    resolve_effective_loss_prevention_state,
    symbol_wide_loss_prevention_state,
    _symbol_wide_monitor_tables,
    sync_symbol_wide_loss_prevention_from_monitor,
    sync_symbol_wide_loss_prevention_followers,
)


class FakeCursor:
    def __init__(
        self,
        *,
        monitor_row,
        live_state="off",
        update_returns=True,
        configured_ids=None,
        project_monitor_row=None,
        monitor_tables=None,
    ):
        self.monitor_row = monitor_row
        self.live_state = live_state
        self.update_returns = update_returns
        self.configured_ids = configured_ids or []
        self.project_monitor_row = project_monitor_row or ("BTC", True, True, "off", "off")
        self.monitor_tables = monitor_tables or [("users", "monitor_list_0001")]
        self.last = None
        self.update_params = None
        self.follower_update_params = []
        self.queries = []
        self.rowcount = 0

    def execute(self, query, params=None):
        q = " ".join(str(query).split())
        self.queries.append(q)
        self.rowcount = 0
        if q.startswith("SELECT id, name, symbol"):
            self.last = "monitor"
        elif q.startswith("SELECT loss_prevention_state FROM live_data.live_symbol_status"):
            self.last = "live_state"
        elif q.startswith("SELECT DISTINCT m.id FROM live_data.live_symbol_status"):
            self.last = "configured_ids"
        elif q.startswith("SELECT table_schema, table_name FROM information_schema.columns"):
            self.last = "monitor_tables"
        elif q.startswith("SELECT symbol, COALESCE(symbol_wide_loss_prevention"):
            self.last = "project_monitor"
        elif q.startswith("UPDATE live_data.live_symbol_status"):
            self.update_params = params
            self.last = "update"
            self.rowcount = 1 if self.update_returns else 0
        elif q.startswith("UPDATE users.monitor_list_") or q.startswith("UPDATE users_"):
            self.follower_update_params.append(params)
            self.last = "follower_update"
            self.rowcount = 1
        else:
            raise AssertionError(f"unexpected query: {q}")

    def fetchone(self):
        if self.last == "monitor":
            return self.monitor_row
        if self.last == "live_state":
            return (self.live_state,)
        if self.last == "update":
            return ("BTC",) if self.update_returns else None
        if self.last == "project_monitor":
            return self.project_monitor_row
        return None

    def fetchall(self):
        if self.last == "configured_ids":
            return [(value,) for value in self.configured_ids]
        if self.last == "monitor_tables":
            return self.monitor_tables
        return []


def _monitor_row(*, local_state="off", symbol_wide=True, computed_local_state=None):
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
        computed_local_state if computed_local_state is not None else local_state,
    )


def test_symbol_wide_suffix_marks_non_off_states_only():
    assert symbol_wide_loss_prevention_state("sim_loss_1c") == "sim_loss_1c_symbol_wide"
    assert symbol_wide_loss_prevention_state("live_loss_1c") == "live_loss_1c_symbol_wide"
    assert symbol_wide_loss_prevention_state("off") == "off"
    assert symbol_wide_loss_prevention_state("none") == "off"


def test_suffixed_states_normalize_to_existing_sizing_rules():
    assert normalize_loss_prevention_state_for_sizing("sim_loss_25_symbol_wide") == "sim_loss_25"
    assert is_loss_prevention_sizing_state("live_loss_1c_symbol_wide")


def test_loss_prevention_severity_hierarchy():
    assert loss_prevention_state_severity("live_loss_1c") > loss_prevention_state_severity("sim_loss_1c")
    assert loss_prevention_state_severity("sim_loss_1c") > loss_prevention_state_severity("sim_loss_50")
    assert loss_prevention_state_severity("sim_loss_50") > loss_prevention_state_severity("sim_loss_25")
    assert loss_prevention_state_severity("sim_loss_25") > loss_prevention_state_severity("off")


def test_more_serious_state_prefers_local_live_loss_over_symbol_sim_tier():
    assert (
        more_serious_loss_prevention_state("live_loss_1c", "sim_loss_1c_symbol_wide")
        == "live_loss_1c"
    )


def test_more_serious_state_prefers_symbol_sim_50_over_local_sim_25():
    assert (
        more_serious_loss_prevention_state("sim_loss_25", "sim_loss_50_symbol_wide")
        == "sim_loss_50_symbol_wide"
    )


def test_more_serious_state_does_not_treat_prior_symbol_wide_as_local():
    assert (
        more_serious_loss_prevention_state(
            "live_loss_1c_symbol_wide",
            "sim_loss_50_symbol_wide",
        )
        == "sim_loss_50_symbol_wide"
    )


def test_more_serious_state_clears_prior_symbol_wide_when_symbol_wide_off():
    assert more_serious_loss_prevention_state("sim_loss_50_symbol_wide", "off") == "off"


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


def test_effective_state_recomputes_local_for_prior_symbol_wide_projection():
    cur = FakeCursor(
        monitor_row=_monitor_row(
            local_state="live_loss_1c_symbol_wide",
            computed_local_state="off",
            symbol_wide=True,
        ),
        live_state="sim_loss_50_symbol_wide",
    )

    assert (
        resolve_effective_loss_prevention_state(cur, "users.monitor_list_0002", "20001")
        == "sim_loss_50_symbol_wide"
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


def test_symbol_wide_monitor_table_discovery_includes_tenant_schemas():
    cur = FakeCursor(
        monitor_row=_monitor_row(),
        monitor_tables=[("users_0001", "monitor_list_0001")],
    )

    assert _symbol_wide_monitor_tables(cur) == ["users_0001.monitor_list_0001"]

    query = cur.queries[-1]
    assert "table_schema = 'users'" in query
    assert "table_schema ~ '^users_[0-9]{4}$'" in query


def test_project_symbol_wide_state_into_follower_monitor_row():
    cur = FakeCursor(
        monitor_row=_monitor_row(),
        live_state="sim_loss_25_symbol_wide",
        project_monitor_row=("BTC", True, True, "off", "off"),
    )

    assert project_symbol_wide_loss_prevention_to_monitor(
        cur, "users.monitor_list_0002", "20001"
    )

    assert cur.follower_update_params[-1] == (
        "sim_loss_25_symbol_wide",
        "20001",
        "sim_loss_25_symbol_wide",
    )


def test_project_keeps_more_serious_local_state_over_symbol_wide_state():
    cur = FakeCursor(
        monitor_row=_monitor_row(),
        live_state="sim_loss_25_symbol_wide",
        project_monitor_row=("BTC", True, True, "live_loss_1c", "live_loss_1c"),
    )

    assert project_symbol_wide_loss_prevention_to_monitor(
        cur, "users.monitor_list_0002", "20001"
    )

    assert cur.follower_update_params[-1] == (
        "live_loss_1c",
        "20001",
        "live_loss_1c",
    )


def test_project_replaces_stale_prior_symbol_wide_state_with_current_symbol_state():
    cur = FakeCursor(
        monitor_row=_monitor_row(),
        live_state="sim_loss_50_symbol_wide",
        project_monitor_row=(
            "BTC",
            True,
            True,
            "live_loss_1c_symbol_wide",
            "off",
        ),
    )

    assert project_symbol_wide_loss_prevention_to_monitor(
        cur, "users.monitor_list_0002", "20001"
    )

    assert cur.follower_update_params[-1] == (
        "sim_loss_50_symbol_wide",
        "20001",
        "sim_loss_50_symbol_wide",
    )


def test_project_symbol_wide_off_restores_local_state_for_prior_symbol_wide_row():
    cur = FakeCursor(
        monitor_row=_monitor_row(),
        live_state="off",
        project_monitor_row=("BTC", True, True, "sim_loss_25_symbol_wide", "off"),
    )

    assert project_symbol_wide_loss_prevention_to_monitor(
        cur, "users.monitor_list_0002", "20001"
    )

    update_query = cur.queries[-1]
    assert "SET loss_prevention_state =" in update_query
    assert "_symbol_wide" not in str(cur.follower_update_params[-1])


def test_hero_sync_projects_live_state_to_symbol_wide_followers():
    cur = FakeCursor(
        monitor_row=_monitor_row(local_state="sim_loss_25"),
        live_state="sim_loss_25_symbol_wide",
        monitor_tables=[("users", "monitor_list_0001"), ("users", "monitor_list_0002")],
    )

    assert sync_symbol_wide_loss_prevention_from_monitor(cur, "users.monitor_list_0001", "10001")

    follower_updates = [
        q for q in cur.queries if q.startswith("UPDATE users.monitor_list_")
    ]
    assert len(follower_updates) == 2
    assert cur.follower_update_params[-1] == (
        1,
        "sim_loss_25_symbol_wide",
        "BTC",
        1,
        "sim_loss_25_symbol_wide",
    )


def test_follower_sync_when_symbol_wide_off_updates_prior_symbol_wide_rows_only():
    cur = FakeCursor(
        monitor_row=_monitor_row(),
        live_state="off",
        monitor_tables=[("users_0001", "monitor_list_0001")],
    )

    assert sync_symbol_wide_loss_prevention_followers(cur, "BTC") == 1

    update_query = cur.queries[-1]
    assert update_query.startswith("UPDATE users_0001.monitor_list_0001")
    assert "RIGHT( LOWER(REPLACE(COALESCE(loss_prevention_state, ''), '-', '_'))" in update_query
    assert cur.follower_update_params[-1] == ("BTC", len("_symbol_wide"), "_symbol_wide")
