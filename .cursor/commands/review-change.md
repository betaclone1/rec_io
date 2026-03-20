---
description: "Review a change set against plan and safety rules. Produce pass/conditional/rework; no edits to the change set."
---

# Review change

Act as **Reviewer**. Review the current change set (and optionally the plan it implements).

1. **Input:** Plan path (if any) and the set of changed files (from git diff or list).
2. **Check:** Alignment with plan goal and completion criteria; code-change safety (see `.cursor/rules/02-code-change-safety.mdc`); obvious risks (e.g. missing migrations, hardcoded secrets, server-specific paths).
3. **Output:** outcome (pass | conditional_pass | rework), findings[], suggested_actions[]. Do not edit the change set; only report.

If outcome is rework, Builder (or user) addresses findings and may re-run review. See `.cursor/skills/change-review/SKILL.md`.
