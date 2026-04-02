# Investigation notes — AES / probability vs price (2026-04-02 ~10:57 ET)

## Established fact: live price feed → DB

**Conclusion:** For the window surrounding auto-entries around **2026-04-02 10:57 US/Eastern**, the **1 Hz price logs in Postgres were healthy** and consistent with normal recording.

**Evidence (production `live_data`):**

- **Tables:** `live_price_log_1s_eth`, `live_price_log_1s_btc`
- **Window checked:** `10:50`–`11:05` ET
- **Gaps:** No multi-second gaps **in that window** except one **ETH** gap **11:03:17 → 11:03:21 (4 s)** (after the incident window)
- **Data quality:** No null/non-positive `price` in that window
- **Cadence:** Per-minute counts ~60 ticks (59–60 at minute boundaries is normal)
- **Watchdog logs (`market_watchdog_ws_kalshi_15m` / `hourly`):** No WARN/ERROR lines in **`10:50`–`10:57`** tied to BTC/ETH feed health; later **11:00** subscribe-ack warnings are **after** the trades

**Implication:** Mismatch between **logged trade probability** and **replay from static lookup tables using the 1s log as “spot”** is **unlikely** to be explained by a broken or missing **live_price_log_1s_*** stream at that time. Next suspects stay **upstream of that replay** (e.g. `live_symbol_status` vs 1s log, strike table snapshot / STG inputs, AES read/cache timing).

## Related trades (context)

- ETH 15m Rising Devil ~**10:57:13** (`mon_0001_10037`, `KXETH15M-26APR021100-00`)
- BTC hourly Rising Devil ~**10:57:16** (`mon_0001_10034`, `KXBTCD-26APR0211-T66899.99`)

## Strike table generator WS logs (production, 2026-04-02 ~10:56–10:58 ET)

**Files:** `strike_table_generator_ws_15m.err.log`, `strike_table_generator_ws_hourly.err.log` (INFO is routed here).

**Errors:** No `ERROR` / `Exception` / `Traceback` lines on **2026-04-02** in either file (full-day grep). No `WARN`/`ERROR` in **`10:50`–`11:02`** for the incident window.

**15m (`KX*15M-26APR021100`):** Continuous `strike refresh ok` for **BTC** and **ETH**, **`rows=1`** each, including seconds **10:57:12–10:57:14** bracketing the ETH auto-entry time.

**Hourly (`KXETHD-26APR0211` / `KXBTCD-26APR0211`):** Continuous `strike refresh ok`. **BTC** stable **`rows=21`**. **ETH** hourly ladder **row count oscillates:** **`rows=5`** early 10:56, then **`rows=6`** from ~**10:56:21** through **10:57:06**, then **`rows=5`** again from **10:57:08** onward through at least **10:57:39** (matches one fewer market row in the WS snapshot, not a logged failure).

**Interpretation:** Two separate generator processes both report **successful** refreshes; nothing in these logs points to Kalshi watchdog or an obvious thrown failure. The **ETH hourly `rows=5` vs `6`** transition aligns in **time** with the bad entries but only directly affects **`strike_table_hourly`** for ETH, not the **15m** ladder used by the ETH 15m monitor (still worth correlating with `live_symbol_status` / buffer for any cross-talk or operator confusion). **BTC hourly** ladder width was unchanged.

## Price → STG comms spine (reference)

1. **`symbol_price_watchdog_{btc,eth,...}`** inserts **`live_data.live_price_log_1s_*`**.
2. **Trigger** upserts **`live_data.live_symbol_status`** (one row per symbol).
3. **`live_symbol_status`** has **`live_symbol_status_rec_io_db_notify`** → **`rec_io_db_changes`** → **`redis_switchboard`** publishes **`database: "live_symbol_status"`** on **`rec_io:db_changes`** (same contract as `docs/REALTIME_BACKBONE.md`).
4. **`strike_table_generator_ws`** subscribes to **`rec_io:db_changes`** and coalesces on **`live_symbol_status`** **and** **`market_kalshi_15m`** or **`market_kalshi_hourly`** (plus debounce / `min_refresh_sec`).

