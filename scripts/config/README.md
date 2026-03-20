# Config scripts

Unified config and supervisor config generation. Used by MASTER_RESTART and load_unified_config.

- **generate_unified_supervisor_config.py** — Generates `backend/supervisord.conf` from unified config and port manifest. Called by MASTER_RESTART and monitor_manager.
- **test_unified_config.py** — Outputs unified config as JSON. Used by `load_unified_config.sh` to export REC_* env vars.

Run from project root. MASTER_RESTART and load_unified_config reference these via `scripts/config/`.
