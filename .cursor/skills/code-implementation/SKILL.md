# Code implementation (Builder)

Run when implementing from an existing plan. You act as **Builder**: execute plan steps, edit code/docs. Do not change rules or AGENTS.md unless the plan explicitly includes knowledge promotion.

## When to use

- Plan exists at `.cursor/plans/<task>.md` and implementation is requested (e.g. `/implement-plan`).
- PM or user hands off with a plan path.

## Steps

1. **Load plan:** Read goal, steps, completion criteria. Resolve any blockers noted in the plan before coding.
2. **Execute steps in order.** For each step: make the minimal code/doc edits required. Follow `.cursor/rules/02-code-change-safety.mdc` and, for schema work, `.cursor/rules/05-db-migration-hygiene.mdc` (batch DDL, one id per logical change, remove unapplied superseded pairs).
3. **Track progress:** Update the plan only to mark steps done or add brief notes if needed; do not turn the plan into a log.
4. **Output:** Report steps_done[], steps_remaining[], files_changed[], restart_required? (if any). When all steps and criteria are met, optionally hand off to Reviewer via `/review-change`.

## Constraints

- Do not add or edit `.cursor/rules/*` or `AGENTS.md` unless the plan explicitly says to promote knowledge.
- One plan per task; no duplicate or rolling plan files.
