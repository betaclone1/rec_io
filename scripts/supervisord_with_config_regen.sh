#!/usr/bin/env bash
# Regenerate backend/supervisord.conf from the database (active system.master_users),
# then exec supervisord. Use this for OS boot / systemd when you do not run MASTER_RESTART.sh.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=load_unified_config.sh
source "$SCRIPT_DIR/load_unified_config.sh"

SUPERVISOR_CONFIG="${REC_PROJECT_ROOT}/backend/supervisord.conf"
GEN="${REC_PROJECT_ROOT}/scripts/config/generate_unified_supervisor_config.py"

echo "[supervisord_with_config_regen] Writing ${SUPERVISOR_CONFIG} from DB..."
"$REC_PYTHON_EXECUTABLE" "$GEN"

rm -rf "${REC_PROJECT_ROOT}/backend/__pycache__" 2>/dev/null || true

exec supervisord -c "$SUPERVISOR_CONFIG" "$@"
