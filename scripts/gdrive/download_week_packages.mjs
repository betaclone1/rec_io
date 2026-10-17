/**
 * Download missing KXBTC15M cycle packages for Aug30–Sep5 2026 from Drive.
 * Usage: node scripts/gdrive/download_week_packages.mjs
 */
import { google } from "googleapis";
import {
  createWriteStream,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
} from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";
import { pipeline } from "stream/promises";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repo = resolve(__dirname, "../..");
const oauthPath = existsSync(resolve(repo, "backend/data/secrets/gdrive_oauth_client.json"))
  ? resolve(repo, "backend/data/secrets/gdrive_oauth_client.json")
  : resolve(repo, ".cursor/gcp-oauth.keys.json");
const credsPath = existsSync(resolve(repo, "backend/data/secrets/gdrive_oauth_token.json"))
  ? resolve(repo, "backend/data/secrets/gdrive_oauth_token.json")
  : resolve(repo, ".cursor/gdrive-server-credentials.json");
const keys = JSON.parse(readFileSync(oauthPath, "utf8"));
const token = JSON.parse(readFileSync(credsPath, "utf8"));
const client = keys.installed || keys.web;
const oauth2 = new google.auth.OAuth2(client.client_id, client.client_secret, "http://localhost");
oauth2.setCredentials(token);
const drive = google.drive({ version: "v3", auth: oauth2 });
const ROOT = process.env.GDRIVE_BACKTESTING_DATA_FOLDER_ID || "1Jlhz57hSXMYe8Yr_GtIJsaXY0GAW6L1v";
const localRoot = resolve(repo, "backend/data/historical_data/backtesting_data");

async function child(parent, name) {
  const r = await drive.files.list({
    q:
      `'${parent}' in parents and name = '${name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false`,
    fields: "files(id,name)",
    pageSize: 5,
    supportsAllDrives: true,
    includeItemsFromAllDrives: true,
  });
  return r.data.files?.[0] || null;
}

async function listFiles(folderId) {
  let pageToken;
  const out = [];
  do {
    const r = await drive.files.list({
      q: `'${folderId}' in parents and trashed = false and name contains 'KXBTC15M-'`,
      fields: "nextPageToken, files(id,name,size)",
      pageSize: 1000,
      pageToken,
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
    });
    out.push(...(r.data.files || []));
    pageToken = r.data.nextPageToken;
  } while (pageToken);
  return out;
}

async function downloadFile(fileId, destPath) {
  mkdirSync(dirname(destPath), { recursive: true });
  const tmp = `${destPath}.tmp`;
  if (existsSync(tmp)) unlinkSync(tmp);
  const res = await drive.files.get(
    { fileId, alt: "media", supportsAllDrives: true },
    { responseType: "stream" },
  );
  await pipeline(res.data, createWriteStream(tmp));
  renameSync(tmp, destPath);
}

const MON = { 8: "2026_08_AUG", 9: "2026_09_SEP" };
const days = [
  [2026, 8, 30],
  [2026, 8, 31],
  [2026, 9, 1],
  [2026, 9, 2],
  [2026, 9, 3],
  [2026, 9, 4],
  [2026, 9, 5],
];

const kx = await child(ROOT, "KXBTC15M");
const y = await child(kx.id, "2026");
const folderCache = {};
const jobs = [];
for (const [, mm, dd] of days) {
  const folderName = MON[mm];
  if (!folderCache[folderName]) folderCache[folderName] = await child(y.id, folderName);
  const folder = folderCache[folderName];
  if (!folder) {
    console.log("missing folder", folderName);
    continue;
  }
  const files = await listFiles(folder.id);
  const dayStr = String(dd).padStart(2, "0");
  const monTok = mm === 8 ? "AUG" : "SEP";
  const prefix = `KXBTC15M-26${monTok}${dayStr}`;
  const dayFiles = files.filter((f) => f.name.startsWith(prefix) && f.name.endsWith(".tar.xz"));
  let need = 0;
  for (const f of dayFiles) {
    const dest = join(localRoot, "KXBTC15M", "2026", folderName, f.name);
    if (existsSync(dest)) continue;
    jobs.push({ id: f.id, name: f.name, dest });
    need++;
  }
  console.log(`${folderName} day=${dayStr} drive=${dayFiles.length} to_download=${need}`);
}
console.log(`TOTAL_JOBS=${jobs.length}`);

const CONCURRENCY = 6;
let done = 0;
let fail = 0;
async function worker(queue) {
  while (queue.length) {
    const job = queue.shift();
    if (!job) return;
    try {
      await downloadFile(job.id, job.dest);
      done++;
      if (done % 10 === 0 || done === jobs.length) {
        console.log(`progress ${done}/${jobs.length} fail=${fail} last=${job.name}`);
      }
    } catch (e) {
      fail++;
      console.log(`FAIL ${job.name}: ${e.message}`);
    }
  }
}
const q = [...jobs];
await Promise.all(Array.from({ length: CONCURRENCY }, () => worker(q)));
console.log(`DOWNLOAD_DONE done=${done} fail=${fail} total=${jobs.length}`);
process.exit(fail ? 1 : 0);
