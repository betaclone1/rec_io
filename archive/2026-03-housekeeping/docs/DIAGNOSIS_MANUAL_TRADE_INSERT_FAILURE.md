# Diagnosis: Manual trade entry failing (insert_trade)

**Date:** 2026-02-14  
**Symptom:** Manual trades from the trade monitor UI (strike table) do not get inserted. Production (without recent schema/volatility-movement changes) still works.

---

## 1. What the logs show

### main_app.out.log
- `[TRIGGER OPEN TRADE] Trade initiated successfully: {'error': 'Failed to insert paper trade to database', 'id': None}`
- Main app receives HTTP **201** from trade_manager and treats it as success, but the response body contains an error and `id: None`.

### trade_manager.out.log
- Repeated pairs:
  - `❌ Failed to write trade to PostgreSQL: not all arguments converted during string formatting`
  - `[TRADE_MANAGER ...] ❌ Failed to insert paper trade to database`
- So `insert_trade()` is raising in the INSERT block; the exception is caught, the trade is not written, and the paper-trade path returns the “Failed to insert paper trade to database” body (still with HTTP 201).

---

## 2. Root cause

The error **“not all arguments converted during string formatting”** is from **psycopg2** when the number of `%s` placeholders in the SQL string does not match the number of items in the parameters tuple.

In `backend/trade_manager.py`, `insert_trade()`:

- The **INSERT** lists **41 columns** (including `volatility`, `volatility_percentile`, `movement`, `movement_percentile`).
- The **VALUES** clause has **40** `%s` placeholders.
- The **parameters tuple** has **41** values.

So we pass 41 values but only 40 placeholders. The 41st value is never consumed, and psycopg2 reports “not all arguments converted during string formatting”. This was introduced when the four new columns (volatility, volatility_percentile, movement, movement_percentile) were added to the INSERT: the column list and the value tuple were updated to 41 items, but only 40 `%s` were left in the VALUES clause (one `%s` was missed).

**Location:** `backend/trade_manager.py`, in `insert_trade()`, the multi-line `cursor.execute(""" INSERT INTO users.trades_0001 ( ... ) VALUES (%s, ... ) RETURNING id """, ( ... ))`. The VALUES line has 40 `%s`; it should have 41.

---

## 3. Why production still works

Production has not been updated with the recent changes that added the volatility/movement columns and the new INSERT shape. Its `insert_trade()` still has a matching number of columns, placeholders, and parameters, so the INSERT succeeds.

---

## 4. Secondary issue (response contract)

When `insert_trade()` fails, the trade_manager still returns **HTTP 201** with a body like `{"error": "Failed to insert paper trade to database", "id": null}`. The main app only checks `response.status_code == 201` and then logs “Trade initiated successfully” with that body. So the UI sees “success” even though the trade was not inserted. A stricter contract would be: on insert failure, return 5xx (or 4xx) and have the frontend treat that as failure.

---

## 5. Fix (when you patch)

- In `backend/trade_manager.py`, in the `insert_trade()` INSERT statement, change the **VALUES** clause from **40** `%s` placeholders to **41** (add one more `%s` so it matches the 41 columns and 41 parameters). No other change is required for the insert to succeed.
- Optionally: when `insert_trade()` returns `None`, have the trade_manager return a non-2xx status and have main_app/frontend treat that as failure.

No patch applied per your request; this document is diagnosis only.
