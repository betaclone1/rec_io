"""Paper Taker Edge must use the Kalshi taker fee schedule (same as Expiration / HTC)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.trade_manager import (
    _paper_open_fee_for_edge_strategy,
    book_maker_edge_external_fill,
    book_taker_edge_external_fill,
    estimate_kalshi_taker_fee,
)


def test_paper_open_fee_taker_edge_matches_kalshi_schedule():
    # 0.07 * 32 * 0.99 * 0.01 = 0.022176 → ceil cent = 0.03
    assert estimate_kalshi_taker_fee(32, 0.99) == 0.03
    assert _paper_open_fee_for_edge_strategy("Taker Edge", 32, 0.99) == 0.03
    assert _paper_open_fee_for_edge_strategy("Maker Edge", 32, 0.99) == 0.0


def test_book_taker_edge_paper_stamps_taker_fees():
    captured = {}

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, q, p=None):
            qs = str(q)
            if "SET fees" in qs or "fees = %s" in qs:
                captured["fees_params"] = p

        def fetchone(self):
            return None

    class Conn:
        def cursor(self):
            return Cur()

        def commit(self):
            pass

        def close(self):
            pass

    with (
        patch(
            "backend.trade_manager.insert_trade",
            return_value=(4242, True),
        ),
        patch(
            "backend.trade_manager.get_postgresql_connection",
            return_value=Conn(),
        ),
        patch("backend.trade_manager.notify_strike_table_trade_change"),
        patch("backend.trade_manager.log_event"),
        patch("backend.trade_manager.log"),
        patch("backend.trade_manager._paper_ledger_on_open") as ledger,
        patch(
            "backend.trade_manager._maker_edge_bankroll_allotment_cents",
            return_value=10000,
        ),
        patch(
            "backend.trade_manager.derive_contract_label_from_kalshi_ticker",
            return_value="ETH",
        ),
    ):
        out = book_taker_edge_external_fill(
            {
                "trade_strategy": "Taker Edge",
                "side": "yes",
                "buy_price": 0.99,
                "position": 32,
                "ticker": "KXETH15M-26OCT231200-30",
                "strike": 2445.0,
                "paper_trade": True,
                "symbol": "ETH",
                "monitor": "99001",
            }
        )
    assert out["id"] == 4242
    assert captured["fees_params"][0] == 0.03
    assert captured["fees_params"][1] == 4242
    ledger.assert_called_once()
    assert ledger.call_args[0][2] == 0.03


def test_book_maker_edge_paper_keeps_zero_fees():
    captured = {}

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, q, p=None):
            if "fees" in str(q):
                captured["fees_params"] = p

        def fetchone(self):
            return None

    class Conn:
        def cursor(self):
            return Cur()

        def commit(self):
            pass

        def close(self):
            pass

    with (
        patch("backend.trade_manager.insert_trade", return_value=(99, True)),
        patch("backend.trade_manager.get_postgresql_connection", return_value=Conn()),
        patch("backend.trade_manager.notify_strike_table_trade_change"),
        patch("backend.trade_manager.log_event"),
        patch("backend.trade_manager.log"),
        patch("backend.trade_manager._paper_ledger_on_open") as ledger,
        patch(
            "backend.trade_manager._maker_edge_bankroll_allotment_cents",
            return_value=10000,
        ),
        patch(
            "backend.trade_manager.derive_contract_label_from_kalshi_ticker",
            return_value="BTC",
        ),
        patch(
            "backend.core.aes_btc15m_maker_edge_cutout.STRATEGY_NAME",
            "Maker Edge",
        ),
    ):
        book_maker_edge_external_fill(
            {
                "trade_strategy": "Maker Edge",
                "side": "yes",
                "buy_price": 0.99,
                "position": 32,
                "ticker": "KXBTC15M-26OCT231200-30",
                "strike": 111000.0,
                "paper_trade": True,
                "symbol": "BTC",
            }
        )
    assert captured["fees_params"][0] == 0.0
    ledger.assert_not_called()
