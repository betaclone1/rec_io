# Discord MCP / Kalshi dev channel

**Goal:** Finish Discord bot setup so @kalshi can read (and optionally post to) the Kalshi dev channel. Eric deferred to come back later and use this as a starting point to learn MCP.

**Scope:** In: invite bot to server, verify read_messages/send_message via MCP. Out: broader MCP usage (optional follow-up).

**Status:** cancelled (this initiative is intentionally parked; any future Discord/MCP work will start from a fresh plan)

## Steps
1. Invite the bot to the Kalshi dev server (OAuth2 URL → authorize). Server ID 871819895443189862, channel ID 927686720990892032. See docs/DISCORD_BOT_SETUP.md §2.
2. Verify read_messages and send_message work via MCP with those IDs; fix any MCP or permission issues.
3. (Optional) Explore broader MCP usage once Discord is working.

## Completion criteria
- [ ] Bot in server; read_messages and send_message work via MCP

## Blockers / decisions
- Deferred by Eric (2026-03-06). Bot and MCP config exist; bot was in 0 servers. Full setup: docs/DISCORD_BOT_SETUP.md.
