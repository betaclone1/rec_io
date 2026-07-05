#!/usr/bin/env bash
# Fast-forward prod main to match origin (no snapshot, no restart). See .cursor/skills/simple-pull/SKILL.md

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/rec_prod_ssh.sh" 'cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main && COMMIT=$(git rev-parse --short HEAD) && (python3 scripts/ops/log_system_event.py --category DEPLOY --severity info --message "Production git pull to ${COMMIT}" --source simple_git_pull --detail-ref supervisord 2>/dev/null || .venv/bin/python scripts/ops/log_system_event.py --category DEPLOY --severity info --message "Production git pull to ${COMMIT}" --source simple_git_pull --detail-ref supervisord 2>/dev/null || true)'
