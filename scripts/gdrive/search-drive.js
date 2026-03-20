#!/usr/bin/env node
/**
 * Search Google Drive using the same OAuth credentials as the gdrive MCP.
 *
 * This is the agent's primary, stable way to discover files in
 * REC_IO / Cursor and elsewhere, independent of the MCP tooling.
 *
 * Usage (from repo root):
 *   node scripts/gdrive/search-drive.js "Cursor Notes"
 *   node scripts/gdrive/search-drive.js --folder "Cursor" "Notes"
 *   node scripts/gdrive/search-drive.js --folder-id FOLDER_ID "Notes"
 *
 * Output: JSON array of files [{ id, name, mimeType, parents }, ...] on stdout.
 */

import { google } from "googleapis";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const repoRoot = resolve(__dirname, "../..");
const defaultOAuthPath = resolve(repoRoot, ".cursor", "gcp-oauth.keys.json");
const defaultCredsPath = resolve(repoRoot, ".cursor", "gdrive-server-credentials.json");

const oauthPath = process.env.GDRIVE_OAUTH_PATH || defaultOAuthPath;
const credsPath = process.env.GDRIVE_CREDENTIALS_PATH || defaultCredsPath;

function loadJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (e) {
    console.error(`Failed to load ${path}:`, e.message);
    process.exit(1);
  }
}

function parseArgs() {
  const args = process.argv.slice(2);
  let folderName = null;
  let folderId = null;
  const rest = [];

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--folder" && args[i + 1]) {
      folderName = args[++i];
    } else if (args[i] === "--folder-id" && args[i + 1]) {
      folderId = args[++i];
    } else {
      rest.push(args[i]);
    }
  }

  const query = rest.join(" ").trim();
  if (!query) {
    console.error(
      "Usage: node scripts/gdrive/search-drive.js [--folder \"Cursor\" | --folder-id ID] \"search text\"",
    );
    process.exit(1);
  }

  return { folderName, folderId, query };
}

async function main() {
  const { folderName, folderId, query } = parseArgs();

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
    "http://localhost",
  );
  oauth2Client.setCredentials(token);

  const drive = google.drive({ version: "v3", auth: oauth2Client });

  let parentId = null;
  if (folderId) {
    parentId = folderId;
  } else if (folderName) {
    const folderQuery = `name = '${folderName.replace(/'/g, "\\'")}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false`;
    const folderRes = await drive.files.list({
      q: folderQuery,
      fields: "files(id, name)",
      spaces: "drive",
      pageSize: 5,
    });
    if (!folderRes.data.files || folderRes.data.files.length === 0) {
      console.error(`Folder not found: "${folderName}"`);
      process.exit(1);
    }
    parentId = folderRes.data.files[0].id;
  }

  const escapedQuery = query.replace(/'/g, "\\'");
  const qParts = [
    `name contains '${escapedQuery}'`,
    "trashed = false",
  ];
  if (parentId) {
    qParts.push(`'${parentId}' in parents`);
  }
  const q = qParts.join(" and ");

  const res = await drive.files.list({
    q,
    fields: "files(id, name, mimeType, parents)",
    spaces: "drive",
    pageSize: 100,
  });

  const files = res.data.files || [];
  process.stdout.write(JSON.stringify(files, null, 2) + "\n");
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});

