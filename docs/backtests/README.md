## Backtest methodologies

This folder defines **reusable backtest methods** that analysts and agents can run directly against the **production database** (default) or a local clone.

- **Scope**: trade history in `users.trades_0001` / `users.trades_simulated_0001` plus any related tables (e.g. `monitor_list_*`, strike tables, price streams).
- **Environment default**: production DB at `137.184.224.94` via `get_postgresql_connection()` / standard DB env vars, unless the caller explicitly asks for local/non‑prod.
- **Paper vs live**: unless a method states otherwise, **paper and live trades are both included**.
- **Safety**: methods are **read‑only** (SELECTs and aggregations). Any proposal to change strategies, thresholds, or schema must go through the normal planning + migration process.

Each method gets:

- A dedicated spec in this directory (e.g. `LP_OPTIMIZATION_MC.md`).
- A matching implementation script under `scripts/backtests/` with the same name pattern (e.g. `lp_optimization_mc.py`).

When asking the analyst agent to run a backtest, describe:

- **Method**: e.g. “LP optimization MC”, “LP optimization HTC”, “cooldown impact study”.
- **Inputs**: monitor ids, date range, filters (e.g. `cooldown_timer <= 3300`), sizing assumptions.
- **Outputs**: what you want back (e.g. “PNL by threshold”, “best threshold and its improvement vs baseline”, “top 20 worst cycles”).

