# Knowledge promotion

Run when promoting justified knowledge into rules, AGENTS.md, or reference docs. Use sparingly; default is ephemeral chat.

## When to use

- User explicitly asks to add a rule, convention, or reference.
- A clear, recurring pattern or mistake justifies a durable rule (e.g. "always run schema drift check after DB changes").

## Steps

1. **Justify:** State why this belongs in a persistent artifact (rule, AGENTS.md, or reference doc) rather than staying in chat or a one-off plan.
2. **Choose target:** One place per concept. Prefer:
   - `.cursor/rules/` for behavioral law (how to operate).
   - `AGENTS.md` for roles, delegation, or handoff contracts.
   - Reference docs (e.g. `docs/`, schema ref) for factual reference.
3. **Edit minimally:** Add or update only what is needed. Keep wording stable and concise. Do not create new rolling logs, memory banks, or append-only files.
4. **Confirm:** After edit, note what was added/updated and where.

## Constraints

- Routine task execution does not promote. Do not auto-update rules or AGENTS.md from normal implementation.
- No new "memory bank" documents or chat-summary vaults. See `.cursor/rules/03-doc-write-policy.mdc`.
