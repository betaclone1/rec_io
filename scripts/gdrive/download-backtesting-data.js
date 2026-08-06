#!/usr/bin/env node
/**
 * Download cycle packages from Google Drive BACKTESTING_DATA into the local
 * backtesting_data tree (mirror of upload-backtesting-data.js).
 *
 * Usage (from repo root):
 *   node scripts/gdrive/download-backtesting-data.js --file PATH.tar.xz
 *   node scripts/gdrive/download-backtesting-data.js --rel KXBTC15M/2026/2026_08_AUG/KXBTC15M-….tar.xz
 *
 * Env:
 *   GDRIVE_BACKTESTING_DATA_FOLDER_ID
 *   GDRIVE_OAUTH_PATH / GDRIVE_CREDENTIALS_PATH
 *   CYCLE_PACKAGE_ROOT / BTC15M_CYCLE_PACKAGE_ROOT
 */

import { google } from "googleapis";
import { createWriteStream, existsSync, mkdirSync, readFileSync, renameSync, unlinkSync } from "fs";
import { basename, dirname, join, relative, resolve } from "path";
import { fileURLToPath } from "url";
import { pipeline } from "stream/promises";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "../..");

const secretsClient = resolve(repoRoot, "backend/data/secrets/gdrive_oauth_client.json");
const secretsToken = resolve(repoRoot, "backend/data/secrets/gdrive_oauth_token.json");
const cursorClient = resolve(repoRoot, ".cursor/gcp-oauth.keys.json");
const cursorToken = resolve(repoRoot, ".cursor/gdrive-server-credentials.json");

function resolveCredPath(envName, preferred, fallback) {
  const fromEnv = (process.env[envName] || "").trim();
  if (fromEnv) return fromEnv;
  if (existsSync(preferred)) return preferred;
  return fallback;
}

const oauthPath = resolveCredPath("GDRIVE_OAUTH_PATH", secretsClient, cursorClient);
const credsPath = resolveCredPath("GDRIVE_CREDENTIALS_PATH", secretsToken, cursorToken);
const DEFAULT_FOLDER_ID = "1Jlhz57hSXMYe8Yr_GtIJsaXY0GAW6L1v";

function loadJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function parseArgs() {
  const args = process.argv.slice(2);
  let localRoot = null;
  let folderId = process.env.GDRIVE_BACKTESTING_DATA_FOLDER_ID || DEFAULT_FOLDER_ID;
  const relPaths = [];
  const onlyFiles = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--local" && args[i + 1]) localRoot = resolve(args[++i]);
    else if (args[i] === "--folder-id" && args[i + 1]) folderId = args[++i];
    else if (args[i] === "--file" && args[i + 1]) onlyFiles.push(resolve(args[++i]));
    else if (args[i] === "--rel" && args[i + 1]) relPaths.push(String(args[++i]).replace(/^\/+/, ""));
    else if (args[i] === "--help" || args[i] === "-h") {
      console.log(
        "Usage: node scripts/gdrive/download-backtesting-data.js [--file PATH ...] [--rel REL ...] [--local PATH] [--folder-id ID]",
      );
      process.exit(0);
    }
  }
  if (!localRoot) {
    const envRoot = (
      process.env.CYCLE_PACKAGE_ROOT ||
      process.env.BTC15M_CYCLE_PACKAGE_ROOT ||
      ""
    ).trim();
    localRoot = envRoot
      ? resolve(envRoot)
      : resolve(repoRoot, "backend/data/historical_data/backtesting_data");
  }
  return { localRoot, folderId, onlyFiles, relPaths };
}

function driveClient() {
  const keys = loadJson(oauthPath);
  const token = loadJson(credsPath);
  const client = keys.installed || keys.web;
  if (!client) throw new Error("OAuth keys must contain installed or web");
  const oauth2Client = new google.auth.OAuth2(
    client.client_id,
    client.client_secret,
    "http://localhost",
  );
  oauth2Client.setCredentials(token);
  return google.drive({ version: "v3", auth: oauth2Client });
}

