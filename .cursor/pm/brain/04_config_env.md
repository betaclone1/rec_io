# Config and environment

## Env var naming (single pattern)

- **DB_*** — Preferred. backend/core/config/database.py reads DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT (defaults: localhost, rec_io_db, rec_io_user, rec_io_password, 5432).
- **REC_DB_*** — Fallback. If DB_* is unset, database.py uses REC_DB_HOST, REC_DB_NAME, REC_DB_USER, REC_DB_PASS, REC_DB_PORT. So .env can use either convention; no manual mapping in scripts.
- **Do not use POSTGRES_*** for new code.** Legacy POSTGRES_* env vars are deprecated; all DB access should go through backend.core.config.database (get_postgresql_connection or get_database_config).

## Files

- **.env** — Project root; gitignored. Primary env for local/dev.
- **.env.example** — Template; REC_DB_*, REC_MAIN_PORT, REC_*, REC_CREDENTIALS_PATH, REC_ACCOUNT_MODE, etc.
- **.env.postgresql** — Optional override for PostgreSQL (referenced in scripts/install_deploy/final_testing_and_deployment.sh).

## Config managers

- **ConfigManager** (backend/core/config/config_manager.py): Loads config.default.json, config.local.json; _apply_env_overrides sets database from REC_DB_*. Dot-notation get/set.
- **UnifiedConfigManager** (backend/core/unified_config.py): System host, DB, venv path; used by main and scripts (load_unified_config.sh calls scripts/config/test_unified_config.py to export REC_*).

## Bash

- scripts/load_unified_config.sh — Sources test_unified_config.py output; exports REC_PROJECT_ROOT, REC_DB_*, REC_VENV_PATH, etc. Used by MASTER_RESTART.sh.

## Python DB connection pattern for scripts

Use the central module; it prefers DB_* and falls back to REC_DB_*:

```python
# Optional: load .env so DB_* or REC_DB_* are set
try:
    from dotenv import load_dotenv
    load_dotenv('.env')
except ImportError:
    pass
from backend.core.config.database import get_postgresql_connection  # or get_database_config
conn = get_postgresql_connection()
```
