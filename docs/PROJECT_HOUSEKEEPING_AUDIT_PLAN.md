# Project housekeeping: audit and cleanup plan

**Goal:** Reduce sprawl by identifying what is actively used vs. litter, then **archiving** (not deleting) unused or obsolete items. No data or code is removed; it is moved to an archive with a clear index.

**Principle:** Archive only when we can confirm something is not in use. When in doubt, leave in place and mark for later review.

---

## 1. Define “in use”

Use these as the source of truth for *active* assets:

| Area | Source of truth |
|------|------------------|
| **Backend services** | `scripts/config/generate_unified_supervisor_config.py` — list of `backend/*.py` scripts it generates `[program:...]` for (main_app, trade_executor, trade_manager, kalshi_account_sync_ws, kalshi_market_watchdog, symbol_price_watchdog_finance, strike_table_generator, system_monitor, monitor_manager, cascading_failure_detector, auto_entry_supervisor, active_trade_supervisor). |
| **Scripts run at restart** | `scripts/MASTER_RESTART.sh` — what it invokes (e.g. generate_unified_supervisor_config, load_unified_config, supervisorctl). |
| **Scripts referenced in docs/agents** | AGENTS.md, `.cursor/rules/`, `.cursor/commands/`, `.cursor/` (VERIFY_COMMAND, SYSTEM_RESTART_COMMAND, etc.) — e.g. verify, system-restart, run_migration, check_db_schema_drift, backfill_account_history_vendor_rail. |
| **DB / migrations** | `scripts/db/run_migration.py`, `scripts/db/check_db_schema_drift.py`, `scripts/db/update_db_schema_to_reference.py`, migrations in `scripts/migrations/`. |
| **Install / deploy** | Scripts actually used in current install or deploy flows (e.g. install.sh, collaborator setup, backup scripts that are still recommended). |
| **Docs** | Docs linked from AGENTS.md, README, ORG_CHART, command docs in .cursor/, changelog, and PM brain index. |

Anything not reachable from these and not imported by active code is a **candidate** for archive (after manual check).

---

## 2. Audit scope (what we classify)

