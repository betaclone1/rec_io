# DigitalOcean integration

DigitalOcean is rec.io's **main production server host and web domain host**. This doc covers how we integrate with DO: MCP, API, and priority use case (snapshots and backups).

**Agent:** **@digitalocean** — use for any DO-related work. See `.cursor/rules/digitalocean.mdc` and `AGENTS.md`. **Autonomous snapshots:** If the agent can't read `.env` when running the script, use the MCP path in `.cursor/pm/DO_AGENT_SNAPSHOT_FIX.md`.

---

## Priority: Snapshots and backups

**Goal:** See, create, modify, and delete **snapshots** and **backups**.

### Snapshots (on-demand)

- **Droplet snapshots:** Create via droplet action: `POST /v2/droplets/:id/actions` with body `{"type":"snapshot","name":"optional-name"}`. List/get/delete via **Images** API (snapshots are a type of image) or the Snapshots API where available.
- **Volume snapshots:** Block storage. Create: `POST /v2/volumes/:id/snapshots` (or equivalent); scope `block_storage_snapshot:create`. List: `GET /v2/snapshots?resource_type=volume`. Delete: `DELETE /v2/snapshots/:id`.
- **Unified snapshot list:** `GET /v2/snapshots` — returns all snapshots; optional `?resource_type=droplet` or `?resource_type=volume`. Response: `snapshots` array with id, name, created_at, resource_id, resource_type, regions, etc.
- **Rate limit:** One snapshot of a given volume per 10 minutes.
- **References:** https://docs.digitalocean.com/products/snapshots/reference/ , https://docs.digitalocean.com/reference/api/api-reference/#tag/Snapshots

### Backups (automatic)

- **Droplet backups:** Enabled per droplet (weekly or daily). When enabled, DO creates backup images automatically. Backup images appear as images with type `backup`. List via Images API: `GET /v2/images?type=backup` (or filter in list). Delete: `DELETE /v2/images/:id` (destroys the backup image).
- **Enable/disable:** Update droplet or use droplet action to enable/disable backups.
- **References:** https://docs.digitalocean.com/products/backups/reference/

### Ways to run snapshot/backup operations

1. **Official DigitalOcean MCP** (below) — if the MCP exposes snapshot/backup tools, use them from Cursor.
2. **doctl** — `doctl compute snapshot list`, `doctl compute snapshot get <id>`, `doctl compute snapshot delete <id>`; droplet actions for create. Requires `doctl auth init` with a token. Good for scripts and one-offs.
3. **REST API** — curl or Python `requests` with `Authorization: Bearer $DIGITALOCEAN_API_TOKEN` and `Content-Type: application/json`. Base: `https://api.digitalocean.com/v2`.
4. **Python pydo** — `pydo` client: `snapshots.list()`, `snapshots.get(id)`, `snapshots.delete(id)`. For droplet snapshot create, use droplet actions. Docs: https://docs.digitalocean.com/reference/pydo/

---

## Official DigitalOcean MCP server

DigitalOcean provides an MCP server that works with Cursor and other MCP clients.

- **Repo:** https://github.com/digitalocean/digitalocean-mcp  
- **Install:** No install; run via `npx`. Add to Cursor MCP config (e.g. `.cursor/mcp.json` or Cursor settings).

### Add to MCP config

In your MCP config (e.g. `.cursor/mcp.json`; do not commit the file if it contains secrets — it is in `.gitignore`), add:

```json
{
  "mcpServers": {
    "digitalocean": {
      "command": "npx",
      "args": ["-y", "@digitalocean/mcp"],
      "env": {
        "DIGITALOCEAN_API_TOKEN": "<<your_api_token>>"
      }
    }
  }
}
```

Replace `<<your_api_token>>` with a valid DO API token. Create tokens in DigitalOcean Control Panel → API → Tokens. Use a token with **read and write** scope for snapshots, images, droplets (or minimal scopes you need). **Never commit the token;** use env substitution or a local-only config.

### MCP capabilities

The official MCP focuses on **App Platform** (deploy apps, view logs, restart services). It may also expose other services (droplets, images, etc.). After adding the server, check which tools Cursor exposes (e.g. list MCP tools) to see if snapshot/backup/image operations are available. If they are not, use **doctl** or the **REST API / pydo** for snapshot and backup CRUD (see above).

### Requirements

- Node.js v18+ and npm (for `npx`).
- DigitalOcean API token with appropriate scopes.

### Snapshot in /prepare-update

**/prepare-update** creates the prod snapshot by calling the **snapshot-droplet** MCP tool (digitalocean-droplets). The MCP is configured in `.cursor/mcp.json` and must be loaded when the project is open. There is no script or API fallback: the MCP is the single path. **If the MCP is "unavailable":** Cursor didn’t load it or the remote connection failed. See **.cursor/pm/MCP_DIGITALOCEAN_TROUBLESHOOTING.md** (check MCP Logs, project vs global mcp.json, HTTP/1.0, auth header).

