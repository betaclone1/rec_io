# /prepare-update command

**Defined in:** `.cursor/commands/prepare-update.md` (slash command) and `.cursor/skills/prepare-update/SKILL.md` (skill). Integrated with @updater and @db.

When the user invokes **/prepare-update**, they are preparing to push a commit. The agent runs the full pre-push workflow and reports whether the update is ready for publishing (with a suggested commit message) or what needs attention.

## Workflow summary

1. **Prod snapshot (BLOCKING)** — Use the **project-owned snapshot script** as the primary, blocking path. From the project root, run `./scripts/do/snapshot_prod.sh rec-io-prod-pre-update-YYYY-MM-DD` (today’s date). This uses `DIGITALOCEAN_API_TOKEN` from `.env` and `doctl` to snapshot droplet **513735057** (or `DO_PROD_DROPLET_ID` if set). If the script fails (non‑zero exit): **STOP.** Do not run steps 2–6. Report that prod snapshot is required and explain what failed (e.g. missing token in `.env`, doctl not installed/configured). Only after the script reports that the snapshot action was submitted should the workflow proceed.

   - **Optional MCP snapshot (best‑effort):** If the DigitalOcean droplets MCP is available, the agent may also call `snapshot-droplet` (server **project-0-3_0-digitalocean-droplets**, ID 513735057, name **rec-io-prod-pre-update-YYYY-MM-DD**). Treat this as non‑blocking: MCP failures (server not present, HTTP 5xx, etc.) should be mentioned but must **not** block `/prepare-update` as long as the script-based snapshot succeeded. See `.cursor/pm/MCP_DIGITALOCEAN_TROUBLESHOOTING.md` for diagnosing recurring MCP issues.
2. **Verify** — Health, supervisor, logs (same as verify-local). Only current errors (after process start) count. Non–All good status is reported but does not block.
3. **Server-agnostic audit** — Scan changed/staged files for localhost, absolute paths, undocumented env differences; flag for review.
4. **Changelog and DB** — @updater prepare update steps: MASTER_CHANGELOG entry, related docs, schema ref and database.py alignment. DB changes must be in docs and changelog.
5. **Other issues** — Note migrations, untracked files, TODOs as needed.
6. **Readiness** — If clear: output "Update ready for publishing" and suggested commit message. **Commit message:** Short title + bullet list (Generate Commit Message style); each bullet one change area; mention every substantive change; no file counts. If blocking issues: list them and do not mark ready.

See .cursor/rules/updater.mdc for changelog/DB steps; .cursor/commands/verify-local.md and .cursor/pm/VERIFY_COMMAND.md for verify steps.