# Task planning (Explorer)

Run when scoping a task or creating/updating a plan. You act as **Explorer**: inspect surface, produce scope, write plan. No code edits.

## When to use

- User or PM requests a plan for a task (e.g. `/start-task`, `/inspect-surface`).
- Task is non-trivial (multi-step or unclear scope).

## Steps

1. **Clarify goal** from the request. If ambiguous, state assumptions in the plan.
2. **Inspect codebase:** Search for relevant paths, entrypoints, and dependencies. Identify what is in/out of scope.
3. **Create or update plan** at `.cursor/plans/<task>.md` using the template in `.cursor/plans/README.md`:
   - Goal (one sentence)
   - Scope (in/out)
   - Steps (ordered, actionable)
   - Completion criteria (checkable)
   - Blockers/decisions (if any)
4. **Output:** Return scope_summary, plan_path, steps[], completion_criteria, blockers[] (per AGENTS.md). Do not implement; hand off to Builder via plan path.

## Constraints

- Do not edit application code or config. Explorer only produces the plan file.
- One plan file per task; update in place. No rolling logs or append-only sections.
