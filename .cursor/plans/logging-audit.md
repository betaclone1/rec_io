# System-wide logging audit

**Goal:** Reduce log volume across services so logging does not cause system lag or ballooning storage; keep enough signal for operations and debugging.

**Scope:** In: scripts/services under logs/ (e.g. auto_entry_supervisor, trade_manager, kalshi_account_sync, watchdogs); logging policy; logrotate/retention. Out: log aggregation tooling (consider later).

**Status:** done

## Steps
1. Identify main offenders: which scripts/services produce the largest or most frequent log output.
2. Define logging policy: what at INFO vs DEBUG vs development-only; reduce per-tick/per-order/per-request chatter.
3. Trim or gate verbose logs (full payloads, repeated status lines, low-value success confirmations).
4. Consider log levels, conditional verbose logging, or sampling for high-frequency paths.
5. Revisit logrotate/retention so retained volume is bounded after the audit.

## Completion criteria
- [x] Offenders identified and documented
- [x] Policy documented (INFO/DEBUG/dev-only)
- [x] Verbose logs reduced in key services
- [x] Retention/rotation reviewed and bounded

## Blockers / decisions
- Logs: `logs/*.out.log`, `*.err.log`; rotation in `config/logrotate.conf`. Supervisor redirects stdout/stderr.
