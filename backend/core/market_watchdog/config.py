"""Production Kalshi market ingest configuration (maps sandbox env names)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from backend.core.market_watchdog.venues.kalshi.schedule import SERIES_15M_BY_SYMBOL


def _env(primary: str, sandbox: str, default: str) -> str:
    return (os.getenv(primary) or os.getenv(sandbox) or default).strip()


@dataclass(frozen=True)
class IngestConfig:
    exchange: str
    market_interval: str
    symbols: tuple[str, ...]
    prediscover_hours: float
    schedule_refresh_sec: float
    orderbook_cutover_sec: float
    outgoing_track_sec: float
    hourly_atm_strikes_each_side: int
    publish_coalesce_sec: float
    ws_market_chunk: int
    channel_resync_debounce_sec: float
    channel_resync_min_interval_sec: float
    lifecycle_sync_sec: float
    periodic_snapshot_sec: float
    event_log_enabled: bool
    disturbance_log_enabled: bool
    settled_redis_key: str

    @property
    def only_15m(self) -> bool:
        """Sandbox ``SANDBOX_KALSHI_15M_ONLY=1`` — skip hourly subs."""
        return self.market_interval == "15m"

    @property
    def includes_15m(self) -> bool:
        return self.market_interval in ("all", "15m")

    @property
    def includes_hourly(self) -> bool:
        return self.market_interval in ("all", "hourly")


def load_config(*, exchange: str, market_interval: str = "all") -> IngestConfig:
    iv = market_interval.strip().lower()
    if iv not in ("all", "15m", "hourly"):
        raise ValueError("market must be all, 15m, or hourly")
    raw = _env("MARKET_WATCHDOG_SYMBOLS", "SANDBOX_KALSHI_SYMBOLS", ",".join(SERIES_15M_BY_SYMBOL))
    symbols = tuple(s.strip().upper() for s in raw.split(",") if s.strip()) or ("BTC",)
    for sym in symbols:
        if sym not in SERIES_15M_BY_SYMBOL:
            raise ValueError(f"Unknown symbol {sym!r}; supported: {sorted(SERIES_15M_BY_SYMBOL)}")
    if iv == "hourly":
        from backend.core.market_watchdog.venues.kalshi.schedule import SERIES_HOURLY_BY_SYMBOL

        symbols = tuple(s for s in symbols if s in SERIES_HOURLY_BY_SYMBOL)
        if not symbols:
            symbols = ("BTC",)
    elif iv == "all":
        pass
    prefix = _env("MARKET_WATCHDOG_REDIS_PREFIX", "SANDBOX_KALSHI_REDIS_PREFIX", "rec_io:market_watchdog:")
    return IngestConfig(
        exchange=exchange.strip().lower(),
        market_interval=iv,
        symbols=symbols,
        prediscover_hours=float(_env("MARKET_WATCHDOG_PREDISCOVER_HOURS", "SANDBOX_KALSHI_PREDISCOVER_HOURS", "4")),
        schedule_refresh_sec=float(
            _env("MARKET_WATCHDOG_SCHEDULE_REFRESH_SEC", "SANDBOX_KALSHI_SCHEDULE_REFRESH_SEC", "900")
        ),
        orderbook_cutover_sec=float(
            _env("MARKET_WATCHDOG_ORDERBOOK_CUTOVER_SEC", "SANDBOX_KALSHI_ORDERBOOK_CUTOVER_SEC", "2")
        ),
        outgoing_track_sec=float(
            _env("MARKET_WATCHDOG_OUTGOING_TRACK_SEC", "SANDBOX_KALSHI_OUTGOING_TRACK_SEC", "960")
        ),
        hourly_atm_strikes_each_side=int(
            _env(
                "MARKET_WATCHDOG_HOURLY_ATM_STRIKES_EACH_SIDE",
                "SANDBOX_KALSHI_HOURLY_ATM_STRIKES_EACH_SIDE",
                "20",
            )
        ),
        publish_coalesce_sec=max(
            0.01,
            float(_env("MARKET_WATCHDOG_PUBLISH_COALESCE_MS", "SANDBOX_KALSHI_PUBLISH_COALESCE_MS", "50"))
            / 1000.0,
        ),
        ws_market_chunk=max(
            1,
            int(_env("MARKET_WATCHDOG_WS_MARKET_CHUNK", "SANDBOX_KALSHI_WS_MARKET_CHUNK", "80")),
        ),
        channel_resync_debounce_sec=float(
            _env(
                "MARKET_WATCHDOG_CHANNEL_RESYNC_DEBOUNCE_SEC",
                "SANDBOX_KALSHI_CHANNEL_RESYNC_DEBOUNCE_SEC",
                "10",
            )
        ),
        channel_resync_min_interval_sec=float(
            _env(
                "MARKET_WATCHDOG_CHANNEL_RESYNC_MIN_INTERVAL_SEC",
                "SANDBOX_KALSHI_CHANNEL_RESYNC_MIN_INTERVAL_SEC",
                "45",
            )
        ),
        lifecycle_sync_sec=float(
            _env("MARKET_WATCHDOG_LIFECYCLE_SYNC_SEC", "SANDBOX_KALSHI_LIFECYCLE_SYNC_SEC", "1.0")
        ),
        periodic_snapshot_sec=float(
            _env("MARKET_WATCHDOG_PERIODIC_SNAPSHOT_SEC", "SANDBOX_KALSHI_PERIODIC_SNAPSHOT_SEC", "0")
        ),
        event_log_enabled=os.getenv("MARKET_WATCHDOG_EVENT_LOG", "").strip() != "",
        disturbance_log_enabled=os.getenv("MARKET_WATCHDOG_DISTURBANCE_LOG", "").strip() != "",
        settled_redis_key=f"{prefix.rstrip(':')}:settled:v1",
    )
