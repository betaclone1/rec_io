"""Pure helpers for Kalshi REST event JSON readiness (no network, no Yahoo/yliveticker)."""


def _nonempty_str(v: object) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return bool(s)


def market_row_has_usable_strike_inputs(market: object) -> bool:
    """Single-row check aligned with ``markets_all_have_usable_strike_inputs``."""
    if not isinstance(market, dict):
        return False
    if market.get("floor_strike") is None:
        return False
    if not _nonempty_str(market.get("yes_ask_dollars")):
        return False
    if not _nonempty_str(market.get("yes_bid_dollars")):
        return False
    return True


def event_with_only_usable_markets(event_data: dict) -> dict | None:
    """
    Shallow copy of ``event_data`` keeping only markets that pass REST readiness.

    Use when Kalshi returns a mix of rows (some missing ``floor_strike`` or quotes) so
    rollover can seed and subscribe to the ready subset instead of blocking forever.
    """
    markets = event_data.get("markets") or []
    usable = [m for m in markets if market_row_has_usable_strike_inputs(m)]
    if not usable:
        return None
    out = dict(event_data)
    out["markets"] = usable
    return out


def markets_all_have_usable_strike_inputs(event_data: dict) -> bool:
    """
    Rollover readiness gate.

    Hard requirement for a usable strike table:
      - explicit `floor_strike` for every market row
      - `yes_ask_dollars`
      - `yes_bid_dollars`

    If strike metadata is temporarily missing for a symbol on the new event, that symbol
    stays pending until it has full data.
    """
    markets = event_data.get("markets") or []
    if not markets:
        return False
    for m in markets:
        if not market_row_has_usable_strike_inputs(m):
            return False
    return True
