# /log-chat command

The PM may update the chat summary log (`.cursor/pm/brain/15_chat_summary_log.md`) **on its own** whenever it would be helpful. **/log-chat** is the **user's tool** to explicitly request an update: when you invoke it, the agent must:

1. **Summarize the current chat** — Topics discussed, key decisions, changes made (files, config, commands), outcomes (success/failure), and any open questions or follow-ups. Be as technical and detailed as necessary for a future session to reconstruct context; memory docs are for the PM's use first—human readability not required.
2. **Append a log entry** — Add a dated and timestamped entry to `.cursor/pm/brain/15_chat_summary_log.md`. Newest entries at the top of the log. Do not remove or overwrite existing entries.

**Defined in:** `.cursor/commands/log-chat.md` and `.cursor/skills/log-chat/SKILL.md`.

## Why this exists

The chat summary log is a **chronological record** of sessions. The agent is allowed to add entries proactively; /log-chat is your way to call for an update when you want one. It complements the rest of memory (topic-based docs, handoff notes in 14, task lists in 13). When starting a **new chat**, the PM (and any agent using this context) should review all memory docs **including the chat summary log** to refresh context.
