# Project rules

Top-level rules for the REC.IO 3.0 project. All code, config, and operations must comply.

---

## 1. Server agnostic

**Everything in this project must be server-agnostic.**

The system must run identically locally and on any remote server as a self-contained operation. No hardcoded hostnames, paths, or environment-specific assumptions that tie the project to one machine.

- Config (ports, DB, paths, credentials) comes from environment variables, config files, or the centralized config/port system (e.g. MASTER_PORT_MANIFEST, get_port(), unified_config, database.py loading env).
- The same codebase must run anywhere: local dev, staging, production, or a new server—without code changes. Any value that can vary by environment must be externalized, not hardcoded.

---

## 2. No fallbacks or defaults for required data

**We deal with real trades and real money.**

If any asset in the system needs a value to run and **does not have that value**, that is a **problem to be fixed**—not papered over.

- Do **not** add fallback or default values merely to avoid errors and allow scripts to run without the needed data.
- Missing required data must surface as a **clear failure** or **explicit configuration requirement**, not silent substitution.
- "Required" means: the system cannot correctly or safely perform its function without that value. For those cases, fail or require configuration; do not guess or default.

---

## 3. Git tracking and agent limits

**New files that are necessary for system operations or development, and that pass our standards for operational security, should be tracked with git.** Track or ignore files appropriately so the repo state is correct; the CEO determines when commits are warranted.

**Agents are not permitted to push or pull through GitHub without explicit authorization from the CEO.** Agents may create, edit, and delete files; they may stage or suggest what should be committed. Only the CEO authorizes actual push/pull. The CEO decides when commits are warranted.

---

*These rules apply to all new and existing code. When reviewing or changing scripts, config, or services, ensure compliance.*
