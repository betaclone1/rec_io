# Long-term initiatives

Backlog items that span the codebase or have no active owner plan yet. For executable task work, prefer a plan in `.cursor/plans/` with **Status** and steps.

## Multi-user readiness

- **Parameterize user id (replace hardcoded `0001`).** Sweep the entire system (backend, scripts, SQL assumptions, supervisor naming, `mon_0001_*` monitor keys, `users.trades_0001` / `active_trades` paths, notifications, tests) and replace literals **`0001`** with the **current user id** from configuration or authenticated context, so a second production user is not a string-replace accident. Treat as a deliberate migration (schema, migrations, and backwards compatibility as needed), not a one-off find-replace.

## Historical cycle data (possible commercial warehouse)

- **BTC 15m cycle packages → integrity-first warehouse (maybe sellable).** Capture/packager bones exist; long-term productization notes and checklist live in [HISTORICAL_CYCLE_DATA_PRODUCT.md](HISTORICAL_CYCLE_DATA_PRODUCT.md) and plan [historical-cycle-data-product.md](../.cursor/plans/historical-cycle-data-product.md). Gate on venue ToS before any external distribution work.
