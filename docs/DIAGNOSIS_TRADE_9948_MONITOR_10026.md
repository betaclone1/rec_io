# Diagnosis: Trade 9948 and monitor 10026 strategy mismatch

## What we see

- **Trade 9948** (`users.trades_0001`):  
  symbol=ETH, market=Kalshi, **trade_strategy=Hourly HTC**, contract=ETH 10am, strike=$1,970, side=Y, **monitor=mon_0001_10026**, **entry_method=auto_entry**, paper_trade=True.

- **Monitor 10026** (`users.monitor_list_0001`):  
  symbol=BTC, **strategy=15m HTC**, market=15m.

So the trade is ETH hourly (10am) with strategy "Hourly HTC", but it is attributed to monitor 10026, which is configured as BTC and "15m HTC". That is a **symbol** and **strategy** mismatch.

## How trades get monitor and strategy

1. **Auto-entry (this trade)**  
   `backend/auto_entry_supervisor.py` → `trigger_auto_entry_trade()` builds the payload and POSTs to trade_manager. It sets:
   - `monitor` = `f"mon_0001_{MONITOR_ID}"` (from the process identity, e.g. script name `auto_entry_supervisor_0001_10026`).
   - `trade_strategy` = `get_trade_strategy()` (reads `strategy` from `users.monitor_list_0001` for that same `MONITOR_ID`).
   - `symbol`, `contract`, strike data = from `get_master_strike_table_data()`, which uses `get_current_monitor_symbol_and_market()` (same monitor’s `symbol` and `market` from `monitor_list_0001`) and the corresponding strike table (e.g. `strike_table_15m_btc` or `strike_table_hourly_eth`).

   So for a single auto_entry process, **monitor**, **strategy**, and **symbol/contract** all come from the **same** monitor row. There is no code path in auto_entry that mixes one monitor’s id with another monitor’s strategy or symbol.

2. **Manual entry**  
   `prepareTradeData()` in the frontend loads strategy (and monitor) from `/api/monitor/{currentMonitorId}`. Strategy can be overridden by `#trade-strategy-picker` if present. So manual trades can theoretically get a different strategy than the monitor’s, but trade 9948 has **entry_method=auto_entry**, so it was not manual.

3. **Simulated 15m**  
   Simulated trades go to `users.trades_simulated_0001` via `insert_simulated_trade()`, not to `trades_0001`. So 9948 was not created by the simulated path.

## Conclusion: monitor 10026 likely had different config when the trade was created

For trade 9948 to be created by the **10026** auto_entry process with **ETH**, **Hourly HTC**, and **ETH 10am** we need:

- `get_current_monitor_symbol_and_market()` to return **ETH** and **hourly** (so the strike table used is hourly ETH, giving "ETH 10am" and ETH symbol).
- `get_trade_strategy()` to return **"Hourly HTC"** (either the monitor’s strategy at that time, or the fallback when the strategy column is null or the query fails).

So at the time this trade was created, **monitor 10026 in `users.monitor_list_0001` most likely had**:

- **symbol = ETH**
- **market = hourly**
- **strategy = Hourly HTC** (or null/query failure, which is fallback "Hourly HTC")

and was later reconfigured to **BTC**, **15m**, **15m HTC**. The trade was correctly attributed to 10026 at creation; the mismatch you see is between **current** monitor config and **historical** trade data.

## Optional checks

1. **History of monitor 10026**  
   If you have history (e.g. audit table, backups, or logs) for `users.monitor_list_0001` for id 10026, confirm whether it was ever ETH / hourly / Hourly HTC.

2. **Strategy fallback**  
   In `get_trade_strategy()`, if the DB query fails or returns no row, the code returns `"Hourly HTC"`. So a transient DB issue could have made a 15m HTC monitor record a trade as "Hourly HTC", but **symbol and contract** still come from `get_master_strike_table_data()` (monitor’s symbol/market). So we would still get **BTC** and a 15m contract, not ETH 10am. So the "wrong strategy but right symbol" case does not explain **ETH 10am**; to get ETH 10am, the monitor’s symbol/market must have been ETH/hourly at the time.

3. **Run the diagnostic script**  
   To re-check the trade and current monitor config:
   ```bash
   PYTHONPATH=/opt/rec_io_server python3 scripts/inspect_trade_and_monitor.py 9948 10026
   ```

## Summary

| Question | Answer |
|----------|--------|
| Why is trade 9948 under monitor 10026 but with Hourly HTC and ETH? | It was created by the auto_entry process for monitor 10026 when that monitor was almost certainly configured as ETH, hourly, Hourly HTC. It was later changed to BTC, 15m HTC. |
| Bug or config change? | Config change (or a one-off wrong row for 10026) is the only way the same process could write this trade. No current code path mixes monitor id with another monitor’s symbol/strategy for auto_entry. |
