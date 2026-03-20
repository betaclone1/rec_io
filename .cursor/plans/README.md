# Plans

Primary persistent memory for active tasks. One plan file per task.

## Usage rules

- **Create** a plan when starting a non-trivial task (e.g. via `/start-task` or when scope is multi-step).
- **One file per task.** Name by task (e.g. `add-login-api.md`, `fix-trade-sync-bug.md`). Use kebab-case.
- **Update in place** as work progresses. Do not create rolling logs, append-only sections, or duplicate plan files for the same task.
- **Close** when done: add a "Status: done" (or "cancelled") line and optionally move to an `archive/` subfolder or delete if no long-term value.
- **No plan required** for one-off questions, single-file edits, or verification-only work.

## Plan template

```markdown
# <Task title>

**Goal:** One sentence.
**Scope:** What is in/out.
**Status:** draft | in progress | done | cancelled

## Steps
1. (ordered steps; check off or update as done)
2.
3.

## Completion criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Blockers / decisions
- (optional; empty if none)
```

Keep the plan concise. Steps and criteria should be actionable.

## Task list

When showing the **task list** (e.g. "what's next"):

- **Include:** plans whose **Status** is `draft` or `in progress`. Include **scheduled** only when the scheduled date (if stated in the plan) is today or in the past; do not list scheduled items with a future date until it's time to do them.
- **Exclude:** `done`, `cancelled`, and scheduled plans whose date has not yet been reached.
- **Order:** List any plan marked **Priority:** top first; then the rest. Give each listed task a short descriptive summary (from the plan's Goal or title), not just the filename.

**Cursor Notes** (G Drive) is a place the user can write notes for the agent when away; it is not a task. If the user has added task-like items there, promote those to a plan in this directory when they become a tracked task.

## Interaction with workflow

- **Explorer** creates or updates the plan (scope, steps, criteria).
- **Builder** reads the plan and implements; may append steps_done or notes.
- **Reviewer** reads the plan and changed files; does not edit the plan except to note review outcome.
- **PM** orchestrates; does not write plan content, only delegates to Explorer.
