#!/usr/bin/env node
/**
 * Daily-briefing Drive check: (1) search for Cursor Notes, (2) read content,
 * (3) compare to daily_briefing_reviewed_drive.json, (4) update the log.
 * Uses scripts-only (no MCP). Exit 0 on success; 1 on auth/file error.
 *
 * Usage (from repo root):
 *   node scripts/gdrive/daily-briefing-drive-check.js
 *
 * Output (stdout): JSON summary
 *   { "files": [ { "id", "name", "changed": boolean } ], "error": null }
 *   or { "files": [], "error": "message" }
 * Reviewed log path: .cursor/archive/pm/daily_briefing_reviewed_drive.json
 */

import { google } from "googleapis";
import { readFileSync, writeFileSync, mkdirSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { createHash } from "crypto";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "../..");
const defaultOAuthPath = resolve(repoRoot, ".cursor", "gcp-oauth.keys.json");
const defaultCredsPath = resolve(repoRoot, ".cursor", "gdrive-server-credentials.json");
const reviewedLogPath = resolve(repoRoot, ".cursor", "archive", "pm", "daily_briefing_reviewed_drive.json");

const oauthPath = process.env.GDRIVE_OAUTH_PATH || defaultOAuthPath;
const credsPath = process.env.GDRIVE_CREDENTIALS_PATH || defaultCredsPath;

function loadJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (e) {
    return null;
  }
}

function loadReviewedLog() {
  const data = loadJson(reviewedLogPath);
  return data && typeof data === "object" ? data : {};
}

function saveReviewedLog(obj) {
  const dir = resolve(reviewedLogPath, "..");
  try {
    mkdirSync(dir, { recursive: true });
  } catch (_) {}
  writeFileSync(reviewedLogPath, JSON.stringify(obj, null, 2) + "\n", "utf8");
}

function sha256(text) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function main() {
  const keys = loadJson(oauthPath);
  const token = loadJson(credsPath);
  if (!keys || !token) {
    const out = { files: [], error: "Missing credentials (gcp-oauth.keys.json or gdrive-server-credentials.json). Run create-doc.js auth." };
    process.stdout.write(JSON.stringify(out) + "\n");
    process.exit(1);
  }

  const client = keys.installed || keys.web;
  if (!client) {
    const out = { files: [], error: "OAuth keys must contain 'installed' or 'web'." };
    process.stdout.write(JSON.stringify(out) + "\n");
    process.exit(1);
  }

  const oauth2Client = new google.auth.OAuth2(client.client_id, client.client_secret, "http://localhost");
  oauth2Client.setCredentials(token);
  const drive = google.drive({ version: "v3", auth: oauth2Client });

  const reviewed = loadReviewedLog();
  const summary = { files: [], error: null };

  try {
    // Search for "Cursor Notes" in Cursor folder
    const folderRes = await drive.files.list({
      q: "name = 'Cursor' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
      fields: "files(id)",
      spaces: "drive",
      pageSize: 5,
    });
    const cursorFolderId = folderRes.data.files?.[0]?.id;
    if (!cursorFolderId) {
      const out = { files: [], error: "Cursor folder not found on Drive." };
      process.stdout.write(JSON.stringify(out) + "\n");
      process.exit(1);
    }

    const listRes = await drive.files.list({
      q: `name contains 'Cursor Notes' and '${cursorFolderId}' in parents and trashed = false`,
      fields: "files(id, name, mimeType)",
      spaces: "drive",
      pageSize: 20,
    });
    const files = listRes.data.files || [];

    for (const file of files) {
      let content = "";
      try {
        if ((file.mimeType || "").startsWith("application/vnd.google-apps.")) {
          const exportRes = await drive.files.export({ fileId: file.id, mimeType: "text/plain" });
          content = typeof exportRes.data === "string" ? exportRes.data : JSON.stringify(exportRes.data);
        } else {
          const getRes = await drive.files.get({ fileId: file.id, alt: "media" }, { responseType: "text" });
          content = typeof getRes.data === "string" ? getRes.data : JSON.stringify(getRes.data);
        }
      } catch (e) {
        summary.files.push({ id: file.id, name: file.name || "?", changed: false, error: e.message });
        continue;
      }

      const sig = sha256(content);
      const prev = reviewed[file.id];
      const changed = !prev || prev.content_signature !== sig;

      summary.files.push({ id: file.id, name: file.name || "?", changed });

      reviewed[file.id] = {
        name: file.name || "?",
        last_reviewed: today(),
        content_signature: sig,
      };
    }

    saveReviewedLog(reviewed);
  } catch (err) {
    summary.error = err.message || String(err);
  }

  process.stdout.write(JSON.stringify(summary) + "\n");
  process.exit(summary.error ? 1 : 0);
}

main().catch((err) => {
  process.stdout.write(JSON.stringify({ files: [], error: err.message || String(err) }) + "\n");
  process.exit(1);
});
