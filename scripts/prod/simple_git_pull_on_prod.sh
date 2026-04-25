#!/usr/bin/env bash
# Fast-forward prod main to match origin (no snapshot, no restart). See .cursor/skills/simple-pull/SKILL.md

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/rec_prod_ssh.sh" 'cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main'
