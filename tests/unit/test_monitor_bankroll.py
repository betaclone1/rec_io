"""Unit tests for per-monitor subaccount bankroll resolution."""

from backend.core.monitor_bankroll import (
    latest_bankroll_cents_for_subaccount,
    subaccount_id_exists,
)


class _Cur:
    def __init__(self, responses):
        self._responses = list(responses)
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((str(query), params))

    def fetchone(self):
        if not self._responses:
            return None
        return self._responses.pop(0)


def test_live_reads_subaccount_balance_bankroll(monkeypatch):
    monkeypatch.setattr(
        "backend.core.monitor_bankroll.use_paper_for_request", lambda *_a, **_k: False
    )
    cur = _Cur(
        [
            (True,),  # table exists
            (50000, 48000),  # bankroll_current, portfolio
        ]
    )
    assert latest_bankroll_cents_for_subaccount(cur, "0001", 3) == 50000


def test_live_missing_table_returns_zero_no_mtb_substitute(monkeypatch):
    monkeypatch.setattr(
        "backend.core.monitor_bankroll.use_paper_for_request", lambda *_a, **_k: False
    )
    cur = _Cur([(False,)])
    assert latest_bankroll_cents_for_subaccount(cur, "0001", 3) == 0


def test_paper_mtb_uses_account_balance_paper(monkeypatch):
    monkeypatch.setattr(
        "backend.core.monitor_bankroll.use_paper_for_request", lambda *_a, **_k: True
    )
    cur = _Cur([(90000, 88000)])
    assert latest_bankroll_cents_for_subaccount(cur, "0001", 1) == 90000


def test_paper_other_uses_subaccounts_paper_balance(monkeypatch):
    monkeypatch.setattr(
        "backend.core.monitor_bankroll.use_paper_for_request", lambda *_a, **_k: True
    )
    cur = _Cur([(12345,)])
    assert latest_bankroll_cents_for_subaccount(cur, "0001", 2) == 12345


def test_subaccount_id_exists(monkeypatch):
    monkeypatch.setattr(
        "backend.core.monitor_bankroll.use_paper_for_request", lambda *_a, **_k: False
    )
    cur = _Cur([(1,)])
    assert subaccount_id_exists(cur, "0001", 1) is True
    cur2 = _Cur([None])
    assert subaccount_id_exists(cur2, "0001", 99) is False
