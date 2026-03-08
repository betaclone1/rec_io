# Logging vs CPU in 1s-Loop Scripts

How much of `symbol_price_watchdog` and `auto_entry_supervisor` CPU is spent writing logs? Both must run 1s loops by design; this doc summarizes their logging behavior and how to measure logging’s share of CPU.

---

## 1. Where they log (hot path)

### symbol_price_watchdog

- **Stdout:** All output is `print()` to stdout (captured by supervisord to `.out.log`).
- **Hot path (every 1s tick):**
  - One `print()` per tick after a successful DB insert:  
    `print(f"✅ {symbol} price logged: ${price:,.2f} at {timestamp}")`  
    So **1 print per second per process** (BTC and ETH each run one process).
  - One small **heartbeat file write** per tick (overwrites a single file).
- **Cold path:** Startup and error paths use more prints (profile load, reconnect, errors). No logging in the tight loop other than the one success print and heartbeat file.

So in the steady state, **1 line per second per symbol** plus one small file write. The heavy work per tick is in `insert_tick()` (DB + momentum/volatility/movement), not in the print.

### auto_entry_supervisor

- **Stdout:** All logging goes through `log()`, which does  
  `print(f"[AUTO_ENTRY_SUPERVISOR_{id} {ts}] {message}", flush=True)`.
- **Main loop:** `monitoring_worker` runs every 1s and calls `check_auto_entry_conditions()`. It does **not** log every iteration:
  - “Check #N” only every **1000** iterations (~16.7 min).
  - Heartbeat every **300** s.
- **Inside `check_auto_entry_conditions()`:** Logging depends on state. When nothing special is happening, there are **no** log calls per second. When spike-alert recovery or similar is active, there can be **several** log calls per second (e.g. “Recovery in progress”, “Cooldown timer change notification sent”, “Using adjusted probability”, “State changed, broadcasting”). So logging rate is **state-dependent**: 0/sec in quiet periods, multiple/sec during cooldown/recovery.

---

## 2. How to measure “how much CPU is logging?”

Two options: run with measurement enabled, or run with logging disabled and compare CPU.

### Option A: Measure with MEASURE_LOG_CPU (recommended)

Both scripts support an optional stdout timer. When enabled, they wrap `sys.stdout` and track time spent in `write()` and `flush()`. Every 60 seconds a single line is written to **stderr**:

- Format: `LOG_CPU_MEASURE: 0.03`  
  meaning about **3%** of the elapsed time in that 60s window was spent inside stdout write/flush (i.e. logging).

**Steps:**

1. Set the env var for the process(es) you care about, e.g. in supervisord or your run script:
   - `MEASURE_LOG_CPU=1`
2. Run for at least 1–2 minutes (one full 60s report).
3. Read the measurement from **stderr** (supervisord will put it in the `.err.log` for that program):
   - e.g. `grep LOG_CPU_MEASURE logs/symbol_price_watchdog_btc.err.log`
   - e.g. `grep LOG_CPU_MEASURE logs/auto_entry_supervisor_0001_10002.err.log`

Implementation: `backend/util/log_cpu_measure.py`. The wrapper is installed at startup when `MEASURE_LOG_CPU` is set; no code changes needed beyond that.

### Option B: Compare CPU with logging disabled

To see if logging is a big cost in practice:

1. Temporarily redirect stdout (and optionally stderr) to `/dev/null` for one instance (e.g. in supervisord set `stdout_logfile=/dev/null` for one watchdog or one supervisor).
2. Let it run for a minute or two and note CPU (e.g. `top` or `ps`).
3. Restore normal logging and compare.

If CPU drops a lot with stdout to `/dev/null`, logging is a significant cost; if it barely moves, most CPU is in the 1s-loop work (DB, HTTP, logic), not in writing logs.

---

## 3. Summary

| Script                    | Hot-path logging (steady state)     | How to get a number                          |
|---------------------------|--------------------------------------|----------------------------------------------|
| symbol_price_watchdog     | 1 print + 1 small file write per 1s | `MEASURE_LOG_CPU=1` → check stderr / .err.log |
| auto_entry_supervisor     | 0/sec when idle; multiple/sec when e.g. spike recovery | Same; run during busy and idle to compare   |

The 1s loops themselves cannot be removed; the open question is what fraction of CPU is in the actual log writes. Use **MEASURE_LOG_CPU=1** and the 60s `LOG_CPU_MEASURE` lines to get that fraction, and optionally use the `/dev/null` test for a quick sanity check.
