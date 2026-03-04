# Fixed-Point Migration (count_fp) — Backend Record-Keeping Audit

**Context:** [Kalshi Fixed-Point Migration](https://docs.kalshi.com/getting_started/fixed_point_migration) — contract count fields are moving from integer to fixed-point strings (`*_fp`). Legacy integer fields will stop being returned after **March 12, 2026**; fractional trading is enabled per-market starting week of **March 9, 2026**.

**Scope of this audit:** Where we **record** Kalshi contract-count-related values in our backend (scripts + DB). Order **submission** (sending count/count_fp to Kalshi) is out of scope.

**Goal:** Ensure we record all `count_fp` (and equivalent `*_fp`) fields wherever we currently record integer count fields, so we have a safe migration path and no data loss when legacy fields are removed or truncated.

---

## 1. Scripts that write count-related data from Kalshi

### 1.1 `backend/kalshi_account_sync_ws.py` (primary live sync)

| Sync function      | API source / endpoint     | Fields read from Kalshi     | Table written        | Columns written                    |
|--------------------|---------------------------|-----------------------------|----------------------|------------------------------------|
| `sync_positions()` | GET /portfolio/positions  | `total_traded`, `position`   | users.positions_0001 | total_traded, position             |
| `sync_fills()`     | GET /portfolio/fills      | `count`                     | users.fills_0001     | count                              |
| `sync_settlements()` | GET /portfolio/settlements | `yes_count`, `no_count`    | users.settlements_0001 | yes_count, no_count              |
| `sync_orders()`    | GET /portfolio/orders     | `initial_count`, `remaining_count`, `fill_count` | users.orders_0001 | initial_count, remaining_count, fill_count |

**Additional:** WebSocket fallback for fills (`use_websocket_fallback_for_fills`) builds a synthetic fill with `"count": abs(ws_data.get("position", 0))`. No API `count_fp` there; if we add count_fp to fills table, fallback could set it from a position_fp if available, or leave null.

**Action for count_fp:** For each of the four sync functions, add reading of the corresponding `*_fp` fields from the API response and persist them (see DB section below). No behavior change yet—just record in parallel.

---

### 1.2 `backend/api/kalshi-api/kalshi_historical_ingest.py` (batch/historical ingest)

Used for one-off or periodic full sync from Kalshi (and from local JSON written by its own `sync_*`). All write to PostgreSQL `users.*` tables.

| Function                 | Data source              | Fields used                 | Table                | Columns written                    |
|--------------------------|--------------------------|-----------------------------|----------------------|------------------------------------|
| `write_fills_to_db()`    | sync_fills → fills.json  | `count`                     | users.fills_0001     | count                              |
| `write_positions_to_db()`| REST /portfolio/positions| `total_traded`, `position`  | users.positions_0001| total_traded, position             |
| `write_settlements_to_db()` | sync_settlements → settlements.json | `yes_count`, `no_count` | users.settlements_0001 | yes_count, no_count          |

**Note:** `write_fills_to_db()` uses a table definition that only has `count` (no yes_price_fixed etc.). Fills in the JSON may come from an older sync; when we add count_fp to the API response, we should also persist it in this path (and add column if not present). Same for positions and settlements: once API returns `*_fp`, historical ingest should record them.

**Other in same file:** `ingest_fills()` and `ingest_positions()` write to **SQLite** under `get_accounts_data_dir()` (local dbs like `fills.db`, `positions.db`) with different schemas. Lower priority for this audit; can add count_fp there later if those DBs are still used.

---

### 1.3 `backend/trade_manager.py` (consumes count; does not write raw Kalshi payload)

- **Reads** from `users.orders_0001`: `remaining_count`, `fill_count`, `initial_count` (and fees/costs) to confirm open/close and to set `position` on `users.trades_0001`.
- **Writes** to `users.trades_0001`: `position` (from `fill_count` when confirming open) and PnL-related fields.

So trade_manager does not write Kalshi API responses directly; it writes **derived** trade records. For “record all count_fp” we do **not** need to change trade_manager in this phase. Later, if we want fractional positions in trades_0001, we would add a position_fp (or equivalent) and optionally derive it from fill_count_fp / orders.

---

### 1.4 `backend/trade_executor.py` (order submission — out of scope)

- Builds order payload with `"count"` from request data. User asked to ignore order submission for now; when we migrate submission to count_fp, we’ll touch this.

---

## 2. Database tables (users schema) — count-related columns

Existing columns and suggested additions for recording `*_fp` in parallel. Type for `*_fp` is string (e.g. TEXT) per Kalshi.

| Table                  | Existing count-related columns     | Add for fixed-point (record only)   |
|------------------------|------------------------------------|-------------------------------------|
| users.fills_0001       | count (integer)                    | count_fp (TEXT)                      |
| users.orders_0001      | initial_count, remaining_count, fill_count (integer) | initial_count_fp, remaining_count_fp, fill_count_fp (TEXT) |
| users.positions_0001   | total_traded, position (integer)   | total_traded_fp, position_fp (TEXT)  |
| users.settlements_0001  | yes_count, no_count (integer)       | yes_count_fp, no_count_fp (TEXT)     |

**Note:** Kalshi’s migration doc explicitly names `count` → `count_fp` for contract counts. For orders, the doc says “count fields” transition to `*_fp`; we assume order size fields map to `initial_count_fp`, `remaining_count_fp`, `fill_count_fp` (confirm against Kalshi API response when implementing). For positions and settlements, same idea: record any `*_fp` fields the API returns for contract counts.

---

## 3. Summary: what to do (no patches yet)

1. **kalshi_account_sync_ws.py**  
   - In `sync_fills`: read `count_fp` from each fill, add column `count_fp` to users.fills_0001, write it.  
   - In `sync_orders`: read `initial_count_fp`, `remaining_count_fp`, `fill_count_fp` (or whatever the API names), add columns to users.orders_0001, write them.  
   - In `sync_positions`: read `position_fp`, `total_traded_fp` (or equivalent), add columns to users.positions_0001, write them.  
   - In `sync_settlements`: read `yes_count_fp`, `no_count_fp` (or equivalent), add columns to users.settlements_0001, write them.  
   - WebSocket fill fallback: optionally set count_fp from position if available, or leave null.

2. **kalshi_historical_ingest.py**  
   - In `write_fills_to_db`: if API/JSON includes count_fp, add column and write it.  
   - In `write_positions_to_db`: add total_traded_fp, position_fp if API provides them.  
   - In `write_settlements_to_db`: add yes_count_fp, no_count_fp if API provides them.

3. **Migrations**  
   - Add the new `*_fp` columns to the four tables (fills, orders, positions, settlements) as nullable TEXT so existing rows and code paths remain valid.

4. **trade_manager / trade_executor**  
   - No change in this “record count_fp only” phase. Order submission and use of count_fp for business logic can be a later step.

---

## 4. Reference: Kalshi migration doc (excerpts)

- **Fractional contracts:** `*_fp` fields are strings, 0–2 decimal places on input; responses use 2 decimals.  
- Legacy integer count fields may be **truncated** between fractional enablement and March 12, 2026, then removed.  
- So we must record `*_fp` everywhere we currently record integer count fields to avoid data loss and to prepare for fractional trading.

---

## 5. File reference

| File | Functions / areas to touch for count_fp recording |
|------|---------------------------------------------------|
| backend/kalshi_account_sync_ws.py | sync_positions, sync_fills, sync_settlements, sync_orders; WebSocket fill fallback |
| backend/api/kalshi-api/kalshi_historical_ingest.py | write_fills_to_db, write_positions_to_db, write_settlements_to_db |
| DB migrations | users.fills_0001, users.orders_0001, users.positions_0001, users.settlements_0001 |

No patches applied in this audit; this document is for planning and implementation in a follow-up step.
