# Drawdown / MTB verification

**Goal:** Ensure drawdown logic uses Master Trading Bankroll (mtb_base_value), not total portfolio value, for the 70% step-down threshold.

**Scope:** In: ratchet in kalshi_account_sync_ws.py — peg drawdown threshold to mtb_base_value when set; fallback to prev_bankroll. Out: other MTB or account-balance work.

**Status:** done (completed 2026-03-14)

## Steps

1. ~~Peg drawdown threshold to mtb_base_value in account sync ratchet~~ — Done: threshold = 70% of mtb_base when set, else 70% of prev_bankroll.
2. ~~Update docstrings to describe MTB-based threshold~~ — Done in kalshi_account_sync_ws.py and notify_monitor_manager.

## Completion criteria

- [x] Drawdown step-down uses mtb_base_value (or prev_bankroll if base not set) for the 70% check.
- [x] Cash reserve (total portfolio) is not used as the highwater reference; MTB base is.
