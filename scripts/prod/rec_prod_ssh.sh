#!/usr/bin/env bash
# Run a single remote command on production via SSH.
#
# Usage (from repo root):
#   ./scripts/prod/rec_prod_ssh.sh 'cd /opt/rec_io_server && git status'
#
# Host: REC_PROD_SSH_HOST if set, else canonical IPv4 from docs/PRODUCTION_HOST.md
# User: REC_PROD_SSH_USER if set, else root (see docs/CURSOR_CLOUD_PROD_SSH_ACCESS_PROPOSAL.md)
#
# Optional: REC_PROD_SSH_BATCH_MODE=1 adds ssh -o BatchMode=yes (fail fast if no key; good for CI / Cursor Cloud).
#
# Bash pitfall (automation/agents): do NOT write
#   REC_PROD_SSH_HOST=x.y.z ssh root@$REC_PROD_SSH_HOST '...'
# because $REC_PROD_SSH_HOST is expanded before the assignment applies, so the
# destination becomes root@ and SSH fails. Export first, or use this script.

set -euo pipefail

DEFAULT_PROD_SSH_HOST="165.22.13.146"
DEFAULT_PROD_SSH_USER="root"
HOST="${REC_PROD_SSH_HOST:-$DEFAULT_PROD_SSH_HOST}"
USER="${REC_PROD_SSH_USER:-$DEFAULT_PROD_SSH_USER}"

if [[ ! "$USER" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  echo "rec_prod_ssh: invalid REC_PROD_SSH_USER (use alphanumerics, ., _, - only): ${USER}" >&2
  exit 2
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 'remote command (one ssh argument)'" >&2
  exit 2
fi

SSH_OPTS=( -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new )
case "${REC_PROD_SSH_BATCH_MODE:-}" in
  1|true|TRUE|yes|YES) SSH_OPTS+=( -o BatchMode=yes ) ;;
esac

exec ssh "${SSH_OPTS[@]}" "${USER}@${HOST}" "$@"
