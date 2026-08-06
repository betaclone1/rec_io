from __future__ import annotations

from backend.core.trades_history_insights import build_trade_history_filter_sql


def test_test_only_shows_test_filter_regardless_of_paper() -> None:
    sql, _params = build_trade_history_filter_sql(
        {
            "include_test_trades": True,
            "show_live": False,
            "show_paper": False,
            "show_win": True,
            "show_loss": True,
        }
    )
    assert "test_filter" in sql
    assert "IS TRUE" in sql
    assert "paper_trade" not in sql


def test_paper_only_excludes_test_filter_rows() -> None:
    sql, _params = build_trade_history_filter_sql(
        {
            "include_test_trades": False,
            "show_live": False,
            "show_paper": True,
            "show_win": True,
            "show_loss": True,
        }
    )
    assert "paper_trade" in sql
    assert "test_filter" in sql
    assert "IS NOT TRUE" in sql
    assert "IS TRUE)" not in sql.replace("IS NOT TRUE", "EXCL")


def test_live_and_test_omits_regular_paper() -> None:
    sql, _params = build_trade_history_filter_sql(
        {
            "include_test_trades": True,
            "show_live": True,
            "show_paper": False,
            "show_win": True,
            "show_loss": True,
        }
    )
    assert " OR " in sql
    assert "paper_trade, FALSE) = FALSE" in sql
    assert "test_filter, FALSE) IS TRUE" in sql


def test_no_trade_type_selected_is_empty() -> None:
    sql, _params = build_trade_history_filter_sql(
        {
            "include_test_trades": False,
            "show_live": False,
            "show_paper": False,
            "show_win": True,
            "show_loss": True,
        }
    )
    assert "1=0" in sql
