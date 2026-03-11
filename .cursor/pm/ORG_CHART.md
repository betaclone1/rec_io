# REC.IO 3.0 — Organization Chart & Standards

Single source of truth for team structure, reporting lines, and organizational standards. Subagents and rules are created and maintained to match this chart.

---

## 1. Executive

| Role | Authority | Notes |
|------|------------|--------|
| **CEO** (you) | Ultimate authority over all operations. | Any decision involving **real money** (live trading, spend, credentials, production financial risk) must go through the CEO. No exceptions. |
| **Project Manager** (@pm) | Reports to CEO. Right hand; most task flow runs through PM. | Autonomous execution; coordinates departments; only pauses for CEO decisions, blockers, or destructive/irreversible actions. See `.cursor/rules/pm.mdc`. |

---

## 2. Departments

Departments own domains of work. Subagents are created under departments as needed and listed here. New agents get a rule in `.cursor/rules/` and an entry in `AGENTS.md`.

### 2.1 Technical / Engineering

- **Scope:** Code, architecture, backend, frontend, database, tooling, security (implementation), performance.
- **Current agents:**
  - **@frontend** — Head of front-end development and maintenance. Expert in HTML, JS, CSS, mobile; owns frontend UI and UI/UX. See `.cursor/rules/frontend.mdc`.
  - **@db** — Head of DB operations; PostgreSQL expert. Monitors all DB changes; keeps reference doc, database.py, migrations, and memory (03) in sync so DB changes are painless across servers. Schema, reversible migrations (`scripts/db/run_migration.py`), reference alignment. See `.cursor/rules/db.mdc`.
- **Future subagents (as needed):** e.g. backend lead (optional "Backend master" that agents touching backend scripts and DB report to), infra/DevOps, **@opsec** (head of security; consulted on auth, secrets, deployment; see .cursor/pm/OPSEC_AUDIT_AND_UPGRADE.md) — created when workload or expertise warrants it.

### 2.2 Analysis

- **Scope:** Data analysis, analytics, backtesting, strategy research, reporting, momentum/volatility/pattern work.
- **Current agents:** *(none yet)*
- **Future subagents (as needed):** e.g. analytics lead, backtest/strategy — created when workload warrants it.

### 2.3 Operations

- **Scope:** Deployment, changelog, release checklist, production hygiene, MASTER_CHANGELOG.
- **Current agents:** **@updater** — changelog and deployment. See `.cursor/rules/updater.mdc`.  
  - `@updater prepare update` — review changes, update changelog and DB docs before push.  
  - `@updater new update` — run outstanding MASTER_CHANGELOG checklist (production).  
  - **/apply-update-from-local** — Primary: from local, SSH to prod and run the production checklist (pull, migrations, restart, verify). **/apply-update** — Alternative: same checklist when the agent is already on the prod server. See `.cursor/pm/APPLY_UPDATE_COMMAND.md`.

### 2.4 Integrations

- **Scope:** External APIs, third-party platforms, Kalshi (API, WebSocket, fixed-point, our integration), DigitalOcean (production host and domain).
- **Current agents:**  
  - **@kalshi** — Kalshi authority. See `.cursor/rules/kalshi.mdc`. Research-first; no guessing.  
  - **@digitalocean** — DigitalOcean authority. Snapshots, backups, droplets, domains; priority: see, create, modify, delete snapshots and backups. See `.cursor/rules/digitalocean.mdc` and `.cursor/pm/DIGITALOCEAN_INTEGRATION.md`.

### 2.5 Personal / CEO support

- **Scope:** Personal productivity; email, calendar, and tasks that do **not** require rec.io operational system resources (backend, DB, trading, deployment).
- **Current agents:** **@assistant** — Personal assistant. Gmail (search, read, draft, send), Google Calendar (events, free time), scheduling, and other personal tasks. Does not touch operational systems; for those, PM or domain agents. See `.cursor/rules/assistant.mdc`.

---

## 3. Governance Rules

1. **Real money**  
   Any action that commits real funds, changes live trading behavior, or exposes production financial risk requires explicit CEO approval. PM and agents do not approve these.

2. **Task flow**  
   Most work is assigned through PM. CEO may talk to individual agents when useful; PM remains the default coordinator and keeps context.

3. **Delegation**  
   PM delegates to domain agents (@frontend, @db, @updater, @kalshi) when the task fits. Keep agent context (rules, AGENTS.md, memory docs) updated so agents stay effective. See 06 "Delegation and agent context."

4. **Org chart maintenance**  
   When adding or retiring a subagent, PM updates this doc and `AGENTS.md` (and `.cursor/rules/` as needed) so the chart stays accurate.

5. **Standards**  
   Organizational standards (naming, docs, changelog, deployment) live in this repo (e.g. `docs/`, `AGENTS.md`, changelog). Stricter standards can be added here or in department-specific docs as we grow.

---

## 4. Communication

- **Primary channel:** rec.io Slack workspace. Day-to-day coordination and agent requests happen there.
- **Reaching Cursor from Slack:** In any channel or DM, mention **@Cursor** and type your request. Cursor runs in a context connected to the repo and can execute tasks (code, docs, audits).
- **Reaching the PM directly from Slack:** There is no separate "@pm" app in Slack. In theory you mention **@Cursor** and **@pm** in the message; in practice the Cursor Slack integration may **not post a reply** in the thread when you target a specific agent (e.g. @pm). This is a known limitation of the integration.
- **When you need a guaranteed PM response:** Use the **Cursor IDE** and start a chat with **@pm** there. That way the PM agent runs in this repo context and replies in the same interface. Use Slack for general Cursor tasks; use IDE @pm for coordination, audits, org, and strategy when you need a direct reply.
- **Other agents from Slack:** Same idea as PM: @Cursor then name the agent. Reply behavior may be inconsistent; IDE is reliable for agent-specific work.

---

## 5. Visual Summary

```
                    CEO (you)
                        |
        +---------------+---------------+
        |               |               |
   @assistant    Project Manager (@pm)
 (personal)              |
        +---------------+---------------+
        |               |               |
   Technical      Analysis      Operations    Integrations
(@frontend,@db)               (@updater)    (@kalshi)
```

---

*Last updated: 2026-03-08. Update this file when adding/removing agents, changing reporting lines, or updating comms.*
