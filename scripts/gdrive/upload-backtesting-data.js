#!/usr/bin/env node
/**
 * Upload local cycle packages to Google Drive under DATA/HISTORICAL_DATA/BACKTESTING_DATA.
 *
 * Mirrors relative paths from the local backtesting_data root, e.g.:
 *   KXBTC15M/2026/2026_07_JUL/KXBTC15M-….tar.xz
 *
 * Usage (from repo root):
 *   node scripts/gdrive/upload-backtesting-data.js
 *   node scripts/gdrive/upload-backtesting-data.js --dry-run
 *   node scripts/gdrive/upload-backtesting-data.js --local PATH --folder-id ID
 *
 * Env:
 *   GDRIVE_BACKTESTING_DATA_FOLDER_ID  (default: known eric@rec-io.com BACKTESTING_DATA)
 *   GDRIVE_OAUTH_PATH / GDRIVE_CREDENTIALS_PATH
 *   CYCLE_PACKAGE_ROOT / BTC15M_CYCLE_PACKAGE_ROOT  (optional local root override)
 */

import { google } from "googleapis";
import { createReadStream, existsSync, readFileSync, statSync } from "fs";
import { readdir } from "fs/promises";
import { basename, dirname, join, relative, resolve } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "../..");

const secretsClient = resolve(
  repoRoot,
  "backend/data/secrets/gdrive_oauth_client.json",
);
const secretsToken = resolve(
  repoRoot,
  "backend/data/secrets/gdrive_oauth_token.json",
);
const cursorClient = resolve(repoRoot, ".cursor/gcp-oauth.keys.json");
const cursorToken = resolve(repoRoot, ".cursor/gdrive-server-credentials.json");

function resolveCredPath(envName, preferred, fallback) {
  const fromEnv = (process.env[envName] || "").trim();
  if (fromEnv) return fromEnv;
  if (existsSync(preferred)) return preferred;
  return fallback;
}

const oauthPath = resolveCredPath(
  "GDRIVE_OAUTH_PATH",
  secretsClient,
  cursorClient,
);
const credsPath = resolveCredPath(
  "GDRIVE_CREDENTIALS_PATH",
  secretsToken,
  cursorToken,
);
const DEFAULT_FOLDER_ID = "1Jlhz57hSXMYe8Yr_GtIJsaXY0GAW6L1v"; // DATA/HISTORICAL_DATA/BACKTESTING_DATA

function loadJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function parseArgs() {
  const args = process.argv.slice(2);
  let dryRun = false;
  let localRoot = null;
  let folderId = process.env.GDRIVE_BACKTESTING_DATA_FOLDER_ID || DEFAULT_FOLDER_ID;
  const onlyFiles = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--dry-run") dryRun = true;
    else if (args[i] === "--local" && args[i + 1]) localRoot = resolve(args[++i]);
    else if (args[i] === "--folder-id" && args[i + 1]) folderId = args[++i];
    else if (args[i] === "--file" && args[i + 1]) onlyFiles.push(resolve(args[++i]));
    else if (args[i] === "--help" || args[i] === "-h") {
      console.log(
        "Usage: node scripts/gdrive/upload-backtesting-data.js [--dry-run] [--local PATH] [--folder-id ID] [--file PATH ...]",
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
  return { dryRun, localRoot, folderId, onlyFiles };
}

async function walkTarXz(root) {
  const out = [];
  async function walk(dir) {
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of entries) {
      const full = join(dir, ent.name);
      if (ent.isDirectory()) {
        if (ent.name === "." || ent.name === "..") continue;
        await walk(full);
      } else if (ent.isFile() && ent.name.endsWith(".tar.xz") && !ent.name.endsWith(".tar.xz.tmp")) {
        out.push(full);
      }
    }
  }
  await walk(root);
  return out.sort();
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

async function ensureChildFolder(drive, parentId, name, cache) {
  const key = `${parentId}/${name}`;
  if (cache.has(key)) return cache.get(key);
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
  if (found.data.files?.length) {
    const id = found.data.files[0].id;
    cache.set(key, id);
    return id;
  }
  const created = await drive.files.create({
    requestBody: {
      name,
      mimeType: "application/vnd.google-apps.folder",
      parents: [parentId],
    },
    fields: "id, name",
    supportsAllDrives: true,
  });
  const id = created.data.id;
  cache.set(key, id);
  console.error(`created folder ${name} (${id}) under ${parentId}`);
  return id;
}

async function ensurePath(drive, rootFolderId, relDir, cache) {
  const parts = relDir.split(/[/\\]/).filter(Boolean);
  let parent = rootFolderId;
  for (const part of parts) {
    parent = await ensureChildFolder(drive, parent, part, cache);
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

async function uploadFile(drive, parentId, localPath) {
  const name = basename(localPath);
  const size = statSync(localPath).size;
  const existing = await findExistingFile(drive, parentId, name);
  if (existing && String(existing.size) === String(size)) {
    return { status: "skip", id: existing.id, name, size };
  }
  if (existing) {
    await drive.files.update({
      fileId: existing.id,
      media: {
        mimeType: "application/x-xz",
        body: createReadStream(localPath),
      },
      fields: "id, name, size",
      supportsAllDrives: true,
    });
    return { status: "update", id: existing.id, name, size };
  }
  const created = await drive.files.create({
    requestBody: {
      name,
      parents: [parentId],
    },
    media: {
      mimeType: "application/x-xz",
      body: createReadStream(localPath),
    },
    fields: "id, name, size",
    supportsAllDrives: true,
  });
  return { status: "create", id: created.data.id, name, size };
}

async function main() {
  const { dryRun, localRoot, folderId, onlyFiles } = parseArgs();
  if (!existsSync(localRoot)) {
    console.error(`Local root missing: ${localRoot}`);
    process.exit(1);
  }
  if (!existsSync(oauthPath) || !existsSync(credsPath)) {
    console.error(
      `Missing Drive credentials (oauth=${oauthPath} creds=${credsPath})`,
    );
    process.exit(1);
  }

  let files;
  if (onlyFiles.length) {
    files = [];
    for (const f of onlyFiles) {
      if (!existsSync(f) || !f.endsWith(".tar.xz")) {
        console.error(`SKIP invalid --file ${f}`);
        continue;
      }
      files.push(f);
    }
  } else {
    files = await walkTarXz(localRoot);
  }
  console.log(`local_root=${localRoot}`);
  console.log(`drive_folder_id=${folderId}`);
  console.log(`oauth=${oauthPath}`);
  console.log(`files=${files.length} dry_run=${dryRun}`);

  if (!files.length) {
    process.exit(0);
  }

  if (dryRun) {
    for (const f of files) {
      console.log(`WOULD_UPLOAD ${relative(localRoot, f)}`);
    }
    process.exit(0);
  }

  const drive = driveClient();
  const about = await drive.about.get({ fields: "user" });
  console.log(`drive_user=${about.data.user?.emailAddress}`);

  const folderCache = new Map();
  let created = 0;
  let updated = 0;
  let skipped = 0;
  let failed = 0;

  for (const localPath of files) {
    const rel = relative(localRoot, localPath);
    if (rel.startsWith("..")) {
      failed += 1;
      console.error(`FAIL ${localPath}: not under local_root`);
      continue;
    }
    const relDir = dirname(rel);
    try {
      const parentId =
        relDir === "."
          ? folderId
          : await ensurePath(drive, folderId, relDir, folderCache);
      const result = await uploadFile(drive, parentId, localPath);
      if (result.status === "skip") skipped += 1;
      else if (result.status === "update") updated += 1;
      else created += 1;
      console.log(`${result.status.toUpperCase()} ${rel} (${result.size} bytes) id=${result.id}`);
    } catch (e) {
      failed += 1;
      console.error(`FAIL ${rel}: ${e.message || e}`);
    }
  }

  console.log(
    JSON.stringify({ created, updated, skipped, failed, total: files.length }, null, 2),
  );
  process.exit(failed ? 1 : 0);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
