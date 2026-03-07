# Cursor IDE — UI, features, and configuration

Reference for Cursor editor so PM and agents understand the environment we run in. Sourced from official docs and community. Doc index: https://cursor.com/llms.txt .

---

## What Cursor is

Cursor is a VS Code–based IDE with integrated AI: Agent (Chat/Composer), Tab completion, Inline Edit, rules, MCP, codebase indexing. It uses the same defaults as VS Code plus AI-specific shortcuts and settings.

---

## Opening Chat or Composer in a separate window

- **Chat:** Use “Open Chat as Editor” (or equivalent in the Chat panel), then **right‑click the Chat tab** → **“Move into New Window”**. Chat then runs in its own window (e.g. second monitor).
- **Composer:** Use the **three‑dot menu** in Composer → **“Open as Editor”**, then **right‑click the Composer tab** → **“Move into New Window”**. Composer then runs in its own window.
- **Composer view modes:** **Bar view** (inline): `Ctrl+I` / `Cmd+I`. **Pane view** (docked sidebar): `Ctrl+I` then `Ctrl+D` / `Cmd+I` then `Cmd+D`. **Control Panel** (floating): `Ctrl+Shift+I` / `Cmd+Shift+I` — in some versions this was removed or changed; if it doesn’t open a movable floating window, use “Open as Editor” + “Move into New Window” instead.
- Community requests for a single unified window (Chat + Composer + Review) exist; not all are implemented. Rely on “Open as Editor” + “Move into New Window” for a separate window.

---

## Keyboard shortcuts (main AI-related)

| Action | Mac | Windows/Linux |
|--------|-----|----------------|
| Toggle Sidepanel (Agent/Chat) | Cmd + I or Cmd + L | Ctrl + I or Ctrl + L |
| Inline edit | Cmd + K | Ctrl + K |
| Composer (Bar/Pane) | Cmd + I | Ctrl + I |
| Composer Pane (after opening) | Cmd + D | Ctrl + D |
| Composer Control Panel (floating) | Cmd + Shift + I | Ctrl + Shift + I |
| Mode menu | Cmd + . | Ctrl + . |
| Rotate Agent modes | Shift + Tab | Shift + Tab |
| Loop AI models | Cmd + / | Ctrl + / |
| Accept Tab suggestion | Tab | Tab |
| **Cursor Settings** | Cmd + Shift + J | Ctrl + Shift + J |
| General (VS Code) settings | Cmd + , | Ctrl + , |
| Keyboard shortcuts editor | Cmd + R then Cmd + S | Ctrl + R then Ctrl + S |
| Command Palette | Cmd + Shift + P | Ctrl + Shift + P |

Customize: open keyboard shortcuts (Cmd+R, Cmd+S), search for the command, click pencil, press new keybinding, press Return.

---

## Agent modes

| Mode | Best for | Can edit files? |
|------|----------|------------------|
| **Agent** | Building features, refactoring, fixing bugs, running commands | Yes |
| **Ask** | Understanding code, exploring architecture (read-only) | No |
| **Plan** | Complex features; review approach before applying | Yes, after approval |
| **Debug** | Tricky bugs needing runtime evidence | Yes |

Switch: **Shift + Tab** to cycle modes, or use the mode picker dropdown in the Agent panel. **Each mode has its own context** — switching starts a fresh conversation. Rules (project, user, team) apply in all modes.

---

## Agent (Chat / Composer) behavior

- **Start:** Cmd+I / Ctrl+I to open panel, type request, press Return. Agent searches codebase, edits files, runs terminal, fixes errors.
- **Interrupt:** Stop button to halt mid-task.
- **Review:** Edits show in diff view; accept or reject. **Restore Checkpoint** (hover previous message, bottom right) rolls back all changes after that point.
- **Queue:** You can send follow-up messages while Agent is working; they queue and run in order. Drag to reorder.
- **Subagents:** Agent can delegate to subagents (research, shell, browser). Custom subagents: add markdown under `.cursor/agents/`.
- **Images:** Agent can generate images from text or references; saved to project, shown inline.
- **Cloud Agents:** cursor.com/agents for browser-based runs.

---

## Rules (project, user, team, AGENTS.md)

