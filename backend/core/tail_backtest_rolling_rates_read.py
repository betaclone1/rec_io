"""Read helpers for ``historical_data.tail_backtest_rolling_rates`` chart UI."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional, Sequence

from backend.core.time_eastern import now_est

Side = Literal["lt", "ut"]

CRYPTO_SERIES: tuple[str, ...] = (
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
)
COMMODITY_SERIES: tuple[str, ...] = (
    "KXGOLD15M",
    "KXSILVER15M",
    "KXWTI15M",
)

SERIES_META: dict[str, dict[str, Any]] = {
    "KXBTC15M": {"symbol": "BTC", "asset_class": "crypto", "start_date": date(2026, 5, 1)},
    "KXETH15M": {"symbol": "ETH", "asset_class": "crypto", "start_date": date(2026, 5, 1)},
    "KXSOL15M": {"symbol": "SOL", "asset_class": "crypto", "start_date": date(2026, 5, 1)},
    "KXXRP15M": {"symbol": "XRP", "asset_class": "crypto", "start_date": date(2026, 5, 1)},
    "KXGOLD15M": {"symbol": "GOLD", "asset_class": "commodity", "start_date": date(2026, 9, 1)},
    "KXSILVER15M": {"symbol": "SILVER", "asset_class": "commodity", "start_date": date(2026, 9, 1)},
    "KXWTI15M": {"symbol": "WTI", "asset_class": "commodity", "start_date": date(2026, 9, 1)},
}

DEFAULT_WINDOWS: tuple[int, ...] = (7, 30, 90)


def _pct(rate: Optional[float]) -> Optional[float]:
    if rate is None:
        return None
    return round(float(rate) * 100.0, 4)


def rolling_rates_chart_payload(
    conn,
    *,
    side: Side = "lt",
    windows: Sequence[int] = DEFAULT_WINDOWS,
) -> dict[str, Any]:
    """Bundle 7/30/90 rolling WR series for the standalone chart page."""
    side_u: Side = "ut" if str(side).strip().lower() == "ut" else "lt"
    wins = tuple(sorted({int(w) for w in windows if int(w) > 0})) or DEFAULT_WINDOWS
    series_list = list(CRYPTO_SERIES) + list(COMMODITY_SERIES)

    rate_col = f"{side_u}_win_rate"
    scored_col = f"{side_u}_scored"
    wins_col = f"{side_u}_wins"

    sql = f"""
        SELECT series, as_of_trading_day, window_trading_days,
               {rate_col}, {scored_col}, {wins_col}
        FROM historical_data.tail_backtest_rolling_rates
        WHERE series = ANY(%s)
          AND window_trading_days = ANY(%s)
          AND (
            (series = ANY(%s) AND as_of_trading_day >= %s)
            OR (series = ANY(%s) AND as_of_trading_day >= %s)
          )
        ORDER BY series, as_of_trading_day, window_trading_days
    """
    crypto_start = SERIES_META["KXBTC15M"]["start_date"]
    cmdty_start = SERIES_META["KXGOLD15M"]["start_date"]

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                series_list,
                list(wins),
                list(CRYPTO_SERIES),
                crypto_start,
                list(COMMODITY_SERIES),
                cmdty_start,
            ),
        )
        rows = cur.fetchall()

    # series -> as_of -> window -> (rate_pct, scored, wins)
    nested: dict[str, dict[date, dict[int, tuple[Optional[float], int, int]]]] = {}
    for series, as_of, window, rate, scored, win_n in rows:
        nested.setdefault(str(series), {}).setdefault(as_of, {})[int(window)] = (
            _pct(rate),
            int(scored or 0),
            int(win_n or 0),
        )

    assets: list[dict[str, Any]] = []
    for series in series_list:
        meta = SERIES_META[series]
        by_day = nested.get(series, {})
        points: list[dict[str, Any]] = []
        for as_of in sorted(by_day):
            day_map = by_day[as_of]
            pt: dict[str, Any] = {"as_of": as_of.isoformat()}
            for w in wins:
                cell = day_map.get(w)
                if cell is None:
                    pt[f"w{w}"] = None
                    pt[f"scored{w}"] = None
                    pt[f"wins{w}"] = None
                else:
                    pt[f"w{w}"] = cell[0]
                    pt[f"scored{w}"] = cell[1]
                    pt[f"wins{w}"] = cell[2]
            points.append(pt)

        latest = points[-1] if points else None
        assets.append(
            {
                "symbol": meta["symbol"],
                "series": series,
                "asset_class": meta["asset_class"],
                "start_date": meta["start_date"].isoformat(),
                "points": points,
                "latest": latest,
            }
        )

    return {
        "side": side_u,
        "windows": list(wins),
        "generated_at": now_est().replace(microsecond=0).isoformat(),
        "assets": assets,
    }
