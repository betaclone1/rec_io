# Backtest patterns

Repeatable backtest setups, data windows, assumptions, and how to re-run them. Build over time so patterns can be repeated and eventually automated.

## Convention

- Each pattern: name, objective, data source (tables/period), key params, command or script to run, and where results are stored or how to interpret them.
- When adding a new pattern, append below with a short header and date.

## Patterns

### HTC probability-cutoff sensitivity (2026-03-11)

**Intent:** See how PnL would change if we required a minimum probability at entry for Hourly HTC and 15m HTC trades. Compare hypothetical PnL at each cutoff to recorded PnL (no cutoff).

**Universe:** Main table only, test_filter excluded, live + paper. Strategies: `trade_strategy IN ('Hourly HTC', '15m HTC')`. Period: one calendar month (e.g. March 2026). Status: closed or expired, pnl not null.

**Parameters:** Cutoff range (e.g. 95% to 99%) and step (e.g. 0.5%). For each cutoff, sum pnl where `prob >= cutoff`; compute PnL gain vs recorded (hypothetical − recorded).

**Query pattern:** Same base WHERE as default trade assumptions plus `trade_strategy IN ('Hourly HTC', '15m HTC')`. Recorded = SUM(pnl), COUNT(*) with no prob filter. For each cutoff: same base AND `prob >= cutoff`; then diff = hypothetical_sum − recorded_sum. Present table: Cutoff %, PnL, Trades, PnL gain. Summation: one sentence on how much more or less we would have made at the best cutoff (or at a chosen cutoff).

**Reuse:** Change date range (e.g. `date >= 'YYYY-MM-01' AND date <= 'YYYY-MM-31'`) and re-run; optionally change cutoff range or step.

---

*Last updated: 2026-03-11.*
