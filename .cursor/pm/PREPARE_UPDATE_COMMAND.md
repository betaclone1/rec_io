# /prepare-update command

**Defined in:** `.cursor/commands/prepare-update.md` (slash command) and `.cursor/skills/prepare-update/SKILL.md` (skill). Integrated with @updater and @db.

When the user invokes **/prepare-update**, they are preparing to push a commit. The agent runs the full pre-push workflow and reports whether the update is ready for publishing (with a suggested commit message) or what needs attention.

## Workflow summary

1. **Prod snapshot (BLOCKING)** — Call MCP **snapshot-droplet** (server **project-0-3_0-digitalocean-droplets**, ID 513735057, name **rec-io-prod-pre-update-YYYY-MM-DD**). If the MCP is not available or the call fails: **STOP.** Do not run steps 2–6. Report that prod snapshot is required and the workspace must be the project root so .cursor/mcp.json is loaded. Only after snapshot created, proceed.
2. **Verify** — Health, supervisor, logs (same as /verify). Only current errors (after process start) count. Non–All good status is reported but does not block.
3. **Server-agnostic audit** — Scan changed/staged files for localhost, absolute paths, undocumented env differences; flag for review.
4. **Changelog and DB** — @updater prepare update steps: MASTER_CHANGELOG entry, related docs, schema ref and database.py alignment. DB changes must be in docs and changelog.
5. **Other issues** — Note migrations, untracked files, TODOs as needed.
6. **Readiness** — If clear: output "Update ready for publishing" and suggested commit message. **Commit message:** Short title + bullet list (Generate Commit Message style); each bullet one change area; mention every substantive change; no file counts. If blocking issues: list them and do not mark ready.

See .cursor/rules/updater.mdc for changelog/DB steps; .cursor/commands/verify.md for verify steps.