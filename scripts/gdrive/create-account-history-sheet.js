#!/usr/bin/env node
/**
 * Export users.account_history_0001 to a new Google Sheet in REC_IO/Cursor.
 * Uses same OAuth as create-doc.js. Requires Sheets API enabled and scope
 * https://www.googleapis.com/auth/spreadsheets (add to GCP OAuth consent and re-run auth if needed).
 */
import { google } from "googleapis";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { spawnSync } from "child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "../..");
const defaultOAuthPath = resolve(repoRoot, ".cursor", "gcp-oauth.keys.json");
const defaultCredsPath = resolve(repoRoot, ".cursor", "gdrive-server-credentials.json");
const oauthPath = process.env.GDRIVE_OAUTH_PATH || defaultOAuthPath;
const credsPath = process.env.GDRIVE_CREDENTIALS_PATH || defaultCredsPath;

function loadJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function runExport() {
  const out = spawnSync(
    "python3",
    [resolve(__dirname, "export_account_history.py")],
    {
      cwd: repoRoot,
      env: { ...process.env, PYTHONPATH: repoRoot },
      encoding: "utf8",
    }
  );
  if (out.error || out.status !== 0) {
    console.error("Export failed:", out.stderr || out.error);
    process.exit(1);
  }
  return out.stdout;
}

function parseCsv(csvText) {
  const rows = [];
  const lines = csvText.trim().split("\n");
  for (const line of lines) {
    const row = [];
    let cell = "";
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') {
        inQuotes = !inQuotes;
      } else if ((c === "," && !inQuotes) || (c === "\r" && !inQuotes)) {
        row.push(cell);
        cell = "";
      } else if (c !== "\r") {
        cell += c;
      }
    }
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

async function main() {
  const csvText = runExport();
  const values = parseCsv(csvText);
  if (values.length === 0) {
    console.error("No data from account_history.");
    process.exit(1);
  }

  const keys = loadJson(oauthPath);
  const token = loadJson(credsPath);
  const client = keys.installed || keys.web;
  if (!client) {
    console.error("OAuth keys file must contain 'installed' or 'web'.");
    process.exit(1);
  }

  const oauth2Client = new google.auth.OAuth2(
    client.client_id,
    client.client_secret,
    "http://localhost"
  );
  oauth2Client.setCredentials(token);

  const drive = google.drive({ version: "v3", auth: oauth2Client });
  const res = await drive.files.list({
    q: "name = 'Cursor' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
    fields: "files(id, name)",
    spaces: "drive",
  });
  if (!res.data.files?.length) {
    console.error("Folder 'Cursor' not found on Drive.");
    process.exit(1);
  }
  const parentId = res.data.files[0].id;

  const created = await drive.files.create({
    requestBody: {
      name: "account_history",
      parents: [parentId],
      mimeType: "application/vnd.google-apps.spreadsheet",
    },
    fields: "id, name, webViewLink",
  });

  const sheetId = created.data.id;
  const sheets = google.sheets({ version: "v4", auth: oauth2Client });
  const lastCol = String.fromCharCode(64 + (values[0]?.length || 1));
  const lastRow = values.length;
  const range = `Sheet1!A1:${lastCol}${lastRow}`;

  await sheets.spreadsheets.values.update({
    spreadsheetId: sheetId,
    range,
    valueInputOption: "USER_ENTERED",
    requestBody: { values },
  });

  console.log("Created:", created.data.name);
  console.log("ID:", sheetId);
  console.log("URL:", created.data.webViewLink);
}

main().catch((err) => {
  console.error(err.message || err);
  if (err.message && err.message.includes("has not been used") && err.message.includes("sheets")) {
    console.error("Enable Sheets API in GCP and add scope https://www.googleapis.com/auth/spreadsheets to OAuth consent, then re-run: node scripts/gdrive/create-doc.js auth");
  }
  process.exit(1);
});
