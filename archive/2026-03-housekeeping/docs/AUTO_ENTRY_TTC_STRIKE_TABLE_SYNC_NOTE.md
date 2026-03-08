# Auto-entry TTC: strike table vs unified_ttc (dev/prod sync)

**Audience:** Dev agent. Codebases should be synced; this is not working the same on production as on dev.

**Date:** 2026-03-04

---

## Issue

Per the **2026-03-03** changelog (strike table alignment), all TTC values are supposed to come **directly from the strike tables** (`ttc_hourly` / `ttc_15m`). The changelog states:

> Strike table generator, main.py, active_trade_supervisor, **and auto_entry_supervisor** read/write the correct columns per market.

On production, **auto_entry_supervisor** is the only component that still does **not** read TTC from the strike tables for status/ACTIVE-INACTIVE logic.

---

## Current behavior (auto_entry_supervisor)

- **`get_current_ttc()`** (lines ~1685–1704) calls the **main app HTTP endpoint**  
  `http://localhost:{port}/api/unified_ttc/{symbol}?market={market}`  
  with a 2s timeout and uses `data.get("ttc_seconds", 0)`.
- All `determine_auto_entry_status_*` functions and any logic that needs “current TTC” for the time window use this function. So **auto_trade_status** (ACTIVE/INACTIVE) is driven by the unified_ttc API, not by a direct strike-table read.
- **`get_master_strike_table_data()`** correctly reads from the strike tables and uses `ttc_hourly` / `ttc_15m` (and probability columns) for watchlist/strike data. Only the TTC-used-for-status path still goes through unified_ttc.

---

## Expected behavior (to match changelog and dev)

- **All TTC** used by auto_entry_supervisor (including for ACTIVE/INACTIVE status) should come **directly from the strike tables**, same as:
  - **active_trade_supervisor**: `get_unified_ttc_seconds()` reads from `live_data.{strike_table}` using `ttc_15m` or `ttc_hourly` (no HTTP, no unified_ttc).
  - **main.py**: `/api/unified_ttc/` reads from strike tables; that endpoint can remain for other callers, but auto_entry_supervisor should not depend on it for TTC.

---

## Action for dev agent

1. Change **`get_current_ttc()`** in `backend/auto_entry_supervisor.py` to read TTC from the strike table (PostgreSQL) for the monitor’s symbol+market, using `ttc_hourly` or `ttc_15m` as appropriate—same pattern as `get_master_strike_table_data()` or as `get_unified_ttc_seconds()` in `active_trade_supervisor.py`.
2. Remove the dependency on the main app’s `/api/unified_ttc/` for this code path so that:
   - TTC is consistent with the 2026-03-03 strike table alignment.
   - No HTTP/timeout to main app can cause spurious “TTC outside window: 0s” and monitors flipping to INACTIVE.
3. Sync and verify behavior on dev and production so both codebases match and status logic uses strike tables only for TTC.

---

## References

- Changelog: `docs/changelog/MASTER_CHANGELOG.md` — 2026-03-03 entry.
- ATS pattern: `backend/active_trade_supervisor.py` — `get_unified_ttc_seconds()` (reads `live_data.{table}`, column `ttc_15m` or `ttc_hourly`).
- AES strike read: `backend/auto_entry_supervisor.py` — `get_master_strike_table_data()` (already uses correct columns; only `get_current_ttc()` still uses unified_ttc).
