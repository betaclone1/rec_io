"""Pure helpers for Kalshi REST event JSON readiness (no network, no Yahoo/yliveticker)."""


def _nonempty_str(v: object) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return bool(s)


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
        if not isinstance(m, dict):
            return False
        if m.get("floor_strike") is None:
            return False
        if not _nonempty_str(m.get("yes_ask_dollars")):
            return False
        if not _nonempty_str(m.get("yes_bid_dollars")):
            return False
    return True
