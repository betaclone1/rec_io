"""Subaccount balance polling orchestrator."""

from unittest.mock import MagicMock, patch

from backend.balance_snapshot import (
    aggregate_account_balance_from_subaccounts,
    apply_balance_snapshot,
    detect_settlement_balance_glitch,
    poll_live_account_balances,
)


def _mtb_prev_row(balance, pv, portfolio=None):
    if portfolio is None:
        portfolio = balance + pv
    return {
        "balance": balance,
        "portfolio_value": pv,
        "portfolio": portfolio,
        "exposure": pv,
        "positions": pv,
        "bankroll_current": 544013,
        "master_trading_bankroll": balance,
        "mtb_base_value": None,
    }


def test_detect_settlement_balance_glitch_101125_pattern():
    prev = _mtb_prev_row(296449, 103796, 400245)
    is_glitch, reason = detect_settlement_balance_glitch(prev, 400349, 103796)
    assert is_glitch is True
    assert reason == "pv_stale_with_cash_jump"


def test_detect_settlement_balance_glitch_101463_pattern():
    prev = _mtb_prev_row(189489, 194752, 384241)
    is_glitch, reason = detect_settlement_balance_glitch(prev, 298289, 215750)
    assert is_glitch is True
    assert reason == "pv_stale_with_cash_jump"


def test_detect_settlement_balance_glitch_clean_after_settlement():
    prev = _mtb_prev_row(189489, 194752, 384241)
    is_glitch, _ = detect_settlement_balance_glitch(prev, 298289, 107712)
    assert is_glitch is False


def test_detect_settlement_balance_glitch_normal_open():
    prev = _mtb_prev_row(296385, 63104, 359489)
    is_glitch, _ = detect_settlement_balance_glitch(prev, 189489, 194752)
    assert is_glitch is False


def test_detect_settlement_balance_glitch_no_prev_row():
    is_glitch, reason = detect_settlement_balance_glitch({}, 400349, 103796)
    assert is_glitch is False
    assert reason == ""


def test_detect_settlement_balance_glitch_not_funding_cash_to_mtb():
    """CASH→MTB funding: MTB cash up, flat marks — not settlement double-count."""
    prev = _mtb_prev_row(274888, 0, 274888)
    is_glitch, reason = detect_settlement_balance_glitch(prev, 424888, 0)
    assert is_glitch is False
    assert reason == ""


def test_detect_settlement_balance_glitch_not_cheap_winner_small_pv_drop():
    """Winning settlement: large cash credit, small PV drop (cheap marks) must write."""
    prev = _mtb_prev_row(475398, 6715, 482113)
    is_glitch, reason = detect_settlement_balance_glitch(prev, 597010, 486)
    assert is_glitch is False
    assert reason == ""


def test_poll_live_account_balances_skips_glitch_then_writes_clean(monkeypatch):
    """101125: first fetch glitchy, second fetch clean → one write after repoll."""
    prev = _mtb_prev_row(296449, 103796, 400245)
    mtb_fetch_sequence = [
        {"balance_cents": 400349, "portfolio_value_cents": 103796, "total_portfolio_cents": 504145},
        {"balance_cents": 400349, "portfolio_value_cents": 0, "total_portfolio_cents": 400349},
    ]
    mtb_fetch_calls = {"n": 0}

    def fake_fetch(slot, *, subaccount=None):
        if subaccount == 0:
            return {"balance_cents": 10000, "portfolio_value_cents": 0, "total_portfolio_cents": 10000}
        if subaccount == 1:
            idx = min(mtb_fetch_calls["n"], len(mtb_fetch_sequence) - 1)
            mtb_fetch_calls["n"] += 1
            return dict(mtb_fetch_sequence[idx])
        return None

    apply_calls = []

    def fake_apply(*args, **kwargs):
        apply_calls.append(kwargs)
        return True, False

    def fake_aggregate(*args, **kwargs):
        return True, False

    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_subaccount_balances_cents_map",
        lambda slot: {0: 10000, 1: 400349},
    )
    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_portfolio_balance_detail",
        fake_fetch,
    )
    monkeypatch.setattr("backend.kalshi_account_sync_ws._sync_subaccounts_from_kalshi_poll", lambda *a, **k: None)
    monkeypatch.setattr("backend.balance_snapshot.refresh_mtb_realized_pnl_from_balance", lambda *a, **k: None)
    monkeypatch.setattr("backend.balance_snapshot.maybe_execute_live_automatic_mtb_rake", lambda *a, **k: False)
    monkeypatch.setattr("backend.balance_snapshot._subaccount_numbers_from_subaccounts_table", lambda *a, **k: [0, 1])
    monkeypatch.setattr("backend.balance_snapshot.ensure_subaccount_balance_table", lambda *a, **k: None)
    monkeypatch.setattr("backend.balance_snapshot._latest_subaccount_balance_row", lambda *a, **k: dict(prev))
    monkeypatch.setattr("backend.balance_snapshot.apply_balance_snapshot", fake_apply)
    monkeypatch.setattr("backend.balance_snapshot.aggregate_account_balance_from_subaccounts", fake_aggregate)
    monkeypatch.setattr("backend.balance_snapshot._balance_glitch_repoll_delays_sec", lambda: [0.0])
    monkeypatch.setattr("backend.balance_snapshot.time.sleep", lambda _s: None)

    cur = MagicMock()
    inserted, _ = poll_live_account_balances(cur, "0001", throttle=False)
    assert inserted is True
    assert mtb_fetch_calls["n"] == 2  # glitch tick, then clean repoll
    assert len(apply_calls) >= 1
    mtb_writes = [c for c in apply_calls if "subaccount_balance_0001_1" in c.get("account_balance_table", "")]
    assert mtb_writes
    assert mtb_writes[-1]["portfolio_value_raw"] == 0


