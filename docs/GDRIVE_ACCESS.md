# G Drive access — canonical path (scripts)

**Canonical read access to Google Drive in this project is via scripts, not the G Drive MCP.** Use the scripts for any workflow that must work every day (e.g. daily briefing). The MCP is optional and often broken.

## Why scripts, not MCP

- The official **`@modelcontextprotocol/server-gdrive`** server is archived and has known bugs.
- In this environment the Cursor MCP layer often fails to pass per-call tool arguments (e.g. `query` for search), leading to `invalid_request` or similar errors.
- Scripts use the same OAuth credentials (`.cursor/gcp-oauth.keys.json`, `.cursor/gdrive-server-credentials.json`) and give **consistent** Drive read access without depending on MCP.

## Canonical read flow

1. **Search** — `node scripts/gdrive/search-drive.js [--folder "Cursor"] "Cursor Notes"`  
   Output: JSON array of `{ id, name, mimeType, parents }`. Use `--folder "Cursor"` to limit to the Cursor folder under REC_IO.

2. **Read file** — `node scripts/gdrive/read-file.js FILE_ID`  
   Output: file contents on stdout (Google Docs as text/plain, others as appropriate).

3. **Compare / track** — For daily briefing, either run the one-shot helper or do the steps manually:
   - **One-shot:** `node scripts/gdrive/daily-briefing-drive-check.js` — searches Cursor Notes, reads content, compares to `.cursor/archive/pm/daily_briefing_reviewed_drive.json`, updates the log, and prints `{ "files": [{ "id", "name", "changed": boolean }], "error": null }`. Use `changed` to decide if the Drive section is needed.
   - **Manual:** Hash content (e.g. `shasum -a 256`) and compare to `content_signature` in the JSON; update `last_reviewed` and `content_signature` after review.

Credentials and auth: same as in `.cursor/archive/pm/GOOGLE_DRIVE_MCP_SETUP.md`. Write operations (create Doc, delete, create spreadsheet): `scripts/gdrive/create-doc.js`, `create-account-history-sheet.js`, auth via `create-doc.js auth`.

**Production:** Use **`eric@rec-io.com`** OAuth JSON under `backend/data/secrets/` (`gdrive_oauth_client.json`, `gdrive_oauth_token.json`), not laptop `.cursor/` paths. See `backend/data/secrets/README.md`. Cycle upload target folder ID: `GDRIVE_BACKTESTING_DATA_FOLDER_ID` (default `DATA/HISTORICAL_DATA/BACKTESTING_DATA`). Nightly DB dumps go to `DATA/DB_BACKUPS` via `scripts/gdrive/upload-db-backup.js` (`GDRIVE_DB_BACKUPS_FOLDER_ID`, default `1yvZm4itVZGmDXlIu7qBeIFKbCTiITO3o`).

## MCP status

- **gdrive** in `.cursor/mcp.json`: may work occasionally; do **not** rely on it for daily briefing or other critical flows.
- If you add or fix MCP tooling later, keep scripts as the documented primary path so workflows stay reliable.