async function findChildFolder(drive, parentId, name) {
  const q =
    `'${parentId}' in parents and name = '${name.replace(/'/g, "\\'")}' ` +
    `and mimeType = 'application/vnd.google-apps.folder' and trashed = false`;
  const found = await drive.files.list({
    q,
    fields: "files(id, name)",
    pageSize: 5,
    supportsAllDrives: true,
    includeItemsFromAllDrives: true,
  });
  return found.data.files?.[0]?.id || null;
}

async function resolveParent(drive, rootFolderId, relDir) {
  const parts = relDir.split(/[/\\]/).filter(Boolean);
  let parent = rootFolderId;
  for (const part of parts) {
    const next = await findChildFolder(drive, parent, part);
    if (!next) return null;
    parent = next;
  }
  return parent;
}

async function findExistingFile(drive, parentId, name) {
  const q =
    `'${parentId}' in parents and name = '${name.replace(/'/g, "\\'")}' ` +
    `and trashed = false`;
  const res = await drive.files.list({
    q,
    fields: "files(id, name, size)",
    pageSize: 5,
    supportsAllDrives: true,
    includeItemsFromAllDrives: true,
  });
  return res.data.files?.[0] || null;
}

async function downloadFile(drive, fileId, destPath) {
  mkdirSync(dirname(destPath), { recursive: true });
  const tmp = `${destPath}.tmp`;
  try {
    if (existsSync(tmp)) unlinkSync(tmp);
    const res = await drive.files.get(
      { fileId, alt: "media", supportsAllDrives: true },
      { responseType: "stream" },
    );
    await pipeline(res.data, createWriteStream(tmp));
    renameSync(tmp, destPath);
  } catch (err) {
    try {
      if (existsSync(tmp)) unlinkSync(tmp);
    } catch {
      /* ignore */
    }
    throw err;
  }
}

async function downloadOne(drive, folderId, localRoot, relPosix) {
  const rel = relPosix.replace(/\\/g, "/");
  const name = basename(rel);
  const relDir = dirname(rel);
  const dest = join(localRoot, ...rel.split("/"));
  if (existsSync(dest)) {
    console.log(JSON.stringify({ status: "exists", path: dest, rel }));
    return { status: "exists", path: dest };
  }
  const parent = await resolveParent(drive, folderId, relDir === "." ? "" : relDir);
  if (!parent) {
    console.log(JSON.stringify({ status: "missing_folder", rel }));
    return { status: "missing_folder", rel };
  }
  const remote = await findExistingFile(drive, parent, name);
  if (!remote) {
    console.log(JSON.stringify({ status: "missing_file", rel }));
    return { status: "missing_file", rel };
  }
  await downloadFile(drive, remote.id, dest);
  console.log(
    JSON.stringify({
      status: "downloaded",
      path: dest,
      rel,
      id: remote.id,
      size: remote.size,
    }),
  );
  return { status: "downloaded", path: dest };
}

async function main() {
  const { localRoot, folderId, onlyFiles, relPaths } = parseArgs();
  if (!existsSync(oauthPath) || !existsSync(credsPath)) {
    console.error(`Missing OAuth files: ${oauthPath} / ${credsPath}`);
    process.exit(2);
  }
  const targets = [...relPaths];
  for (const abs of onlyFiles) {
    const rel = relative(localRoot, abs);
    if (!rel || rel.startsWith("..")) {
      console.error(`--file must be under local root ${localRoot}: ${abs}`);
      process.exit(2);
    }
    targets.push(rel.replace(/\\/g, "/"));
  }
  if (!targets.length) {
    console.error("Provide --file PATH and/or --rel REL");
    process.exit(2);
  }
  const drive = driveClient();
  let failed = 0;
  for (const rel of targets) {
    const result = await downloadOne(drive, folderId, localRoot, rel);
    if (result.status !== "downloaded" && result.status !== "exists") failed += 1;
  }
  process.exit(failed ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
