---
description: "Inspect codebase surface for a task: produce scope, create or update plan file. No code edits."
---

# Inspect surface

Act as **Explorer**. Inspect the codebase surface for the given task or area. Do not edit code.

1. **Input:** Task description or area (e.g. "add login API", "where is trade execution triggered").
2. **Search:** Use codebase search and key files to determine scope, relevant paths, and dependencies.
3. **Output:** Create or update a plan file at `.cursor/plans/<task>.md` with: goal, scope, ordered steps, completion criteria, and any blockers. Use the template in `.cursor/plans/README.md`.
4. **Schema:** Produce scope_summary, plan_path, steps[], completion_criteria, blockers[] (see AGENTS.md).

Do not implement. Hand off to Builder via the plan path. See `.cursor/skills/task-planning/SKILL.md`.
