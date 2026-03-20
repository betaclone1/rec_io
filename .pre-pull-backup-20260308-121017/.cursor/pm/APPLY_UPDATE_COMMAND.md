# /apply-update command

**Defined in:** `.cursor/commands/apply-update.md` (slash command). Triggered by `/apply-update` or "follow the changelog instructions". Rule: `.cursor/rules/changelog.mdc`. Equivalent: **@updater new update**.

When the user (or production server agent) invokes **/apply-update**, they want to **calibrate this server with the latest update**: review the latest MASTER_CHANGELOG entries and instruction docs, then run every open production checklist so this deployment matches the release.

## When to use

- After **pulling** the latest code on this server (production, staging, or another deployment).
- When you need this server to **apply** the steps documented in the newest MASTER_CHANGELOG entries (DB updates, one-time scripts, restarts, verification).

## Agent behavior

The agent must **execute** the workflow, not just describe it. Follow `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md` in full:

1. Parse `MASTER_CHANGELOG.md` for open entries (at least one `- [ ]` in the Production agent checklist).
2. For each open entry (newest-first), perform every unchecked task in order.
3. After each completed task, set that item to `- [x]` in `MASTER_CHANGELOG.md`.
4. Report what was done and any blockers.

Commands run from **project root**. Python: `PYTHONPATH=$(pwd) venv/bin/python` (see `docs/changelog/README.md`).

## References

- Full instructions: `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`
- Master checklist: `docs/changelog/MASTER_CHANGELOG.md`
- Workflow overview: `docs/changelog/README.md`
