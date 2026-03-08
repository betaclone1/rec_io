# Fix: Let the DO agent create snapshots autonomously

**One step to enable:** Put your DO API token in `.cursor/mcp.json` under `mcpServers.digitalocean-droplets.headers.Authorization`. Ensure the digitalocean-droplets server is loading (Reload Window after editing mcp.json if needed). **/prepare-update** and @digitalocean use the **snapshot-droplet** MCP tool only; no script fallback.

---

**Problem:** The agent can't read `.env` when it runs `scripts/do/snapshot_prod.sh` (Cursor's sandbox blocks or redacts it), so the script gets an empty token and fails.

**Fix (recommended): Use the DigitalOcean MCP so the agent never needs .env**

The token lives in **MCP config** (e.g. `.cursor/mcp.json`). The MCP server process uses it to call the DO API. The agent only invokes the MCP tool; it never reads the token.

1. **Use an MCP server that exposes `snapshot-droplet`**  
   DigitalOcean's droplet MCP tools include **snapshot-droplet** (Droplet ID + snapshot name).  
   Docs: https://docs.digitalocean.com/reference/mcp/droplet-mcp-tools/  
   Source: https://github.com/digitalocean-labs/mcp-digitalocean  

2. **Add the server to Cursor**  
   - If there is an npm package or runnable for the labs server, add it to `.cursor/mcp.json` with `DIGITALOCEAN_API_TOKEN` in `env` (paste the value from your `.env` once).  
   - Or use DigitalOcean's **remote** MCP endpoint for droplets if documented (e.g. `https://droplets.mcp.digitalocean.com/mcp`) and configure auth per their docs.  
   - `.cursor/mcp.json` is gitignored; the token stays local.

3. **@digitalocean agent behavior**  
   When you ask for a prod snapshot, the agent calls the MCP tool **snapshot-droplet** with:
   - `ID`: **513735057** (prod droplet)
   - `Name`: **rec-io-prod-YYYY-MM-DD** (or the name you want)  
   No script, no .env read, no sandbox issue.

4. **If the official `@digitalocean/mcp` (npx) includes droplet tools**  
   Add to `.cursor/mcp.json`:
   ```json
   "digitalocean": {
     "command": "npx",
     "args": ["-y", "@digitalocean/mcp"],
     "env": {
       "DIGITALOCEAN_API_TOKEN": "<paste token from .env>"
     }
   }
   ```
   Then in Cursor, check which tools appear. If **snapshot-droplet** (or equivalent) is there, use it. If the official package is App Platform–only, use the **digitalocean-labs** MCP or the remote droplet endpoint instead.

**Alternative: Allow the script to read .env via sandbox**

Cursor’s sandbox can grant extra read paths. If making .env readable to the agent’s shell is acceptable for this repo:

1. Create **`.cursor/sandbox.json`** (per-repo) with:
   ```json
   {
     "additionalReadonlyPaths": ["<absolute-path-to-project>/.env"]
   }
   ```
   Use the real project root path (e.g. `/Users/ericwais1/rec_io_local/3_0`). A repo-local `.cursor/sandbox.json` with this path is machine-specific; on another machine, update the path or rely on the MCP fix instead.

2. Ensure the script is allowlisted so the agent can run it without confirmation.

3. Re-test: ask the agent to create a prod snapshot. If the sandbox still redacts .env, this path won’t work and the **MCP path** above is the fix.

**Summary**

- **Preferred:** Add a DigitalOcean MCP that has **snapshot-droplet**; put the token in MCP config; agent calls the tool. No .env read.
- **Fallback:** Try `additionalReadonlyPaths` for `.env` in `.cursor/sandbox.json` and re-run the script; only use if your security posture allows the agent to read .env.
