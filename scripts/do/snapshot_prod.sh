#!/usr/bin/env bash
# Create a snapshot of the production droplet with a readable date-based name.
# Usage: from project root, ./scripts/do/snapshot_prod.sh [name]
#   If name is omitted, uses rec-io-prod-pre-update-YYYY-MM-DD.
# Token: DIGITALOCEAN_API_TOKEN from env or .env. Requires doctl.
# For /prepare-update the agent uses the snapshot-droplet MCP tool (see .cursor/mcp.json).
set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
# Default: active prod (rec-io-server-new-york-1, 165.22.13.146). Legacy: 513735057 was prior droplet (off).
PROD_DROPLET_ID="${DO_PROD_DROPLET_ID:-562337636}"

if [[ -z "$DIGITALOCEAN_API_TOKEN" ]]; then
  if [[ -f "$ENV_FILE" ]]; then
    DIGITALOCEAN_API_TOKEN=$(grep '^DIGITALOCEAN_API_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true)
  fi
fi
if [[ -z "$DIGITALOCEAN_API_TOKEN" ]]; then
  echo "DIGITALOCEAN_API_TOKEN not set. Set it in .env or export before running." >&2
  exit 1
fi

NAME="${1:-rec-io-prod-pre-update-$(date +%Y-%m-%d)}"
echo "Creating snapshot of droplet $PROD_DROPLET_ID with name: $NAME"
export DIGITALOCEAN_API_TOKEN
doctl compute droplet-action snapshot "$PROD_DROPLET_ID" --snapshot-name "$NAME"
echo "Snapshot action submitted. Name: $NAME"
