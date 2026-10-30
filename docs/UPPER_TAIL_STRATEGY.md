# Upper Tail

One-sided entry at the expensive end of a 15m book. Same monitor criteria as Lower Tail: a time window (`min_time`–`max_time`) and one target price (`min_ask` = `max_ask`, default $0.99).

Kalshi will not rest these orders from the open. `upper_tail_agent` watches live ticker BBO from market_watchdog Redis (`yes_ask_dollars` / `no_ask_dollars`). When best ask on one side first reaches the target (e.g. YES ask = $0.99), and current TTC is inside the window, the agent sends a single GTC limit at the target on that side (`post_only` off). BBO is the trigger (earlier than waiting for a public print at that rail). The trade is booked only after our own fill (`intent=upper_tail_fill`). Paper monitors book when BBO qualifies.

Symbols: any 15m underlying whose `live_data_level` is `full` or `market`. AES does not enter these monitors. ATS supervises the open leg the same way as Expiration Scalp: the monitor stop-loss price is the opposite-ask floor, and floor flip sell follows that close when the monitor enables it. A stop price of 0 leaves the leg on until settlement. Lower Tail stays outside ATS.

Process: `upper_tail_agent_*` (port 8052 for user 0001). Strategy seed: migration `20261020_1645_taker_edge_strategy`.
