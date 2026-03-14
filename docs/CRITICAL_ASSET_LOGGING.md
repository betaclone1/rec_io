# Critical-asset logging policy

Components that are essential for reliability and incident investigation must keep adequate logs: durable location, sufficient retention, and consistent timestamps so we can answer "what happened?" after an outage.

## Critical assets

- **supervisord** — Process control; its log is the source of truth for spawn/stop/exit of every service. Lost or truncated = we cannot reconstruct process lifecycle.
- **system_monitor** — Health checks and recovery; when it misbehaves or crashes we need pre-failure and recovery-attempt history.
- **cascading_failure_detector** — Secondary failure detection; same need for pre-failure and recovery history.

## Requirements

1. **Supervisord**
   - Log file under project `logs/` (durable), not `/tmp` (lost on reboot).
   - Rotation with backups: e.g. 50MB max, 10 backups, so we retain ~500MB of supervisor history.
   - No change to socket/pid location (e.g. stay in `/tmp`) unless we explicitly migrate them.

2. **Critical services (system_monitor, cascading_failure_detector)**
   - Higher retention than default: e.g. stdout 20MB × 10 backups, stderr 10MB × 10 backups, so we have more history for post-incident review.
   - All application log lines must include an ISO-style timestamp (e.g. EST with offset); see LOGGING_INVENTORY.md.

3. **All supervised services**
   - Default remains 10MB stdout / 5MB stderr, 5 backups (unchanged).
   - Single destination: stdout/stderr only; no script-owned log files unless documented.

## Gaps that led to 2026-03-14 investigation limits

- Supervisord log was in `/tmp` with no rotation; on prod the file was the only copy and pre-incident entries were not in the segments we inspected; `/tmp` is also lost on reboot.
- system_monitor stderr in rotated `.1` had no per-line timestamps (Python default format from other modules), making it hard to correlate with supervisor events.
- system_monitor stdout had only one line for the incident window (07:14 "33 failed"); no prior lines in the current file, so we could not see what led to that check.

## Implementation

- **Generator:** `scripts/config/generate_unified_supervisor_config.py` writes supervisord `logfile` to `logs/supervisord.log` with `logfile_maxbytes=50MB`, `logfile_backups=10`. For program sections, `system_monitor` and `cascading_failure_detector` get larger `*_logfile_maxbytes` and `*_logfile_backups` (see generator constants).
- **Local/dev:** `backend/supervisord.conf` may still use `/tmp` for supervisord; for production, config is generated and must use the durable path. If you run the generator locally, you get the durable path.
- **Existing docs:** LOGGING_INVENTORY.md describes per-script logging; this doc describes retention and location for critical assets only.

## After deployment

- Regenerate supervisor config on prod so supervisord uses `logs/supervisord.log` with rotation.
- Restart supervisord (or the whole stack) so it reopens the new log path. Existing `/tmp/supervisord.log` is not migrated; new history will go to `logs/`.
