#!/usr/bin/env node
/**
 * Create a Google Doc in a Drive folder using the same OAuth credentials as the gdrive MCP.
 * Requires GDRIVE_OAUTH_PATH and GDRIVE_CREDENTIALS_PATH (or defaults to repo .cursor/).
 * Usage:
 *   node create-doc.js auth                          # get token with write scope (run once; or auth --code "URL")
 *   node create-doc.js delete FILE_ID [FILE_ID...]   # delete file(s) by Drive ID
 *   node create-doc.js "Doc title"                   # create in root (or use --folder)
 *   node create-doc.js --folder "Cursor" "Doc title"  # create in folder named Cursor
 *   node create-doc.js --folder-id ID "Doc title"   # create in folder ID
 *   node create-doc.js --folder "Cursor" "Title" "Body"  # Doc with body (needs Docs API) or .txt if no Docs API
 *   node create-doc.js --text-file --folder "Cursor" "Name" "Body"  # plain text file with body (Drive only)
 */

import { google } from "googleapis";
import { readFileSync, writeFileSync, mkdirSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { createServer } from "http";

const __dirname = dirname(fileURLToPath(import.meta.url));

const repoRoot = resolve(__dirname, "../..");
const defaultOAuthPath = resolve(repoRoot, ".cursor", "gcp-oauth.keys.json");
const defaultCredsPath = resolve(repoRoot, ".cursor", "gdrive-server-credentials.json");

const oauthPath = process.env.GDRIVE_OAUTH_PATH || defaultOAuthPath;
const credsPath = process.env.GDRIVE_CREDENTIALS_PATH || defaultCredsPath;

const WRITE_SCOPES = [
  "https://www.googleapis.com/auth/drive",
  "https://www.googleapis.com/auth/drive.file",
  "https://www.googleapis.com/auth/documents",
];

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
  if (args[0] === "auth") {
    const codeIdx = args.indexOf("--code");
    const code = codeIdx >= 0 && args[codeIdx + 1] ? args[codeIdx + 1] : null;
    return { auth: true, code };
  }
  if (args[0] === "delete" && args.length > 1) {
    return { delete: true, fileIds: args.slice(1) };
  }
  let folderName = null;
  let folderId = null;
  let textFile = false;
  const rest = [];

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--folder" && args[i + 1]) {
      folderName = args[++i];
    } else if (args[i] === "--folder-id" && args[i + 1]) {
      folderId = args[++i];
    } else if (args[i] === "--text-file") {
      textFile = true;
    } else {
      rest.push(args[i]);
    }
  }

  const title = rest[0] || "Untitled";
  const body = rest.slice(1).join(" ") || "";
  return { folderName, folderId, title, body, textFile, auth: false };
}

async function runAuth(codeFromArg) {
  const keys = loadJson(oauthPath);
  const client = keys.installed || keys.web;
  if (!client) {
    console.error("OAuth keys file must contain 'installed' or 'web'.");
    process.exit(1);
  }
  const redirectUri = "http://localhost:3333/oauth2callback";
  const oauth2Client = new google.auth.OAuth2(
    client.client_id,
    client.client_secret,
    redirectUri
  );

  if (codeFromArg) {
    let code = codeFromArg.trim();
    if (code.includes("code=")) {
      try {
        const q = code.includes("?") ? code.split("?")[1] : code;
        const u = new URL("http://x?" + q);
        code = u.searchParams.get("code") || code;
      } catch (_) {}
    }
    if (!code) {
      console.error("No code found. Paste the full redirect URL or the code= value.");
      process.exit(1);
    }
    const { tokens } = await oauth2Client.getToken(code);
    writeFileSync(credsPath, JSON.stringify(tokens, null, 2));
    console.log("Token saved to", credsPath);
    return;
  }

  const url = oauth2Client.generateAuthUrl({
    access_type: "offline",
    prompt: "consent",
    scope: WRITE_SCOPES,
  });
  return new Promise((resolvePromise, reject) => {
    const server = createServer(async (req, res) => {
      const u = new URL(req.url || "", "http://localhost");
      if (u.pathname !== "/oauth2callback" || !u.searchParams.get("code")) {
        res.writeHead(400).end("Missing code");
        return;
      }
      const code = u.searchParams.get("code");
      res.writeHead(200, { "Content-Type": "text/html" }).end(
        "<p>Auth done. You can close this tab and return to the terminal.</p>"
      );
      server.close();
      try {
        const { tokens } = await oauth2Client.getToken(code);
        oauth2Client.setCredentials(tokens);
        writeFileSync(credsPath, JSON.stringify(tokens, null, 2));
        console.log("Token saved to", credsPath);
        resolvePromise();
      } catch (e) {
        reject(e);
      }
    });
    server.listen(3333, "127.0.0.1", () => {
      const urlFile = resolve(repoRoot, ".cursor", "gdrive-auth-url.txt");
      try {
        mkdirSync(resolve(repoRoot, ".cursor"), { recursive: true });
        writeFileSync(urlFile, url);
      } catch (_) {}
      console.log("Open this URL in your browser, then approve access:");
      console.log(url);
    });
  });
}

async function runDelete(fileIds) {
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
  for (const id of fileIds) {
    await drive.files.delete({ fileId: id });
    console.log("Deleted", id);
  }
}

async function main() {
  const parsed = parseArgs();
  if (parsed.auth) {
    await runAuth(parsed.code);
    return;
  }
  if (parsed.delete) {
    await runDelete(parsed.fileIds);
    return;
  }

  const { folderName, folderId, title, body, textFile } = parsed;

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

  let parentId = "root";
  if (folderId) {
    parentId = folderId;
  } else if (folderName) {
    const q = `name = '${folderName.replace(/'/g, "\\'")}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false`;
    const res = await drive.files.list({
      q,
      fields: "files(id, name)",
      spaces: "drive",
    });
    if (!res.data.files?.length) {
      console.error(`Folder not found: "${folderName}"`);
      process.exit(1);
    }
    parentId = res.data.files[0].id;
  }

  const isTextFile = textFile;
  const fileMetadata = {
    name: title + (isTextFile && !title.endsWith(".txt") ? ".txt" : ""),
    parents: [parentId],
    mimeType: isTextFile ? "text/plain" : "application/vnd.google-apps.document",
  };

  const createOpts = {
    requestBody: fileMetadata,
    fields: "id, name, webViewLink",
  };
  if (isTextFile && body) {
    createOpts.media = { mimeType: "text/plain", body };
  }
  const created = await drive.files.create(createOpts);

  if (!isTextFile && body) {
    try {
      const docs = google.docs({ version: "v1", auth: oauth2Client });
      await docs.documents.batchUpdate({
        documentId: created.data.id,
        requestBody: {
          requests: [
            {
              insertText: {
                location: { index: 1 },
                text: body + "\n",
              },
            },
          ],
        },
      });
    } catch (e) {
      if (e.message && e.message.includes("has not been used") && e.message.includes("docs.googleapis.com")) {
        console.error("Google Docs API is disabled. Create a .txt file with --text-file or enable Docs API.");
        process.exit(1);
      }
      throw e;
    }
  }

  console.log("Created:", created.data.name);
  console.log("ID:", created.data.id);
  console.log("URL:", created.data.webViewLink);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
