---
description: "Production: hard resync users_0003 from users_0001. Wipe users_0003 tenant tables, rebuild from users_0001, remap 0001/100xx -> 0003/300xx. Never modify users_0001."
---

# Sync user 0003 (hard resync from 0001)

Use this command when `users_0003` must be rebuilt to mirror `users_0001` while preserving strict tenant separation.

## Safety contract (non-negotiable)

- Scope is **only** schema `users_0003`.
- `users_0001` is **read-only source**. Do not run `UPDATE/DELETE/TRUNCATE/ALTER/DROP` on `users_0001`.
- All DDL/DML writes must be wrapped in a single transaction; rollback on any error.
- Before commit, run verification queries and print results.

## Target

- **Production host:** `ssh root@$REC_PROD_SSH_HOST`
- **Database:** `rec_io_db` as `rec_io_user` (`PGPASSWORD` env)
- **Schema source:** `users_0001`
- **Schema destination:** `users_0003`

## Execute

Execute the workflow in `.cursor/skills/sync-user-0003/SKILL.md` exactly.

That skill is the canonical uniform process and includes:

1. Fixed rebuild table set.
2. Fixed transform rules (`0001/100xx` -> `0003/300xx`).
3. One-transaction SQL template.
4. Mandatory verification block and output contract.

## Minimum default table set for this command

- `trades_0003` from `trades_0001`
- `trades_simulated_0003` from `trades_simulated_0001`
- `account_balance_paper_0003` from `account_balance_paper_0001`
- `subaccounts_paper_0003` from `subaccounts_paper_0001`

If the user asks for additional tables, include them in the same transaction with the same safety contract.

## Required response format

Return:

- Tables rebuilt.
- Source/destination row counts.
- Marker-remnant checks (must be zero).
- Explicit statement: **no modifications were made to `users_0001`**.
