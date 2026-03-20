#!/usr/bin/env node
/**
 * Read a Google Drive file's contents using the same OAuth credentials
 * as the gdrive MCP. Supports Google Docs (exported as text/plain) and
 * generic files (downloaded as-is).
 *
 * Usage (from repo root):
 *   node scripts/gdrive/read-file.js FILE_ID
 *
 * Output: file contents on stdout (text for Docs and most text files).
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
  const fileId = args[0];
  if (!fileId) {
    console.error("Usage: node scripts/gdrive/read-file.js FILE_ID");
    process.exit(1);
  }
  return { fileId };
}

async function main() {
  const { fileId } = parseArgs();

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

  const metaRes = await drive.files.get({
    fileId,
    fields: "id, name, mimeType",
  });
  const mimeType = metaRes.data.mimeType || "";

  if (mimeType.startsWith("application/vnd.google-apps.")) {
    // Google Docs/Sheets/Slides/etc. Try a text export.
    const exportMime = "text/plain";
    const exportRes = await drive.files.export({
      fileId,
      mimeType: exportMime,
    });
    const data = exportRes.data;
    if (typeof data === "string") {
      process.stdout.write(data);
    } else {
      process.stdout.write(JSON.stringify(data, null, 2));
    }
    return;
  }

  // Generic file download (alt=media). For text files this will be the content;
  // for binary you will likely not use this script directly.
  const getRes = await drive.files.get(
    {
      fileId,
      alt: "media",
    },
    {
      responseType: "text",
    },
  );
  const body = getRes.data;
  if (typeof body === "string") {
    process.stdout.write(body);
  } else {
    process.stdout.write(JSON.stringify(body, null, 2));
  }
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});

