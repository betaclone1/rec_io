#!/usr/bin/env node
/**
 * Upload a compressed Postgres backup to Google Drive DATA/DB_BACKUPS and
 * prune to a rolling keep count (default 14).
 *
 * Same OAuth resolution as upload-backtesting-data.js:
 *   backend/data/secrets/gdrive_oauth_*.json  (prod)
 *   .cursor/gcp-oauth.keys.json + gdrive-server-credentials.json (local)
 *
 * Usage (from repo root):
 *   node scripts/gdrive/upload-db-backup.js --file path/to/rec_io_db_backup_….sql.gz
 *   node scripts/gdrive/upload-db-backup.js --file PATH --keep 14
 *   node scripts/gdrive/upload-db-backup.js --prune-only --keep 14
 *   node scripts/gdrive/upload-db-backup.js --file PATH --dry-run
 *
 * Env:
 *   GDRIVE_DB_BACKUPS_FOLDER_ID  (default: DATA/DB_BACKUPS)
 *   GDRIVE_OAUTH_PATH / GDRIVE_CREDENTIALS_PATH
 *   DB_BACKUP_KEEP               (default 14; overridden by --keep)
 */

import { google } from "googleapis";
import { createReadStream, existsSync, readFileSync, statSync } from "fs";
import { basename, dirname, resolve } from "path";
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

/** DATA / DB_BACKUPS on eric@rec-io.com */
const DEFAULT_FOLDER_ID = "1yvZm4itVZGmDXlIu7qBeIFKbCTiITO3o";
const NAME_PREFIX = "rec_io_db_backup_";

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

function loadJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function parseArgs() {
  const args = process.argv.slice(2);
  let dryRun = false;
  let pruneOnly = false;
  let filePath = null;
  let folderId =
    process.env.GDRIVE_DB_BACKUPS_FOLDER_ID || DEFAULT_FOLDER_ID;
  let keep = parseInt(process.env.DB_BACKUP_KEEP || "14", 10);
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--dry-run") dryRun = true;
    else if (args[i] === "--prune-only") pruneOnly = true;
    else if (args[i] === "--file" && args[i + 1]) filePath = resolve(args[++i]);
    else if (args[i] === "--folder-id" && args[i + 1]) folderId = args[++i];
    else if (args[i] === "--keep" && args[i + 1]) keep = parseInt(args[++i], 10);
    else if (args[i] === "--help" || args[i] === "-h") {
      console.log(
        "Usage: node scripts/gdrive/upload-db-backup.js [--file PATH] [--keep N] [--folder-id ID] [--prune-only] [--dry-run]",
      );
      process.exit(0);
    }
  }
  if (!Number.isFinite(keep) || keep < 1) {
    console.error("--keep / DB_BACKUP_KEEP must be >= 1");
    process.exit(1);
  }
  if (!pruneOnly && !filePath) {
    console.error("Provide --file PATH or --prune-only");
    process.exit(1);
  }
  return { dryRun, pruneOnly, filePath, folderId, keep };
}

function driveClient() {
  if (!existsSync(oauthPath) || !existsSync(credsPath)) {
    throw new Error(
      `Missing Drive OAuth files. Looked for:\n  ${oauthPath}\n  ${credsPath}`,
    );
  }
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

async function listBackupFiles(drive, folderId) {
  const out = [];
  let pageToken;
  do {
    const res = await drive.files.list({
      q:
        `'${folderId}' in parents and trashed = false ` +
        `and name contains '${NAME_PREFIX}'`,
      fields: "nextPageToken, files(id, name, size, createdTime, modifiedTime)",
      pageSize: 100,
      pageToken,
      orderBy: "createdTime asc",
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
    });
    for (const f of res.data.files || []) {
      if (typeof f.name === "string" && f.name.startsWith(NAME_PREFIX)) {
        out.push(f);
      }
    }
    pageToken = res.data.nextPageToken || undefined;
  } while (pageToken);
  out.sort((a, b) => {
    const ta = a.createdTime || a.modifiedTime || "";
    const tb = b.createdTime || b.modifiedTime || "";
    if (ta !== tb) return ta < tb ? -1 : 1;
    return String(a.name || "").localeCompare(String(b.name || ""));
  });
  return out;
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

async function uploadFile(drive, parentId, localPath, dryRun) {
  const name = basename(localPath);
  const size = statSync(localPath).size;
  const existing = await findExistingFile(drive, parentId, name);
  if (existing && String(existing.size) === String(size)) {
    console.log(`skip (same size): ${name} id=${existing.id}`);
    return { status: "skip", id: existing.id, name, size };
  }
  if (dryRun) {
    console.log(
      `DRY_RUN would ${existing ? "update" : "upload"}: ${name} (${size} bytes)`,
    );
    return { status: "dry_run", id: existing?.id || null, name, size };
  }
  if (existing) {
    const updated = await drive.files.update({
      fileId: existing.id,
      media: {
        mimeType: "application/gzip",
        body: createReadStream(localPath),
      },
      fields: "id, name, size",
      supportsAllDrives: true,
    });
    console.log(`updated: ${name} id=${updated.data.id}`);
    return { status: "update", id: updated.data.id, name, size };
  }
  const created = await drive.files.create({
    requestBody: {
      name,
      parents: [parentId],
    },
    media: {
      mimeType: "application/gzip",
      body: createReadStream(localPath),
    },
    fields: "id, name, size",
    supportsAllDrives: true,
  });
  console.log(`uploaded: ${name} id=${created.data.id} size=${size}`);
  return { status: "upload", id: created.data.id, name, size };
}

async function prune(drive, folderId, keep, dryRun) {
  const files = await listBackupFiles(drive, folderId);
  console.log(`Drive DB_BACKUPS matching ${NAME_PREFIX}*: ${files.length} (keep=${keep})`);
  for (const f of files) {
    console.log(`  ${f.createdTime}\t${f.name}\t${f.id}`);
  }
  const excess = files.length - keep;
  if (excess <= 0) {
    console.log("no prune needed");
    return;
  }
  const toDelete = files.slice(0, excess);
  for (const f of toDelete) {
    console.log(
      `${dryRun ? "DRY_RUN would delete" : "deleting"}: ${f.name} id=${f.id}`,
    );
    if (!dryRun) {
      await drive.files.delete({
        fileId: f.id,
        supportsAllDrives: true,
      });
    }
  }
}

async function main() {
  const { dryRun, pruneOnly, filePath, folderId, keep } = parseArgs();
  console.log(
    `upload-db-backup: folder=${folderId} keep=${keep} dry_run=${dryRun} prune_only=${pruneOnly}`,
  );
  console.log(`oauth=${oauthPath}`);
  console.log(`creds=${credsPath}`);

  const drive = driveClient();

  if (!pruneOnly) {
    if (!existsSync(filePath)) {
      throw new Error(`file not found: ${filePath}`);
    }
    await uploadFile(drive, folderId, filePath, dryRun);
  }

  await prune(drive, folderId, keep, dryRun);
  console.log("upload-db-backup: done");
}

main().catch((err) => {
  console.error("upload-db-backup FAILED:", err.message || err);
  process.exit(1);
});
