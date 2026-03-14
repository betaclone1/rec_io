# Push commits and update production (one-shot)

Run when the user wants a **single command** to prepare an update, commit and push with the suggested message, and then apply that update to production. Intended for lighter, high-confidence commits.

## Workflow (execute in order)

1. **Run prepare-update**
   - Execute the full **prepare-update** workflow per `.cursor/skills/prepare-update/SKILL.md`:
     - Prod snapshot (blocking; stop entire flow if snapshot fails).
     - Verify local system (health, supervisor, logs; status block).
     - Server-agnostic audit (hardcoded hosts, absolute paths, env).
     - Plans → changelog and DB docs (MASTER_CHANGELOG entry, schema ref, related docs).
     - Flag other issues (migrations, untracked, TODOs).
     - Produce suggested commit message and report **ready for publishing** or **blocking issues**.
   - **If prepare-update reports blocking issues:** Stop. Do not run steps 2 or 3. Report the blocking issues and that the flow was aborted before commit/push.

2. **Commit and push**
   - Only if prepare-update reported **ready for publishing** and produced a suggested commit message:
   - Stage changes: `git add -A` (from project root). If the user or prepare-update indicated a subset of files, stage that subset instead.
   - Commit with the **exact suggested commit message** from step 1 (title line + blank line + bullet list as body). Use `git commit -m "<title>" -m "<body>"` or a temporary file for multi-line message so the full message is preserved.
   - Push: `git push origin $(git branch --show-current)` (or `git push` if tracking is set).
   - If there is nothing to commit (e.g. no changes after staging, or already committed): run `git status`; if the branch is ahead of origin, run `git push`; then proceed to step 3. If there was nothing to push, still proceed to step 3 (apply may still have open checklist items from a previous push).

3. **Run apply-update-from-local**
   - Execute the full **apply-update-from-local** workflow per `.cursor/skills/apply-update-from-local/SKILL.md`:
     - Confirm the commit to deploy is pushed.
     - Read `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`.
     - List open MASTER_CHANGELOG entries (newest-first); for each, run every unchecked checklist task on prod via SSH (`ssh root@137.184.224.94 'cd /opt/rec_io_server && <command>'`).
     - Mark each completed task as `- [x]` in MASTER_CHANGELOG.md locally.
     - Verify production (health, supervisor, logs; VERIFY STATUS block).
     - Fidelity check (local vs prod commit and migrations).
     - Report outcome, remaining open items, VERIFY STATUS, fidelity.
   - Respect all apply-update-from-local rules (e.g. migration pre-flight; never mark DB tasks done or report "All good" if migrations were required and not successfully run).

## Summary

- **Prepare** → if blocking issues, **stop**.
- **Commit and push** with the suggested message.
- **Apply** on prod via SSH (checklist, verify, fidelity, report).

References: `.cursor/commands/push-commits-and-update-production.md`, prepare-update skill, apply-update-from-local skill.
