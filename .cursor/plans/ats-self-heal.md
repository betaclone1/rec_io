# ATS self-heal (Redis ghost + enroll subscriber)

## Goal

Make unified ATS recover automatically when the monitoring thread stays alive but the Redis enroll/TM-notify subscriber dies or hangs, leaving closed trades as Redis “active” ghosts and blocking new open ACKs.

## Scope

- In: enroll subscriber heartbeat + supervised restart; Redis↔`trades_*` ghost sweep; periodic `sync_with_trades_db`; tick reconcile terminal-drop even on monitor mismatch; process restart escalation with cooldown.
- Out: TM closed-notify ACK protocol change; cascading_failure_detector changes; migrations.

## Steps

1. Pubsub loop uses timed `get_message` + progress mono (`ats_enrollment_redis.py`).
2. Supervised `start_ats_enroll_redis_subscriber` with hung→process restart.
3. `sweep_redis_active_trade_ghosts_vs_trades_db` + `check_ats_self_heal` in brute-force loop.
4. Fix tick reconcile terminal remove despite mon mismatch.
5. Unit tests for terminal classification + progress loop.

## Completion criteria

- [x] Dead enroll subscriber restarted without requiring monitoring thread death
- [x] Hung subscriber (no progress > stale sec) escalates to process restart
- [x] Redis pool entries whose `trades_*` status is terminal/missing are removed on a timer
- [x] Periodic sync re-enrolls missing opens from `trades_*`
- [x] Unit tests pass

## Blockers / decisions

- Hung daemon threads cannot be killed in-process; process restart is required (300s cooldown).
- After deploy: restart `active_trade_supervisor_0001` on prod and confirm Redis ghost 30100 is cleared.
