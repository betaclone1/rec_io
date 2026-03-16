## LP optimization — Momentum Contain / Breakout

**Goal:** choose a loss‑prevention (LP) win‑streak threshold that maximizes PnL for Momentum Contain / Momentum Breakout monitors, given:

- Two‑leg cycles (each cycle has two trades / legs).
- Full‑size exposure in normal mode (e.g. 500/leg).
- Reduced exposure in LP mode (e.g. 1 contract/leg).

### Data and grouping

- **Source tables:** `users.trades_0001` (and optionally `users.trades_simulated_0001` if we ever include simulated MC data).
- **Monitor selection:** one or more monitors (e.g. `mon_0001_10023` for BTC MC).
- **Date filter:** arbitrary (`created_at` range); caller specifies (e.g. “last 30 days”).
- **Cooldown filter:** optional (common default: `cooldown_timer IS NULL OR cooldown_timer <= 3300`).
- **Cycle key:** use the trade `ticker` prefix as in the live win‑streak logic:
  - `cycle_id = regexp_replace(ticker, '-[^-]*$', '')`
  - Group all trades for a given monitor + `cycle_id`.
- **Cycle result:**
  - **Winning cycle**: all trades in that cycle have `win_loss = 'W'`.
  - **Losing cycle**: any trade in that cycle has `win_loss = 'L'`.
- **Cycle PnL:** `cycle_pnl = SUM(pnl)` over trades in the cycle.

### LP state machine (MC / MB)

This mirrors the production logic in `trade_manager.update_monitor_win_streak` for Momentum Contain / Breakout:

- **State variables (per monitor):**
  - `in_lp`: whether the monitor is in loss‑prevention mode.
  - `streak`: current count of **winning cycles** since the last loss.
  - `threshold`: `win_streak_threshold` being tested (integer ≥ 1).
- **Exposure assumption for backtest:**
  - Normal mode: cycle PnL uses recorded PnL unchanged (represents full‑size, e.g. 500/leg).
  - LP mode: cycle PnL is scaled down by a factor (current default: **0.5**, representing 1 contract/leg vs 500/leg).
- **Update rules per cycle (ordered by `first_created_at`):**
  - If `is_win`:
    - `streak += 1`.
    - If `in_lp` and `streak >= threshold`: exit LP (`in_lp = False`).
  - If loss:
    - Enter LP (`in_lp = True`).
    - Reset `streak = 0`.
  - PnL contribution for the cycle:
    - `scale = 0.5 if in_lp else 1.0`
    - `contribution = cycle_pnl * scale`

### Backtest procedure

For a given monitor and data slice:

1. Build an ordered list of cycles:
   - Fields: `cycle_id`, `first_created_at`, `cycle_pnl`, `is_win`.
   - Sort by `first_created_at` ascending.
2. Choose:
   - `threshold_min`, `threshold_max` (e.g. 1–20).
   - LP scale factor (default 0.5).
3. For each `threshold` in `[threshold_min, threshold_max]`:
   - Initialize `in_lp = False`, `streak = 0`, `total_pnl = 0`.
   - Iterate cycles in order, applying the state machine above and accumulating `total_pnl`.
   - Record `(threshold, total_pnl, wins, losses, num_cycles)`.
4. Compute:
   - **Baseline (no LP)** PnL for the same slice (just sum `cycle_pnl` with `scale = 1` always).
   - **Improvement**: `total_pnl_lp - total_pnl_baseline` for each threshold.

### Current example results (production, all trades, cooldown_timer <= 3300)

These examples are *snapshots* from the live production DB and will change as more data arrives; they are here to illustrate the method:

- **Monitor 10023 (BTC MC, `mon_0001_10023`)**
  - Cycles: 359 (filtered by `cooldown_timer <= 3300`).
  - Baseline (no LP): total PnL ≈ 2595.13.
  - LP sweep thresholds 1–20:
    - Best threshold: **2**, total PnL ≈ **2826.09** (improvement vs baseline).

- **Monitor 10022 (`mon_0001_10022`)**
  - Cycles: 183 (filtered by `cooldown_timer <= 3300`).
  - Baseline (no LP): total PnL ≈ -89.64.
  - LP sweep thresholds 1–20:
    - Best threshold in this run: **8**, total PnL ≈ **-27.62** (less negative than baseline).

### Implementation hook

Implementation script: `scripts/backtests/lp_optimization_mc.py` (to be added).

Suggested CLI:

```bash
PYTHONPATH=. python3 scripts/backtests/lp_optimization_mc.py \
  --monitor-id 10023 \
  --start-date 2026-02-01 \
  --end-date 2026-02-29 \
  --cooldown-max 3300 \
  --min-threshold 1 \
  --max-threshold 20
```

The analyst agent should:

- Prefer **production DB** unless explicitly told otherwise.
- Use this spec as the source of truth for how cycles, wins/losses, LP state, and scaling are defined.
- Keep this document updated if the methodology changes (e.g. different scaling, additional filters, or multi‑monitor portfolio variants).

