# Momentum Contain: BTC/ETH Entry Criteria + Strike Selection (Temporary)

## What this change is about
Momentum Contain is a Momentum-spike auto-entry strategy. When we modified strike selection for BTC, we ran into an important issue:
- Changing the selected strike spacing can shrink or expand the resulting “bracket width”, which in turn can break downstream probability / probability-diff logic.

To reduce risk, we temporarily split BTC vs ETH logic so we can:
1. Move toward symbol-specific handling.
2. Keep ETH behavior stable while validating BTC-specific strike selection.

## Current state (as of this commit)
### Entry criteria (all symbols)
Momentum Contain entry criteria are shared across symbols.

### Strike selection (all symbols)
Strike selection uses a unified **minimum-width, centered bracket** rule for all symbols:

- Minimum bracket width = **0.35%** of spot (hardcoded for now).
- Among pairs of **available** strikes with **YES < price < NO** and `NO − YES ≥` that minimum, choose the pair whose width is **closest to the minimum** (smallest excess width).
- **Tie-break:** keep spot **as close to the bracket midpoint** as possible; then prefer deterministic lower YES strike.

## Entry criteria gate (shared logic)
Inside `backend/auto_entry_supervisor.py` / `check_auto_entry_conditions_momentum_contain()`, after spike + TTC checks:
1. **TTC window**: only proceed when `min_time <= current_ttc <= max_time`.
2. **Spike alert gate**: require `spike_alert_active == True`.
3. **Cooldown timer window (optional)**:
   - If `min_cooldown_timer` and/or `max_cooldown_timer` are set in settings, we fetch `cooldown_timer` from `users.monitor_list_0001` for this `MONITOR_ID`.
   - Compute `time_since_spike` from `spike_alert_cooldown_minutes` and the DB cooldown value.
   - Skip entry when `time_since_spike` is outside the min/max bounds.
4. **Already entered guard**: do nothing if `momentum_contain_trades_entered` is already true.
5. **Volume gates** (both legs):
   - Require `volume_above >= min_volume`
   - Require `volume_below >= min_volume`
6. **Momentum gates** (both metrics must be below threshold):
   - `abs(momentum_30s_avg) < spike_alert_cooldown_threshold`
   - `abs(momentum_percentile) < spike_alert_cooldown_threshold`
7. **Ask price gates** (both legs):
   - For the **NO** leg at the strike above: `min_ask <= no_ask_price_above <= max_ask`
   - For the **YES** leg at the strike below: `min_ask <= yes_ask_price_below <= max_ask`

## Trade sides (flipped vs Breakout)
Momentum Contain opens two trades with flipped sides relative to Momentum Breakout:
- **NO** at the strike immediately above the money line (`strike_above_data`)
- **YES** at the strike immediately below the money line (`strike_below_data`)

## Strike selection methodology (what we actively do now)
### Minimum width + centering (active)
1. `min_bracket_width = current_price × 0.0035` (0.35% of spot; hardcoded for now).
2. Consider every pair `(YES_strike, NO_strike)` from `strike_table_data["strikes"]` with `YES_strike < current_price < NO_strike`.
3. Keep pairs where `NO_strike − YES_strike ≥ min_bracket_width`.
4. Rank by:
   - smallest **width excess** `(NO − YES) − min_bracket_width`;
   - then smallest distance from `current_price` to the bracket midpoint `(YES + NO) / 2`;
   - then lower `YES_strike` for a deterministic tie-break.

## TODO (planned next)
1. Make `min_bracket_width_pct` configurable (and optionally symbol-specific).

