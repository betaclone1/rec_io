# Log current chat (/log-chat)

When the user invokes **/log-chat**, they are requesting a log update. Summarize the current chat and append a dated, timestamped entry to the chat summary log. (The PM may also update the log on its own when helpful; /log-chat is the user's tool to request an update.)

## Steps

1. **Summarize the current chat**
   - What was discussed (topics, questions, requests).
   - Key decisions (by user or agent).
   - Changes made (files edited, commands run, config updates).
   - Outcomes (what succeeded, what failed and why).
   - Open questions or follow-ups for later.
   - Be as technical and detailed as necessary for a future session to reconstruct context; the log is for the PM's use first—human readability not required.

2. **Append to the chat summary log**
   - File: `.cursor/pm/brain/15_chat_summary_log.md`.
   - Add a new entry with **date and time** (e.g. 2026-03-07 15:30 EST) and the summary.
   - Place **newest entries at the top** of the "Log entries" section.
   - Do not delete or overwrite existing entries; only append.

This log is part of the brain. On **new chat** start, review all brain documents including this chat summary log to refresh context.
