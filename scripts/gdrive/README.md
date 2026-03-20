# Google API scripts (Drive, Docs, Sheets)

Use the same OAuth credentials as the gdrive MCP (`.cursor/gcp-oauth.keys.json`, `.cursor/gdrive-server-credentials.json`). **Write scope required** (drive; documents for Docs; spreadsheets for Sheets). Full setup: **.cursor/GOOGLE_DRIVE_MCP_SETUP.md**. **Canonical Drive read:** Use these scripts, not the G Drive MCP, for reliable access — see **docs/GDRIVE_ACCESS.md**.

**Enabled in GCP:** Drive API, Docs API, Sheets API (used by these scripts). Gmail API and Calendar API are enabled for future use.

## Read (search, read file, daily-briefing check)

- **search-drive.js** — Search Drive; same credentials as MCP.  
  `node scripts/gdrive/search-drive.js --folder "Cursor" "Cursor Notes"` → JSON array of `{ id, name, mimeType, parents }`.
- **read-file.js** — Read file by ID (Docs → text/plain, others as appropriate).  
  `node scripts/gdrive/read-file.js FILE_ID`
- **daily-briefing-drive-check.js** — One-shot for daily briefing: search Cursor Notes, read content, compare to `.cursor/archive/pm/daily_briefing_reviewed_drive.json`, update the log. Output: `{ "files": [{ "id", "name", "changed": boolean }], "error": null }`.  
  `node scripts/gdrive/daily-briefing-drive-check.js`

## Auth (write scope)

- **Server flow:** Run `node scripts/gdrive/create-doc.js auth` (leave running). Open the printed URL (or the one in `.cursor/gdrive-auth-url.txt`). After you allow access, the callback saves the token.
- **Paste code:** If the redirect hit “can’t be reached,” paste the full redirect URL:  
  `node scripts/gdrive/create-doc.js auth --code "localhost:3333/oauth2callback?code=4/0Afr..."`

Add scopes in GCP OAuth consent: `drive`, `documents`, `spreadsheets` (and re-run auth) so Docs and Sheets scripts work.

## create-doc.js — Docs and plain text

From repo root. **Default: when the user asks for a "doc" or "document" on Drive, create a Google Doc** (do not use `--text-file`). Use `--text-file` only when they explicitly want a plain text file.

```bash
# Empty Doc in Cursor folder
node scripts/gdrive/create-doc.js --folder "Cursor" "My Doc"

# Google Doc with body (needs Google Docs API enabled in GCP)
node scripts/gdrive/create-doc.js --folder "Cursor" "My Doc" "First paragraph."

# Plain text file (use only when user explicitly wants .txt)
node scripts/gdrive/create-doc.js --text-file --folder "Cursor" "Notes" "Some text."

# By folder ID
node scripts/gdrive/create-doc.js --folder-id FOLDER_ID "Title"
```

With a body and no `--text-file`, the script creates a Google Doc if Docs API is enabled. Enable **Google Docs API** in GCP (APIs & Services → Library) for real Docs.

## create-account-history-sheet.js — Spreadsheet from DB

Creates a new Google Sheet in REC_IO/Cursor with the contents of `users.account_history_0001` (all columns, newest first). Requires **Sheets API** enabled and scope `https://www.googleapis.com/auth/spreadsheets`. Uses `export_account_history.py` (same folder) to export from PostgreSQL; ensure `.env` / DB_* or REC_DB_* are set.

```bash
node scripts/gdrive/create-account-history-sheet.js
```

Each run creates a **new** sheet named "account_history". To update an existing sheet, the script would need to be extended (e.g. accept a sheet ID and clear/rewrite).

## export_account_history.py

Exports `users.account_history_0001` to CSV on stdout. Used by create-account-history-sheet.js. Run from repo root with `PYTHONPATH` set; loads DB config from `.env` and `backend.core.config.database`.

## Delete

```bash
node scripts/gdrive/create-doc.js delete FILE_ID [FILE_ID ...]
```

## Env (optional)

`GDRIVE_OAUTH_PATH`, `GDRIVE_CREDENTIALS_PATH` — default to `<repo>/.cursor/gcp-oauth.keys.json` and `.cursor/gdrive-server-credentials.json`.

## Dependencies

`npm install` in this directory (adds `googleapis`). Python: project `backend` and `dotenv` for export_account_history.py.
