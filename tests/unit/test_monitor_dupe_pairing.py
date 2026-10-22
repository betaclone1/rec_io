"""Monitor dupe pairing helpers."""

from backend.core.monitor_dupe_pairing import (
    apply_monitor_dupe_pairing_position_cap,
    normalize_monitor_dupe_pairing,
    reversal_flip_blocked_by_dupe_pairing,
)


def test_normalize_monitor_dupe_pairing_dedupes_and_excludes_self():
    assert normalize_monitor_dupe_pairing([10058, 10046, 10058], self_monitor_id=10046) == [10058]
    assert normalize_monitor_dupe_pairing("10058,10059", self_monitor_id=10046) == [10058, 10059]
    assert normalize_monitor_dupe_pairing(None) == []


class _FakeCursor:
    def __init__(self, pairing, paired_sum):
        self.pairing = pairing
        self.paired_sum = paired_sum
        self.calls = 0

    def execute(self, sql, params=None):
        self.calls += 1
        if "monitor_dupe_pairing" in sql:
            self._last = ("pairing", params)
        else:
            self._last = ("sum", params)

    def fetchone(self):
        if self._last[0] == "pairing":
            return (self.pairing,)
        return (self.paired_sum,)


def test_apply_monitor_dupe_pairing_caps_position():
    data = {
        "monitor": "mon_0001_10046",
        "ticker": "KXBTC15M-TEST",
        "side": "Y",
        "position": 1000,
        "paper_trade": False,
    }
    cur = _FakeCursor([10058], 800)
    allowed, detail = apply_monitor_dupe_pairing_position_cap(
        data,
        cursor=cur,
        monitor_list_table="users.monitor_list_0001",
        trades_table="users.trades_0001",
        user_slot="0001",
        monitor_id=10046,
        normalize_side_fn=lambda s: "yes" if str(s).upper().startswith("Y") else "no",
    )
    assert allowed is True
    assert data["position"] == 200
    assert data["count_fp"] == "200.00"
    assert detail and "monitor_dupe_pairing_capped" in detail


def test_apply_monitor_dupe_pairing_blocks_when_fully_allocated():
    data = {
        "monitor": "mon_0001_10046",
        "ticker": "KXBTC15M-TEST",
        "side": "yes",
        "position": 1000,
        "paper_trade": False,
    }
    cur = _FakeCursor([10058], 1000)
    allowed, detail = apply_monitor_dupe_pairing_position_cap(
        data,
        cursor=cur,
        monitor_list_table="users.monitor_list_0001",
        trades_table="users.trades_0001",
        user_slot="0001",
        monitor_id=10046,
        normalize_side_fn=lambda s: "yes" if str(s).upper().startswith("Y") else "no",
    )
    assert allowed is False
    assert detail and "monitor_dupe_pairing_blocked" in detail


class _FlipCursor:
    def __init__(self, pairing, peer_present):
        self.pairing = pairing
        self.peer_present = peer_present
        self._kind = None

    def execute(self, sql, params=None):
        self._kind = "pairing" if "monitor_dupe_pairing" in sql else "peer"
        self.params = params

    def fetchone(self):
        if self._kind == "pairing":
            return (self.pairing,)
        return (1,) if self.peer_present else None


def _flip_check(pairing, peer_present, ticker="KXBTC15M-26OCT211715-15"):
    return reversal_flip_blocked_by_dupe_pairing(
        _FlipCursor(pairing, peer_present),
        monitor_list_table="users_0001.monitor_list_0001",
        trades_table="users_0001.trades_0001",
        user_slot="0001",
        monitor_id=10063,
        ticker=ticker,
    )


def test_reversal_flip_allowed_when_unpaired():
    blocked, detail = _flip_check([], False)
    assert blocked is False
    assert detail is None


def test_reversal_flip_allowed_when_peer_was_not_in_cycle():
    blocked, detail = _flip_check([10046], False)
    assert blocked is False
    assert detail is None


def test_reversal_flip_blocked_when_peer_was_in_cycle():
    blocked, detail = _flip_check([10046], True)
    assert blocked is True
    assert detail and "reversal_dupe_pairing_blocked" in detail
    assert "10046" in detail


def test_reversal_flip_blocked_when_ticker_missing_and_paired():
    blocked, detail = _flip_check([10046], False, ticker="")
    assert blocked is True
    assert detail and "ticker_missing" in detail
