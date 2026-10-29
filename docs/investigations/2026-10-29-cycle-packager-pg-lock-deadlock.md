# 2026-10-29 — Cycle packager PG lock deadlock (prod UI hang)

**Audience:** backtest / cycle packaging agent and anyone clearing prod Postgres lock storms.  
**Host:** production `165.22.13.146` (`rec-io-server-new-york-1`), project `/opt/rec_io_server`.  
**Observed:** 2026-10-29 ~17:20 UTC (ops check). Stuck sessions originated ~2026-10-26 21:13 UTC.  
**Status at write-up:** diagnosed; **sessions not yet terminated** by the investigating agent — ops clearance still required.

---

## One-line summary

`cycle_packager` held an open Postgres transaction (with `ACCESS SHARE` locks from `COPY` of hot cycle tables), then called `DROP TABLE` on a **second** connection for the same ticker → permanent wait → nightly `pg_dump` queued behind it → host load spiked → `main_app` / UI API calls hung.

This is a **packaging code deadlock**, not a dead Postgres or network outage.

---

## Symptoms (prod)

| Signal | Value / note |
|--------|----------------|
| `core.system_state.mode` | `normal` |
| Supervisor | All programs RUNNING (~24), including `cycle_packager`, `main_app` |
| Load | ~17 on 8 vCPU |
| Disk / RAM | OK (~28% disk; plenty free RAM) |
| `main_app` `GET /health` | **Timeout** (5s / 15s) — process alive but not answering |
| `trade_executor` / `read_api` health | 200 quickly |
| UI proxy latencies | `/api/monitors/health` often **7–10s**; intermittent recovery to &lt;1s |
| Operator report | Frontend “hanging trying to connect to the database” |

Postgres was **up and accepting connections**. The problem was **lock congestion**, not connectivity failure.

---

## Evidence (Postgres)

### Activity snapshot (approx)

- ~35 connections to `rec_io_db`
- Many `active` / waiting; several `idle in transaction`
- Blocked lock count &gt; 0

### Root waiters (multi-day)

Two parallel pairs (same pattern):

1. **Idle in transaction** (~2d 20h) — last query:

   ```sql
   SELECT market_ticker, floor_strike, volume_fp, market_result, updated_at
   FROM historical_data."KXBTC15M-…_market_meta"
   WHERE market_ticker = %s
   LIMIT 1
   ```

   Example tickers:
   - `KXBTC15M-26OCT220500-00`
   - `KXBTC15M-26OCT010315-15`

2. **`DROP TABLE IF EXISTS historical_data."KXBTC15M-…_snapshot"`** — `wait_event = Lock / relation`, same age, blocked by the idle-in-transaction PID above.

3. **Three stuck nightly backups** (`application_name = pg_dump`, from `scripts/backup/create_compressed_db_backup.sh`):

   - ~Oct 27 05:02 UTC  
   - ~Oct 28 05:02 UTC  
   - ~Oct 29 05:02 UTC  

   Each waiting on:

   ```sql
   LOCK TABLE historical_data."KXBTC15M-26OCT010315-15_snapshot" IN ACCESS SHARE MODE
   ```

   Blocked behind the waiting `DROP TABLE`.

### Who blocks whom (simplified)

```
idle-in-txn (SELECT market_meta / prior COPY locks)
    └── blocks DROP TABLE …_snapshot
            └── blocks pg_dump LOCK TABLE …_snapshot  (×3 nights)
```

Client addr on app sessions was the droplet itself (`165.22.13.146`) — local app → PG via configured host IP.

`cycle_packager` process uptime aligned with the stuck window (started ~Oct 26).

---

## Root cause (code)

### Files

| Path | Role |
|------|------|
| `backend/core/cycle_packager.py` | Seal / quarantine / package attempt |
| `backend/core/cycle_hot_tables.py` | `drop_cycle_tables()` |
| `backend/cycle_packager.py` | Supervisor entrypoint |
| `scripts/backup/create_compressed_db_backup.sh` | Nightly `pg_dump` (victim, not cause) |