| Scope | What to do |
|-------|------------|
| **scripts/** | List every script. Mark: (a) in supervisor or MASTER_RESTART or explicitly referenced in agents/docs, (b) called by (a) or by backend, (c) one-off/backfill used occasionally, (d) archive candidate. `scripts/archive_old/` is already archived; confirm nothing in (a)–(c) lives only there. |
| **docs/** | List top-level and key subdirs. Mark: linked from README/AGENTS/brain/changelog = keep. Old snapshots (e.g. VER3_ONBOARDING_DOCUMENTS/v2_final_snapshot_*), one-off reports, duplicate/obsolete guides = archive candidates. |
| **backend/** | Entry points = supervisor list + anything imported by them. Under backend/util, backend/api: mark modules that are imported by entry points vs. orphaned. backend/data, backend/util/logs = generated/runtime; do not archive, just document. |
| **Root** | Root-level scripts and markdown (e.g. COLLABORATOR_DEPLOYMENT_GUIDE.md, DASHBOARD_MOBILE_AUDIT.md). Compare to “in use” and mark keep vs. archive candidate. |
| **config/** | Logrotate, port manifests. Keep active; corrupted backups (e.g. MASTER_PORT_MANIFEST.json.corrupted_*) = archive candidates. |
| **reports/** | One-off audit/diagnostic reports; if not referenced, archive. |
| **tests/** | Keep test dir; old dated snapshots (e.g. websocket_deployment_*) = archive candidates. |

Do **not** audit as “litter”: `.cursor/`, `venv/`, `node_modules/`, `logs/`, live DB data, `.env`.

---

## 3. Archive policy

- **Do not delete.** Move to an archive location. Restore is always possible.
- **One archive tree.** Use a single root, e.g. `archive/` at project root (you already have `archive/deprecated_services/` and docs refer to it). Option: `archive/2026-03-housekeeping/` for this pass so this audit is one dated batch.
- **Index.** Add `archive/2026-03-housekeeping/INDEX.md` (or same name at archive root) listing what was moved, from where, and why (e.g. “not referenced by supervisor or docs”).
- **References.** After move, if something still points at the old path (e.g. a doc saying “see scripts/archive_old/foo”), either update the link to the new archive path or add a one-line note in place: “Moved to archive/… (see archive INDEX).”

---

## 4. Phased plan

### Phase 1 — Discover and list (no moves)

1. **Scripts**
   - List every file under `scripts/` (excluding `archive_old/`).
   - For each, determine: used by supervisor, MASTER_RESTART, run_migration, verify/changelog/docs, or called by another script in the “used” set. If none, tag as “archive candidate”.
   - Output: `docs/changelog/todo_docs/HOUSEKEEPING_SCRIPTS_INVENTORY.md` (or similar) with columns: path, status [active / dependency / occasional / archive candidate], notes.

2. **Docs**
   - List top-level `docs/` entries and major subdirs (e.g. VER3_ONBOARDING_DOCUMENTS, archive, changelog, pm_brain).
   - Mark: linked from README, AGENTS, brain index, changelog, verify, org chart = keep. Old snapshots, one-off reports, superseded guides = archive candidates.
   - Output: `docs/changelog/todo_docs/HOUSEKEEPING_DOCS_INVENTORY.md` with path, status, notes.

3. **Backend**
   - From supervisor list + main.py, build the set of backend entry points and their direct imports.
   - List `backend/util/*.py` and `backend/api/` modules; mark “imported by entry point” vs “orphan”.
   - Output: `docs/changelog/todo_docs/HOUSEKEEPING_BACKEND_INVENTORY.md` (optional; can be lighter than scripts/docs).

4. **Root and config**
   - List root-level `.md`, `.sh` and key config files; tag keep vs archive candidate (e.g. corrupted manifest backups → archive).
   - Add a short “Root & config” section to one of the inventories or a small separate list.

### Phase 2 — Classify and decide

1. Review the inventories with a human/PM pass: confirm archive candidates are safe to move (no hidden references, no “we might need this for legal/compliance”).
2. For anything ambiguous, leave in place and add to “defer” list for a later pass.
3. Produce a single **archive list**: path → destination under `archive/2026-03-housekeeping/` (or chosen name), preserving relative structure where helpful (e.g. `docs/OLD_GUIDE.md` → `archive/2026-03-housekeeping/docs/OLD_GUIDE.md`).

### Phase 3 — Archive (move) and index

1. Create archive directory and subdirs to mirror structure (e.g. `archive/2026-03-housekeeping/scripts/`, `.../docs/`, `.../reports/`).
2. Move each file/dir from the archive list. Use `git mv` so history is preserved.
3. Write `archive/2026-03-housekeeping/INDEX.md`: date, purpose (“housekeeping audit 2026-03”), and a table or list: original path, new path, reason (e.g. “not in supervisor or docs”).

### Phase 4 — Update references

1. Grep codebase and docs for paths that pointed at moved files; update to new archive path or add a one-line “Moved to …” note.
2. If something was only in `scripts/archive_old/` and is still referenced (e.g. old VER3 snapshot docs), add a note in INDEX or in the doc that “archive_old is legacy; see archive/2026-03-housekeeping for later moves.”

### Phase 5 — Document and close

1. Add a short “Housekeeping” section to `docs/changelog/TODO.md` or a changelog entry: “2026-03: Housekeeping audit; X scripts, Y docs, Z other items archived to archive/2026-03-housekeeping. See archive/…/INDEX.md.”
2. Optionally add a single “Project housekeeping” item to `docs/pm_brain/13_proposed_tasks.md` pointing at this plan and the archive INDEX for future passes.

---

## 5. Already-archived areas (no re-archive)

- **scripts/archive_old/** — Already treated as archive. Only action: ensure no active path depends on it; if something does, either move that dependency to an active script or document the exception.
- **docs/archive/** — Already archived docs. Keep as-is; new doc moves can go to `archive/2026-03-housekeeping/docs/` or into `docs/archive/` with a note in INDEX.
- **archive/deprecated_services/** — Already used for retired services. Leave in place.

---

## 6. Out of scope for this pass

- Deleting anything permanently.
- Changing behavior of active code (only move and update references).
- Auditing .cursor, venv, or runtime data.
- Deep dependency analysis of every Python import (only “clearly orphan” modules).

---

## 7. Success criteria

- We have written inventories (scripts, docs, and optionally backend/root) with a clear “in use” vs “archive candidate” classification.
- All archive candidates that are safe to move live under one archive tree with an INDEX.
- No active workflow (supervisor, verify, MASTER_RESTART, migrations, referenced docs) points at a path that no longer exists without a “Moved to …” or updated link.
- A short changelog/brain note records that the housekeeping pass was done and where to find the archive index.

---

*Plan created 2026-03-07. Execute phases in order; Phase 1 can be done by script or by hand; Phases 2–5 are deliberate move-and-document steps.*

---

## 2026-03-07 — First batch completed

- **Phase 1:** Scripts, docs, and backend/root inventories created in `docs/changelog/todo_docs/` (HOUSEKEEPING_SCRIPTS_INVENTORY.md, HOUSEKEEPING_DOCS_INVENTORY.md, HOUSEKEEPING_BACKEND_ROOT_INVENTORY.md).
- **Phase 2–3 (first batch):** Archived: 83× `backend/core/config/MASTER_PORT_MANIFEST.json.corrupted_*` → `archive/2026-03-housekeeping/backend/core/config/`; `scripts/START_SERVICES_DIRECT.sh` and `scripts/auto_add_files.sh` → `archive/2026-03-housekeeping/scripts/`. INDEX written at `archive/2026-03-housekeeping/INDEX.md`.
- **Not archived (reviewed):** MASTER_RESTART_WITH_SANITIZATION_CHECK.sh is in scripts/install_deploy/; referenced by install_auto_startup_service and auto_startup_wrapper — kept. update_applications_for_postgresql.sh was archived; final_testing_and_deployment.sh is in scripts/install_deploy/. Docs and remaining script candidates left for a later pass; see inventories.