def test_poll_live_account_balances_deposit_cycle_bypasses_guard(monkeypatch):
    prev = _mtb_prev_row(296449, 103796, 400245)
    glitch_detail = {
        "balance_cents": 400349,
        "portfolio_value_cents": 103796,
        "total_portfolio_cents": 504145,
    }

    def fake_fetch(slot, *, subaccount=None):
        if subaccount == 0:
            return {"balance_cents": 10000, "portfolio_value_cents": 0, "total_portfolio_cents": 10000}
        if subaccount == 1:
            return dict(glitch_detail)
        return None

    apply_calls = []

    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_subaccount_balances_cents_map",
        lambda slot: {0: 10000, 1: 400349},
    )
    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_portfolio_balance_detail",
        fake_fetch,
    )
    monkeypatch.setattr("backend.kalshi_account_sync_ws._sync_subaccounts_from_kalshi_poll", lambda *a, **k: None)
    monkeypatch.setattr("backend.balance_snapshot.refresh_mtb_realized_pnl_from_balance", lambda *a, **k: None)
    monkeypatch.setattr("backend.balance_snapshot.maybe_execute_live_automatic_mtb_rake", lambda *a, **k: False)
    monkeypatch.setattr("backend.balance_snapshot._subaccount_numbers_from_subaccounts_table", lambda *a, **k: [0, 1])
    monkeypatch.setattr("backend.balance_snapshot.ensure_subaccount_balance_table", lambda *a, **k: None)
    monkeypatch.setattr("backend.balance_snapshot._latest_subaccount_balance_row", lambda *a, **k: dict(prev))
    monkeypatch.setattr(
        "backend.balance_snapshot.apply_balance_snapshot",
        lambda *a, **k: apply_calls.append(k) or (True, False),
    )
    monkeypatch.setattr(
        "backend.balance_snapshot.aggregate_account_balance_from_subaccounts",
        lambda *a, **k: (True, False),
    )

    cur = MagicMock()
    poll_live_account_balances(cur, "0001", throttle=False, deposit_cycle=True)
    mtb_writes = [c for c in apply_calls if "subaccount_balance_0001_1" in c.get("account_balance_table", "")]
    assert len(mtb_writes) == 1
    assert mtb_writes[0]["portfolio_value_raw"] == 103796


def test_poll_live_account_balances_exhausted_retries_no_write(monkeypatch):
    prev = _mtb_prev_row(296449, 103796, 400245)
    glitch_detail = {
        "balance_cents": 400349,
        "portfolio_value_cents": 103796,
        "total_portfolio_cents": 504145,
    }

    def fake_fetch(slot, *, subaccount=None):
        if subaccount == 0:
            return {"balance_cents": 10000, "portfolio_value_cents": 0, "total_portfolio_cents": 10000}
        if subaccount == 1:
            return dict(glitch_detail)
        return None

    apply_calls = []

    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_subaccount_balances_cents_map",
        lambda slot: {0: 10000, 1: 400349},
    )
    monkeypatch.setattr(
        "backend.bookkeeper.kalshi_portfolio_balance.fetch_portfolio_balance_detail",
        fake_fetch,
    )
    monkeypatch.setattr("backend.kalshi_account_sync_ws._sync_subaccounts_from_kalshi_poll", lambda *a, **k: None)
    monkeypatch.setattr("backend.balance_snapshot.refresh_mtb_realized_pnl_from_balance", lambda *a, **k: None)
    monkeypatch.setattr("backend.balance_snapshot.maybe_execute_live_automatic_mtb_rake", lambda *a, **k: False)
    monkeypatch.setattr("backend.balance_snapshot._subaccount_numbers_from_subaccounts_table", lambda *a, **k: [0, 1])
    monkeypatch.setattr("backend.balance_snapshot._latest_subaccount_balance_row", lambda *a, **k: dict(prev))
    monkeypatch.setattr(
        "backend.balance_snapshot.apply_balance_snapshot",
        lambda *a, **k: apply_calls.append(1) or (True, False),
    )
    monkeypatch.setattr("backend.balance_snapshot._balance_glitch_repoll_delays_sec", lambda: [0.0, 0.0, 0.0])
    monkeypatch.setattr("backend.balance_snapshot.time.sleep", lambda _s: None)

    cur = MagicMock()
    inserted, _ = poll_live_account_balances(cur, "0001", throttle=False)
    assert inserted is False
    assert apply_calls == []


