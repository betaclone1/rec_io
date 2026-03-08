# Audit: Post-update TTC and monitor 10026 (2026-03-04)

**Scope:** Confirm latest update/restart addressed TTC-from-strike-tables; diagnose why monitor 10026 (15m HTC, BTC) stays INACTIVE when it should be active.

---

## 1. TTC source (unified_ttc vs strike tables)

**Result: Addressed.**

- **auto_entry_supervisor.get_current_ttc()** (lines ~1685–1712) now reads TTC **directly from PostgreSQL** strike tables:
  - Uses `get_strike_table_name(symbol, market)` and column `ttc_15m` or `ttc_hourly`.
  - No HTTP call to main app; no unified_ttc dependency for this path.
- Docstring: "Get current TTC from strike table (PostgreSQL). Uses ttc_hourly or ttc_15m per monitor market; no HTTP to main app."

---

## 2. Monitor 10026 – why INACTIVE

**Config (from DB):** id=10026, symbol=BTC, market=15m, strategy=**15m HTC**, auto_trade=true, window 120–900s.

**Root cause: `live_data.strike_table_15m_btc` has 0 rows.**

- Auto_entry_supervisor for 10026 calls `get_master_strike_table_data()` and `get_current_ttc()` against `live_data.strike_table_15m_btc`.
- With no rows:
  - `get_current_ttc()` gets no TTC → returns 0 or fallback → TTC “outside window” → INACTIVE.
  - Logs show: **"[WATCHLIST] No strike table data found in PostgreSQL"**.
- Strategy "15m HTC" is routed to `determine_auto_entry_status_hourly_htc()` (else branch). That only checks TTC window; with TTC 0 or invalid, status is INACTIVE.

**Why the 15m BTC strike table is empty**

- **strike_table_generator_15m_btc** is RUNNING and iterating.
- Each run it **clears** the table then tries to insert rows.
- Logs show: **"⚠️ Missing ask prices for strike 73708, skipping"** → **"✅ Generated 0 strike table records for BTC"**.
- So the only strike (73708) is skipped every time due to missing ask prices; the table stays empty.
- For comparison: `live_data.strike_table_hourly_btc` has 11 rows and non-null `ttc_hourly` (e.g. 2781s).

**Additional:** Generator log shows **"❌ Error getting summary: unsupported format string passed to NoneType.__format__"** — likely a None value used in a format string when no rows are written.

---

## 3. Summary

| Item | Status |
|------|--------|
| TTC from strike tables (no unified_ttc) | **Addressed** – auto_entry_supervisor reads from PostgreSQL strike tables. |
| Monitor 10026 INACTIVE | **Not a TTC-source bug.** 15m BTC strike table is empty because strike_table_generator_15m_btc skips the only strike (missing ask prices) and writes 0 rows. |
| Fix for 10026 | Populate `strike_table_15m_btc`: resolve “Missing ask prices” in strike_table_generator_15m_btc (and the NoneType format error) so it inserts rows; then 10026 will get TTC and strike data and can go ACTIVE when in window. |

---

## 4. References

- Monitor 10026: `users.monitor_list_0001` id=10026.
- Strike table: `live_data.strike_table_15m_btc` (0 rows at audit time).
- Generator logs: `logs/strike_table_generator_15m_btc.out.log`, `logs/strike_table_generator_15m_btc.err.log`.
- Auto_entry logs: `logs/auto_entry_supervisor_0001_10026.out.log`.
