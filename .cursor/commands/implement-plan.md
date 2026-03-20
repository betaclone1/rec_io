---
description: "Implement from an existing plan: execute steps, edit code/docs. Report when done or blocked."
---

# Implement plan

Act as **Builder**. Implement from an existing plan file.

1. **Input:** Plan file path (e.g. `.cursor/plans/add-login-api.md`). If not given, ask or infer from current task.
2. **Read plan:** Load goal, steps, and completion criteria. Follow `.cursor/rules/02-code-change-safety.mdc` for DB/code changes.
3. **Execute:** Work through steps in order. Edit code and docs only as specified by the plan. Do not change `.cursor/rules/*` or `AGENTS.md` unless the plan explicitly includes knowledge promotion.
4. **Output:** Report steps_done[], steps_remaining[], files_changed[], and restart_required? if applicable. On completion, optionally hand off to Reviewer via `/review-change`.

See `.cursor/skills/code-implementation/SKILL.md` and `.cursor/rules/02-code-change-safety.mdc`.
