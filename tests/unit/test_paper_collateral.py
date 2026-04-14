"""Unit tests for FIFO YES/NO collateral netting (paper trading)."""

from backend.paper_collateral import netted_open_premium_cents_from_rows


def test_netted_only_yes_sums():
    rows = [(1, "KX-TEST", "Y", 0.40, 100)]
    assert netted_open_premium_cents_from_rows(rows) == 40 * 100


def test_netted_full_box_zero_unpaired():
    rows = [
        (1, "KX-TEST", "Y", 0.40, 100),
        (2, "KX-TEST", "N", 0.58, 100),
    ]
    assert netted_open_premium_cents_from_rows(rows) == 0


def test_netted_partial_pair_leaves_residual_yes():
    rows = [
        (1, "KX-TEST", "Y", 0.40, 100),
        (2, "KX-TEST", "N", 0.58, 50),
    ]
    # 50 paired, 50 YES @ 0.40 -> $20
    assert netted_open_premium_cents_from_rows(rows) == 20 * 100


def test_netted_fifo_across_lots():
    rows = [
        (1, "KX-TEST", "Y", 0.30, 40),
        (2, "KX-TEST", "Y", 0.50, 60),
        (3, "KX-TEST", "N", 0.55, 50),
    ]
    # Pair 50 YES: 40 @ 0.30 + 10 @ 0.50 vs 50 NO; residual 50 YES @ 0.50
    assert netted_open_premium_cents_from_rows(rows) == int(round(0.50 * 50 * 100))


def test_separate_tickers_no_cross_pair():
    rows = [
        (1, "A", "Y", 0.40, 10),
        (2, "B", "N", 0.50, 10),
    ]
    assert netted_open_premium_cents_from_rows(rows) == int(round((0.40 * 10 + 0.50 * 10) * 100))
