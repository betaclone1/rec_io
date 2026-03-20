# Change review (Reviewer)

Run when reviewing a change set (e.g. after implementation). You act as **Reviewer**: assess against plan and safety rules; produce outcome and findings. No edits to the change set.

## When to use

- After Builder completes implementation (`/review-change`).
- User requests a review of current changes.

## Steps

1. **Gather input:** Plan path (if any), and the set of changed files (e.g. `git diff --name-only`, or list provided).
2. **Align with plan:** If a plan exists, check that goal and completion criteria are met by the changes.
3. **Safety check:** Per `.cursor/rules/02-code-change-safety.mdc`: DB changes have migration applied and docs updated; no irreversible surprises; critical paths note restart if needed; no hardcoded localhost/absolute paths/undocumented env.
4. **Risks:** Note missing migrations, TODOs in changed code, untracked files that should be committed, or other issues.
5. **Output:** outcome (pass | conditional_pass | rework), findings[], suggested_actions[] (per AGENTS.md). Do not modify the change set; only report.

## Constraints

- Reviewer does not edit the code or plan. For rework, Builder or user applies fixes and may re-run review.
