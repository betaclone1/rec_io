# Scripts

Top-level scripts (restart and config loader only):

- **MASTER_RESTART.sh** — Full system restart; sources `load_unified_config.sh`, runs `config/generate_unified_supervisor_config.py`.
- **load_unified_config.sh** — Exports REC_* from `config/test_unified_config.py`. Used by MASTER_RESTART.
- **restart** — Small wrapper for restart.

Subfolders:

| Folder | Contents |
|--------|----------|
| **[config/](config/)** | `generate_unified_supervisor_config.py`, `test_unified_config.py` |
| **[db/](db/)** | Migration runner, drift check, schema update, audit, backfills, compare. See `db/README.md`. |
| **[backup/](backup/)** | `package_user_data.sh`, package_user_data_fast, essential/minimal/quick backup, test_backup |
| **[manage/](manage/)** | `manage_monitors_list.sh`, `manage_master_users.sh`, `user_registration_system.sh`, `test_monitors_list_table.py` |
| **[diagnostics/](diagnostics/)** | `check_kalshi_account_endpoints.py`, `view_installation_logs.py`, `remove_legacy_credentials.sh` |
| **[install_deploy/](install_deploy/)** | Install and deploy: collaborator_setup, first_boot_sanitize, simple_deploy, git_update_system, install_auto_startup_service, etc. |
| **[migrations/](migrations/)** | Reversible migration SQL (`.up.sql` / `.down.sql`). Runner: `db/run_migration.py`. |
