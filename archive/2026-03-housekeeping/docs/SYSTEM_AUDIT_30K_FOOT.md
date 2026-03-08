# Live System Audit — 30k Foot View

*Snapshot: 2025-03-06. Focus: CPU and storage hogs, categorized for housekeeping prioritization.*

---

## CPU

### By category (approximate share of top processes)

| Category | Notes | Priority |
|----------|--------|----------|
| **Cursor/IDE** | Cursor server + extension host + file watcher: ~35–45% CPU combined. Expected for active dev. | Low (env cost) |
| **rec_io_server backend** | `main.py` ~25%; two `symbol_price_watchdog` (BTC/ETH) ~13% each; **8× `auto_entry_supervisor`** ~6–7% each (~50% total). | **High** |
| **PostgreSQL** | ~10% (stats collector + main). Long uptime, normal for DB. | Low |
| **Strike/market/watchdogs** | Multiple `strike_table_generator`, `kalshi_market_watchdog`, etc. ~2–3% each, many processes. | Medium |
| **Supervisord** | ~4.5%. Orchestrator overhead. | Low |

**Takeaway:** The largest controllable CPU cost is **auto_entry_supervisor** (8 instances × ~6–7% ≈ 50%+). Then `main.py` and the two `symbol_price_watchdog` (BTC/ETH). Any reduction in supervisor count, polling frequency, or work per loop will have the biggest impact.

---

## Database (PostgreSQL)

- **Data dir:** `/var/lib/postgresql` — **~3.6 GB** on root filesystem (same 78 GB volume).
- **App database:** `rec_io_db` — **~3.5 GB** (owner `rec_io_user`).

### Size by schema (rec_io_db)

| Schema | Total size | Notes |
|--------|------------|--------|
| **live_data** | **~1.3 GB** | live_price_log_1s_* (BTC 650 MB, ETH 507 MB), price_change_*, strike_table_hourly_*, etc. |
| **historical_data** | **~1.0 GB** | btc/eth_price_history ~455/434 MB; ndx/spx_price_history ~73/69 MB. |
| **analytics** | **~1.0 GB** | probability_lookup_*_master_* tables — many at ~124 MB each (SPX/NDX/ETH/BTC, various dates). |
| users | 67 MB | trade_logs_0001, orders_0001, account_balance_0001. |
| work_progress | 18 MB | ttc_* tables. |
| testing, public, archive, system, core | &lt; 2 MB | Negligible. |

### Largest tables (rec_io_db)

- `live_data.live_price_log_1s_btc` — 650 MB  
- `live_data.live_price_log_1s_eth` — 507 MB  
- `historical_data.btc_price_history` — 455 MB  
- `historical_data.eth_price_history` — 434 MB  
- `analytics.probability_lookup_*_master_*` — 124 MB each (multiple tables/dates)

**Takeaway:** DB is the second-largest storage consumer after logs. Growth is driven by 1s price logs (live_data), historical price tables, and analytics lookup tables. Retention/partitioning on live_price_log_1s_* and pruning old probability_lookup_* snapshots are the main levers.

---

## Storage (within `/opt/rec_io_server`)

**Total workspace: ~16 GB.** Root filesystem 78 GB, **~30 GB used** (workspace + database + system). Database lives under `/var/lib/postgresql` (~3.6 GB), not under the repo.

### By top-level directory

| Directory | Size | Notes |
|-----------|------|--------|
| **logs** | **~13 GB** | Dominant. ~2,100 log files. |
| **backup** | **~2.4 GB** | Old user_data_package + DB dump (Nov 2025). |
| **venv** | 402 MB | Python env. Normal. |
| **.git** | 143 MB | Repo history. Normal. |
| **frontend** | 45 MB | |
| **backend** | 18 MB | |
| **docs, scripts, archive, etc.** | &lt; 4 MB | Negligible. |

### Logs breakdown

| Category | Size | Notes |
|----------|------|--------|
| **.out.log** (stdout) | ~6.7 GB | Supervisor/app stdout. |
| **.err.log** (stderr) | ~5.1 GB | Many at ~51 MB each (strike_table_generator_*, system_monitor). |
| **log_archive** | ~2 GB | Archived/rotated logs. |
| **Single large** | 167 MB | e.g. `auto_entry_supervisor_0001_10018.log.1` in archive. |

**Largest single files**

- `backup/user_data_package_20251112_173357/database_backup.sql` — **1.7 GB**
- `backup/*.tar.gz` — ~360 MB and ~355 MB (Nov 2025)
- `.git/objects/pack/...` — 81 MB
- Many **51 MB** `.err.log` files (strike_table_generator SPX/NDX/hourly, system_monitor)

**Takeaway:** Logs (~13 GB), database (~3.5 GB), and backup (~2.4 GB) are the main disk consumers. Log rotation/retention and backup pruning free the most space in the repo; DB retention/partitioning affects root FS.

---

## Process count (rec_io_server + supervisord)

- **~37** app-related processes (supervisord tree + backend workers).
- **8** auto_entry_supervisor instances.
- Multiple strike_table_generator, kalshi watchdogs, symbol_price_watchdog (2), active_trade_supervisor, etc.

---

## System storage summary (root FS, ~30 GB used)

| Category | Location | Size |
|----------|----------|------|
| **Logs** | `/opt/rec_io_server/logs` | ~13 GB |
| **Database** | `/var/lib/postgresql` (rec_io_db) | ~3.6 GB |
| **Backups** | `/opt/rec_io_server/backup` | ~2.4 GB |
| **Venv + .git + app code** | `/opt/rec_io_server` (rest) | ~0.6 GB |
| **System + other** | elsewhere on `/` | remainder |

---

## Housekeeping priorities (summary)

1. **CPU**
   - **auto_entry_supervisor**: 8 instances; largest single CPU consumer. Consider fewer instances, less frequent work, or batching.
   - **symbol_price_watchdog** (BTC/ETH): ~26% combined; review poll interval / work per tick.
   - **main.py**: ~25%; profile and trim hot paths if possible.

2. **Storage (filesystem)**
   - **Log retention/rotation**: 13 GB logs, 2,100 files; tighten retention and rotation (especially .err.log) so fewer 51 MB files accumulate.
   - **Backup**: 2.4 GB in Nov 2025 backups; prune or move old backups off-box; consider excluding or compressing the 1.7 GB DB dump.
   - **Strike_table_generator / system_monitor .err.log**: Reduce verbosity or separate noisy stderr so rotation doesn’t keep 51 MB blobs.

3. **Storage (database)**
   - **live_data**: ~1.3 GB; `live_price_log_1s_btc`/`_eth` dominate (650 MB + 507 MB). Add retention/partitioning or down-sample old 1s data.
   - **analytics**: ~1 GB in probability_lookup_*_master_* tables (124 MB each). Prune or archive old snapshot dates.
   - **historical_data**: ~1 GB; btc/eth_price_history largest. Consider retention policy if history grows unbounded.

4. **Low priority for now**
   - Cursor/IDE, PostgreSQL, supervisord, venv, .git: acceptable for current usage.
   - frontend/backend/docs: small; no action needed for disk.