### Mechanism

1. `package_ticker_attempt` opens a system PG connection (`get_system_postgresql_connection()` — **autocommit off** by default).

2. Inside one cursor / implicit transaction it:

   - `COPY` + `COUNT` hot tables including `…_snapshot` → holds **`ACCESS SHARE`** until commit/rollback/close  
   - `SELECT … FROM …_market_meta` (exact SQL seen in `pg_stat_activity`)

3. Cursor exits **without `conn.commit()`**. Transaction stays open while the code does **non-DB work** (Redis settle enrich, Kalshi API enrich, public trades fetch, tar build).

4. On the **aged unsealable / quarantine** path (and any path that drops via a **new** connection while the packager conn is still open):

   ```python
   # backend/core/cycle_packager.py — inside package_ticker_attempt try:
   receipt = quarantine_unsealable_cycle(..., drop=drop_after)
   ```

   `quarantine_unsealable_cycle(..., drop=True)` calls:

   ```python
   drop_cycle_tables(mt)  # conn=None → NEW connection
   ```

5. `drop_cycle_tables` on the second connection runs `DROP TABLE IF EXISTS` for all cycle tables → needs **`ACCESS EXCLUSIVE`** → **waits forever** on share locks from step 2.

6. The first call stack never returns from quarantine’s DROP, so it **never reaches** `finally: conn.close()` → locks never released → **self-deadlock**.

Successful seal path that calls `drop_cycle_tables(mt, conn)` **reusing the same connection** is fine. The bug is **drop on a second connection while the first still holds uncommitted share locks**.

### Why UI felt “DB dead”

- Multi-day waiting `DROP` + stacked `pg_dump` kept PG and CPU busy.  
- Live paths (monitors, trades updates) competed with that backlog.  
- `main_app` stayed RUNNING but `/health` timed out under load / blocked workers.  
- Misread as “can’t connect”; reality was **connect OK, queries / event loop starved**.

---

## Immediate ops remediation (production)

Do this in order. Prefer **targeted** clears over a blind MASTER_RESTART (restart alone may not kill waiting backends cleanly if clients respawn the same pattern).

### 1. Confirm current blockers

```sql
SELECT pid, state, wait_event_type, wait_event,
       now() - xact_start AS xact_age,
       now() - query_start AS query_age,
       left(query, 120) AS q
FROM pg_stat_activity
WHERE datname = 'rec_io_db'
  AND (
    state = 'idle in transaction'
    OR wait_event = 'relation'
    OR pid IN (SELECT pid FROM pg_locks WHERE NOT granted)
  )
ORDER BY xact_start NULLS LAST;
```

```sql
SELECT blocked.pid AS blocked_pid,
       left(blocked.query, 80) AS blocked_q,
       array_agg(DISTINCT blocker.pid) AS blocker_pids
FROM pg_stat_activity blocked
JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS bp(pid) ON true
JOIN pg_stat_activity blocker ON blocker.pid = bp.pid
WHERE blocked.datname = 'rec_io_db'
GROUP BY 1, 2;
```

### 2. Terminate root idle-in-transaction packager sessions

Terminate the **idle in transaction** PIDs that match the `market_meta` SELECT / aged xact (examples from incident: `3109469`, `3117996` — **re-check PIDs live**; do not copy blindly days later).

```sql
SELECT pg_terminate_backend(<idle_in_txn_pid>);
```

That should allow waiting `DROP TABLE`s to finish or fail cleanly, then unblock `pg_dump`s (or leave them to be killed — see next).

### 3. Clear orphaned nightly dumps

If `pg_dump` / `create_compressed_db_backup.sh` are still stuck after step 2:

- `pg_terminate_backend` on dump backends, and/or  
- kill the stuck bash/`pg_dump` process trees (Oct 27/28/29 cron stacks).

Re-run **one** backup only after locks are clear and load is sane.

### 4. Restart packaging + verify UI path

