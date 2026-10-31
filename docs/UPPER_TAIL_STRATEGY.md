# Upper Tail

One-sided entry at the expensive end of a 15m book. Same monitor criteria as Lower Tail: a time window (`min_time`–`max_time`) and one target price (`min_ask` = `max_ask`, default $0.99).

Kalshi will not rest these orders from the open. `upper_tail_agent` qualifies during the monitor time window, then sends a single GTC limit at the target on that side (`post_only` off):

- **Crypto** at `live_data_level=full` — Redis orderbook touch (best bid/ask ≥ target) via market_watchdog OB → `rec_io:live_state:updated`. Crypto 15m is assumed **24/7**.
- **Commodity** / lean `market` feed — public trades tape print ≥ target (market_watchdog `public_trade` Redis). Commodity books stay off the orderbook path for now. Weekend REST polling is gated by hardcoded metals/energy dark hours in `backend/core/market_watchdog/venues/kalshi/schedule.py` (assume recent-month calendar; recheck periodically; new non-crypto symbols need their own close_time back-check before joining a cohort).

The trade is booked only after our own fill (`intent=upper_tail_fill`). Paper monitors book when the trigger qualifies.

Symbols: any 15m underlying whose `live_data_level` is `full` or `market`. AES does not enter these monitors. ATS supervises the open leg the same way as Expiration Scalp: the monitor stop-loss price is the opposite-ask floor, and floor flip sell follows that close when the monitor enables it. A stop price of 0 leaves the leg on until settlement. Lower Tail stays outside ATS.

Process: `upper_tail_agent_*` (port 8052 for user 0001). Strategy seed: migration `20261020_1645_taker_edge_strategy`.
