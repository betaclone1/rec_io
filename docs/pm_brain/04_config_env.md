# Config and environment

## Env var naming

- **DB_*** — Used by backend/core/config/database.py: DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT. Defaults: localhost, rec_io_db, rec_io_user, rec_io_password, 5432.
- **REC_DB_*** — .env.example and ConfigManager/UnifiedConfigManager: REC_DB_HOST, REC_DB_PORT, REC_DB_NAME, REC_DB_USER, REC_DB_PASS, REC_DB_SSLMODE. config_manager applies these to config['database'].
- **POSTGRES_*** — Used in many scripts and some backend modules: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD. Defaults often localhost, 5432, rec_io_db, rec_io_user, '' or rec_io_password.
- **Mapping:** Scripts that use database.py should load .env and set DB_* from REC_DB_* when REC_* is set (e.g. scripts/compare_simulated_table_schema.py, scripts/audit_db_schema.py).

## Files

- **.env** — Project root; gitignored. Primary env for local/dev.
- **.env.example** — Template; REC_DB_*, REC_MAIN_PORT, REC_*, REC_CREDENTIALS_PATH, REC_ACCOUNT_MODE, etc.
- **.env.postgresql** — Optional override for PostgreSQL (referenced in scripts/final_testing_and_deployment.sh).

## Config managers

- **ConfigManager** (backend/core/config/config_manager.py): Loads config.default.json, config.local.json; _apply_env_overrides sets database from REC_DB_*. Dot-notation get/set.
- **UnifiedConfigManager** (backend/core/unified_config.py): System host, DB, venv path; used by main and scripts (load_unified_config.sh calls scripts/test_unified_config.py to export REC_*).

## Bash

- scripts/load_unified_config.sh — Sources test_unified_config.py output; exports REC_PROJECT_ROOT, REC_DB_*, REC_VENV_PATH, etc. Used by MASTER_RESTART.sh.

## Python DB connection pattern for scripts

```python
import os
try:
    from dotenv import load_dotenv
    load_dotenv('.env')
    load_dotenv('.env.postgresql')
except ImportError:
    pass
for rec_k, db_k in [('REC_DB_HOST', 'DB_HOST'), ('REC_DB_PORT', 'DB_PORT'), ('REC_DB_NAME', 'DB_NAME'), ('REC_DB_USER', 'DB_USER'), ('REC_DB_PASS', 'DB_PASSWORD')]:
    if os.getenv(rec_k) and not os.getenv(db_k):
        os.environ[db_k] = os.getenv(rec_k)
from backend.core.config.database import get_postgresql_connection  # or get_database_config, test_database_connection
```
