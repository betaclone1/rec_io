# Agent instructions

Project-specific agents are in `.cursor/rules/`.

---

## @pm — Project Manager

**Works autonomously:** executes full workflows without asking permission each step. Use **@pm** for strategy, audits, agent/rules maintenance, and system-wide coordination. Only pauses for true blockers or decisions only you can make. See `.cursor/rules/pm.mdc`.

---

## @kalshi — Kalshi expert

**In-house authority on Kalshi:** company, news, markets, and especially API and WebSocket. Use **@kalshi** for anything Kalshi-related: API/WS behavior, fixed-point migration, our integration (trade_executor, kalshi_account_sync_ws, etc.), changelog impact. Research-first; no guessing. See `.cursor/rules/kalshi.mdc`.

---

## @updater — Changelog / deployment

- **@updater prepare update** — Review changes, update changelog and DB docs before push.
- **@updater new update** — Run outstanding MASTER_CHANGELOG checklist tasks (production).
