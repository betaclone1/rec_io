---
description: "Promote justified knowledge into rules, AGENTS.md, or reference docs. Use sparingly; default is ephemeral."
---

# Promote knowledge

Promote knowledge into persistent, low-entropy artifacts only when clearly justified.

1. **Trigger:** User request or explicit conclusion that a pattern, rule, or reference must be durable (e.g. new convention, recurring mistake, schema rule).
2. **Target:** `.cursor/rules/*`, `AGENTS.md`, or reference docs (e.g. `docs/`, schema ref). Do not create rolling logs, memory banks, or append-only context files.
3. **Process:** Follow `.cursor/skills/knowledge-promotion/SKILL.md`: propose change, keep edits minimal and stable, update one place per concept.
4. **Policy:** Routine task execution does not promote. Only use when the benefit of persistent rule/docs outweighs entropy. Default to ephemeral chat.

See `.cursor/rules/03-doc-write-policy.mdc` and `.cursor/skills/knowledge-promotion/SKILL.md`.
