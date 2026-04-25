#!/usr/bin/env bash
# Run a single remote command on production as root via SSH.
#
# Usage (from repo root):
#   ./scripts/prod/rec_prod_ssh.sh 'cd /opt/rec_io_server && git status'
#
# Host: REC_PROD_SSH_HOST if set, else canonical IPv4 from docs/PRODUCTION_HOST.md
#
# Bash pitfall (automation/agents): do NOT write
#   REC_PROD_SSH_HOST=x.y.z ssh root@$REC_PROD_SSH_HOST '...'
# because $REC_PROD_SSH_HOST is expanded before the assignment applies, so the
# destination becomes root@ and SSH fails. Export first, or use this script.

set -euo pipefail

DEFAULT_PROD_SSH_HOST="165.22.13.146"
HOST="${REC_PROD_SSH_HOST:-$DEFAULT_PROD_SSH_HOST}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 'remote command (one ssh argument)'" >&2
  exit 2
fi

exec ssh \
  -o ConnectTimeout=30 \
  -o StrictHostKeyChecking=accept-new \
  "root@${HOST}" "$@"
