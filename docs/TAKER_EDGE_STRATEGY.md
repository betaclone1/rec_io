# Taker Edge

One-sided entry at the expensive end of a 15m book. Same monitor criteria as Maker Edge: a time window (`min_time`–`max_time`) and one target price (`min_ask` = `max_ask`, default $0.99).

Kalshi will not rest these orders from the open. `taker_edge_agent` watches the live public tape. When a print on one side is at or above the target, and that print's time-to-close is inside the window, the agent sends a single GTC limit at the target on that side (`post_only` off). The public print is the trigger. The trade is booked only after our own fill (`intent=taker_edge_fill`). Paper monitors book from the qualifying print.

Symbols: BTC, ETH, GOLD, SILVER, WTI on 15m. AES does not enter these monitors. ATS supervises the open leg the same way as Expiration Scalp: the monitor stop-loss price is the opposite-ask floor, and floor flip sell follows that close when the monitor enables it. A stop price of 0 leaves the leg on until settlement. Maker Edge stays outside ATS.

Process: `taker_edge_agent_*` (port 8052 for user 0001). Strategy seed: migration `20261020_1645_taker_edge_strategy`.
