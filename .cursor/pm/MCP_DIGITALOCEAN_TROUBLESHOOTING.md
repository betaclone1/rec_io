# Why the DigitalOcean MCP might be "unavailable"

**Server name:** Cursor exposes project MCPs with a prefix. Use server **project-0-3_0-digitalocean-droplets** (not "digitalocean-droplets"). The prepare-update command and @digitalocean rule are updated to use this name.

When the agent calls the **snapshot-droplet** tool and gets "MCP server does not exist", it may mean the wrong server name was used, or Cursor did **not** add that server to the list of available MCPs for this session. Your `.cursor/mcp.json` has the entry; Cursor either didn't load it or the server failed to connect and was dropped.

**Most common cause when it "was working and now it isn't":** The workspace is no longer the **project root**. Cursor loads `.cursor/mcp.json` only when the folder you opened is the one that **contains** `.cursor/`. If you opened a parent folder (e.g. `rec_io_local`) instead of this project (`3_0`), or reopened from a different path, Cursor will not load the project's MCPs and you'll see only built-in servers. **Fix:** File → Open Folder → select the folder that contains `.cursor` (this repo's root, e.g. `3_0`). Then run /prepare-update again.

---

## 1. Check MCP Logs (actual reason)

Cursor logs why an MCP fails to load.

- **Open:** Output panel (Cmd+Shift+U / Ctrl+Shift+U) → dropdown → **"MCP Logs"** (or "Cursor MCP").
- Look for **digitalocean-droplets** (or the URL `droplets.mcp.digitalocean.com`). You’ll see either:
  - Connection/SSE/stream errors (e.g. "Failed to open SSE stream", timeout, TLS),
  - HTTP/2 issues ("stuck loading"),
  - Or that the server never appears (config not read).

That tells you the real cause.

---

## 2. Cursor might not be using this project’s mcp.json

Cursor merges **global** `~/.cursor/mcp.json` and **project** `.cursor/mcp.json`. If the project file isn’t used, your DO server never loads.

- Ensure you opened the **project root** (the folder that contains `.cursor/mcp.json`) as the workspace, not a parent or subfolder.
- If you use a multi-root workspace, the project that has `.cursor/mcp.json` must be one of the roots.
- Try adding **digitalocean-droplets** to **global** `~/.cursor/mcp.json` (same entry as in the project). Restart Cursor. If it appears in MCP Logs and in the tools list, then the project-level config wasn’t being loaded for that session.

---

## 3. Remote (streamableHttp) MCPs often fail in Cursor

The DO server is a **remote URL** (`https://droplets.mcp.digitalocean.com/mcp`). In Cursor, remote/StreamableHttp MCPs are known to:

- Fail with SSE/stream errors,
- Get stuck if Cursor uses HTTP/2 to connect.

**Things to try:**

- **Settings → Network:** Set **HTTP Compatibility Mode** to **HTTP/1.0**, or turn on **Disable HTTP/2**. Then restart Cursor and check MCP Logs again.
- **Reload Window:** Cmd+Shift+P → "Developer: Reload Window". Sometimes the server appears after a reload.
- **Restart Cursor** after any change to `mcp.json` or network settings.

---

## 4. Auth header format

DigitalOcean’s docs often show:

```json
"Authorization": "Bearer YOUR_API_TOKEN"
```

Your token is `dop_v1_...`. Some clients want:

```json
"Authorization": "Bearer dop_v1_YOUR_TOKEN_HERE"
```

If MCP Logs show **401 Unauthorized** or similar, try adding `Bearer ` in front of the token in `.cursor/mcp.json`. If it already works without `Bearer`, leave it as-is.

---

## 5. Summary

| What you see | What to do |
|--------------|------------|
| "MCP server does not exist: digitalocean-droplets" | Open **MCP Logs** and find the line for digitalocean-droplets or the DO URL. That’s the real reason. |
| No mention of DO in MCP Logs | Cursor may not be loading this project’s mcp.json. Open project root; or add the server to `~/.cursor/mcp.json` and restart. |
| SSE/stream or connection errors | Try **HTTP/1.0** or **Disable HTTP/2** in Settings → Network; restart. |
| 401 / auth errors | Try `"Authorization": "Bearer dop_v1_..."` in mcp.json. |

Once the server shows up in MCP Logs as connected, the agent will see **digitalocean-droplets** in the available servers and the snapshot step will work.