**read_api** is not on this path for STG refreshes (no evidence it writes price tables).

## Comms / logs — production, incident minute (10:57 ET = 14:57 UTC)

**`redis_switchboard.err.log` (rotated):** Incident window appears in **`redis_switchboard.err.log.5`** (current files may only hold later high-churn minutes). For **`2026-04-02T14:57:*` UTC** (~one minute):

- **`Published db_change live_symbol_status`:** **228** (no gaps implied; feed + NOTIFY + Redis publish active).
- **`strike_table_15m`:** **268**; **`strike_table_hourly`:** **122**; **`market_kalshi_hourly`:** **3410** (noisy market table).
- **No** `ERROR` / `fail` / `exception` lines in that minute in that file.

**`main_app.err.log` / `read_api.err.log`:** Filtered pass on **`2026-04-02T10:50`–`11:02` ET** — **no** Redis forwarder / db_changes / matching WARN-ERROR lines for this probe (**read_api** had **0** lines in `10:5*` window in `.err`).

**`symbol_price_watchdog_*`:** **ETH** logged **`WebSocket connection closed… Reconnecting`** at **`2026-04-02T10:53:17-04:00`**; **no** WARN/ERROR in **`10:56`–`10:57`** ET for BTC/ETH watchdogs. (DB 1s ticks were already verified healthy through **`10:57`**.)

**Conclusion (comms slice):** For the incident minute, **backbone NOTIFY → Redis for `live_symbol_status` is extremely active**, not silent or failed. **No red flag** in the sampled **main/read_api/watchdog** logs in the tight window; the only notable event is **ETH price WS reconnect ~4 minutes earlier**, which does not coincide with missing 1s ticks at decision time.

## Audit: `live_price_log_1s_*` → `live_symbol_status` → STG spot

**Trigger:** `live_data.trg_sync_live_symbol_status_from_price_log` on **`AFTER INSERT OR UPDATE`** copies **`NEW.price`**, **`NEW.one_minute_avg`**, **`NEW.momentum_percentile`**, etc. into **`live_symbol_status`** (`ON CONFLICT (symbol) DO UPDATE` replaces all mirrored columns). So for a given symbol, **after each committed tick the status row matches that tick’s row** in the 1s log — there is no second writer in this path.

**STG (WS)** reads **`COALESCE(one_minute_avg, price)`** from **`live_symbol_status`** as **spot for buffer / probability** (`strike_table_generator_ws.get_current_market_data`), **not** raw `price` alone.

**Production schema note:** On prod, **`live_symbol_status.price`** and **`one_minute_avg`** are **`numeric(10,2)`** (same as `live_price_log_1s_eth` in the sample query — not high-precision subpenny in this table).

### Incident window replay (`2026-04-02T10:56:50`–`10:57:25` ET, from `live_price_log_1s_*`)

**BTC:** Whenever both columns are non-null, **`COALESCE` picks `one_minute_avg`**. In this stretch, **`one_minute_avg` is typically ~$40–65 above `price`** (e.g. at **10:57:16**: price **~66926**, avg **~66969**, STG spot **~66969**). That is **order-of-magnitude** enough to change **buffer** vs **~$66,800 / $66,900** strikes versus using the printed **last** price.

**ETH:** **`|one_minute_avg - price|`** is only **~$1–3** in the same window — same mechanism but **much smaller** effect; unlikely alone to explain an **~80%** surprise vs replay on raw **`price`**.

**Conclusion:** The chain is **consistent** (trigger not dropping ticks). The actionable insight is **semantic**: **“healthy 1s `price`” ≠ “spot used by STG”** when **`one_minute_avg`** is smooth and **`price` moves fast**; replay against lookup tables should use **`coalesce(one_minute_avg, price)`** from the log row, not **`price` alone**, to match STG.

_Last updated from prod checks in-repo; adjust if new evidence appears._
