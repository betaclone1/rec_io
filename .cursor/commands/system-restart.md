---
description: "Run MASTER_RESTART, wait for completion, then run the full verify workflow (health, supervisor, logs, summary)."
---

# System restart and verify

Run a full system restart, then run the **verify** command so the same report (including the required status block) is always produced.

**Execute in order (do not skip or only describe):**

1. **Run MASTER_RESTART** — From the project root, run: `bash scripts/MASTER_RESTART.sh` (or `./scripts/MASTER_RESTART.sh`). Use a single blocking invocation so the command runs to completion. Do not background it. **Important:** The script must stop supervisor and kill processes on ports; run it with full/unrestricted permissions (e.g. request `all` or disable sandbox for this invocation) so it can succeed. Sandboxed runs will fail with PermissionError or "port in use."
2. **Wait for completion** — The script exits when the restart is done. Proceed only after it has finished.
3. **Run the verify command** — Execute the full verify workflow **exactly as the verify command specifies** (`.cursor/commands/verify.md` and verify skill). That means: Health, Supervisor, Logs, Summary, and **the required status block at the end** (the `---` / `## VERIFY STATUS` / icon line / "(If icon does not render: ...)" block; do not report "All good" if there are errors in logs). Do not omit any verify step; you are running verify after the restart.

Ports and log paths: .cursor/pm/brain/02_services_ports.md and project `logs/` directory. Full verify spec: .cursor/commands/verify.md and .cursor/pm/VERIFY_COMMAND.md.
