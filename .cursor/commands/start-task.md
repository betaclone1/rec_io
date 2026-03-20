---
description: "Start a task: interpret the request, delegate to Explorer for scoping/plan, then hand off to Builder or report plan to user."
---

# Start task

User has requested a task. Act as **PM**: interpret the request, then delegate.

1. **Scope:** If the task is non-trivial (multi-step, unclear scope), delegate to **Explorer** (use task-planning skill or `/inspect-surface`): produce scope and a plan file in `.cursor/plans/<task>.md`.
2. **Plan:** Ensure one plan file exists for the task. Plan path and steps are the handoff to Builder.
3. **Next:** Either (a) hand off to Builder with the plan path for implementation, or (b) present the plan to the user and wait for go-ahead.

Do not implement code or write plan content yourself; delegate to Explorer for planning and Builder for implementation. See `AGENTS.md` (workflow agents) and `.cursor/skills/task-planning/SKILL.md`.
