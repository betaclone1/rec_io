# Archive index: 2026-03 housekeeping

**Date:** 2026-03-07  
**Purpose:** Aggressive cleanup — move clutter out of active tree to reach professional hygiene. Nothing deleted; restore by moving back or copying from this archive. System functionality unchanged: runbooks, schema reference, changelog, and deploy docs remain in `docs/`.

---

## Contents

### backend/core/config/
- **MASTER_PORT_MANIFEST.json.corrupted_*** (83 files) — Timestamped backup files. Only current `MASTER_PORT_MANIFEST.json` remains in active config.

### scripts/
- **START_SERVICES_DIRECT.sh**, **auto_add_files.sh** — Unreferenced or superseded by MASTER_RESTART.
- **validate_user_0001_migration.py** — One-off validation; migration long done.
- **backfill_trades_bankroll.py**, **backfill_trades_bankroll_corrected.py**, **backfill_trades_bankroll_final.py**, **backfill_trades_bankroll_portfolio_only.py**, **backfill_trades_bankroll_v2.py**, **backfill_trades_bankroll_portfolio_final.py**, **backfill_trades_ret_pct.py**, **backfill_today_ret_pct.py** — Superseded by backfill_trades_volatility_movement / account_history_vendor_rail or one-time use.
- **backfill_movement_test_table.py** — One-off test table backfill.
- **btc_strike_breach_analysis.py**, **strike_breach_analysis.py**, **strike_breach_edge_analysis.py** — One-off analyses.
- **inspect_simulated_trades_btc_2pm.py** — One-off inspect.
- **rename_kalshi_market_tables_to_hourly.py**, **rename_strike_tables_to_hourly.py** — One-off renames; done.
- **repopulate_trades_from_old.py** — One-off repopulate.
- **add_dashboard_order_column.py**, **add_live_paper_columns.py**, **add_movement_to_main_price_tables.py**, **add_trade_history_preferences_columns.py**, **add_win_streak_threshold_column.py** — One-off schema/migration scripts.
- **fix_position_to_100.py**, **rollback_position_update.py**, **update_position_to_100.py**, **update_specific_trades_position.py**, **fix_manual_trades_ret_pct.py**, **fix_pnl_calculation.py**, **fix_user_0001_tables.sql** — One-off position/fix scripts.
- **analyze_movement_percentile.py**, **manual_prev_day_avg_update.py** — One-off analytics/manual update.
- **check_account_balance.py**, **check_postgresql_logging.sh**, **ping_kalshi_v1_account_history.py** — One-off diagnostics.
- **run_multiplier_migration.sh**, **update_applications_for_postgresql.sh** — One-time migrations.
- **add_fp_columns_fixed_point_migration.sql**, **alter_fp_columns_to_numeric.sql**, **setup_installer_user.sql**, **update_multiplier_column.sql** — One-time SQL.
- **README_db_schema_migration.md**, **README_user_notifications.md**, **README_kalshi_credentials.md** — Script READMEs for one-off or archived flows.

### docs/
- **127+ top-level .md files** — One-off reports, audits, summaries, proposals, diagnoses, and legacy guides. Kept in `docs/`: README, MASTER_DB_SCHEMA_REFERENCE, PRODUCTION_SYNC_CHECKLIST, PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER, VERIFY_COMMAND, MONITORS_LIST_INFRASTRUCTURE, PROJECT_HOUSEKEEPING_AUDIT_PLAN, DEPLOYMENT_GUIDE, AUTHENTICATION_GUIDE, QUICK_INSTALL_GUIDE, DIGITAL_OCEAN_DEPLOYMENT_GUIDE, SYSTEM_DATA_PACKAGING, INSTALLATION_PACKAGE_SUMMARY, AUTOMATIC_MAINTENANCE_DEPLOYMENT_PROTECTION, MASTER_DATABASE_REGISTRATION_GUIDE, and **changelog/**.
- **TODO_changelog_backlog.md** — Former `docs/changelog/TODO.md` content (archived when task tracking moved to `.cursor/plans/`). Historical backlog only; current tasks live in plans.
- **VER3_ONBOARDING_DOCUMENTS/** — Full v2 snapshot (Jan 2025); reference only.
- **archive_legacy/** — Former `docs/archive/` (deprecated services, old migration docs, etc.).

### root/
- **COLLABORATOR_DEPLOYMENT_GUIDE.md**, **DASHBOARD_MOBILE_AUDIT.md**, **DATABASE_CHANGES_LOG.md**, **INSTALL.md**, **KALSHI_DEMO_README.md**, **POSTGRESQL_FAILURE_DIAGNOSIS_20260214.md**, **PROJECT_STRUCTURE.md**
- **check_cron_status.sh**, **db_access.sh**, **install_production_cron.sh**
- **add_cooldown_timer_window_migration.sql**, **add_max_differential_migration.sql**, **add_momentum_30s_avg_migration.sql**, **local_trades_0001_dump.sql**, **prod_trades_0001_backup_20251108.sql**, **update_position_to_100.sql**, **xrp_tables_dump_20251022_132634.sql** — One-off dumps/migrations. Root kept: README.md, AGENTS.md, .gitignore, install.sh.

### reports/
- **reports/** (entire directory) — One-off audit and diagnostic reports (SYSTEM_AUDIT_COMPLETE_*, etc.) and reports/archive/.

---

## Active tree after cleanup

- **docs/** — 15 kept .md + changelog/; README is a short index.
- **Root** — README.md, AGENTS.md, .gitignore, install.sh (+ any other essential config).
- **scripts/** — Active and referenced scripts only; one-offs and archive candidates moved to archive/2026-03-housekeeping/scripts/ (see INDEX above).
- **backend/** — Unchanged.