- **Project rules:** `.cursor/rules/` — markdown (`.md` or `.mdc`). Version-controlled, scoped to codebase. Frontmatter: `description`, `globs`, `alwaysApply`. Types: Always Apply, Apply Intelligently, Apply to Specific Files (globs), Apply Manually (@mention).
- **User rules:** Cursor Settings → Rules — global, apply to Agent (Chat). Not applied to Inline Edit (Cmd+K).
- **Team rules:** Dashboard (Team/Enterprise). Precedence: Team → Project → User. Can be enforced (required for all).
- **AGENTS.md:** Project root (and subdirs). Plain markdown, no frontmatter. Simple alternative to `.cursor/rules`. Nested AGENTS.md in subdirs applies when working in that subtree; more specific overrides.
- **Create rule:** Cursor Settings → Rules, Commands → + Add Rule; or in chat type `/create-rule` and describe. Rules do **not** affect Tab or other non-Agent features. Best practice: &lt;500 lines, reference files, check into git.

---

## @ mentions and context

- **@** in chat or Cmd+K attaches context. Types: **@file** (e.g. `@auth.ts`), **@folder** (e.g. `@src/components/`), **@codebase** (semantic search), **@symbol** (e.g. `@getUserById`), **@Docs**, **@Past Chats**, **@web**. Multiple @ refs allowed.
- Typing `@` shows suggestions. Long files are chunked and reranked in Chat; in Cmd+K you can choose full file, outline, or chunked.
- `.cursorignore` blocks access to paths from @ refs, Tab, Agent, and Inline Edit (but **not** from terminal or MCP tools).

---

## Codebase indexing and ignore files

- **Indexing:** Automatic when project is opened; vector embeddings for semantic search. Syncs periodically (e.g. every 5 min). Improves Agent discovery and @codebase.
- **`.cursorignore`:** Project root, `.gitignore` syntax. Excludes files from indexing, @ refs, Tab, Agent, Inline Edit. Terminal and MCP bypass. Use for security (keys, secrets) and performance (node_modules, dist, etc.). Pattern examples: `dist/`, `*.log`, `**/logs`, `!important.log`.
- **`.cursorindexingignore`:** Exclude from index only; files still accessible to AI (e.g. large generated files).
- **Hierarchical:** Cursor Settings → Features → Editor → “Hierarchical Cursor Ignore” to use `.cursorignore` in parent dirs.
- **Default ignores:** .gitignore plus a long default list (lock files, media, build dirs, .env*, node_modules, etc.). See https://cursor.com/docs/reference/ignore-file . Override with `!` in `.cursorignore`.

---

## MCP (Model Context Protocol)

- **Purpose:** Connect Cursor to external tools and data (DBs, APIs, GitHub, Linear, Notion, etc.). Agent can use MCP tools when relevant.
- **Resources:** Tools (functions), Resources (data), Prompts (templates). Agent detects enabled servers and uses them automatically.
- **Config:** `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project, can be committed). Add servers via Cursor Marketplace “Add to Cursor” or manually.
- **Settings:** Cmd+Shift+J → Tools & MCP — toggle individual tools; optional auto-run without approval.

---

## Cursor Settings (Cmd+Shift+J / Ctrl+Shift+J)

- **Features:** Chat & Composer (stickiness, auto-scroll, auto-apply, lints), Codebase Indexing (index new files, ignore, git graph), Editor (tooltips, links, Cmd+K behavior, diffs), Terminal (hover hints, preview). Docs, Tab, etc.
- **Rules, Commands:** Add/edit project and user rules, slash commands.
- **Tools & MCP:** Enable/disable MCP tools, auto-run behavior.
- **Models, usage, privacy, account:** Per help/docs.

---

## Other UI and behavior

- **Tab completion:** Multi-line, cross-file; accept by word or full. “Jump in file” for next edit location.
- **Inline Edit (Cmd+K):** Quick edits in place. User rules do **not** apply.
- **Command Palette:** Cmd+Shift+P — “Cursor Settings”, “Keyboard Shortcuts”, etc.
- **Docs:** Full sitemap at https://cursor.com/llms.txt . Help: cursor.com/help/* . Reference: cursor.com/docs/reference/* .

---

## Summary for Eric’s question (separate window)

To use Chat (or Composer) in a **separate window**: open Chat or Composer → use “Open as Editor” (or “Open Chat as Editor”) → right‑click the new **tab** → **“Move into New Window”**. That tab then runs in its own window so you can keep the main project editor in one window and the conversation in another (e.g. second monitor).
