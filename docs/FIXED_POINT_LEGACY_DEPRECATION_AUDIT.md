# Fixed-Point Migration: Legacy Deprecation Readiness Audit

**Date:** 2025-03-04  
**Question:** If Kalshi stops supplying legacy values (integer `count`, `position`, `total_traded`, `yes_count`, `no_count`, etc.) and only supplies `_fp` equivalents, would our operations be unaffected? Would we simply see NULL in legacy columns?

**Conclusion: Yes.** Operations would continue to work. Legacy columns in portfolio tables would receive NULL for new/updated rows; all reads that matter use `_fp` when present (or a helper that prefers `_fp` over legacy). Below is the full audit.

---

## 1. Data flow summary

| Source | Legacy columns (could become NULL) | _fp columns (we store) | Who reads |
|--------|------------------------------------|-------------------------|-----------|
| **fills** | `count` | `count_fp` | main (API response), trade_manager (indirect via orders) |
| **orders** | `initial_count`, `remaining_count`, `fill_count` | `initial_count_fp`, `remaining_count_fp`, `fill_count_fp` | trade_manager (confirm open/close) |
| **positions** | `total_traded`, `position` | `total_traded_fp`, `position_fp` | main (API response) |
| **settlements** | `yes_count`, `no_count` | `yes_count_fp`, `no_count_fp` | main (API response) |

Our internal **trades_0001.position** is written by us from order fill data (using `_order_count_val(fill_count, fill_count_fp)`), not from the portfolio API, so it is unaffected by legacy deprecation.

---

## 2. Write path (sync) – legacy can be NULL

**kalshi_account_sync_ws.py**

- **Positions:** `total_traded = p.get("total_traded")`, `position_value = p.get("position")`. If API omits them, we write NULL. We always write `total_traded_fp` and `position_fp` from `_fp_to_numeric(p.get(...))`.
- **Fills:** `count = fill.get("count")`, `count_fp = _fp_to_numeric(fill.get("count_fp"))`. Same: legacy can be NULL, _fp stored.
- **Orders:** INSERT/UPDATE use `order.get("initial_count")`, `order.get("fill_count")`, etc. If API omits them, we write NULL; we always write the `_fp` columns.
- **Settlements:** `yes_count = settlement.get("yes_count")`, `no_count = settlement.get("no_count")`, plus `yes_count_fp` / `no_count_fp`. Legacy can be NULL.

So if the API stops sending legacy fields, we will simply write NULL into the legacy columns and keep writing the `_fp` columns. No code change required on the write path.

---

## 3. Read path – all critical readers prefer _fp

### 3.1 trade_manager.py (orders → confirm open/close)

- **Confirm open:** Reads `users.orders_0001` with `remaining_count`, `remaining_count_fp`, `fill_count`, `fill_count_fp`, `initial_count`, `initial_count_fp`. Uses **`_order_count_val(legacy, fp)`** everywhere (prefers `fp`, falls back to `legacy`). So when legacy is NULL and _fp is set, behavior is correct.
- **Confirm close:** Same pattern: uses `_order_count_val` for remaining/fill counts and PnL from order data.
- **trades_0001.position:** Set from order fill (`position_for_db = int(round(position_size))` where `position_size = fill_val` from `_order_count_val`). Not read from portfolio API. Unaffected by legacy deprecation.

### 3.2 main.py (API responses for UI)

- **GET /api/db/fills:** After fetching rows, for each item: if `count_fp` is not None, sets `fill_dict["count"] = int(round(float(count_fp)))`. So UI gets an integer count from _fp when present; legacy column can be NULL.
- **GET /api/db/positions:** If `position_fp` / `total_traded_fp` present, sets `position_dict["position"]` and `position_dict["total_traded"]` from them. Same for positions.
- **GET /api/db/settlements:** If `yes_count_fp` / `no_count_fp` present, sets `yes_count` / `no_count` from them. Same for settlements.

So even when legacy columns are NULL, the API responses still expose integer counts from _fp where available.

### 3.3 active_trade_supervisor.py

- Reads **position** from `users.trades_0001` and from its own active_trades cache. That position is our internal value (set by trade_manager from order fill _fp). Not from portfolio API. Unaffected.

### 3.4 kalshi_historical_ingest.py

- Writes portfolio data the same way as sync: uses `.get()` for legacy and `_fp_to_numeric(...)` for _fp. If API response has only _fp, legacy columns get NULL, _fp columns get values. No reader of historical ingest output assumes legacy is non-NULL.

---

## 4. Order delta check in sync (implemented)

In **kalshi_account_sync_ws.py**, when deciding whether to UPDATE an existing order we now compare using _fp:

- We SELECT `fill_count_fp`, `remaining_count_fp` and set `needs_update` from `existing['fill_count_fp'] != api_fill_fp` and `existing['remaining_count_fp'] != api_remaining_fp` (api values from `_fp_to_numeric(order.get("..._fp"))`), so we only trigger an UPDATE when _fp counts or other fields actually change.

This avoids redundant UPDATEs when the API omits legacy.---

## 5. Outbound (we only send _fp)

- **trade_executor.py** builds the Kalshi order payload with **only** `count_fp` (no legacy `count`). So we do not depend on the API still accepting legacy on the way out.

---

## 6. Direct answer to your question

- **If tomorrow all legacy values with _fp equivalents stopped being supplied by the API:**
  - **Operations would not be affected.** All critical reads use _fp when present (trade_manager via `_order_count_val`, main via normalizing from _fp for API responses). Writes use `.get()` and already support missing legacy (we write NULL).
  - **We would simply see NULL in those legacy columns in the DB** for new/updated data. Existing rows would keep their current legacy values until overwritten by a sync that receives only _fp.

No code changes are required for this scenario. The sync order delta check has been updated to compare using _fp so we avoid unnecessary UPDATEs when the API omits legacy.