```bash
cd /opt/rec_io_server
./venv/bin/supervisorctl -c backend/supervisord.conf restart cycle_packager
# If main_app /health still times out after PG is clear:
./venv/bin/supervisorctl -c backend/supervisord.conf restart main_app
curl -m 5 -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/health
```

### 5. Optional: scan for other long idle-in-transaction

During the same incident a shorter idle-in-txn was also seen on `UPDATE users_0001.trades_0001 SET symbol_expiration = …` — **different subsystem**; clear only if still aged and blocking. Do not conflate with packager fix.

---

## Code fix requirements (for packaging agent)

These are the durable fixes; ops kill is temporary.

1. **Never hold an open transaction across network / API / Redis / tar I/O.**  
   After hot-table `COPY`/`SELECT`, `commit()` (or use a short-lived connection that is closed) **before** `enrich_market_meta_from_api`, public trades fetch, quarantine writes to disk, etc.

2. **Never call `drop_cycle_tables(mt)` on a new connection while the packaging connection still holds locks on those tables.**  
   Either:
   - commit/close the read/COPY connection **first**, then drop on a fresh connection; or  
   - pass the **same** `conn` into `drop_cycle_tables(mt, conn)` only after reads are done and you intend to drop in that txn; or  
   - set `drop=False` in quarantine while the parent conn is open, then drop after parent close.

3. **Quarantine path audit:** every `quarantine_unsealable_cycle(..., drop=True)` call site inside `package_ticker_attempt` must be lock-safe w.r.t. the open `conn`.

4. **Defensive PG settings (optional but useful):**  
   - `idle_in_transaction_session_timeout` (e.g. minutes, not days) on the system role or packager sessions  
   - so a future bug cannot pin locks for 70+ hours

5. **Backup coupling:** nightly `pg_dump --clean` taking `LOCK TABLE` on hot cycle snapshots will amplify any stuck DROP. Prefer not stacking overlapping dumps; alert if `pg_dump` age &gt; N minutes.

6. **Tests / review checklist:** unit or integration test that packaging + quarantine drop cannot block itself (two-connection scenario); code review gate on “DB txn open across await/HTTP.”

---

## Verification after fix

- No `idle in transaction` older than a few minutes from packager SQL.  
- No `DROP TABLE …_snapshot` waiting on `Lock/relation` for more than seconds.  
- No multi-day `pg_dump` processes.  
- `cycle_packager` logs show `package_due_cycles pass` / quarantine without wedging.  
- `main_app` `/health` 200 in &lt;1s; UI monitors APIs back to normal latency.  
- Load average returns toward historical baseline.

---

## Related docs / code

- Cycle package product: `docs/HISTORICAL_CYCLE_DATA_PRODUCT.md`, schema notes in `docs/MASTER_DB_SCHEMA_REFERENCE.md` (packaging section)  
- Maker / backtest packaging pointers: `docs/MAKER_EDGE_STRATEGY.md`  
- Prod host: `docs/PRODUCTION_HOST.md`  
- Entry: `backend/cycle_packager.py` → `backend/core/cycle_packager.py`  
- Drop helper: `backend/core/cycle_hot_tables.py` → `drop_cycle_tables`  
- Nightly dump: `scripts/backup/create_compressed_db_backup.sh`

---

## Handoff checklist for packaging agent

- [ ] Read this report end-to-end  
- [ ] Reproduce deadlock mentally / with a small local test (COPY txn open + second-conn DROP)  
- [ ] Patch txn lifetime + quarantine drop ordering  
- [ ] Add regression coverage  
- [ ] Coordinate with ops: clear any remaining stuck prod backends before/after deploy  
- [ ] Restart `cycle_packager` on prod; confirm backlog drains newest-first without multi-hour waits  
- [ ] Confirm nightly backup completes once without stacking  

**Do not** treat this as a generic “Postgres is unhealthy” ticket. Fix packaging lock discipline; then UI hang class should not recur from this path.
