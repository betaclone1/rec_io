# DB maintenance system audit — findings (task 3)

**Date:** 2026-03-07  
**Scope:** Reference doc vs `backend/core/config/database.py` vs local DB. No remote (prod) execution.

---

## 1. Single source of truth

- **Source of truth:** `docs/MASTER_DB_SCHEMA_REFERENCE.md` is the canonical schema. It reflects the intended shape (types, nullability, defaults) for all tables.
- **database.py:** `init_database()` is for bootstrap and new environments. It creates tables and adds missing columns; its CREATE TABLE definitions use types that may differ from the reference (e.g. VARCHAR vs TEXT, DECIMAL vs REAL, DATE vs TEXT) for historical reasons. Local DB may have been altered over time to match the reference (e.g. types migrated to TEXT/REAL).
- **Alignment rule:** New migrations and reference doc updates define the target state. When changing the reference, add a reversible migration for existing DBs and update `database.py` CREATE TABLE for new envs where safe (non-breaking).

---

## 2. Audit output summary (scripts/audit_db_schema.py)

### Doc vs local DB

- **Tables matching exactly:** Most tables in both doc and DB match.
- **Doc vs DB discrepancies (18 tables):**
  - **users.trades_0001:** Type mismatch `hour_idx`: DB=SMALLINT, DOC=INTEGER (doc actually says `smallint(16)`; normalizer may show INTEGER; functionally equivalent).
  - **users.trades_simulated_0001:** Parser reports “Columns in DB only” for all columns — the reference doc uses “#### Columns (from DB)” with a different table format (`| Column | Type |`) that the audit script does not parse. So the doc has the same logical columns; the audit cannot compare. Consider adding a standard “#### Columns” block for trades_simulated_0001 to the reference for consistent auditing.
  - **live_data.strike_table_15m_btc/eth:** Doc may be missing columns or use different section format; DB has full column set.
  - **live_data.strike_table_hourly_ndx/spx:** Doc still lists legacy `probability`, `ttc_seconds`; DB has `probability_hourly`, `probability_15m`, `ttc_hourly`, `ttc_15m`.
  - **system.installation_access_log:** `total_rows_cloned` DB=BIGINT, DOC=INTEGER.
  - **users.dashboard_preferences_0001:** `portfolio_view` DB=VARCHAR(10), DOC=TEXT.
  - **users.monitor_cycle_performance_0001_*:** `weekly_cycle` DB=SMALLINT, DOC=INTEGER.
  - **users.monitor_list_0001:** `current_weekly_cycle` DB=SMALLINT, DOC=INTEGER.
  - **users.strategy_list_0001:** `min_probability` DB=INTEGER, DOC=NUMERIC(5,2); “Columns in DB only” includes `max_probability` (likely doc omission).
  - **users.trade_history_preferences_0001:** `last_search_timestamp` DB=BIGINT, DOC=INTEGER.
  - **users.user_info_0001:** `kalshi_user_id` DB=TEXT, DOC=VARCHAR(50) (compatible).

### database.py vs local DB

- **Tables matching exactly:** users.account_history_0001, users.active_trades_0001, users.trade_preferences_0001, users.trades_simulated_0001, plus several live_data price/change tables.
- **Critical table users.trades_0001:** Many type differences. DB (and reference doc) use TEXT, REAL, etc.; database.py CREATE TABLE uses VARCHAR, DECIMAL, DATE, TIME. So the live DB was migrated to the reference shape; database.py was not updated. Risk: new envs created by init_database() would get the old types; then update_db_schema_to_reference or manual ALTERs would add columns but not necessarily fix types. Recommendation: do not change database.py CREATE TABLE for trades_0001 to match reference in one shot (could break existing logic). Prefer reversible migrations to align types on existing DBs and, in a follow-up, update database.py CREATE TABLE to match reference for new installs.
- **users.monitor_list_0001:** database.py defines a subset of columns; DB has many more (strategy/auto-entry columns). Reference doc and DB are the source of truth; database.py is incomplete.
- **users.strategy_list_0001:** database.py has a parsing quirk (“--” as column); `min_probability` type differs (INTEGER vs NUMERIC(5,2)).
- **historical_data.*_price_history:** database.py has older types (e.g. DECIMAL(15,2), id, created_at); DB has NUMERIC(20,8), timestamp as PK, plus volatility/movement columns.
- **system.health_status:** database.py has generic columns; DB has expanded health-check columns (cpu_percent, database_status, etc.).
- **live_data.live_symbol_status:** Quoted column `"timestamp"` in database.py vs `timestamp` in DB (same column, different quoting).

---

## 3. Critical tables (from 03_db_schema_brain)

| Table | Reference vs DB | database.py vs DB |
|-------|-----------------|-------------------|
| users.trades_0001 | hour_idx type only (minor) | Many type diffs (VARCHAR/DECIMAL/DATE/TIME in py vs TEXT/REAL in DB/doc) |
| users.trades_simulated_0001 | Parser misses doc columns (format) | Match |
| users.monitor_list_0001 | current_weekly_cycle SMALLINT vs INTEGER | database.py missing many columns |
| users.strategy_list_0001 | min_probability, max_probability | Type/parse quirks |
| live_data.strike_table_* | 15m doc format; hourly ndx/spx legacy names | — |
| live_data.live_price_log_1s_* | — | DB has extra momentum/volatility columns |
| live_data.live_symbol_status | — | timestamp quoting |

---

## 4. Actions taken (this audit)

- Ran `scripts/audit_db_schema.py` (local only; no prod).
- Wrote this findings doc.
- Single source of truth confirmed: reference doc; database.py for bootstrap; migrations for changes.
- Added `scripts/db/check_db_schema_drift.py` to fail CI if database.py drifts from reference for critical tables.
- Documented in `scripts/update_db_schema_to_reference.py` and README that type/default fixes are out of scope; use reversible migrations or manual ALTERs.
- Prod schema fix plan added to `docs/changelog/TODO.md` task 3 Milestones (plan only; no execution).

---

## 5. Deferred / recommendations

- **Prod (137.184.224.94):** No DDL or migrations run. Plan is in TODO.md; execute only during a maintenance window with backups. Prefer reversible migrations in `scripts/migrations/`.
- **database.py CREATE TABLE for trades_0001:** Aligning it to the reference (TEXT, REAL, etc.) in one go could affect any code that assumes VARCHAR/DECIMAL. Prefer: (1) reversible migrations to alter existing DBs to match reference; (2) then update database.py CREATE TABLE so new envs match.
- **Reference doc:** Add a standard “#### Columns” table for `users.trades_simulated_0001` (same as trades_0001 with nullable buy_price/position/fees/bankroll/price_spread/sell_price) so the audit script can compare. Update strike_table hourly ndx/spx to use probability_hourly/ttc_hourly and 15m columns instead of legacy names.
- **update_db_schema_to_reference.py:** Uses hardcoded DB_CONFIG; should use `get_postgresql_connection()` from `backend.core.config.database` so it respects DB_* / REC_DB_* env.