def test_aggregate_account_balance_from_subaccounts_sums_and_copies_mtb():
    class Cur:
        def __init__(self):
            self._latest = {
                "users_0001.subaccount_balance_0001_0": (
                    10000, 0, 0, 10000, 0, 10000, None, None
                ),
                "users_0001.subaccount_balance_0001_1": (
                    5000, 2000, 2000, 7000, 2000, 55000, 55000, 50000
                ),
            }
            self._hero_prev = [(200000, 55000)]
            self._mtb_sub = [(55000, 50000)]
            self.calls = []

        def execute(self, q, p=None):
            self.calls.append((str(q), p))

        def fetchone(self):
            if self._hero_prev:
                return self._hero_prev.pop(0)
            if self._mtb_sub:
                return self._mtb_sub.pop(0)
            return None

    cur = Cur()

    def fake_latest(cursor, table_fqn):
        row = cur._latest.get(table_fqn)
        if not row:
            return None
        keys = (
            "balance",
            "exposure",
            "positions",
            "portfolio",
            "portfolio_value",
            "bankroll_current",
            "master_trading_bankroll",
            "mtb_base_value",
        )
        return {k: row[i] for i, k in enumerate(keys)}

    import backend.balance_snapshot as bs

    orig = bs._latest_subaccount_balance_row
    bs._latest_subaccount_balance_row = fake_latest
    try:
        inserted, _ = aggregate_account_balance_from_subaccounts(
            cur,
            user_no="0001",
            account_balance_table="users_0001.account_balance_0001",
            subaccount_numbers=[0, 1],
            current_timestamp="2026-05-23T12:00:00",
            throttle=False,
        )
    finally:
        bs._latest_subaccount_balance_row = orig

    assert inserted is True
    insert_calls = [c for c in cur.calls if c[0] and "INSERT INTO" in c[0]]
    assert insert_calls
    vals = insert_calls[-1][1]
    assert vals[0] == 15000  # balance sum
    assert vals[3] == 17000  # portfolio sum
    assert vals[4] == 55000  # bankroll from MTB subaccount 1


def test_parse_user_number_subaccount_balance_table():
    from backend.core.system_settings_store import parse_user_number_from_account_balance_table

    assert parse_user_number_from_account_balance_table("users_0001.subaccount_balance_0001_3") == "0001"
    assert parse_user_number_from_account_balance_table("users_0001.subaccount_balance_0001_0") == "0001"
    assert parse_user_number_from_account_balance_table("users_0001.account_balance_0001") == "0001"


def test_apply_balance_snapshot_subaccount_table_slot_match():
    """subaccount_balance FQN must not be parsed as user slot 0/3."""
    class Cur:
        def __init__(self):
            self.calls = []
            self._fetch = [None, (50000, 50000), (50000, 40000)]

        def execute(self, q, p=None):
            self.calls.append((str(q), p))

        def fetchone(self):
            if self._fetch:
                return self._fetch.pop(0)
            return None

    cur = Cur()
    inserted, _ = apply_balance_snapshot(
        cur,
        balance_amount=1000,
        portfolio_value_raw=0,
        positions_value=0,
        total_exposure=0,
        portfolio_value=1000,
        account_balance_table="users_0001.subaccount_balance_0001_0",
        subaccounts_table="users_0001.subaccounts_0001",
        current_timestamp="2026-05-23T12:00:00",
        throttle=False,
        record_internal_transfers=False,
        notify_frontend=False,
        notify_monitors=False,
    )
    assert inserted is True
    insert_calls = [c for c in cur.calls if "INSERT INTO" in c[0]]
    assert insert_calls


def test_fetch_portfolio_balance_detail_subaccount_query(monkeypatch):
    captured = {}

    def fake_request(user_no, method, path, *, params=None, **kwargs):
        captured["path"] = path
        captured["params"] = params
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"balance": 100, "portfolio_value": 50}
        return resp

    import backend.bookkeeper.kalshi_portfolio_balance as kpb

    monkeypatch.setattr(kpb, "kalshi_prod_request", fake_request)
    detail = kpb.fetch_portfolio_balance_detail("0001", subaccount=2)
    assert captured["path"] == "/portfolio/balance"
    assert captured["params"] == {"subaccount": 2}
    assert detail == {
        "balance_cents": 100,
        "portfolio_value_cents": 50,
        "total_portfolio_cents": 150,
    }
