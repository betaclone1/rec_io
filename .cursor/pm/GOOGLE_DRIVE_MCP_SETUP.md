# Google API integrations (Cursor)

Step-by-step to give the agent **read** access to Google Drive (e.g. REC_IO / Cursor folder) via the official MCP server `@modelcontextprotocol/server-gdrive`, **write** (create/delete files, create Docs and Sheets) via **scripts/gdrive/** using the same OAuth credentials, and **Gmail + Calendar** via the **google-workspace** MCP (`@presto-ai/google-workspace-mcp`).

**Quick reference (this project):** **Drive:** credentials in `.cursor/gcp-oauth.keys.json` and `.cursor/gdrive-server-credentials.json`; MCP `gdrive` in `.cursor/mcp.json`. Read: MCP **search** + **gdrive:///**. Write: `node scripts/gdrive/create-doc.js --folder "Cursor" "Title" ["body"]`, `create-doc.js delete ID`, `create-account-history-sheet.js`, auth via `create-doc.js auth`. **Gmail & Calendar:** MCP `google-workspace` in `.cursor/mcp.json`; one-time OAuth on first use (credentials in `~/.config/google-workspace-mcp/`). **Default location:** REC_IO / Cursor when the user says they've put something on Drive.

**When the user asks to write a doc or create a document on Drive:** Create a **Google Doc** (do **not** use `--text-file`). Use `create-doc.js --folder "Cursor" "Title" "body"`. Only use `--text-file` when they explicitly ask for a plain text file.

---

## Enabled Google APIs (GCP)

The following APIs are enabled in the project and available for scripts/MCP:

| API | Use |
|-----|-----|
| **Drive API** | MCP read (search, resources); scripts create/delete files, create Docs/Sheets in Drive. |
| **Google Docs API** | create-doc.js writes body into new Google Docs (not .txt). |
| **Google Sheets API** | create-account-history-sheet.js creates spreadsheets and writes data. Add scope `https://www.googleapis.com/auth/spreadsheets` to OAuth consent if needed. |
| **Gmail API** | **google-workspace** MCP: read/send mail, search, drafts, labels. Enable in GCP; OAuth on first MCP use. |
| **Google Calendar API** | **google-workspace** MCP: list calendars, list/create/update/delete events, find free time. Enable in GCP; same OAuth. |

Enable APIs in GCP: **APIs & Services → Library** → search and **Enable**. The **google-workspace** MCP uses its own OAuth flow and stores tokens in `~/.config/google-workspace-mcp/` (macOS); no need to share the gdrive token. Ensure Gmail API and Google Calendar API are enabled so the first-time auth can request the right scopes.

---

## 1. Google Cloud: project and Drive API

1. Open [Google Cloud Console](https://console.cloud.google.com/) and sign in.
2. **Create a project** (or pick an existing one): top bar → Select a project → New Project → name it (e.g. `cursor-gdrive-mcp`) → Create.
3. **Enable the Drive API**: left menu → APIs & Services → Enable APIs and Services → search “Google Drive API” → open it → **Enable**. Also enable **Google Docs API**, **Google Sheets API**; optionally **Gmail API** and **Google Calendar API** for future integrations.

---

## 2. OAuth consent screen

1. Left menu → **APIs & Services** → **OAuth consent screen**.
2. Choose **Internal** (only your Google Workspace / account) → Create.
3. **App information**: fill App name (e.g. `Cursor GDrive MCP`), User support email, Developer contact → Save and Continue.
4. **Scopes** → Add or Remove Scopes → add **`https://www.googleapis.com/auth/drive.readonly`** (read) and **`https://www.googleapis.com/auth/drive`** (or **`drive.file`**) for write. Add **`https://www.googleapis.com/auth/documents`** for create-doc body text, **`https://www.googleapis.com/auth/spreadsheets`** for create-account-history-sheet.js. For future Gmail/Calendar integrations add **`https://www.googleapis.com/auth/gmail.readonly`** (or **gmail.modify**), **`https://www.googleapis.com/auth/calendar`** (or **calendar.events**) as needed. Update → Save and Continue.
5. **Test users**: if the app is Internal, your account is already allowed. Save and Continue through Summary.

---

## 3. OAuth Desktop client and keys file

1. Left menu → **APIs & Services** → **Credentials**.
2. **Create Credentials** → **OAuth client ID**.
3. Application type: **Desktop app**. Name it (e.g. `Cursor MCP Desktop`). Create.
4. In the OAuth client list, open the new client → **Download JSON**.
5. Save the file somewhere safe. Rename it to **`gcp-oauth.keys.json`**.
6. Put it in a fixed path the MCP server will use, for example:
   - **Global (all projects):** `~/.cursor/gcp-oauth.keys.json`
   - **This project only:** `<repo>/.cursor/gcp-oauth.keys.json` (and add `.cursor/gcp-oauth.keys.json` to `.gitignore` so it’s never committed).

---

## 4. Where to store credentials (after first auth)

The server will save a token file after you complete the browser login once. Use a path only on your machine, e.g.:

- **Global:** `~/.cursor/gdrive-server-credentials.json`

Do **not** commit this file. If you use a path under the repo, add it to `.gitignore`.

---

## 5. First-time authentication (one-time, write scope)

For **write** (create/delete) the token must include **drive** (or **drive.file**) scope. The MCP server’s `npx ... auth` only requests read scope, so use the project script instead:

**Option A — server (recommended):** Run from repo root and leave running. Open the URL it prints (also written to `.cursor/gdrive-auth-url.txt`). After you allow access, the callback saves the token.

```bash
cd /path/to/repo && node scripts/gdrive/create-doc.js auth
```

**Option B — paste code:** If the redirect showed “can’t be reached,” copy the full address-bar URL and run:

```bash
node scripts/gdrive/create-doc.js auth --code "PASTE_FULL_REDIRECT_URL_HERE"
```

Redirect URI is `http://localhost:3333/oauth2callback`. Desktop OAuth clients often allow any localhost port without adding it in the console. If you get `redirect_uri_mismatch`, add that exact URI in GCP → Credentials → your Desktop client → Authorized redirect URIs.

---

## 6. Cursor MCP config

Cursor reads MCP config from:

- **Global:** `~/.cursor/mcp.json`
- **Project:** `<repo>/.cursor/mcp.json`

Create or edit one of these so the `mcpServers` section includes the gdrive server and the same paths you used for auth. Cursor supports an `env` object so the server can find the keys and credentials.

**Example `~/.cursor/mcp.json` (global):**

```json
{
  "mcpServers": {
    "gdrive": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-gdrive"],
      "env": {
        "GDRIVE_OAUTH_PATH": "/Users/YOUR_USERNAME/.cursor/gcp-oauth.keys.json",
        "GDRIVE_CREDENTIALS_PATH": "/Users/YOUR_USERNAME/.cursor/gdrive-server-credentials.json"
      }
    }
  }
}
```

Replace `YOUR_USERNAME` with your macOS username (or use `$HOME` if your client supports expanding it; if not, use the full path as above).

**Example project-only `.cursor/mcp.json`** (only if you stored keys/credentials under the repo and added them to `.gitignore`):

```json
{
  "mcpServers": {
    "gdrive": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-gdrive"],
      "env": {
        "GDRIVE_OAUTH_PATH": "/Users/YOUR_USERNAME/rec_io_local/3_0/.cursor/gcp-oauth.keys.json",
        "GDRIVE_CREDENTIALS_PATH": "/Users/YOUR_USERNAME/rec_io_local/3_0/.cursor/gdrive-server-credentials.json"
      }
    }
  }
}
```

Use absolute paths in `env`; Cursor does not expand `~` or `$HOME` in `mcp.json`.

---

## 7. Restart Cursor and confirm

1. Save `mcp.json` and **restart Cursor** (or reload the window).
2. In Cursor: **Cmd+Shift+J** → **Tools & MCP** and confirm the **gdrive** server is listed and enabled.
3. In a chat, you can ask the agent to “search my Google Drive for …” or “open file X from my Drive”; the agent will use the server’s **search** tool and **gdrive:///** resources.

---

## What the agent can do

- **Search:** find files by name/query in your Drive (MCP **search** tool).
- **Read:** open files by ID via **gdrive:///<file_id>** (MCP resources). Docs → Markdown, Sheets → CSV, etc.
- **Create Doc:** `node scripts/gdrive/create-doc.js --folder "Cursor" "Title"` (empty Doc) or `"Title" "Body"` (Google Doc with body). **When the user says "write a doc" or "create a document":** use this form **without** `--text-file`. Use `--text-file` only when they explicitly want a plain text file.
- **Create spreadsheet:** `node scripts/gdrive/create-account-history-sheet.js` — exports `users.account_history_0001` to a new Google Sheet in REC_IO/Cursor (uses `scripts/gdrive/export_account_history.py` for DB export). Requires Sheets API enabled and scope `spreadsheets`. Run again to create a fresh sheet (each run creates a new file).
- **Delete:** `node scripts/gdrive/create-doc.js delete FILE_ID [FILE_ID...]`.

### Gmail and Calendar (google-workspace MCP)

The **google-workspace** MCP (`@presto-ai/google-workspace-mcp`) is listed in `.cursor/mcp.json`. It provides Gmail (search, read, send, drafts, labels) and Google Calendar (list calendars, list/create/update/delete events, find free time). **First-time setup:** Ensure Gmail API and Google Calendar API are enabled in your GCP project. Restart Cursor (or reload the window) so the new server loads. The first time the agent uses a Gmail or Calendar tool, the server will open a browser for OAuth; complete the flow and tokens are stored in `~/.config/google-workspace-mcp/` (macOS). No env vars are required in mcp.json; the server manages its own credentials. If you see token or scope errors, delete the config folder and trigger a tool again to re-auth: `rm -rf ~/.config/google-workspace-mcp`.

We keep **gdrive** for Drive read and **scripts/gdrive/** for Doc/Sheet creation so we can use the same token and folder conventions; the **google-workspace** MCP is separate and uses its own OAuth/token storage.

REC_IO is the Drive folder; **Cursor** is a subfolder. See **scripts/gdrive/README.md** for full usage.

---

## Write access (create/delete)

1. In GCP, add scopes **`https://www.googleapis.com/auth/drive`** (or **`drive.file`**), **`documents`** (for Doc body), **`spreadsheets`** (for account_history sheet) to the OAuth consent screen.
2. Run auth via the script (Section 5 above) so the saved token has the needed scopes.
3. Create Doc: `node scripts/gdrive/create-doc.js --folder "Cursor" "My Doc" ["body"]`. Create account_history sheet: `node scripts/gdrive/create-account-history-sheet.js`. Delete: `node scripts/gdrive/create-doc.js delete FILE_ID [FILE_ID...]`. See **scripts/gdrive/README.md**.

## Security

- **Scopes:** use `drive.readonly` for MCP only; add `drive` (or `drive.file`), `documents` (Docs), `spreadsheets` (Sheets). Gmail and Calendar scopes when you add those integrations.
- **Secrets:** never commit `gcp-oauth.keys.json` or `gdrive-server-credentials.json`. Prefer storing them under `~/.cursor/` and using the global `~/.cursor/mcp.json` so they stay off the repo.
- If you use project-level paths, add those files to `.gitignore`.

---

## Troubleshooting

- **“Credentials not found”:** Ensure `GDRIVE_OAUTH_PATH` and `GDRIVE_CREDENTIALS_PATH` in `mcp.json` match the paths you used when running `npx ... auth`, and use absolute paths.
- **“Insufficient Permission” when running create-doc.js:** The saved token was created with only read scope. Add the `drive` (or `drive.file`) scope in GCP, delete `gdrive-server-credentials.json`, and run `node scripts/gdrive/create-doc.js auth` again (with same env).
- **Sheets API "has not been used" / 403:** Enable Google Sheets API in GCP (APIs & Services → Library). Add scope `https://www.googleapis.com/auth/spreadsheets` to OAuth consent, then re-run `node scripts/gdrive/create-doc.js auth` so the token includes it.
- **Auth again:** If the token is revoked or expired, run `node scripts/gdrive/create-doc.js auth` (or `auth --code "URL"`) with the same env vars.
- **Server not listed:** Restart Cursor after editing `mcp.json`; ensure the file is valid JSON and the server entry is under `mcpServers`.
