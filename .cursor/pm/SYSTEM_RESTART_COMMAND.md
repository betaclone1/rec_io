# /system-restart command

When the user invokes **/system-restart**, the agent must:

1. **Run MASTER_RESTART** — Execute `bash scripts/MASTER_RESTART.sh` from the project root. Run it as a blocking command; wait for the script to exit. The script must stop supervisor and free ports, so run it with full/unrestricted permissions (e.g. request `all` for the shell invocation); a sandboxed run will fail with PermissionError or "port in use."
2. **Run the verify command** — After the script completes, execute the full verify workflow exactly as the verify command specifies ([VERIFY_COMMAND.md](VERIFY_COMMAND.md), `.cursor/commands/verify.md`): health, supervisor, logs, summary, and the **required status block** at the end (`---` then `## ✅ All good` or `## ⚠️ Investigate` or `## 🔴 Critical`).

**Defined in:** `.cursor/commands/system-restart.md` (slash command) and `.cursor/skills/system-restart/SKILL.md` (skill). If `/system-restart` does not appear when you type `/`, try typing `/system-restart` anyway, or say "run system restart".

## Agent behavior

The agent must **execute** the restart and verification, not describe how. Run the script, wait for completion, then run all verify checks and report results.