---

## doctl CLI (alternative or complement)

If you prefer not to use the MCP, or need snapshot/backup commands the MCP doesn’t provide:

- **Install:** https://docs.digitalocean.com/reference/doctl/how-to/install/
- **Auth:** `doctl auth init` and paste your API token.
- **Snapshots:** `doctl compute snapshot list`, `doctl compute snapshot get <id>`, `doctl compute snapshot delete <id>`.
- **Images (backups):** `doctl compute image list --public false` (includes backups and snapshots).
- **Droplet actions:** `doctl compute droplet action snapshot <droplet-id> --snapshot-name "name"` to create a droplet snapshot.

Use doctl in scripts or from the terminal; @digitalocean can guide exact commands.

---

## Credentials and security

- **API token:** Store in env (e.g. `DIGITALOCEAN_API_TOKEN`) or in a local config file that is not committed. Add `DIGITALOCEAN_API_TOKEN` to `.env.example` with a placeholder if we add DO to the app or scripts.
- **.cursor/mcp.json** is in `.gitignore`; if you store the token there for MCP, keep the file local only.
- **Scopes:** Use the minimum scopes needed (e.g. read/write for snapshots, images, droplets if you manage backups and snapshots).

---

## Persistent token setup (walkthrough)

One source of truth: project **`.env`** (gitignored). Use it for doctl and for loading in scripts; optionally copy into MCP config for Cursor.

### Step 1: Create or edit `.env`

From the project root:

```bash
# If .env doesn't exist, copy from example
cp .env.example .env

# Edit .env and add your token (no quotes needed)
# DIGITALOCEAN_API_TOKEN=dop_v1_xxxxxxxx...
```

Add one line (with your real token):

```
DIGITALOCEAN_API_TOKEN=dop_v1_your_actual_token_here
```

Save. **Never commit `.env`**; it is in `.gitignore`.

### Step 2: Use it with doctl

In any terminal where you want to use doctl:

```bash
cd /path/to/3_0
export $(grep -v '^#' .env | xargs)   # load all .env vars into this shell
doctl compute snapshot list
```

To make it automatic in this project, you can source .env before running doctl, or add a one-liner to your shell profile that only exports `DIGITALOCEAN_API_TOKEN` when in this repo (optional).

### Step 3 (optional): Use the same token in Cursor MCP

If you use the DigitalOcean MCP in Cursor, put the token in `.cursor/mcp.json` (gitignored) in the `env` block for the `digitalocean` server. You can copy the value from `.env`. That way Cursor and doctl both use the same token; rotate it in both places when you change it.

### Step 4: Verify

```bash
export $(grep -v '^#' .env | xargs)
doctl compute snapshot list
```

You should see your snapshots. After this, you don’t need to create a new token unless you revoke it or rotate for security.

---

## Production context

- **Production droplet:** 137.184.224.94 (see `.cursor/pm/brain/11_external_ecosystem.md`). Droplet ID **513735057** (used by `scripts/do/snapshot_prod.sh`). When creating or listing snapshots/backups, the production droplet is the primary target for backup-on-demand and backup management.
- **Governance:** Destructive or production-affecting actions (e.g. delete backup, resize droplet) require user/CEO approval. @digitalocean proposes and documents; user confirms before irreversible changes.

---

## Autonomous snapshot creation (no confirmation)

When you ask @digitalocean to create a snapshot of the prod server, the agent runs **`./scripts/do/snapshot_prod.sh`** from project root. The script:

- Loads `DIGITALOCEAN_API_TOKEN` from `.env`
- Snapshots droplet **513735057** (override with `DO_PROD_DROPLET_ID` if needed)
- Names the snapshot **rec-io-prod-YYYY-MM-DD** (or pass a name as the first argument)

**So the agent can do this without asking you each time.** Cursor's sandbox often blocks or redacts reads of `.env`, so when the agent runs the script the token may be empty even though it's in the file. Workaround: run `export DIGITALOCEAN_API_TOKEN=$(grep '^DIGITALOCEAN_API_TOKEN=' .env | cut -d= -f2-)` in your terminal before asking for a snapshot, or run the script yourself: `./scripts/do/snapshot_prod.sh`. If Cursor prompts for approval when the agent runs the script (e.g. because it uses network or reads `.env`), add the script to Cursor’s **command allowlist** so it runs autonomously:

- In Cursor: **Settings → Cursor Settings → Features → Agent** (or **Rules / Commands**), find the option for commands that don’t require approval, and add `scripts/do/snapshot_prod.sh` or the exact command the agent runs (e.g. `./scripts/do/snapshot_prod.sh`). Exact location may vary by Cursor version.
