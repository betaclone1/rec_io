# VER 4.0 development (agent workspace)

Machine-oriented notes for the v3 → v4 initiative. Written for agents. Not a user manual and not a design yet.

| File | Role |
|------|------|
| [AUDIT_V3_BASELINE.md](AUDIT_V3_BASELINE.md) | As-built v3 snapshot. Facts only. |
| [V4_DIRECTION.md](V4_DIRECTION.md) | Owner constraints for v4. Not a design. Read after the audit. |
| [PG_AND_HOST_OPTIONS.md](PG_AND_HOST_OPTIONS.md) | Working assumption: self-managed Postgres on its own lean droplet. Managed DO/AWS prices kept as the alternative. Not executed. |

## Rules for this folder

- Prefer facts with a source path, function, table, or a dated production observation.
- Do not copy secrets, tokens, passwords, or private keys into these files. Name the file that holds them.
- Production writes, deploys, and restarts are out of scope until an explicit instruction in chat.
- Later design and step plans belong in new files here. Do not rewrite the baseline audit to match a proposal. Add a dated addendum or a new doc and point at the baseline.
