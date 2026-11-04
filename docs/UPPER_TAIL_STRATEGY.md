# Upper Tail

**v4 CORE context:** Upper Tail is one rail of the main live strategy set — probe W/L → bias meter → sized arm. See `docs/VER4_DEVELOPMENT/CORE_TAIL_BIAS_STRATEGY.md`.

One-sided entry at the expensive end of a 15m book. Same monitor criteria as Lower Tail: a time window (`min_time`–`max_time`) and one target price (`min_ask` = `max_ask`, default $0.99).

Kalshi will not rest these orders from the open. `upper_tail_agent` qualifies during the monitor time window, then sends a single GTC limit at the target on that side (`post_only` off):

- **Crypto** at `live_data_level=full` — active trigger on the OB publish path: when an armed ticker’s touch crosses the rail, watchdog publishes `rec_io:upper_tail:rail_trigger:v1`; `upper_tail_agent` places once (`path=rail`). The agent does **not** subscribe to every orderbook delta. Housekeeping (monitors, markets, fills, arm registry) is a slow timer loop with a Redis-touch failsafe (`path=failsafe`). Crypto 15m is assumed **24/7**.
- **Commodity** / lean `market` feed — public trades tape print ≥ target on the timer loop (`path=slow`). Commodity books stay off the rail-trigger path for now. Weekend REST polling is gated by hardcoded metals/energy dark hours in `backend/core/market_watchdog/venues/kalshi/schedule.py` (assume recent-month calendar; recheck periodically; new non-crypto symbols need their own close_time back-check before joining a cohort).

The trade is booked only after our own fill (`intent=upper_tail_fill`). Paper monitors book when the trigger qualifies.

Symbols: any 15m underlying whose `live_data_level` is `full` or `market`. AES does not enter these monitors. ATS supervises the open leg the same way as Expiration Scalp: the monitor stop-loss price is the opposite-ask floor, and floor flip sell follows that close when the monitor enables it. A stop price of 0 leaves the leg on until settlement. Lower Tail stays outside ATS.

Process: `upper_tail_agent_*` (port 8052 for user 0001). Strategy seed: migration `20261020_1645_taker_edge_strategy`.
