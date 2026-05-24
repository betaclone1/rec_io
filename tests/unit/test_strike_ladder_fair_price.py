from backend.core.strike_ladder_fetch import yes_fair_price_dollars_from_strike_row


def test_yes_fair_price_spot_above_strike_uses_yes_prob_15m():
    row = {
        "strike": 100.0,
        "yes_prob_15m": 92.5,
        "no_prob_15m": 7.5,
    }
    assert yes_fair_price_dollars_from_strike_row(
        row, market="15m", current_price=105.0
    ) == 0.925


def test_yes_fair_price_spot_below_strike_uses_one_minus_no_prob_15m():
    row = {
        "strike": 110.0,
        "yes_prob_15m": 8.0,
        "no_prob_15m": 92.0,
    }
    assert yes_fair_price_dollars_from_strike_row(
        row, market="15m", current_price=105.0
    ) == 0.08


def test_yes_fair_price_hourly_uses_hourly_legs():
    row = {
        "strike": 100.0,
        "yes_prob_hourly": 60.0,
        "no_prob_hourly": 40.0,
    }
    assert yes_fair_price_dollars_from_strike_row(
        row, market="hourly", current_price=95.0
    ) == 0.60


def test_yes_fair_price_at_strike_uses_no_complement():
    row = {"strike": 100.0, "yes_prob_15m": 50.0, "no_prob_15m": 50.0}
    assert yes_fair_price_dollars_from_strike_row(
        row, market="15m", current_price=100.0
    ) == 0.50
