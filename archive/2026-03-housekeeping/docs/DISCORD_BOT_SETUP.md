# Kalshi dev Discord bot — setup

**Status: deferred.** We will come back to this later. Eric wants to dig into MCP functionality at some point; Discord access is a good place to start (he is new to MCP). Until then, bot is created and configured in Cursor; remaining step is inviting the bot to the Kalshi dev server (see §2).

This bot gives the **@kalshi** agent read access to the Kalshi developer Discord for research (API announcements, #dev discussion). It is **not a spam bot**: research only, concise and casual if it ever posts, no flooding.

**Application (created):** [Discord Developer Portal](https://discord.com/developers/applications/1479908766177824891/information) — Application ID `1479908766177824891`.

---

## 1. Create the bot (you do this in the Discord portal)

I can't log into Discord for you. Do this once:

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) and log in.
2. Click **New Application**. Name it (e.g. **rec-io-kalshi** or whatever you prefer). Create.
3. In the left sidebar, open **Bot**. Click **Add Bot**.
4. **Bot name:** Same or similar (e.g. **rec-io Kalshi**). Optional: turn off **Public Bot** so only you can add it to servers.
5. Under **Privileged Gateway Intents**, enable **Message Content Intent** (required for the MCP to read messages). Leave Server Members Intent off unless the MCP you use needs it.
6. Click **Reset Token** (or **View Token**), copy the token once, and store it somewhere safe. You'll put it in MCP config below; never commit it to git.

---

## 2. Invite the bot to the Kalshi dev server

You need **Manage Server** or **Administrator** on the Kalshi dev Discord. If you don't have it, Kalshi would need to add the bot.

**Kalshi dev server (for MCP):** Server ID `871819895443189862`, channel ID `927686720990892032` (from [channel link](https://discord.com/channels/871819895443189862/927686720990892032)). Use these when calling read_messages/send_message if name lookup fails.

**How to add the bot:**
1. Developer Portal → your app → **OAuth2** → **URL Generator**.
2. **Scopes:** check **bot**. **Bot Permissions:** check **View Channels**, **Read Message History**, and **Send Messages** if the agent should post.
3. Copy the **Generated URL**, open it in a browser, select the Kalshi dev server in the dropdown, click **Authorize**. Done—bot is in the server.

---

## 3. MCP config in Cursor

We use a **bot-based** Discord MCP (not a selfbot; selfbots violate Discord ToS). Example: **@missionsquad/mcp-discord**.

**Option A — Project-local (recommended so token stays out of repo)**

1. Copy the example config:
   ```bash
   cp .cursor/mcp.json.example .cursor/mcp.json
   ```
2. Edit `.cursor/mcp.json` and replace `YOUR_DISCORD_BOT_TOKEN` with your bot token. Do not commit `.cursor/mcp.json` (it's in .gitignore).
3. Restart Cursor or reload MCP (Cursor Settings → Tools & MCP).

**Option B — Global**

Edit `~/.cursor/mcp.json` and add the same `discord-kalshi` server block with your token in `env.DISCORD_TOKEN`.

---

## 4. Behavior (no spam)

- **Purpose:** Research only. The @kalshi agent uses Discord to **read** the Kalshi dev channel (announcements, API discussion, changelog chatter).
- **Posting:** Do not post unless the user explicitly asks. If the agent ever posts: **one short, casual message** only. Never flood or send multiple messages.
- This is enforced in the @kalshi rule (`.cursor/rules/kalshi.mdc`).

---

## 5. Channel access

- **Which channels:** The bot can read (and if permitted, send to) any channel on the server where it has the right permissions. Use the same MCP tools with different `channel` names (or channel IDs) to access other channels later.
- **Names vs IDs:** Tools accept channel name (e.g. `"general"`, `"dev"`) or channel ID. If name lookup fails, use IDs: Discord → User Settings → Advanced → Developer Mode ON → right‑click the server or channel → Copy ID. Pass `server` as the server (guild) ID and `channel` as the channel ID.

---

## 6. If something breaks

- **Bot offline / MCP not loading:** Check that the token in `.cursor/mcp.json` is correct and that Message Content Intent is enabled in the portal.
- **Can't read channel:** Bot must be in the server (invite step) and have Read Message History on that channel. If you get errors like `Cannot read properties of undefined (reading 'fetch')` or `channel.send is not a function`, the MCP may be failing to resolve the server/channel—confirm the bot is in the server and try passing **server ID** and **channel ID** (see above) instead of names.
- **Send message fails:** Bot needs **Send Messages** permission on that channel (re-invite with that permission if you originally used read-only).
- **Don't commit your token:** `.cursor/mcp.json` is gitignored. Keep it that way.
