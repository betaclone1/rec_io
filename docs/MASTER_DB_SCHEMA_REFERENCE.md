# Master Database Schema Reference

**Generated:** 2026-03-03 (schema review, includes maintenance-mode system_state)

This document provides a complete reference of all database schemas, tables, and columns.
Update this document whenever schema changes are made during development.

### Application connection timezone

Python code should open PostgreSQL connections via `get_postgresql_connection()` / `get_database_config()` in [`backend/core/config/database.py`](../backend/core/config/database.py). Those connections include **`options=-c timezone=America/New_York`**, so session `TimeZone` is US Eastern. That keeps **`timestamp without time zone`** columns that use `DEFAULT CURRENT_TIMESTAMP` / `NOW()` aligned with the project convention (Eastern naive wall time), matching series such as `historical_data.*_price_history.timestamp` and Kalshi candle scratch tables documented below. **`timestamptz`** columns store absolute instants and are unaffected by session display semantics.

---

## How to Check and Update Your Database (No Scripts)

Use this document as the source of truth. Do both steps whenever you pull schema changes or need to sync the DB. To check that `database.py` table definitions have not drifted from this doc (for critical tables), run `PYTHONPATH=$(pwd) python3 scripts/db/check_db_schema_drift.py` (exit 1 = drift). For the **live production** host when running these steps over SSH or tunneled Postgres, see [PRODUCTION_HOST.md](PRODUCTION_HOST.md).

### 1. Run code-defined migrations

From the project root (e.g. `/opt/rec_io_server`), run once:

```bash
python3 -c "
from backend.core.config.database import init_database
ok, msg = init_database()
print('OK:', ok, msg)
"
```

This applies all schema and column changes defined in `backend/core/config/database.py` (new schemas, new tables, new columns on existing tables).

### 2. Check for anything still missing

List what your database has and compare to this document.

**List schemas and tables:**

```sql
SELECT nspname AS schema, relname AS table
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1, 2;
```

Run that in `psql` or any SQL client connected to your DB. Then:

- **Tables:** Every `Schema: X` / `Table: X.Y` in this doc should have a matching schema and table. If a table in the doc is missing, create it (step 3).
- **Columns:** For each table that exists, open its **Columns** section in this doc and compare to your table. If a column is missing, add it (step 3).

**Optional – list columns for one table:**

```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'users' AND table_name = 'trades_0001'
ORDER BY ordinal_position;
```

Change `table_schema` and `table_name` as needed.

### 3. Add missing tables or columns directly

- **Missing table:** In this doc, find the table’s **Columns** (and **Constraints** if any). Write a `CREATE TABLE schema.name ( ... );` that matches (use `SERIAL` for integer IDs with no default, and `CREATE SCHEMA IF NOT EXISTS schema;` if the schema might not exist). Run it against your DB.
- **Missing column:** From the table’s **Columns** section, note name, type, nullable, and default. Run:

  `ALTER TABLE schema.table_name ADD COLUMN column_name type [DEFAULT value] [NOT NULL];`

  Use the exact types from the doc (e.g. `NUMERIC(5,2)`, `TEXT`, `TIMESTAMP WITH TIME ZONE`). Omit NOT NULL if the column is nullable or you’re not sure.

Re-run the check (step 2) until nothing is missing.

### 4. After updating portfolio-level user tables (fills, orders, positions, settlements)

If you added or changed columns on `users.fills_0001`, `users.orders_0001`, `users.positions_0001`, or `users.settlements_0001`, run the historical ingest once so those tables get (or backfill) data into the new columns from the Kalshi API:

```bash
PYTHONPATH=$(pwd) python3 backend/api/kalshi-api/kalshi_historical_ingest.py
```

This syncs settlements, fills, and orders (with cursor pagination) and writes to PostgreSQL; positions are fetched and written as well. Ensures _fp and other API-sourced columns are populated consistently with the live account sync.

---

## Real-time DB change notification (public)

The system uses PostgreSQL NOTIFY plus a switchboard (LISTEN → Redis → WebSocket/backend subscribers) so that any writer (main app, scripts, other services) can drive real-time updates. Frontend and backend consumers subscribe once and receive the same payloads.

### Function: `public.rec_io_db_notify()`

- **Purpose:** Trigger function for DB-wide change notifications. Any table in any schema can use it.
- **Channel:** Sends to `rec_io_db_changes` (override via env `PG_NOTIFY_CHANNEL` in the switchboard).
- **Payload (JSON):** `{"schema":"<schema>","table":"<table>","op":"INSERT"|"UPDATE"|"DELETE"}`.

### Adding a trigger to any table

```sql
CREATE TRIGGER <trigger_name>
  AFTER INSERT OR UPDATE OR DELETE ON <schema>.<table>
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();
```

The switchboard maps `(schema, table)` to a **stream name** via `backend/core/stream_registry.py` and publishes to Redis `rec_io:db_changes`. Frontend and backend subscribers filter by stream name and refetch or react as needed. **When adding a trigger for a new table:** add the same table to the stream registry (one entry per table). See [REALTIME_BACKBONE.md](REALTIME_BACKBONE.md) and [REDIS_DB_CHANGES_BACKEND_INTEGRATION.md](REDIS_DB_CHANGES_BACKEND_INTEGRATION.md).

---

## Schema: `analytics`

### Table: `analytics.btc_fingerprint_-10`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_-10_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_-10_pkey`
  ```sql
  CREATE UNIQUE INDEX "btc_fingerprint_-10_pkey" ON analytics."btc_fingerprint_-10" USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_-20`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_-20_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_-20_pkey`
  ```sql
  CREATE UNIQUE INDEX "btc_fingerprint_-20_pkey" ON analytics."btc_fingerprint_-20" USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_-30`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_-30_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_-30_pkey`
  ```sql
  CREATE UNIQUE INDEX "btc_fingerprint_-30_pkey" ON analytics."btc_fingerprint_-30" USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_-40`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_-40_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_-40_pkey`
  ```sql
  CREATE UNIQUE INDEX "btc_fingerprint_-40_pkey" ON analytics."btc_fingerprint_-40" USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_-50`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_-50_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_-50_pkey`
  ```sql
  CREATE UNIQUE INDEX "btc_fingerprint_-50_pkey" ON analytics."btc_fingerprint_-50" USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_-60`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_-60_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_-60_pkey`
  ```sql
  CREATE UNIQUE INDEX "btc_fingerprint_-60_pkey" ON analytics."btc_fingerprint_-60" USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_-70`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_-70_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_-70_pkey`
  ```sql
  CREATE UNIQUE INDEX "btc_fingerprint_-70_pkey" ON analytics."btc_fingerprint_-70" USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_-80`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_-80_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_-80_pkey`
  ```sql
  CREATE UNIQUE INDEX "btc_fingerprint_-80_pkey" ON analytics."btc_fingerprint_-80" USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_-90`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_-90_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_-90_pkey`
  ```sql
  CREATE UNIQUE INDEX "btc_fingerprint_-90_pkey" ON analytics."btc_fingerprint_-90" USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_10`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_10_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_10_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_fingerprint_10_pkey ON analytics.btc_fingerprint_10 USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_20`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_20_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_20_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_fingerprint_20_pkey ON analytics.btc_fingerprint_20 USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_30`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_30_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_30_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_fingerprint_30_pkey ON analytics.btc_fingerprint_30 USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_40`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_40_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_40_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_fingerprint_40_pkey ON analytics.btc_fingerprint_40 USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_50`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_50_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_50_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_fingerprint_50_pkey ON analytics.btc_fingerprint_50 USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_60`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_60_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_60_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_fingerprint_60_pkey ON analytics.btc_fingerprint_60 USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_70`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_70_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_70_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_fingerprint_70_pkey ON analytics.btc_fingerprint_70 USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_80`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_80_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_80_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_fingerprint_80_pkey ON analytics.btc_fingerprint_80 USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_fingerprint_90`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `btc_fingerprint_90_pkey` on `time_to_close`

#### Indexes

- `btc_fingerprint_90_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_fingerprint_90_pkey ON analytics.btc_fingerprint_90 USING btree (time_to_close)
  ```

---

### Table: `analytics.btc_momentum_profile_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `percentile` | `numeric(6,1)` | NO | - | |
| `momentum_value` | `numeric(15,6)` | NO | - | |
| `deviation_from_mean` | `numeric(15,6)` | NO | - | |
| `z_score` | `numeric(15,6)` | NO | - | |
| `weighted_mean` | `numeric(15,6)` | NO | - | |
| `weighted_std` | `numeric(15,6)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `btc_momentum_profile_20250917_pkey` on `percentile`

#### Indexes

- `btc_momentum_profile_20250917_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_momentum_profile_20250917_pkey ON analytics.btc_momentum_profile_20250917 USING btree (percentile)
  ```

---

### Table: `analytics.btc_momentum_profile_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `percentile` | `numeric(6,1)` | NO | - | |
| `momentum_value` | `numeric(15,6)` | NO | - | |
| `deviation_from_mean` | `numeric(15,6)` | NO | - | |
| `z_score` | `numeric(15,6)` | NO | - | |
| `weighted_mean` | `numeric(15,6)` | NO | - | |
| `weighted_std` | `numeric(15,6)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `btc_momentum_profile_20251016_pkey` on `percentile`

#### Indexes

- `btc_momentum_profile_20251016_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_momentum_profile_20251016_pkey ON analytics.btc_momentum_profile_20251016 USING btree (percentile)
  ```

---

### Table: `analytics.btc_price_profile_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `range_name` | `character varying(20)` | NO | - | |
| `percentile_min` | `numeric(5,1)` | NO | - | |
| `percentile_max` | `numeric(5,1)` | NO | - | |
| `price_change_min` | `numeric(10,6)` | NO | - | |
| `price_change_max` | `numeric(10,6)` | NO | - | |
| `avg_price_change_pct` | `numeric(10,6)` | NO | - | |
| `sample_count` | `integer(32)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `btc_price_profile_20250917_pkey` on `range_name`

#### Indexes

- `btc_price_profile_20250917_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_price_profile_20250917_pkey ON analytics.btc_price_profile_20250917 USING btree (range_name)
  ```

---

### Table: `analytics.btc_price_profile_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `range_name` | `character varying(20)` | NO | - | |
| `percentile_min` | `numeric(5,1)` | NO | - | |
| `percentile_max` | `numeric(5,1)` | NO | - | |
| `price_change_min` | `numeric(10,6)` | NO | - | |
| `price_change_max` | `numeric(10,6)` | NO | - | |
| `avg_price_change_pct` | `numeric(10,6)` | NO | - | |
| `sample_count` | `integer(32)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `btc_price_profile_20251016_pkey` on `range_name`

#### Indexes

- `btc_price_profile_20251016_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_price_profile_20251016_pkey ON analytics.btc_price_profile_20251016 USING btree (range_name)
  ```

---

### Table: `analytics.eth_fingerprint_-10`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_-10_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_-10_pkey`
  ```sql
  CREATE UNIQUE INDEX "eth_fingerprint_-10_pkey" ON analytics."eth_fingerprint_-10" USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_-20`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_-20_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_-20_pkey`
  ```sql
  CREATE UNIQUE INDEX "eth_fingerprint_-20_pkey" ON analytics."eth_fingerprint_-20" USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_-30`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_-30_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_-30_pkey`
  ```sql
  CREATE UNIQUE INDEX "eth_fingerprint_-30_pkey" ON analytics."eth_fingerprint_-30" USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_-40`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_-40_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_-40_pkey`
  ```sql
  CREATE UNIQUE INDEX "eth_fingerprint_-40_pkey" ON analytics."eth_fingerprint_-40" USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_-50`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_-50_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_-50_pkey`
  ```sql
  CREATE UNIQUE INDEX "eth_fingerprint_-50_pkey" ON analytics."eth_fingerprint_-50" USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_-60`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_-60_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_-60_pkey`
  ```sql
  CREATE UNIQUE INDEX "eth_fingerprint_-60_pkey" ON analytics."eth_fingerprint_-60" USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_-70`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_-70_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_-70_pkey`
  ```sql
  CREATE UNIQUE INDEX "eth_fingerprint_-70_pkey" ON analytics."eth_fingerprint_-70" USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_-80`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_-80_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_-80_pkey`
  ```sql
  CREATE UNIQUE INDEX "eth_fingerprint_-80_pkey" ON analytics."eth_fingerprint_-80" USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_-90`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_-90_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_-90_pkey`
  ```sql
  CREATE UNIQUE INDEX "eth_fingerprint_-90_pkey" ON analytics."eth_fingerprint_-90" USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_10`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_10_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_10_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_fingerprint_10_pkey ON analytics.eth_fingerprint_10 USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_20`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_20_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_20_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_fingerprint_20_pkey ON analytics.eth_fingerprint_20 USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_30`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_30_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_30_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_fingerprint_30_pkey ON analytics.eth_fingerprint_30 USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_40`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_40_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_40_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_fingerprint_40_pkey ON analytics.eth_fingerprint_40 USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_50`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_50_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_50_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_fingerprint_50_pkey ON analytics.eth_fingerprint_50 USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_60`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_60_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_60_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_fingerprint_60_pkey ON analytics.eth_fingerprint_60 USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_70`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_70_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_70_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_fingerprint_70_pkey ON analytics.eth_fingerprint_70 USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_80`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_80_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_80_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_fingerprint_80_pkey ON analytics.eth_fingerprint_80 USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_fingerprint_90`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `eth_fingerprint_90_pkey` on `time_to_close`

#### Indexes

- `eth_fingerprint_90_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_fingerprint_90_pkey ON analytics.eth_fingerprint_90 USING btree (time_to_close)
  ```

---

### Table: `analytics.eth_momentum_profile_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `percentile` | `numeric(6,1)` | NO | - | |
| `momentum_value` | `numeric(15,6)` | NO | - | |
| `deviation_from_mean` | `numeric(15,6)` | NO | - | |
| `z_score` | `numeric(15,6)` | NO | - | |
| `weighted_mean` | `numeric(15,6)` | NO | - | |
| `weighted_std` | `numeric(15,6)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `eth_momentum_profile_20250917_pkey` on `percentile`

#### Indexes

- `eth_momentum_profile_20250917_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_momentum_profile_20250917_pkey ON analytics.eth_momentum_profile_20250917 USING btree (percentile)
  ```

---

### Table: `analytics.eth_momentum_profile_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `percentile` | `numeric(6,1)` | NO | - | |
| `momentum_value` | `numeric(15,6)` | NO | - | |
| `deviation_from_mean` | `numeric(15,6)` | NO | - | |
| `z_score` | `numeric(15,6)` | NO | - | |
| `weighted_mean` | `numeric(15,6)` | NO | - | |
| `weighted_std` | `numeric(15,6)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `eth_momentum_profile_20251016_pkey` on `percentile`

#### Indexes

- `eth_momentum_profile_20251016_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_momentum_profile_20251016_pkey ON analytics.eth_momentum_profile_20251016 USING btree (percentile)
  ```

---

### Table: `analytics.eth_price_profile_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `range_name` | `character varying(20)` | NO | - | |
| `percentile_min` | `numeric(5,1)` | NO | - | |
| `percentile_max` | `numeric(5,1)` | NO | - | |
| `price_change_min` | `numeric(10,6)` | NO | - | |
| `price_change_max` | `numeric(10,6)` | NO | - | |
| `avg_price_change_pct` | `numeric(10,6)` | NO | - | |
| `sample_count` | `integer(32)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `eth_price_profile_20250917_pkey` on `range_name`

#### Indexes

- `eth_price_profile_20250917_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_price_profile_20250917_pkey ON analytics.eth_price_profile_20250917 USING btree (range_name)
  ```

---

### Table: `analytics.eth_price_profile_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `range_name` | `character varying(20)` | NO | - | |
| `percentile_min` | `numeric(5,1)` | NO | - | |
| `percentile_max` | `numeric(5,1)` | NO | - | |
| `price_change_min` | `numeric(10,6)` | NO | - | |
| `price_change_max` | `numeric(10,6)` | NO | - | |
| `avg_price_change_pct` | `numeric(10,6)` | NO | - | |
| `sample_count` | `integer(32)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `eth_price_profile_20251016_pkey` on `range_name`

#### Indexes

- `eth_price_profile_20251016_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_price_profile_20251016_pkey ON analytics.eth_price_profile_20251016 USING btree (range_name)
  ```

---

### Table: `analytics.ndx_fingerprint_-10`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_-10_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_-10_pkey`
  ```sql
  CREATE UNIQUE INDEX "ndx_fingerprint_-10_pkey" ON analytics."ndx_fingerprint_-10" USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_-20`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_-20_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_-20_pkey`
  ```sql
  CREATE UNIQUE INDEX "ndx_fingerprint_-20_pkey" ON analytics."ndx_fingerprint_-20" USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_-30`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_-30_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_-30_pkey`
  ```sql
  CREATE UNIQUE INDEX "ndx_fingerprint_-30_pkey" ON analytics."ndx_fingerprint_-30" USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_-40`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_-40_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_-40_pkey`
  ```sql
  CREATE UNIQUE INDEX "ndx_fingerprint_-40_pkey" ON analytics."ndx_fingerprint_-40" USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_-50`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_-50_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_-50_pkey`
  ```sql
  CREATE UNIQUE INDEX "ndx_fingerprint_-50_pkey" ON analytics."ndx_fingerprint_-50" USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_-60`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_-60_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_-60_pkey`
  ```sql
  CREATE UNIQUE INDEX "ndx_fingerprint_-60_pkey" ON analytics."ndx_fingerprint_-60" USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_-70`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_-70_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_-70_pkey`
  ```sql
  CREATE UNIQUE INDEX "ndx_fingerprint_-70_pkey" ON analytics."ndx_fingerprint_-70" USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_-80`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_-80_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_-80_pkey`
  ```sql
  CREATE UNIQUE INDEX "ndx_fingerprint_-80_pkey" ON analytics."ndx_fingerprint_-80" USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_-90`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_-90_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_-90_pkey`
  ```sql
  CREATE UNIQUE INDEX "ndx_fingerprint_-90_pkey" ON analytics."ndx_fingerprint_-90" USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_10`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_10_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_10_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_fingerprint_10_pkey ON analytics.ndx_fingerprint_10 USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_20`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_20_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_20_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_fingerprint_20_pkey ON analytics.ndx_fingerprint_20 USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_30`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_30_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_30_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_fingerprint_30_pkey ON analytics.ndx_fingerprint_30 USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_40`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_40_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_40_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_fingerprint_40_pkey ON analytics.ndx_fingerprint_40 USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_50`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_50_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_50_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_fingerprint_50_pkey ON analytics.ndx_fingerprint_50 USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_60`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_60_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_60_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_fingerprint_60_pkey ON analytics.ndx_fingerprint_60 USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_70`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_70_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_70_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_fingerprint_70_pkey ON analytics.ndx_fingerprint_70 USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_80`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_80_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_80_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_fingerprint_80_pkey ON analytics.ndx_fingerprint_80 USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_fingerprint_90`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_fingerprint_90_pkey` on `time_to_close`

#### Indexes

- `ndx_fingerprint_90_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_fingerprint_90_pkey ON analytics.ndx_fingerprint_90 USING btree (time_to_close)
  ```

---

### Table: `analytics.ndx_momentum_profile_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `percentile` | `numeric(6,1)` | YES | - | |
| `momentum_value` | `numeric(15,6)` | YES | - | |
| `deviation_from_mean` | `numeric(15,6)` | YES | - | |
| `z_score` | `numeric(15,6)` | YES | - | |
| `weighted_mean` | `numeric(15,6)` | YES | - | |
| `weighted_std` | `numeric(15,6)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |
| `updated_at` | `timestamp without time zone` | YES | - | |

---

### Table: `analytics.ndx_momentum_profile_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `percentile` | `numeric(6,1)` | NO | - | |
| `momentum_value` | `numeric(15,6)` | NO | - | |
| `deviation_from_mean` | `numeric(15,6)` | NO | - | |
| `z_score` | `numeric(15,6)` | NO | - | |
| `weighted_mean` | `numeric(15,6)` | NO | - | |
| `weighted_std` | `numeric(15,6)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `ndx_momentum_profile_20251016_pkey` on `percentile`

#### Indexes

- `ndx_momentum_profile_20251016_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_momentum_profile_20251016_pkey ON analytics.ndx_momentum_profile_20251016 USING btree (percentile)
  ```

---

### Table: `analytics.ndx_price_profile_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `range_name` | `character varying(20)` | NO | - | |
| `percentile_min` | `numeric(5,1)` | YES | - | |
| `percentile_max` | `numeric(5,1)` | YES | - | |
| `price_change_min` | `numeric(10,6)` | YES | - | |
| `price_change_max` | `numeric(10,6)` | YES | - | |
| `avg_price_change_pct` | `numeric(10,6)` | YES | - | |
| `sample_count` | `integer(32)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |
| `updated_at` | `timestamp without time zone` | YES | - | |

#### Constraints

- **Primary Key:** `ndx_price_profile_20250917_pkey` on `range_name`

#### Indexes

- `ndx_price_profile_20250917_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_price_profile_20250917_pkey ON analytics.ndx_price_profile_20250917 USING btree (range_name)
  ```

---

### Table: `analytics.ndx_price_profile_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `range_name` | `character varying(20)` | NO | - | |
| `percentile_min` | `numeric(5,1)` | NO | - | |
| `percentile_max` | `numeric(5,1)` | NO | - | |
| `price_change_min` | `numeric(10,6)` | NO | - | |
| `price_change_max` | `numeric(10,6)` | NO | - | |
| `avg_price_change_pct` | `numeric(10,6)` | NO | - | |
| `sample_count` | `integer(32)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `ndx_price_profile_20251016_pkey` on `range_name`

#### Indexes

- `ndx_price_profile_20251016_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_price_profile_20251016_pkey ON analytics.ndx_price_profile_20251016 USING btree (range_name)
  ```

---

### Table: `analytics.probability_lookup_btc_master_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | YES | - | |
| `buffer_points` | `numeric(10,4)` | YES | - | |
| `momentum_bucket` | `integer(32)` | YES | - | |
| `prob_within_positive` | `numeric(5,2)` | YES | - | |
| `prob_within_negative` | `numeric(5,2)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |

#### Indexes

- `idx_probability_lookup_btc_master_20250917_lookup`
  ```sql
  CREATE INDEX idx_probability_lookup_btc_master_20250917_lookup ON analytics.probability_lookup_btc_master_20250917 USING btree (ttc_seconds, buffer_points, momentum_bucket)
  ```

---

### Table: `analytics.probability_lookup_btc_master_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | YES | - | |
| `buffer_points` | `numeric(10,4)` | YES | - | |
| `momentum_bucket` | `integer(32)` | YES | - | |
| `prob_within_positive` | `numeric(5,2)` | YES | - | |
| `prob_within_negative` | `numeric(5,2)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |

#### Indexes

- `idx_probability_lookup_btc_master_20251016_lookup`
  ```sql
  CREATE INDEX idx_probability_lookup_btc_master_20251016_lookup ON analytics.probability_lookup_btc_master_20251016 USING btree (ttc_seconds, buffer_points, momentum_bucket)
  ```

---

### Table: `analytics.probability_lookup_eth_master_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | YES | - | |
| `buffer_points` | `numeric(10,4)` | YES | - | |
| `momentum_bucket` | `integer(32)` | YES | - | |
| `prob_within_positive` | `numeric(5,2)` | YES | - | |
| `prob_within_negative` | `numeric(5,2)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |

#### Indexes

- `idx_probability_lookup_eth_master_20250917_lookup`
  ```sql
  CREATE INDEX idx_probability_lookup_eth_master_20250917_lookup ON analytics.probability_lookup_eth_master_20250917 USING btree (ttc_seconds, buffer_points, momentum_bucket)
  ```

---

### Table: `analytics.probability_lookup_eth_master_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | YES | - | |
| `buffer_points` | `numeric(10,4)` | YES | - | |
| `momentum_bucket` | `integer(32)` | YES | - | |
| `prob_within_positive` | `numeric(5,2)` | YES | - | |
| `prob_within_negative` | `numeric(5,2)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |

#### Indexes

- `idx_probability_lookup_eth_master_20251016_lookup`
  ```sql
  CREATE INDEX idx_probability_lookup_eth_master_20251016_lookup ON analytics.probability_lookup_eth_master_20251016 USING btree (ttc_seconds, buffer_points, momentum_bucket)
  ```

---

### Table: `analytics.probability_lookup_ndx_master_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | YES | - | |
| `buffer_points` | `numeric(10,4)` | YES | - | |
| `momentum_bucket` | `integer(32)` | YES | - | |
| `prob_within_positive` | `numeric(5,2)` | YES | - | |
| `prob_within_negative` | `numeric(5,2)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |

#### Indexes

- `idx_probability_lookup_ndx_master_20250917_lookup`
  ```sql
  CREATE INDEX idx_probability_lookup_ndx_master_20250917_lookup ON analytics.probability_lookup_ndx_master_20250917 USING btree (ttc_seconds, buffer_points, momentum_bucket)
  ```

---

### Table: `analytics.probability_lookup_ndx_master_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | YES | - | |
| `buffer_points` | `numeric(10,4)` | YES | - | |
| `momentum_bucket` | `integer(32)` | YES | - | |
| `prob_within_positive` | `numeric(5,2)` | YES | - | |
| `prob_within_negative` | `numeric(5,2)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |

#### Indexes

- `idx_probability_lookup_ndx_master_20251016_lookup`
  ```sql
  CREATE INDEX idx_probability_lookup_ndx_master_20251016_lookup ON analytics.probability_lookup_ndx_master_20251016 USING btree (ttc_seconds, buffer_points, momentum_bucket)
  ```

---

### Table: `analytics.probability_lookup_spx_master_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | YES | - | |
| `buffer_points` | `numeric(10,4)` | YES | - | |
| `momentum_bucket` | `integer(32)` | YES | - | |
| `prob_within_positive` | `numeric(5,2)` | YES | - | |
| `prob_within_negative` | `numeric(5,2)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |

#### Indexes

- `idx_probability_lookup_spx_master_20250917_lookup`
  ```sql
  CREATE INDEX idx_probability_lookup_spx_master_20250917_lookup ON analytics.probability_lookup_spx_master_20250917 USING btree (ttc_seconds, buffer_points, momentum_bucket)
  ```

---

### Table: `analytics.probability_lookup_spx_master_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | YES | - | |
| `buffer_points` | `numeric(10,4)` | YES | - | |
| `momentum_bucket` | `integer(32)` | YES | - | |
| `prob_within_positive` | `numeric(5,2)` | YES | - | |
| `prob_within_negative` | `numeric(5,2)` | YES | - | |
| `created_at` | `timestamp without time zone` | YES | - | |

#### Indexes

- `idx_probability_lookup_spx_master_20251016_lookup`
  ```sql
  CREATE INDEX idx_probability_lookup_spx_master_20251016_lookup ON analytics.probability_lookup_spx_master_20251016 USING btree (ttc_seconds, buffer_points, momentum_bucket)
  ```

---

### Table: `analytics.spx_fingerprint_-10`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_-10_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_-10_pkey`
  ```sql
  CREATE UNIQUE INDEX "spx_fingerprint_-10_pkey" ON analytics."spx_fingerprint_-10" USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_-20`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_-20_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_-20_pkey`
  ```sql
  CREATE UNIQUE INDEX "spx_fingerprint_-20_pkey" ON analytics."spx_fingerprint_-20" USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_-30`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_-30_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_-30_pkey`
  ```sql
  CREATE UNIQUE INDEX "spx_fingerprint_-30_pkey" ON analytics."spx_fingerprint_-30" USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_-40`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_-40_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_-40_pkey`
  ```sql
  CREATE UNIQUE INDEX "spx_fingerprint_-40_pkey" ON analytics."spx_fingerprint_-40" USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_-50`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_-50_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_-50_pkey`
  ```sql
  CREATE UNIQUE INDEX "spx_fingerprint_-50_pkey" ON analytics."spx_fingerprint_-50" USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_-60`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_-60_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_-60_pkey`
  ```sql
  CREATE UNIQUE INDEX "spx_fingerprint_-60_pkey" ON analytics."spx_fingerprint_-60" USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_-70`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_-70_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_-70_pkey`
  ```sql
  CREATE UNIQUE INDEX "spx_fingerprint_-70_pkey" ON analytics."spx_fingerprint_-70" USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_-80`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_-80_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_-80_pkey`
  ```sql
  CREATE UNIQUE INDEX "spx_fingerprint_-80_pkey" ON analytics."spx_fingerprint_-80" USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_-90`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_-90_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_-90_pkey`
  ```sql
  CREATE UNIQUE INDEX "spx_fingerprint_-90_pkey" ON analytics."spx_fingerprint_-90" USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_10`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_10_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_10_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_fingerprint_10_pkey ON analytics.spx_fingerprint_10 USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_20`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_20_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_20_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_fingerprint_20_pkey ON analytics.spx_fingerprint_20 USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_30`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_30_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_30_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_fingerprint_30_pkey ON analytics.spx_fingerprint_30 USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_40`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_40_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_40_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_fingerprint_40_pkey ON analytics.spx_fingerprint_40 USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_50`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_50_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_50_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_fingerprint_50_pkey ON analytics.spx_fingerprint_50 USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_60`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_60_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_60_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_fingerprint_60_pkey ON analytics.spx_fingerprint_60 USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_70`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_70_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_70_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_fingerprint_70_pkey ON analytics.spx_fingerprint_70 USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_80`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_80_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_80_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_fingerprint_80_pkey ON analytics.spx_fingerprint_80 USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_fingerprint_90`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `time_to_close` | `text` | NO | - | |
| `pos_0_00` | `numeric(5,2)` | YES | - | |
| `neg_0_00` | `numeric(5,2)` | YES | - | |
| `pos_0_05` | `numeric(5,2)` | YES | - | |
| `neg_0_05` | `numeric(5,2)` | YES | - | |
| `pos_0_10` | `numeric(5,2)` | YES | - | |
| `neg_0_10` | `numeric(5,2)` | YES | - | |
| `pos_0_15` | `numeric(5,2)` | YES | - | |
| `neg_0_15` | `numeric(5,2)` | YES | - | |
| `pos_0_20` | `numeric(5,2)` | YES | - | |
| `neg_0_20` | `numeric(5,2)` | YES | - | |
| `pos_0_25` | `numeric(5,2)` | YES | - | |
| `neg_0_25` | `numeric(5,2)` | YES | - | |
| `pos_0_30` | `numeric(5,2)` | YES | - | |
| `neg_0_30` | `numeric(5,2)` | YES | - | |
| `pos_0_35` | `numeric(5,2)` | YES | - | |
| `neg_0_35` | `numeric(5,2)` | YES | - | |
| `pos_0_40` | `numeric(5,2)` | YES | - | |
| `neg_0_40` | `numeric(5,2)` | YES | - | |
| `pos_0_45` | `numeric(5,2)` | YES | - | |
| `neg_0_45` | `numeric(5,2)` | YES | - | |
| `pos_0_50` | `numeric(5,2)` | YES | - | |
| `neg_0_50` | `numeric(5,2)` | YES | - | |
| `pos_0_55` | `numeric(5,2)` | YES | - | |
| `neg_0_55` | `numeric(5,2)` | YES | - | |
| `pos_0_60` | `numeric(5,2)` | YES | - | |
| `neg_0_60` | `numeric(5,2)` | YES | - | |
| `pos_0_65` | `numeric(5,2)` | YES | - | |
| `neg_0_65` | `numeric(5,2)` | YES | - | |
| `pos_0_70` | `numeric(5,2)` | YES | - | |
| `neg_0_70` | `numeric(5,2)` | YES | - | |
| `pos_0_75` | `numeric(5,2)` | YES | - | |
| `neg_0_75` | `numeric(5,2)` | YES | - | |
| `pos_0_80` | `numeric(5,2)` | YES | - | |
| `neg_0_80` | `numeric(5,2)` | YES | - | |
| `pos_0_85` | `numeric(5,2)` | YES | - | |
| `neg_0_85` | `numeric(5,2)` | YES | - | |
| `pos_0_90` | `numeric(5,2)` | YES | - | |
| `neg_0_90` | `numeric(5,2)` | YES | - | |
| `pos_0_95` | `numeric(5,2)` | YES | - | |
| `neg_0_95` | `numeric(5,2)` | YES | - | |
| `pos_1_00` | `numeric(5,2)` | YES | - | |
| `neg_1_00` | `numeric(5,2)` | YES | - | |
| `pos_1_05` | `numeric(5,2)` | YES | - | |
| `neg_1_05` | `numeric(5,2)` | YES | - | |
| `pos_1_10` | `numeric(5,2)` | YES | - | |
| `neg_1_10` | `numeric(5,2)` | YES | - | |
| `pos_1_15` | `numeric(5,2)` | YES | - | |
| `neg_1_15` | `numeric(5,2)` | YES | - | |
| `pos_1_20` | `numeric(5,2)` | YES | - | |
| `neg_1_20` | `numeric(5,2)` | YES | - | |
| `pos_1_25` | `numeric(5,2)` | YES | - | |
| `neg_1_25` | `numeric(5,2)` | YES | - | |
| `pos_1_30` | `numeric(5,2)` | YES | - | |
| `neg_1_30` | `numeric(5,2)` | YES | - | |
| `pos_1_35` | `numeric(5,2)` | YES | - | |
| `neg_1_35` | `numeric(5,2)` | YES | - | |
| `pos_1_40` | `numeric(5,2)` | YES | - | |
| `neg_1_40` | `numeric(5,2)` | YES | - | |
| `pos_1_45` | `numeric(5,2)` | YES | - | |
| `neg_1_45` | `numeric(5,2)` | YES | - | |
| `pos_1_50` | `numeric(5,2)` | YES | - | |
| `neg_1_50` | `numeric(5,2)` | YES | - | |
| `pos_1_55` | `numeric(5,2)` | YES | - | |
| `neg_1_55` | `numeric(5,2)` | YES | - | |
| `pos_1_60` | `numeric(5,2)` | YES | - | |
| `neg_1_60` | `numeric(5,2)` | YES | - | |
| `pos_1_65` | `numeric(5,2)` | YES | - | |
| `neg_1_65` | `numeric(5,2)` | YES | - | |
| `pos_1_75` | `numeric(5,2)` | YES | - | |
| `neg_1_75` | `numeric(5,2)` | YES | - | |
| `pos_1_80` | `numeric(5,2)` | YES | - | |
| `neg_1_80` | `numeric(5,2)` | YES | - | |
| `pos_1_85` | `numeric(5,2)` | YES | - | |
| `neg_1_85` | `numeric(5,2)` | YES | - | |
| `pos_1_90` | `numeric(5,2)` | YES | - | |
| `neg_1_90` | `numeric(5,2)` | YES | - | |
| `pos_1_95` | `numeric(5,2)` | YES | - | |
| `neg_1_95` | `numeric(5,2)` | YES | - | |
| `pos_2_00` | `numeric(5,2)` | YES | - | |
| `neg_2_00` | `numeric(5,2)` | YES | - | |

#### Constraints

- **Primary Key:** `spx_fingerprint_90_pkey` on `time_to_close`

#### Indexes

- `spx_fingerprint_90_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_fingerprint_90_pkey ON analytics.spx_fingerprint_90 USING btree (time_to_close)
  ```

---

### Table: `analytics.spx_momentum_profile_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `percentile` | `numeric(6,1)` | NO | - | |
| `momentum_value` | `numeric(15,6)` | NO | - | |
| `deviation_from_mean` | `numeric(15,6)` | NO | - | |
| `z_score` | `numeric(15,6)` | NO | - | |
| `weighted_mean` | `numeric(15,6)` | NO | - | |
| `weighted_std` | `numeric(15,6)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `spx_momentum_profile_20250917_pkey` on `percentile`

#### Indexes

- `spx_momentum_profile_20250917_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_momentum_profile_20250917_pkey ON analytics.spx_momentum_profile_20250917 USING btree (percentile)
  ```

---

### Table: `analytics.spx_momentum_profile_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `percentile` | `numeric(6,1)` | NO | - | |
| `momentum_value` | `numeric(15,6)` | NO | - | |
| `deviation_from_mean` | `numeric(15,6)` | NO | - | |
| `z_score` | `numeric(15,6)` | NO | - | |
| `weighted_mean` | `numeric(15,6)` | NO | - | |
| `weighted_std` | `numeric(15,6)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `spx_momentum_profile_20251016_pkey` on `percentile`

#### Indexes

- `spx_momentum_profile_20251016_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_momentum_profile_20251016_pkey ON analytics.spx_momentum_profile_20251016 USING btree (percentile)
  ```

---

### Table: `analytics.spx_price_profile_20250917`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `range_name` | `character varying(20)` | NO | - | |
| `percentile_min` | `numeric(5,1)` | NO | - | |
| `percentile_max` | `numeric(5,1)` | NO | - | |
| `price_change_min` | `numeric(10,6)` | NO | - | |
| `price_change_max` | `numeric(10,6)` | NO | - | |
| `avg_price_change_pct` | `numeric(10,6)` | NO | - | |
| `sample_count` | `integer(32)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `spx_price_profile_20250917_pkey` on `range_name`

#### Indexes

- `spx_price_profile_20250917_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_price_profile_20250917_pkey ON analytics.spx_price_profile_20250917 USING btree (range_name)
  ```

---

### Table: `analytics.spx_price_profile_20251016`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `range_name` | `character varying(20)` | NO | - | |
| `percentile_min` | `numeric(5,1)` | NO | - | |
| `percentile_max` | `numeric(5,1)` | NO | - | |
| `price_change_min` | `numeric(10,6)` | NO | - | |
| `price_change_max` | `numeric(10,6)` | NO | - | |
| `avg_price_change_pct` | `numeric(10,6)` | NO | - | |
| `sample_count` | `integer(32)` | NO | - | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `spx_price_profile_20251016_pkey` on `range_name`

#### Indexes

- `spx_price_profile_20251016_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_price_profile_20251016_pkey ON analytics.spx_price_profile_20251016 USING btree (range_name)
  ```

---

## Schema: `archive`

### Table: `archive.trades_0001_archive_20251003`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | YES | - | |
| `status` | `text` | YES | - | |
| `date` | `text` | YES | - | |
| `time` | `text` | YES | - | |
| `symbol` | `text` | YES | - | |
| `market` | `text` | YES | - | |
| `trade_strategy` | `text` | YES | - | |
| `contract` | `text` | YES | - | |
| `strike` | `text` | YES | - | |
| `side` | `text` | YES | - | |
| `prob` | `real(24)` | YES | - | |
| `diff` | `text` | YES | - | |
| `buy_price` | `real(24)` | YES | - | |
| `position` | `integer(32)` | YES | - | |
| `sell_price` | `real(24)` | YES | - | |
| `closed_at` | `text` | YES | - | |
| `fees` | `real(24)` | YES | - | |
| `pnl` | `real(24)` | YES | - | |
| `symbol_open` | `real(24)` | YES | - | |
| `symbol_close` | `real(24)` | YES | - | |
| `momentum` | `integer(32)` | YES | - | |
| `volatility` | `integer(32)` | YES | - | |
| `win_loss` | `text` | YES | - | |
| `ticker` | `text` | YES | - | |
| `ticket_id` | `text` | YES | - | |
| `market_id` | `text` | YES | - | |
| `momentum_percentile` | `real(24)` | YES | - | |
| `entry_method` | `text` | YES | - | |
| `close_method` | `text` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | - | |
| `updated_at` | `timestamp with time zone` | YES | - | |
| `test_filter` | `boolean` | YES | - | |
| `notes` | `text` | YES | - | |
| `monitor` | `text` | YES | - | |
| `bankroll` | `real(24)` | YES | - | |
| `ret_pct` | `real(24)` | YES | - | |
| `momentum_5s_avg` | `numeric(10,4)` | YES | - | |
| `order_id` | `text` | YES | - | |
| `order_id_open` | `text` | YES | - | |
| `order_id_close` | `text` | YES | - | |

---

### Table: `archive.trades_archive_live_0001`

**Purpose:** Rows moved from `users.trades_0001` when a monitor is archived (`POST /api/monitor/archive` or backfill script). Contains only trades that had `paper_trade = false` (or null treated as live at archive time) for that monitor. Same column set as `users.trades_0001` at migration time, **plus** `archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`. **No** `rec_io_db_notify` trigger.

**Creation:** Migration `20260327_2200_archive_trades_live_paper_0001` (`CREATE TABLE ... (LIKE users.trades_0001 INCLUDING CONSTRAINTS INCLUDING INDEXES EXCLUDING DEFAULTS)` then `archived_at` and dedicated `id` sequence in schema `archive`). Follow-on: `20260402_2320_archive_trades_ats_updated` adds **`ats_updated`** when `users.trades_0001` gains that column so `union_trades_with_archives_select` stays valid.

**Application:** `backend.util.trade_log_archivist.archive_trades_for_monitor`; read paths union this table with the master log and `archive.trades_archive_paper_0001`.

---

### Table: `archive.trades_archive_paper_0001`

**Purpose:** Same as `archive.trades_archive_live_0001`, but for rows where `COALESCE(paper_trade, FALSE)` was true when archived.

**Creation / usage:** Same migration and archivist as live table; separate table so reporting can stay split by paper vs live.

---

## Schema: `historical_data`

### Ephemeral: `historical_data.kalshi_candles_1m_*_*` (scratch)

**Not** created by `database.py` or routine migrations. Tables matching **`kalshi_candles_1m_<slug>_<YYYYMMDD>`** are created by **`scripts/backtest/helpers/kalshi_market_candles_scratch.py`** for ad-hoc analysis (Kalshi 1m OHLC for a market’s trading window). **`YYYYMMDD`** is a UTC calendar date suffix for rotation. **Row count** follows Kalshi’s session length (e.g. **15** rows for a **15m** contract, **~60** for a typical **hourly** contract); see **`docs/BACKTESTING.md`** §5.4.

**Column layout** matches testing Kalshi candle tables: **`timestamp`** (`timestamp without time zone`, US Eastern wall time, first column), **`end_period_ts`** (PK), **`market_ticker`**, bid/ask/trade dollar columns, **`volume_fp`**, **`open_interest_fp`**, **`created_at`**.

**Cleanup:** `kalshi_market_candles_scratch.py --cleanup-only --retention-days N` drops tables whose suffix date is older than **`UTC today − N`** days.

---

### Table: `historical_data.btc_price_history`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `timestamp` | `timestamp without time zone` | NO | - | |
| `open` | `numeric(20,8)` | YES | - | |
| `high` | `numeric(20,8)` | YES | - | |
| `low` | `numeric(20,8)` | YES | - | |
| `close` | `numeric(20,8)` | YES | - | |
| `volume` | `numeric(20,8)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(15,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `movement` | `numeric(10,4)` | YES | - | Composite intra-candle range score (weighted (H-L)/O and rolling means). NULL for first 30 rows. |
| `movement_percentile` | `numeric(5,1)` | YES | - | Percentile of movement vs analytics.btc_movement_profile (0.5–99.5). Movement profile tables use column **movement_value** for the value at each percentile. |

#### Constraints

- **Primary Key:** `btc_price_history_pkey` on `timestamp`

#### Indexes

- `btc_price_history_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_price_history_pkey ON historical_data.btc_price_history USING btree ("timestamp")
  ```
- `unique_btc_price_history_timestamp`
  ```sql
  CREATE UNIQUE INDEX unique_btc_price_history_timestamp ON historical_data.btc_price_history USING btree ("timestamp")
  ```

---

### Table: `historical_data.eth_price_history`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `timestamp` | `timestamp without time zone` | NO | - | |
| `open` | `numeric(20,8)` | YES | - | |
| `high` | `numeric(20,8)` | YES | - | |
| `low` | `numeric(20,8)` | YES | - | |
| `close` | `numeric(20,8)` | YES | - | |
| `volume` | `numeric(20,8)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(15,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `movement` | `numeric(10,4)` | YES | - | Composite intra-candle range score (weighted (H-L)/O and rolling means). NULL for first 30 rows. |
| `movement_percentile` | `numeric(5,1)` | YES | - | Percentile of movement vs analytics.eth_movement_profile (0.5–99.5). Movement profile tables use column **movement_value** for the value at each percentile. |

#### Constraints

- **Primary Key:** `eth_price_history_pkey` on `timestamp`

#### Indexes

- `eth_price_history_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_price_history_pkey ON historical_data.eth_price_history USING btree ("timestamp")
  ```
- `unique_eth_price_history_timestamp`
  ```sql
  CREATE UNIQUE INDEX unique_eth_price_history_timestamp ON historical_data.eth_price_history USING btree ("timestamp")
  ```

---

### Table: `historical_data.ndx_price_history`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `timestamp` | `timestamp without time zone` | NO | - | |
| `open` | `numeric(20,8)` | YES | - | |
| `high` | `numeric(20,8)` | YES | - | |
| `low` | `numeric(20,8)` | YES | - | |
| `close` | `numeric(20,8)` | YES | - | |
| `volume` | `numeric(20,8)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(15,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `movement` | `numeric(10,4)` | YES | - | Composite intra-candle range score (weighted (H-L)/O and rolling means). NULL for first 30 rows. |
| `movement_percentile` | `numeric(5,1)` | YES | - | Percentile of movement vs analytics.ndx_movement_profile (0.5–99.5). Movement profile tables use column **movement_value** for the value at each percentile. |

#### Constraints

- **Primary Key:** `ndx_price_history_pkey` on `timestamp`

#### Indexes

- `ndx_price_history_pkey`
  ```sql
  CREATE UNIQUE INDEX ndx_price_history_pkey ON historical_data.ndx_price_history USING btree ("timestamp")
  ```
- `unique_ndx_price_history_timestamp`
  ```sql
  CREATE UNIQUE INDEX unique_ndx_price_history_timestamp ON historical_data.ndx_price_history USING btree ("timestamp")
  ```

---

### Table: `historical_data.spx_price_history`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `timestamp` | `timestamp without time zone` | NO | - | |
| `open` | `numeric(20,8)` | YES | - | |
| `high` | `numeric(20,8)` | YES | - | |
| `low` | `numeric(20,8)` | YES | - | |
| `close` | `numeric(20,8)` | YES | - | |
| `volume` | `numeric(20,8)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(15,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `movement` | `numeric(10,4)` | YES | - | Composite intra-candle range score (weighted (H-L)/O and rolling means). NULL for first 30 rows. |
| `movement_percentile` | `numeric(5,1)` | YES | - | Percentile of movement vs analytics.spx_movement_profile (0.5–99.5). Movement profile tables use column **movement_value** for the value at each percentile. |

#### Constraints

- **Primary Key:** `spx_price_history_pkey` on `timestamp`

#### Indexes

- `spx_price_history_pkey`
  ```sql
  CREATE UNIQUE INDEX spx_price_history_pkey ON historical_data.spx_price_history USING btree ("timestamp")
  ```
- `unique_spx_price_history_timestamp`
  ```sql
  CREATE UNIQUE INDEX unique_spx_price_history_timestamp ON historical_data.spx_price_history USING btree ("timestamp")
  ```

---

## Schema: `live_data`

### Table: `live_data.btc_price_change`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.btc_price_change_id_seq'::re... | |
| `change1h` | `numeric(10,6)` | YES | - | |
| `change3h` | `numeric(10,6)` | YES | - | |
| `change1d` | `numeric(10,6)` | YES | - | |
| `timestamp` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `btc_price_change_pkey` on `id`

#### Indexes

- `btc_price_change_pkey`
  ```sql
  CREATE UNIQUE INDEX btc_price_change_pkey ON live_data.btc_price_change USING btree (id)
  ```

---

### Table: `live_data.eth_price_change`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.eth_price_change_id_seq'::re... | |
| `change1h` | `numeric(10,6)` | YES | - | |
| `change3h` | `numeric(10,6)` | YES | - | |
| `change1d` | `numeric(10,6)` | YES | - | |
| `timestamp` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `eth_price_change_pkey` on `id`

#### Indexes

- `eth_price_change_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_price_change_pkey ON live_data.eth_price_change USING btree (id)
  ```

---

### Table: `live_data.live_price_log_1s_btc`

**Population (movement columns):** `move_1m` … `move_30m`, `movement`, and `movement_percentile` are written by `backend/symbol_price_watchdog.py` on each tick. High/low/open per window are derived from ticks in the same table; the weighted composite and percentile use `analytics.{symbol}_movement_profile` (which has column **movement_value** at each percentile). Same applies to `live_price_log_1s_eth`, `live_price_log_1s_sol`, and `live_price_log_1s_xrp`.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `timestamp` | `text` | NO | - | |
| `price` | `numeric(10,2)` | YES | - | |
| `one_minute_avg` | `numeric(10,2)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `delta_1m` | `numeric(10,4)` | YES | - | |
| `delta_2m` | `numeric(10,4)` | YES | - | |
| `delta_3m` | `numeric(10,4)` | YES | - | |
| `delta_4m` | `numeric(10,4)` | YES | - | |
| `delta_15m` | `numeric(10,4)` | YES | - | |
| `delta_30m` | `numeric(10,4)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `momentum_5s_avg` | `numeric(5,1)` | YES | - | |
| `momentum_30s_avg` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `move_1m` | `numeric(10,4)` | YES | - | Raw movement (high-low)/open for last 1m window. |
| `move_2m` | `numeric(10,4)` | YES | - | Raw movement for last 2m window. |
| `move_3m` | `numeric(10,4)` | YES | - | Raw movement for last 3m window. |
| `move_4m` | `numeric(10,4)` | YES | - | Raw movement for last 4m window. |
| `move_15m` | `numeric(10,4)` | YES | - | Raw movement for last 15m window. |
| `move_30m` | `numeric(10,4)` | YES | - | Raw movement for last 30m window. |
| `movement` | `numeric(10,4)` | YES | - | Weighted composite of move_1m..move_30m (same weights as momentum). |
| `movement_percentile` | `numeric(5,1)` | YES | - | Percentile from analytics movement profile (0.5–99.5). |

#### Constraints

- **Primary Key:** `live_price_log_1s_btc_pkey` on `timestamp`

#### Indexes

- `idx_live_price_log_1s_btc_timestamp`
  ```sql
  CREATE INDEX idx_live_price_log_1s_btc_timestamp ON live_data.live_price_log_1s_btc USING btree ("timestamp")
  ```
- `live_price_log_1s_btc_pkey`
  ```sql
  CREATE UNIQUE INDEX live_price_log_1s_btc_pkey ON live_data.live_price_log_1s_btc USING btree ("timestamp")
  ```

---

### Table: `live_data.live_price_log_1s_eth`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `timestamp` | `text` | NO | - | |
| `price` | `numeric(10,2)` | YES | - | |
| `one_minute_avg` | `numeric(10,2)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `delta_1m` | `numeric(10,4)` | YES | - | |
| `delta_2m` | `numeric(10,4)` | YES | - | |
| `delta_3m` | `numeric(10,4)` | YES | - | |
| `delta_4m` | `numeric(10,4)` | YES | - | |
| `delta_15m` | `numeric(10,4)` | YES | - | |
| `delta_30m` | `numeric(10,4)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `momentum_5s_avg` | `numeric(5,1)` | YES | - | |
| `momentum_30s_avg` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `move_1m` | `numeric(10,4)` | YES | - | Raw movement (high-low)/open for last 1m window. |
| `move_2m` | `numeric(10,4)` | YES | - | Raw movement for last 2m window. |
| `move_3m` | `numeric(10,4)` | YES | - | Raw movement for last 3m window. |
| `move_4m` | `numeric(10,4)` | YES | - | Raw movement for last 4m window. |
| `move_15m` | `numeric(10,4)` | YES | - | Raw movement for last 15m window. |
| `move_30m` | `numeric(10,4)` | YES | - | Raw movement for last 30m window. |
| `movement` | `numeric(10,4)` | YES | - | Weighted composite of move_1m..move_30m (same weights as momentum). |
| `movement_percentile` | `numeric(5,1)` | YES | - | Percentile from analytics movement profile (0.5–99.5). |

#### Constraints

- **Primary Key:** `live_price_log_1s_eth_pkey` on `timestamp`

#### Indexes

- `idx_live_price_log_1s_eth_timestamp`
  ```sql
  CREATE INDEX idx_live_price_log_1s_eth_timestamp ON live_data.live_price_log_1s_eth USING btree ("timestamp")
  ```
- `live_price_log_1s_eth_pkey`
  ```sql
  CREATE UNIQUE INDEX live_price_log_1s_eth_pkey ON live_data.live_price_log_1s_eth USING btree ("timestamp")
  ```

---

### Table: `live_data.live_price_log_1s_sol`

Same shape as `live_data.live_price_log_1s_eth`; `price` and `one_minute_avg` use `numeric(10,6)` for sub-dollar precision.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `timestamp` | `text` | NO | - | |
| `price` | `numeric(10,6)` | YES | - | |
| `one_minute_avg` | `numeric(10,6)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `delta_1m` | `numeric(10,4)` | YES | - | |
| `delta_2m` | `numeric(10,4)` | YES | - | |
| `delta_3m` | `numeric(10,4)` | YES | - | |
| `delta_4m` | `numeric(10,4)` | YES | - | |
| `delta_15m` | `numeric(10,4)` | YES | - | |
| `delta_30m` | `numeric(10,4)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `momentum_5s_avg` | `numeric(5,1)` | YES | - | |
| `momentum_30s_avg` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `move_1m` | `numeric(10,4)` | YES | - | Raw movement (high-low)/open for last 1m window. |
| `move_2m` | `numeric(10,4)` | YES | - | Raw movement for last 2m window. |
| `move_3m` | `numeric(10,4)` | YES | - | Raw movement for last 3m window. |
| `move_4m` | `numeric(10,4)` | YES | - | Raw movement for last 4m window. |
| `move_15m` | `numeric(10,4)` | YES | - | Raw movement for last 15m window. |
| `move_30m` | `numeric(10,4)` | YES | - | Raw movement for last 30m window. |
| `movement` | `numeric(10,4)` | YES | - | Weighted composite of move_1m..move_30m (same weights as momentum). |
| `movement_percentile` | `numeric(5,1)` | YES | - | Percentile from analytics movement profile (0.5–99.5). |

#### Constraints

- **Primary Key:** `live_price_log_1s_sol_pkey` on `timestamp`

#### Indexes

- `idx_live_price_log_1s_sol_timestamp` on `timestamp` (btree)

---

### Table: `live_data.live_price_log_1s_xrp`

Same as `live_data.live_price_log_1s_sol` (including `numeric(10,6)` for spot price fields).

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `timestamp` | `text` | NO | - | |
| `price` | `numeric(10,6)` | YES | - | |
| `one_minute_avg` | `numeric(10,6)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `delta_1m` | `numeric(10,4)` | YES | - | |
| `delta_2m` | `numeric(10,4)` | YES | - | |
| `delta_3m` | `numeric(10,4)` | YES | - | |
| `delta_4m` | `numeric(10,4)` | YES | - | |
| `delta_15m` | `numeric(10,4)` | YES | - | |
| `delta_30m` | `numeric(10,4)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `momentum_5s_avg` | `numeric(5,1)` | YES | - | |
| `momentum_30s_avg` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `move_1m` | `numeric(10,4)` | YES | - | Raw movement (high-low)/open for last 1m window. |
| `move_2m` | `numeric(10,4)` | YES | - | Raw movement for last 2m window. |
| `move_3m` | `numeric(10,4)` | YES | - | Raw movement for last 3m window. |
| `move_4m` | `numeric(10,4)` | YES | - | Raw movement for last 4m window. |
| `move_15m` | `numeric(10,4)` | YES | - | Raw movement for last 15m window. |
| `move_30m` | `numeric(10,4)` | YES | - | Raw movement for last 30m window. |
| `movement` | `numeric(10,4)` | YES | - | Weighted composite of move_1m..move_30m (same weights as momentum). |
| `movement_percentile` | `numeric(5,1)` | YES | - | Percentile from analytics movement profile (0.5–99.5). |

#### Constraints

- **Primary Key:** `live_price_log_1s_xrp_pkey` on `timestamp`

#### Indexes

- `idx_live_price_log_1s_xrp_timestamp` on `timestamp` (btree)

---

### Table: `live_data.live_symbol_status`

**Population:** Trigger-driven from `live_data.live_price_log_1s_btc`, `live_price_log_1s_eth`, `live_price_log_1s_sol`, and `live_price_log_1s_xrp` (latest row per symbol via upsert on `symbol`).

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.live_symbol_status_id_seq'::regclass) | |
| `symbol` | `character varying(20)` | YES | - | |
| `timestamp` | `text` | YES | - | |
| `price` | `numeric(10,2)` | YES | - | |
| `one_minute_avg` | `numeric(10,2)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `delta_1m` | `numeric(10,4)` | YES | - | |
| `delta_2m` | `numeric(10,4)` | YES | - | |
| `delta_3m` | `numeric(10,4)` | YES | - | |
| `delta_4m` | `numeric(10,4)` | YES | - | |
| `delta_15m` | `numeric(10,4)` | YES | - | |
| `delta_30m` | `numeric(10,4)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `momentum_5s_avg` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `momentum_30s_avg` | `numeric(5,1)` | YES | - | |
| `move_1m` | `numeric(10,4)` | YES | - | |
| `move_2m` | `numeric(10,4)` | YES | - | |
| `move_3m` | `numeric(10,4)` | YES | - | |
| `move_4m` | `numeric(10,4)` | YES | - | |
| `move_15m` | `numeric(10,4)` | YES | - | |
| `move_30m` | `numeric(10,4)` | YES | - | |
| `movement` | `numeric(10,4)` | YES | - | |
| `movement_percentile` | `numeric(5,1)` | YES | - | |
| `prev_day_avg_momentum_percentile` | `numeric(5,1)` | YES | - | |
| `prev_day_avg_volatility_percentile` | `numeric(5,1)` | YES | - | |
| `prev_day_avg_movement_percentile` | `numeric(5,1)` | YES | - | |
| `daily_update` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `live_symbol_status_pkey` on `id`

#### Indexes

- `live_symbol_status_pkey`
  ```sql
  CREATE UNIQUE INDEX live_symbol_status_pkey ON live_data.live_symbol_status USING btree (id)
  ```
- `live_symbol_status_symbol_uniq_all`
  ```sql
  CREATE UNIQUE INDEX live_symbol_status_symbol_uniq_all ON live_data.live_symbol_status USING btree (symbol)
  ```

---

### Table: `live_data.market_kalshi_hourly`

Unified hourly Kalshi market ladder for **BTC** and **ETH** (and any future rows) in one table; filter by **`symbol`** and **`exchange`**. Same logical shape as unified 15m market tables: dollar quote columns, **TEXT** `volume_fp` / `open_interest_fp`, **`updated_at`** for freshness.

**Migrations:** `20260329_2359_unified_hourly_pipeline_health` (merge + drop `market_kalshi_hourly_btc` / `market_kalshi_hourly_eth`); optional follow-ups such as `20260330_1000_hourly_tables_match_15m_shape` for column-order parity with 15m.

#### Constraints

- **Unique:** `market_kalshi_hourly_ex_sym_evt_mkt_uniq` on `(exchange, symbol, event_ticker, market_ticker)`

#### Indexes

- `market_kalshi_hourly_exchange_symbol_idx` on `(exchange, symbol)`
- `market_kalshi_hourly_exchange_symbol_event_idx` on `(exchange, symbol, event_ticker)`

---

### Table: `live_data.market_kalshi_15m`

Unified 15-minute market snapshots for tracked crypto symbols (BTC, ETH, SOL, XRP). Multiple rows per symbol (one per venue market in the active event). **`exchange`** identifies the exchange/API source (e.g. `kalshi`). Legacy split-symbol 15m market tables were dropped in migration `20260331_1200_live_data_drop_legacy_split_and_equity_tables`. On event rotation for a given symbol and exchange, those rows are deleted and repopulated; open-trade tickers may be preserved and re-inserted. `strike` is seeded from Kalshi `floor_strike`/subtitle at rollover. Migration `20260326_1000_venue_exchange_column_names` renames **`broker` → `exchange`**, migration `20260326_1600_market_kalshi_15m_drop_unused_legacy_columns` drops unused integer quote columns, and migration `20260327_2005_market_kalshi_15m_fp_text_columns` aligns fixed-point API fields (`volume_fp`, `open_interest_fp`) as text columns.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.market_kalshi_15m_id_seq'::regclass) | |
| `symbol` | `character varying(10)` | NO | - | e.g. BTC, ETH, SOL, XRP |
| `exchange` | `character varying(20)` | NO | - | e.g. `kalshi` |
| `event_ticker` | `character varying(50)` | NO | - | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | '15m' | Interval label |
| `strike` | `character varying(20)` | YES | - | From API `floor_strike` / subtitle or price-log backfill |
| `volume_fp` | `text` | YES | - | Kalshi fixed-point volume string (2dp), e.g. `123.00` |
| `open_interest_fp` | `text` | YES | - | Kalshi fixed-point open-interest string (2dp), e.g. `456.00` |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |
| `yes_bid_dollars` | `text` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `last_price_dollars` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `market_kalshi_15m_pkey` on `id`
- **Unique:** `market_kalshi_15m_exchange_symbol_event_market_unique` on `(exchange, symbol, event_ticker, market_ticker)`

#### Indexes

- `market_kalshi_15m_exchange_symbol_event_market_unique`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_15m_exchange_symbol_event_market_unique ON live_data.market_kalshi_15m USING btree (exchange, symbol, event_ticker, market_ticker)
  ```
- `market_kalshi_15m_broker_symbol_idx`
  ```sql
  CREATE INDEX market_kalshi_15m_broker_symbol_idx ON live_data.market_kalshi_15m USING btree (exchange, symbol)
  ```
- `market_kalshi_15m_broker_symbol_event_idx`
  ```sql
  CREATE INDEX market_kalshi_15m_broker_symbol_event_idx ON live_data.market_kalshi_15m USING btree (exchange, symbol, event_ticker)
  ```
- `market_kalshi_15m_pkey`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_15m_pkey ON live_data.market_kalshi_15m USING btree (id)
  ```

---

### Table: `live_data.market_kalshi_ws_15m`

Parallel 15-minute Kalshi market rows fed only by **`backend/market_watchdog_ws.py`** (WebSocket **Market Ticker**, channel `ticker`). **`yes_*` / `last_price_dollars`** are normalized to **4** decimal places (handles JSON float decoding). **`no_*_dollars`** use the same width (derived complements). **`volume_fp`** and **`open_interest_fp`** are **TEXT** with **2** fractional digits (Kalshi fixed-point semantics). `strike` is seeded from REST event `markets[]` at rollover (via `floor_strike`) and preserved on WS upserts (`COALESCE`). Ticker **`dollar_volume`** / **`dollar_open_interest`** are not persisted. On event rotation per symbol, rows for that symbol and exchange are cleared before new tickers are subscribed. Migrations: `20260328_1000_market_kalshi_ws_15m`, `20260328_1200_market_kalshi_ws_15m_slim_columns`, `20260328_1300_market_kalshi_ws_15m_volume_fp_text`.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.market_kalshi_ws_15m_id_seq'::regclass) | |
| `symbol` | `character varying(10)` | NO | - | e.g. BTC, ETH, SOL, XRP |
| `exchange` | `character varying(20)` | NO | - | e.g. `kalshi` |
| `event_ticker` | `character varying(50)` | NO | - | From REST discovery (same as REST watchdog) |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | '15m' | Interval label |
| `strike` | `character varying(20)` | YES | - | Usually NULL on WS path |
| `yes_bid_dollars` | `text` | YES | - | Normalized 4 dp (`kalshi_market_normalize.normalize_kalshi_dollar_text`) |
| `yes_ask_dollars` | `text` | YES | - | Same |
| `no_bid_dollars` | `text` | YES | - | Complement of yes ask, 4 dp |
| `no_ask_dollars` | `text` | YES | - | Complement of yes bid, 4 dp |
| `last_price_dollars` | `text` | YES | - | From ticker `price_dollars`, 4 dp |
| `volume_fp` | `text` | YES | - | Ticker `volume_fp`, 2 dp string (e.g. `142468.00`) |
| `open_interest_fp` | `text` | YES | - | Ticker `open_interest_fp`, 2 dp string |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |

#### Constraints

- **Primary Key:** `market_kalshi_ws_15m_pkey` on `id`
- **Unique:** `market_kalshi_ws_15m_exchange_symbol_event_market_unique` on `(exchange, symbol, event_ticker, market_ticker)`

#### Indexes

- `market_kalshi_ws_15m_exchange_symbol_event_market_unique`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_ws_15m_exchange_symbol_event_market_unique ON live_data.market_kalshi_ws_15m USING btree (exchange, symbol, event_ticker, market_ticker)
  ```
- `market_kalshi_ws_15m_exchange_symbol_idx`
  ```sql
  CREATE INDEX market_kalshi_ws_15m_exchange_symbol_idx ON live_data.market_kalshi_ws_15m USING btree (exchange, symbol)
  ```
- `market_kalshi_ws_15m_exchange_symbol_event_idx`
  ```sql
  CREATE INDEX market_kalshi_ws_15m_exchange_symbol_event_idx ON live_data.market_kalshi_ws_15m USING btree (exchange, symbol, event_ticker)
  ```
- `market_kalshi_ws_15m_pkey`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_ws_15m_pkey ON live_data.market_kalshi_ws_15m USING btree (id)
  ```

---

### Table: `live_data.price_change_btc`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.price_change_btc_id_seq'::re... | |
| `change1h` | `numeric(10,6)` | YES | - | |
| `change3h` | `numeric(10,6)` | YES | - | |
| `change1d` | `numeric(10,6)` | YES | - | |
| `timestamp` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

---

### Table: `live_data.price_change_eth`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.price_change_eth_id_seq'::re... | |
| `change1h` | `numeric(10,6)` | YES | - | |
| `change3h` | `numeric(10,6)` | YES | - | |
| `change1d` | `numeric(10,6)` | YES | - | |
| `timestamp` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

`live_data.price_change_sol` and `live_data.price_change_xrp` use the same column set and data types as `live_data.price_change_eth`.

#### Constraints

- **Primary Key:** `price_change_eth_pkey` on `id`

#### Indexes

- `price_change_eth_pkey`
  ```sql
  CREATE UNIQUE INDEX price_change_eth_pkey ON live_data.price_change_eth USING btree (id)
  ```

---

### Table: `live_data.strike_table_hourly`

Unified hourly strike snapshots for **BTC**, **ETH**, and any future symbols in one table; filter by **`exchange`** + **`symbol`**. **Column set, types, and physical order match `live_data.strike_table_15m`** (see that section for the full column list).

**Migrations:** `20260402_2300_strike_table_yes_no_prob_columns`, `20260329_2359_unified_hourly_pipeline_health` (merge + drop `strike_table_hourly_btc` / `strike_table_hourly_eth`); `20260330_1000_hourly_tables_match_15m_shape` rebuilds from `LIKE` 15m where applied.

#### Indexes

- `idx_strike_table_hourly_lookup` on `("timestamp", symbol, current_price)`
- `strike_table_hourly_exchange_symbol_idx` on `(exchange, symbol)`
- `strike_table_hourly_exchange_symbol_timestamp_idx` on `(exchange, symbol, "timestamp" DESC)`

---

### Table: `live_data.strike_table_15m`

Unified 15-minute strike table for all Kalshi 15m symbols (**BTC**, **ETH**, **SOL**, **XRP**). Rows are scoped by **`exchange`** (data-source key, e.g. `kalshi`, aligned with `live_data.market_kalshi_15m.exchange`). Populated by `backend/strike_table_generator.py --master-15m` and `backend/strike_table_generator_ws.py` (same table unless `STRIKE_TABLE_15M_TARGET` overrides). Legacy split-symbol `strike_table_15m_*` tables and **`strike_table_ws_15m`** were dropped in migration `20260331_1200_live_data_drop_legacy_split_and_equity_tables`.

Migrations: `20260325_1500_strike_table_15m_unified`, `20260325_1600_strike_table_15m_drop_exchange_display`, `20260326_1000_venue_exchange_column_names` (renames **`broker` → `exchange`** on this table), `20260326_2000_strike_table_15m_db_notify` (trigger `strike_table_15m_rec_io_db_notify` → `public.rec_io_db_notify()` for real-time backbone / pilot UIs), `20260327_2030_strike_table_15m_open_interest_and_dollars_only` (drop legacy cents asks, widen volume precision, add open_interest), `20260328_2115_strike_table_final_quarter_ask_tracking` (final-window YES/NO ask min/max/range in dollars for full 15m cycles), `20260330_2130_strike_final_quarter_asks_numeric_4dp` (store those six columns as `NUMERIC(18,4)`), `20260331_1200_live_data_drop_legacy_split_and_equity_tables` (drops `strike_table_ws_15m` and split-symbol `strike_table_15m_*`), `20260329_1800_strike_tables_volume_open_interest_fp_text` (Kalshi depth columns **`volume_fp` / `open_interest_fp` TEXT** only; drops `volume` / `open_interest`), `20260402_2300_strike_table_yes_no_prob_columns` (literal **yes_prob_hourly** / **no_prob_hourly** / **yes_prob_15m** / **no_prob_15m** lookup legs).

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer` | NO | nextval | Primary key |
| `timestamp` | `timestamptz` | YES | now() | Row snapshot time |
| `symbol` | `varchar(10)` | NO | - | `BTC`, `ETH`, etc. |
| `exchange` | `varchar(20)` | NO | - | Source key (e.g. `kalshi`) |
| `market` | `text` | YES | `15m` | Interval label |
| `current_price` | `numeric(18,5)` | YES | - | Spot |
| `ttc_hourly` | `integer` | YES | - | Unused for 15m (NULL) |
| `ttc_15m` | `integer` | YES | - | Seconds to next 15m boundary |
| `event_ticker` | `varchar(50)` | YES | - | Kalshi event |
| `market_title` | `text` | YES | - | Derived title |
| `strike_tier` | `integer` | YES | - | 0 for 15m |
| `market_status` | `varchar(20)` | YES | - | |
| `strike` | `numeric(18,5)` | YES | - | Strike level |
| `buffer` | `numeric(18,5)` | YES | - | |
| `buffer_pct` | `numeric(12,6)` | YES | - | |
| `probability_hourly` | `decimal(5,2)` | YES | - | NULL for 15m |
| `probability_15m` | `decimal(5,2)` | YES | - | Model probability |
| `yes_prob_hourly` | `decimal(5,2)` | YES | - | Lookup positive leg (hourly TTC); NULL on 15m rows. Migration `20260402_2300_strike_table_yes_no_prob_columns`. |
| `no_prob_hourly` | `decimal(5,2)` | YES | - | Lookup negative leg (hourly TTC); NULL on 15m rows. |
| `yes_prob_15m` | `decimal(5,2)` | YES | - | Lookup positive leg for 15m TTC. |
| `no_prob_15m` | `decimal(5,2)` | YES | - | Lookup negative leg for 15m TTC. |
| `yes_ask_dollars` / `no_ask_dollars` | `text` | YES | - | |
| `yes_bid_dollars` / `no_bid_dollars` | `text` | YES | - | |
| `yes_price_spread` / `no_price_spread` | `numeric(6,4)` | YES | - | |
| `yes_diff` / `no_diff` | `decimal(5,2)` | YES | - | |
| `volume_fp` | `text` | YES | - | Kalshi fixed-point volume string (same semantics as `live_data.market_kalshi_*`) |
| `open_interest_fp` | `text` | YES | - | Kalshi fixed-point open-interest string |
| `ticker` | `varchar(50)` | YES | - | Market ticker |
| `active_side` | `varchar(10)` | YES | - | |
| `momentum_weighted_score` | `decimal(5,3)` | YES | - | |
| `momentum_percentile` | `decimal(5,1)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `movement` | `numeric(10,4)` | YES | - | |
| `movement_percentile` | `numeric(5,1)` | YES | - | |
| `yes_ask_min_15m` / `yes_ask_max_15m` | `numeric(18,4)` | YES | - | Min/max `yes_ask_dollars` over the active **15m contract window** (full period for `market = 15m`). |
| `no_ask_min_15m` / `no_ask_max_15m` | `numeric(18,4)` | YES | - | Same for NO asks. |
| `yes_ask_range_15m` / `no_ask_range_15m` | `numeric(18,4)` | YES | - | `max - min` in dollars. |
| `created_at` | `timestamptz` | YES | now() | |

#### Indexes

- `strike_table_15m_broker_symbol_idx` on `(broker, symbol)`
- `idx_strike_table_15m_lookup` on `(timestamp, symbol, current_price)`
- `strike_table_15m_broker_symbol_timestamp_idx` on `(broker, symbol, timestamp DESC)`

---

### Table: `live_data.strike_pipeline_health`

Per-symbol pipeline health for **Kalshi 15m and hourly** WS strike publishers, trading gates, and dashboard power-light display (when `STRIKE_PIPELINE_HEALTH_STRICT_MODE` is on). Rows are keyed by **`(exchange, market, symbol)`** where **`market`** is `15m` or `hourly`. **`ws_transport_ok_at`** is updated by the market WS path (ping/recv) for catastrophic transport detection; strike WS writers update **`pipeline_health_checked_at`** and boolean health.

**Migrations:** `20260329_2359_unified_hourly_pipeline_health` (creates table, backfills `market='15m'` from legacy `strike_pipeline_health_15m`, drops legacy table). Older migration `20260326_1335_strike_pipeline_health_15m` applies only on DBs that have not yet run the unified migration.

#### Columns

- `exchange` VARCHAR(20) NOT NULL
- `market` VARCHAR(20) NOT NULL
- `symbol` VARCHAR(10) NOT NULL
- `pipeline_healthy` BOOLEAN NOT NULL DEFAULT FALSE
- `pipeline_health_reason` TEXT
- `pipeline_health_checked_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()
- `pipeline_health_max_age_sec` INTEGER NOT NULL DEFAULT 900
- `ws_transport_ok_at` TIMESTAMPTZ
- `updated_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()

#### Constraints

- Primary key on `(exchange, market, symbol)`

#### Indexes

- `strike_pipeline_health_checked_idx` on `(pipeline_health_checked_at DESC)`
- `strike_pipeline_health_transport_idx` on `(ws_transport_ok_at DESC NULLS LAST)`

---

### Table: `live_data.symbols_list`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.symbols_list_id_seq'::regclass) | |
| `symbol` | `text` | YES | - | |
| `analytics_updated` | `timestamp without time zone` | YES | - | |
| `date_added` | `timestamp without time zone` | YES | - | |

#### Constraints

- **Primary Key:** `symbols_list_pkey` on `id`

#### Indexes

- `symbols_list_pkey`
  ```sql
  CREATE UNIQUE INDEX symbols_list_pkey ON live_data.symbols_list USING btree (id)
  ```

---

## Schema: `public`

### Table: `public.active_trades`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('active_trades_id_seq'::regclass) | |
| `trade_id` | `integer(32)` | NO | - | |
| `ticket_id` | `character varying(100)` | NO | - | |
| `date` | `date` | NO | - | |
| `time` | `time without time zone` | NO | - | |
| `strike` | `character varying(50)` | NO | - | |
| `side` | `character varying(10)` | NO | - | |
| `buy_price` | `numeric(10,4)` | NO | - | |
| `position` | `integer(32)` | NO | - | |
| `contract` | `character varying(100)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `symbol` | `character varying(20)` | YES | - | |
| `market` | `character varying(50)` | YES | - | |
| `trade_strategy` | `character varying(50)` | YES | - | |
| `symbol_open` | `numeric(10,2)` | YES | - | |
| `momentum` | `character varying(20)` | YES | - | |
| `prob` | `numeric(10,4)` | YES | - | |
| `fees` | `numeric(10,4)` | YES | - | |
| `diff` | `character varying(20)` | YES | - | |
| `current_symbol_price` | `numeric(10,2)` | YES | NULL::numeric | |
| `current_probability` | `numeric(10,4)` | YES | NULL::numeric | |
| `buffer_from_entry` | `numeric(10,4)` | YES | NULL::numeric | |
| `time_since_entry` | `integer(32)` | YES | - | |
| `current_close_price` | `numeric(10,4)` | YES | NULL::numeric | |
| `current_pnl` | `character varying(20)` | YES | NULL::character varying | |
| `last_updated` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `status` | `character varying(20)` | YES | 'active'::character varying | |
| `notes` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `active_trades_pkey` on `id`

#### Indexes

- `active_trades_pkey`
  ```sql
  CREATE UNIQUE INDEX active_trades_pkey ON public.active_trades USING btree (id)
  ```

---

### Table: `public.fills`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('fills_id_seq'::regclass) | |
| `trade_id` | `character varying(50)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `order_id` | `character varying(50)` | YES | - | |
| `side` | `character varying(10)` | YES | - | |
| `action` | `character varying(20)` | YES | - | |
| `count` | `integer(32)` | YES | - | |
| `yes_price` | `numeric(10,4)` | YES | - | |
| `no_price` | `numeric(10,4)` | YES | - | |
| `is_taker` | `integer(32)` | YES | - | |
| `created_time` | `timestamp with time zone` | YES | - | |
| `raw_json` | `text` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `fills_pkey` on `id`
- **Unique:** `fills_trade_id_key` on `trade_id`

#### Indexes

- `fills_pkey`
  ```sql
  CREATE UNIQUE INDEX fills_pkey ON public.fills USING btree (id)
  ```
- `fills_trade_id_key`
  ```sql
  CREATE UNIQUE INDEX fills_trade_id_key ON public.fills USING btree (trade_id)
  ```
- `idx_fills_trade_id`
  ```sql
  CREATE INDEX idx_fills_trade_id ON public.fills USING btree (trade_id)
  ```

---

### Table: `public.positions`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('positions_id_seq'::regclass) | |
| `ticker` | `character varying(50)` | YES | - | |
| `total_traded` | `integer(32)` | YES | - | |
| `position` | `integer(32)` | YES | - | |
| `market_exposure` | `integer(32)` | YES | - | |
| `realized_pnl` | `numeric(10,4)` | YES | - | |
| `fees_paid` | `numeric(10,4)` | YES | - | |
| `last_updated_ts` | `timestamp with time zone` | YES | - | |
| `raw_json` | `text` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `positions_pkey` on `id`
- **Unique:** `positions_ticker_key` on `ticker`

#### Indexes

- `idx_positions_ticker`
  ```sql
  CREATE INDEX idx_positions_ticker ON public.positions USING btree (ticker)
  ```
- `idx_positions_updated_at`
  ```sql
  CREATE INDEX idx_positions_updated_at ON public.positions USING btree (updated_at)
  ```
- `positions_pkey`
  ```sql
  CREATE UNIQUE INDEX positions_pkey ON public.positions USING btree (id)
  ```
- `positions_ticker_key`
  ```sql
  CREATE UNIQUE INDEX positions_ticker_key ON public.positions USING btree (ticker)
  ```

---

### Table: `public.trades`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('trades_id_seq'::regclass) | |
| `status` | `character varying(20)` | NO | - | |
| `date` | `date` | NO | - | |
| `time` | `time without time zone` | NO | - | |
| `symbol` | `character varying(20)` | YES | 'BTC'::character varying | |
| `market` | `character varying(50)` | YES | 'Kalshi'::character varying | |
| `trade_strategy` | `character varying(50)` | YES | 'Hourly HTC'::character varying | |
| `contract` | `character varying(100)` | NO | - | |
| `strike` | `character varying(50)` | NO | - | |
| `side` | `character varying(10)` | NO | - | |
| `prob` | `numeric(10,4)` | YES | - | |
| `diff` | `character varying(50)` | YES | - | |
| `buy_price` | `numeric(10,4)` | NO | - | |
| `position` | `integer(32)` | NO | - | |
| `sell_price` | `numeric(10,4)` | YES | - | |
| `closed_at` | `timestamp with time zone` | YES | - | |
| `fees` | `integer(32)` | YES | - | |
| `pnl` | `integer(32)` | YES | - | |
| `symbol_open` | `integer(32)` | YES | - | |
| `symbol_close` | `integer(32)` | YES | - | |
| `momentum` | `numeric(10,4)` | YES | - | |
| `volatility` | `integer(32)` | YES | - | |
| `win_loss` | `character varying(1)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `ticket_id` | `character varying(100)` | YES | - | |
| `market_id` | `character varying(50)` | YES | 'BTC-USD'::character varying | |
| `momentum_delta` | `numeric(10,4)` | YES | - | |
| `entry_method` | `character varying(20)` | YES | 'manual'::character varying | |
| `close_method` | `character varying(20)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `momentum_percentile` | `numeric(10,4)` | YES | - | |

#### Constraints

- **Primary Key:** `trades_pkey` on `id`

#### Indexes

- `idx_trades_created_at`
  ```sql
  CREATE INDEX idx_trades_created_at ON public.trades USING btree (created_at)
  ```
- `idx_trades_date`
  ```sql
  CREATE INDEX idx_trades_date ON public.trades USING btree (date)
  ```
- `idx_trades_status`
  ```sql
  CREATE INDEX idx_trades_status ON public.trades USING btree (status)
  ```
- `idx_trades_symbol`
  ```sql
  CREATE INDEX idx_trades_symbol ON public.trades USING btree (symbol)
  ```
- `idx_trades_ticket_id`
  ```sql
  CREATE INDEX idx_trades_ticket_id ON public.trades USING btree (ticket_id)
  ```
- `trades_pkey`
  ```sql
  CREATE UNIQUE INDEX trades_pkey ON public.trades USING btree (id)
  ```

---

## Schema: `system`

### Table: `system.health_status`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | 1 | |
| `overall_status` | `character varying(20)` | NO | - | |
| `cpu_percent` | `numeric(5,2)` | YES | - | |
| `memory_percent` | `numeric(5,2)` | YES | - | |
| `disk_percent` | `numeric(5,2)` | YES | - | |
| `database_status` | `character varying(20)` | YES | - | |
| `supervisor_status` | `character varying(20)` | YES | - | |
| `services_healthy` | `integer(32)` | YES | - | |
| `services_total` | `integer(32)` | YES | - | |
| `failed_services` | `ARRAY` | YES | - | |
| `health_details` | `jsonb` | YES | - | |
| `timestamp` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `health_status_pkey` on `id`

#### Indexes

- `health_status_pkey`
  ```sql
  CREATE UNIQUE INDEX health_status_pkey ON system.health_status USING btree (id)
  ```

---

### Table: `system.installation_access_log`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('system.installation_access_log_id_seq'... | |
| `installer_user_id` | `character varying(100)` | NO | - | |
| `installer_name` | `character varying(200)` | YES | - | |
| `installer_email` | `character varying(200)` | YES | - | |
| `installer_ip_address` | `inet` | YES | - | |
| `connection_start` | `timestamp with time zone` | YES | now() | |
| `connection_end` | `timestamp with time zone` | YES | - | |
| `schemas_accessed` | `ARRAY` | YES | - | |
| `tables_cloned` | `integer(32)` | YES | - | |
| `total_rows_cloned` | `bigint(64)` | YES | - | |
| `clone_duration_seconds` | `integer(32)` | YES | - | |
| `status` | `character varying(50)` | YES | 'in_progress'::character varying | |
| `error_message` | `text` | YES | - | |
| `user_agent` | `text` | YES | - | |
| `installation_package_version` | `character varying(50)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |

#### Constraints

- **Primary Key:** `installation_access_log_pkey` on `id`

#### Indexes

- `installation_access_log_pkey`
  ```sql
  CREATE UNIQUE INDEX installation_access_log_pkey ON system.installation_access_log USING btree (id)
  ```

---

## Schema: `testing`

### Table: `testing.kalshi_level2_orderbook`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('testing.kalshi_level2_orderbook_id_seq... | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `strike_price` | `numeric(10,2)` | NO | - | |
| `side` | `character varying(10)` | NO | - | |
| `price` | `integer(32)` | NO | - | |
| `size` | `integer(32)` | NO | - | |
| `level_rank` | `integer(32)` | NO | - | |
| `is_best_bid` | `boolean` | YES | false | |
| `is_best_ask` | `boolean` | YES | false | |
| `spread` | `integer(32)` | YES | - | |
| `mid_price` | `numeric(5,2)` | YES | - | |
| `total_bid_volume` | `integer(32)` | YES | 0 | |
| `total_ask_volume` | `integer(32)` | YES | 0 | |
| `last_updated` | `timestamp with time zone` | YES | now() | |
| `sequence_number` | `integer(32)` | YES | - | |

#### Constraints

- **Primary Key:** `kalshi_level2_orderbook_pkey` on `id`
- **Unique:** `kalshi_level2_orderbook_market_ticker_side_price_key` on `market_ticker`
- **Unique:** `kalshi_level2_orderbook_market_ticker_side_price_key` on `market_ticker`
- **Unique:** `kalshi_level2_orderbook_market_ticker_side_price_key` on `side`
- **Unique:** `kalshi_level2_orderbook_market_ticker_side_price_key` on `side`
- **Unique:** `kalshi_level2_orderbook_market_ticker_side_price_key` on `market_ticker`
- **Unique:** `kalshi_level2_orderbook_market_ticker_side_price_key` on `price`
- **Unique:** `kalshi_level2_orderbook_market_ticker_side_price_key` on `price`
- **Unique:** `kalshi_level2_orderbook_market_ticker_side_price_key` on `price`
- **Unique:** `kalshi_level2_orderbook_market_ticker_side_price_key` on `side`

#### Indexes

- `idx_level2_orderbook_best_levels`
  ```sql
  CREATE INDEX idx_level2_orderbook_best_levels ON testing.kalshi_level2_orderbook USING btree (market_ticker, is_best_bid, is_best_ask)
  ```
- `idx_level2_orderbook_market`
  ```sql
  CREATE INDEX idx_level2_orderbook_market ON testing.kalshi_level2_orderbook USING btree (market_ticker)
  ```
- `idx_level2_orderbook_side_price`
  ```sql
  CREATE INDEX idx_level2_orderbook_side_price ON testing.kalshi_level2_orderbook USING btree (market_ticker, side, price)
  ```
- `idx_level2_orderbook_updated`
  ```sql
  CREATE INDEX idx_level2_orderbook_updated ON testing.kalshi_level2_orderbook USING btree (last_updated)
  ```
- `kalshi_level2_orderbook_market_ticker_side_price_key`
  ```sql
  CREATE UNIQUE INDEX kalshi_level2_orderbook_market_ticker_side_price_key ON testing.kalshi_level2_orderbook USING btree (market_ticker, side, price)
  ```
- `kalshi_level2_orderbook_pkey`
  ```sql
  CREATE UNIQUE INDEX kalshi_level2_orderbook_pkey ON testing.kalshi_level2_orderbook USING btree (id)
  ```

---

### Table: `testing.kalshi_orderbook_deltas`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('testing.kalshi_orderbook_deltas_id_seq... | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `side` | `character varying(10)` | NO | - | |
| `price` | `integer(32)` | NO | - | |
| `delta` | `integer(32)` | NO | - | |
| `sequence_number` | `integer(32)` | YES | - | |
| `delta_timestamp` | `timestamp with time zone` | YES | now() | |

#### Constraints

- **Primary Key:** `kalshi_orderbook_deltas_pkey` on `id`

#### Indexes

- `idx_orderbook_deltas_market`
  ```sql
  CREATE INDEX idx_orderbook_deltas_market ON testing.kalshi_orderbook_deltas USING btree (market_ticker)
  ```
- `idx_orderbook_deltas_timestamp`
  ```sql
  CREATE INDEX idx_orderbook_deltas_timestamp ON testing.kalshi_orderbook_deltas USING btree (delta_timestamp)
  ```
- `kalshi_orderbook_deltas_pkey`
  ```sql
  CREATE UNIQUE INDEX kalshi_orderbook_deltas_pkey ON testing.kalshi_orderbook_deltas USING btree (id)
  ```

---

### Table: `testing.kalshi_orderbook_snapshot`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('testing.kalshi_orderbook_snapshot_id_s... | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `side` | `character varying(10)` | NO | - | |
| `price` | `integer(32)` | NO | - | |
| `size` | `integer(32)` | NO | - | |
| `snapshot_timestamp` | `timestamp with time zone` | YES | now() | |
| `sequence_number` | `integer(32)` | YES | - | |

#### Constraints

- **Primary Key:** `kalshi_orderbook_snapshot_pkey` on `id`
- **Unique:** `kalshi_orderbook_snapshot_market_ticker_side_price_key` on `market_ticker`
- **Unique:** `kalshi_orderbook_snapshot_market_ticker_side_price_key` on `market_ticker`
- **Unique:** `kalshi_orderbook_snapshot_market_ticker_side_price_key` on `side`
- **Unique:** `kalshi_orderbook_snapshot_market_ticker_side_price_key` on `side`
- **Unique:** `kalshi_orderbook_snapshot_market_ticker_side_price_key` on `market_ticker`
- **Unique:** `kalshi_orderbook_snapshot_market_ticker_side_price_key` on `price`
- **Unique:** `kalshi_orderbook_snapshot_market_ticker_side_price_key` on `price`
- **Unique:** `kalshi_orderbook_snapshot_market_ticker_side_price_key` on `price`
- **Unique:** `kalshi_orderbook_snapshot_market_ticker_side_price_key` on `side`

#### Indexes

- `idx_orderbook_snapshot_market`
  ```sql
  CREATE INDEX idx_orderbook_snapshot_market ON testing.kalshi_orderbook_snapshot USING btree (market_ticker)
  ```
- `kalshi_orderbook_snapshot_market_ticker_side_price_key`
  ```sql
  CREATE UNIQUE INDEX kalshi_orderbook_snapshot_market_ticker_side_price_key ON testing.kalshi_orderbook_snapshot USING btree (market_ticker, side, price)
  ```
- `kalshi_orderbook_snapshot_pkey`
  ```sql
  CREATE UNIQUE INDEX kalshi_orderbook_snapshot_pkey ON testing.kalshi_orderbook_snapshot USING btree (id)
  ```

---

### Table: `testing.market_kalshi_btc_websocket`

Dev/testing sink for `backend/api/kalshi-api/kalshi_market_ticker_websocket.py`. Migration `20260329_1900_testing_market_kalshi_btc_websocket_dollars_fp` replaces legacy integer cent columns with dollar TEXT quotes and **`volume_fp` / `open_interest_fp` TEXT** only (parity with `live_data.market_kalshi_*`).

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval | |
| `event_ticker` | `character varying(50)` | NO | - | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | `hourly` | Interval label |
| `strike` | `character varying(20)` | YES | - | |
| `yes_bid_dollars` | `text` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `last_price_dollars` | `text` | YES | - | |
| `volume_fp` | `text` | YES | - | Orderbook total contracts as string |
| `open_interest_fp` | `text` | YES | - | Same source as `volume_fp` in this test writer |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |

#### Constraints

- **Primary Key:** `market_kalshi_btc_websocket_pkey` on `id`
- **Unique:** `market_kalshi_btc_websocket_event_ticker_market_ticker_key` on `(event_ticker, market_ticker)`

#### Indexes

- `market_kalshi_btc_websocket_event_ticker_market_ticker_key`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_btc_websocket_event_ticker_market_ticker_key ON testing.market_kalshi_btc_websocket USING btree (event_ticker, market_ticker)
  ```
- `market_kalshi_btc_websocket_pkey`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_btc_websocket_pkey ON testing.market_kalshi_btc_websocket USING btree (id)
  ```

---

### Table: `testing.redis_basic_test`

#### Columns
| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('testing.redis_basic_test_id_seq'::regclass) | |
| `test_value_1` | `numeric(10,4)` | YES | - | |
| `test_value_2` | `numeric(10,4)` | YES | - | |
| `test_value_3` | `numeric(10,4)` | YES | - | |
| `test_value_4` | `numeric(10,4)` | YES | - | |
| `test_value_5` | `numeric(10,4)` | YES | - | |
| `test_value_6` | `numeric(10,4)` | YES | - | |
| `test_value_7` | `numeric(10,4)` | YES | - | |
| `test_value_8` | `numeric(10,4)` | YES | - | |
| `test_value_9` | `numeric(10,4)` | YES | - | |
| `test_value_10` | `numeric(10,4)` | YES | - | |
| `test_value_11` | `numeric(10,4)` | YES | - | |
| `test_value_12` | `numeric(10,4)` | YES | - | |
| `test_value_13` | `numeric(10,4)` | YES | - | |
| `test_value_14` | `numeric(10,4)` | YES | - | |
| `test_value_15` | `numeric(10,4)` | YES | - | |
| `test_value_16` | `numeric(10,4)` | YES | - | |
| `test_value_17` | `numeric(10,4)` | YES | - | |
| `test_value_18` | `numeric(10,4)` | YES | - | |
| `test_value_19` | `numeric(10,4)` | YES | - | |
| `test_value_20` | `numeric(10,4)` | YES | - | |

#### Constraints
- **Primary Key:** `redis_basic_test_pkey` on `id`

---

### Table: `testing.candlesticks_1m_KXBTCD-26MAR2116-T70399.99`

Kalshi **1-minute** candlestick snapshot table for a single market (testing / backfill). SQL references must quote the table name: `testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99"`.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `timestamp` | `timestamp without time zone` | NO | - | Bar end instant as **US Eastern** wall time (`America/New_York`), no TZ — same convention as `historical_data.btc_price_history.timestamp` (first column for joins with price history) |
| `end_period_ts` | `bigint(64)` | NO | - | Unix seconds: end of the 1m bar (Kalshi `end_period_ts`) |
| `market_ticker` | `text` | NO | `KXBTCD-26MAR2116-T70399.99` | Market ticker (redundant with table name; safe for inserts) |
| `price_open_dollars` | `numeric(20,6)` | YES | - | Trade YES `price.open_dollars` |
| `price_high_dollars` | `numeric(20,6)` | YES | - | Trade YES `price.high_dollars` |
| `price_low_dollars` | `numeric(20,6)` | YES | - | Trade YES `price.low_dollars` |
| `price_close_dollars` | `numeric(20,6)` | YES | - | Trade YES `price.close_dollars` |
| `price_mean_dollars` | `numeric(20,6)` | YES | - | Trade YES `price.mean_dollars` |
| `price_previous_dollars` | `numeric(20,6)` | YES | - | Trade YES `price.previous_dollars` |
| `yes_bid_open_dollars` | `numeric(20,6)` | YES | - | `yes_bid.open_dollars` |
| `yes_bid_high_dollars` | `numeric(20,6)` | YES | - | `yes_bid.high_dollars` |
| `yes_bid_low_dollars` | `numeric(20,6)` | YES | - | `yes_bid.low_dollars` |
| `yes_bid_close_dollars` | `numeric(20,6)` | YES | - | `yes_bid.close_dollars` |
| `yes_ask_open_dollars` | `numeric(20,6)` | YES | - | `yes_ask.open_dollars` |
| `yes_ask_high_dollars` | `numeric(20,6)` | YES | - | `yes_ask.high_dollars` |
| `yes_ask_low_dollars` | `numeric(20,6)` | YES | - | `yes_ask.low_dollars` |
| `yes_ask_close_dollars` | `numeric(20,6)` | YES | - | `yes_ask.close_dollars` |
| `volume_fp` | `numeric(20,2)` | YES | - | `volume_fp` |
| `open_interest_fp` | `numeric(20,2)` | YES | - | `open_interest_fp` |
| `created_at` | `timestamp with time zone` | NO | `now()` | Row insert time |

#### Constraints

- **Primary Key:** `candle_1m_kxbtcd_26mar2116_rebuild_pkey` on `end_period_ts` (name from rebuild migration; functionally unique on `end_period_ts`)

---

### Table: `testing.candlesticks_1m_KXBTCD-26JAN1320-T95499.99`

Same layout as `testing.candlesticks_1m_KXBTCD-26MAR2116-T70399.99` (Kalshi 1m bars, **`timestamp` first**, US Eastern naive). SQL: `testing."candlesticks_1m_KXBTCD-26JAN1320-T95499.99"`. Populate from API: `scripts/testing/populate_kalshi_testing_candles_1m.py --ticker KXBTCD-26JAN1320-T95499.99` after migration.

#### Columns

Same as `testing.candlesticks_1m_KXBTCD-26MAR2116-T70399.99` except `market_ticker` default is `KXBTCD-26JAN1320-T95499.99`.

#### Constraints

- **Primary Key:** system-generated `*_pkey` on `end_period_ts`

---

### Table: `testing.candlesticks_1m_KXBTC15M-26MAR191745-45`

Same layout as `testing.candlesticks_1m_KXBTCD-26JAN1320-T95499.99` (Kalshi 1m bars, **`timestamp` first**, US Eastern naive). SQL: `testing."candlesticks_1m_KXBTC15M-26MAR191745-45"`. Used by `scripts/backtest/backtest_market_simulator.py` (default ticker). Migration: `20260322_1420_testing_candlesticks_1m_kxbtc15m_26mar191745_45`. Populate: `run_fill` / `--fetch-candles` on that script or `populate_kalshi_testing_candles_1m.py --ticker KXBTC15M-26MAR191745-45`.

#### Columns

Same as `testing.candlesticks_1m_KXBTCD-26JAN1320-T95499.99` except `market_ticker` default is `KXBTC15M-26MAR191745-45`.

#### Constraints

- **Primary Key:** `candlesticks_1m_kxbtc15m_26mar191745_45_pkey` on `end_period_ts` (name may vary by PostgreSQL)

---

## Schema: `users`

### Table: `users.account_balance_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.account_balance_0001_final_id_se... | |
| `balance` | `real(24)` | NO | - | |
| `exposure` | `integer(32)` | YES | - | |
| `positions` | `integer(32)` | YES | - | |
| `portfolio` | `integer(32)` | YES | - | |
| `timestamp` | `text` | NO | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `bankroll_current` | `integer(32)` | YES | - | |
| `bankroll_prev` | `integer(32)` | YES | - | |
| `portfolio_value` | `integer(32)` | YES | - | |
| `master_trading_bankroll` | `integer(32)` | YES | - | Snapshot of Master Trading Bankroll (MTB) balance in cents at the time of this row |
| `mtb_base_value` | `integer(32)` | YES | - | Snapshot of MTB base_value in cents at the time of this row |

#### Constraints

- **Primary Key:** `account_balance_0001_final_pkey` on `id`

#### Indexes

- `account_balance_0001_final_pkey`
  ```sql
  CREATE UNIQUE INDEX account_balance_0001_final_pkey ON users.account_balance_0001 USING btree (id)
  ```

---

### Table: `users.active_trades_15m_0001`

Unified Kalshi 15m active-trade tracking: **one table per user** (`active_trades_15m_<user>`), with **`monitor_id`** scoping (numeric monitor id, e.g. `10034`). Populated by `active_trade_supervisor` when run as `unified_15m`. At most one open/pending/closing row per monitor in normal operation; **`trade_id`** is globally unique in the table.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | serial | |
| `monitor_id` | `character varying(20)` | NO | - | Monitor id (e.g. `10034`), not `mon_` prefix |
| `trade_id` | `integer(32)` | NO | - | FK-like reference to `users.trades_0001.id` |
| `ticket_id` | `character varying(50)` | YES | - | |
| `date` | `date` | YES | - | |
| `time` | `time without time zone` | YES | - | |
| `strike` | `character varying(50)` | YES | - | |
| `side` | `character varying(10)` | YES | - | |
| `buy_price` | `numeric(10,4)` | YES | - | |
| `position` | `integer(32)` | YES | - | |
| `contract` | `character varying(50)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `symbol` | `character varying(10)` | YES | - | |
| `exchange` | `character varying(50)` | YES | - | Execution venue slug (same convention as `users.trades_0001.exchange`) |
| `trade_strategy` | `character varying(50)` | YES | - | |
| `symbol_open` | `numeric(10,2)` | YES | - | |
| `momentum` | `numeric(5,2)` | YES | - | |
| `prob` | `numeric(5,2)` | YES | - | |
| `fees` | `numeric(10,4)` | YES | - | |
| `diff` | `numeric(10,4)` | YES | - | |
| `status` | `character varying(20)` | YES | `'active'` | |
| `current_symbol_price` | `numeric(20,8)` | YES | - | Spot from `live_price_log_1s_*` at full precision |
| `current_probability` | `numeric(5,2)` | YES | - | |
| `buffer_from_entry` | `numeric(20,8)` | YES | - | `current_symbol_price − strike` (signed per side rules) |
| `time_since_entry` | `integer(32)` | YES | - | |
| `current_close_price` | `numeric(10,4)` | YES | - | |
| `current_pnl` | `character varying(20)` | YES | - | |
| `high_price` | `numeric(10,4)` | YES | - | |
| `low_price` | `numeric(10,4)` | YES | - | |
| `last_updated` | `timestamp without time zone` | YES | `CURRENT_TIMESTAMP` | |
| `created_at` | `timestamp without time zone` | YES | `CURRENT_TIMESTAMP` | |

#### Constraints / indexes

- **Unique:** `trade_id` (one row per trade).
- **Index:** `(monitor_id, status)` for lookups by monitor.

**Migrations:** `20260326_1800_active_trades_0001_15m_pool` (create pool). `20260331_1115_active_trades_unified_table_naming` (rename to `active_trades_15m_0001`). `20260327_1015_active_trades_ensure_exchange` (idempotent: rename `market` → `exchange` or add `exchange` on any `users.active_trades_*` still missing it). `20260327_1020_active_trades_monitoring_price_precision` (`current_symbol_price`, `buffer_from_entry` → `numeric(20,8)` on all `users.active_trades_*`).

---

### Table: `users.active_trades_hourly_0001`

Unified Kalshi **hourly** active-trade tracking: **one table per user** (`active_trades_hourly_<user>`), with **`monitor_id`** scoping. Populated by `active_trade_supervisor` when run as `unified_hourly`. **`trade_id`** is globally unique in the table (same shape as `users.active_trades_15m_0001`).

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | serial | |
| `monitor_id` | `character varying(20)` | NO | - | Monitor id (e.g. `10034`), not `mon_` prefix |
| `trade_id` | `integer(32)` | NO | - | Reference to `users.trades_0001.id` |
| `ticket_id` | `character varying(50)` | YES | - | |
| `date` | `date` | YES | - | |
| `time` | `time without time zone` | YES | - | |
| `strike` | `character varying(50)` | YES | - | |
| `side` | `character varying(10)` | YES | - | |
| `buy_price` | `numeric(10,4)` | YES | - | |
| `position` | `integer(32)` | YES | - | |
| `contract` | `character varying(50)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `symbol` | `character varying(10)` | YES | - | |
| `exchange` | `character varying(50)` | YES | - | Execution venue slug |
| `trade_strategy` | `character varying(50)` | YES | - | |
| `symbol_open` | `numeric(10,2)` | YES | - | |
| `momentum` | `numeric(5,2)` | YES | - | |
| `prob` | `numeric(5,2)` | YES | - | |
| `fees` | `numeric(10,4)` | YES | - | |
| `diff` | `numeric(10,4)` | YES | - | |
| `status` | `character varying(20)` | YES | `'active'` | |
| `current_symbol_price` | `numeric(20,8)` | YES | - | |
| `current_probability` | `numeric(5,2)` | YES | - | |
| `buffer_from_entry` | `numeric(20,8)` | YES | - | |
| `time_since_entry` | `integer(32)` | YES | - | |
| `current_close_price` | `numeric(10,4)` | YES | - | |
| `current_pnl` | `character varying(20)` | YES | - | |
| `high_price` | `numeric(10,4)` | YES | - | |
| `low_price` | `numeric(10,4)` | YES | - | |
| `last_updated` | `timestamp without time zone` | YES | `CURRENT_TIMESTAMP` | |
| `created_at` | `timestamp without time zone` | YES | `CURRENT_TIMESTAMP` | |

#### Constraints / indexes

- **Unique:** `trade_id`.
- **Index:** `(monitor_id, status)` for lookups by monitor.

**Migrations:** `20260330_2200_active_trades_0001_hourly_pool` (create pool). `20260331_1115_active_trades_unified_table_naming` (rename to `active_trades_hourly_0001`). Same follow-on migrations as other `users.active_trades_*` tables apply where idempotent (`exchange` column, monitoring price precision).

---

### Table: `users.active_trades_0001_10002`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.active_trades_0001_10002_id_seq'... | |
| `trade_id` | `integer(32)` | NO | - | |
| `ticket_id` | `character varying(50)` | YES | - | |
| `date` | `date` | YES | - | |
| `time` | `time without time zone` | YES | - | |
| `strike` | `character varying(50)` | YES | - | |
| `side` | `character varying(10)` | YES | - | |
| `buy_price` | `numeric(10,4)` | YES | - | |
| `position` | `integer(32)` | YES | - | |
| `contract` | `character varying(50)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `symbol` | `character varying(10)` | YES | - | |
| `exchange` | `character varying(50)` | YES | - | Execution venue slug. Migration `20260326_1000_venue_exchange_column_names` renames **`market` → `exchange`**. |
| `trade_strategy` | `character varying(50)` | YES | - | |
| `symbol_open` | `numeric(10,2)` | YES | - | |
| `momentum` | `numeric(5,2)` | YES | - | |
| `prob` | `numeric(5,2)` | YES | - | |
| `fees` | `numeric(10,4)` | YES | - | |
| `diff` | `numeric(10,4)` | YES | - | |
| `status` | `character varying(20)` | YES | 'active'::character varying | |
| `current_symbol_price` | `numeric(20,8)` | YES | - | |
| `current_probability` | `numeric(5,2)` | YES | - | |
| `buffer_from_entry` | `numeric(20,8)` | YES | - | |
| `time_since_entry` | `integer(32)` | YES | - | |
| `current_close_price` | `numeric(10,4)` | YES | - | |
| `current_pnl` | `character varying(20)` | YES | - | |
| `high_price` | `numeric(10,4)` | YES | - | |
| `low_price` | `numeric(10,4)` | YES | - | |
| `last_updated` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `active_trades_0001_10002_pkey` on `id`

#### Indexes

- `active_trades_0001_10002_pkey`
  ```sql
  CREATE UNIQUE INDEX active_trades_0001_10002_pkey ON users.active_trades_0001_10002 USING btree (id)
  ```

---

### Table: `users.active_trades_0001_10009`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.active_trades_0001_10009_id_seq'... | |
| `trade_id` | `integer(32)` | NO | - | |
| `ticket_id` | `character varying(50)` | YES | - | |
| `date` | `date` | YES | - | |
| `time` | `time without time zone` | YES | - | |
| `strike` | `character varying(50)` | YES | - | |
| `side` | `character varying(10)` | YES | - | |
| `buy_price` | `numeric(10,4)` | YES | - | |
| `position` | `integer(32)` | YES | - | |
| `contract` | `character varying(50)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `symbol` | `character varying(10)` | YES | - | |
| `exchange` | `character varying(50)` | YES | - | Execution venue slug. Migration `20260326_1000_venue_exchange_column_names` renames **`market` → `exchange`**. |
| `trade_strategy` | `character varying(50)` | YES | - | |
| `symbol_open` | `numeric(10,2)` | YES | - | |
| `momentum` | `numeric(5,2)` | YES | - | |
| `prob` | `numeric(5,2)` | YES | - | |
| `fees` | `numeric(10,4)` | YES | - | |
| `diff` | `numeric(10,4)` | YES | - | |
| `status` | `character varying(20)` | YES | 'active'::character varying | |
| `current_symbol_price` | `numeric(20,8)` | YES | - | |
| `current_probability` | `numeric(5,2)` | YES | - | |
| `buffer_from_entry` | `numeric(20,8)` | YES | - | |
| `time_since_entry` | `integer(32)` | YES | - | |
| `current_close_price` | `numeric(10,4)` | YES | - | |
| `current_pnl` | `character varying(20)` | YES | - | |
| `high_price` | `numeric(10,4)` | YES | - | |
| `low_price` | `numeric(10,4)` | YES | - | |
| `last_updated` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `created_at` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `active_trades_0001_10009_pkey` on `id`

#### Indexes

- `active_trades_0001_10009_pkey`
  ```sql
  CREATE UNIQUE INDEX active_trades_0001_10009_pkey ON users.active_trades_0001_10009 USING btree (id)
  ```

---

### Table: `users.dashboard_preferences_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.dashboard_preferences_0001_id_se... | |
| `user_id` | `integer(32)` | NO | - | |
| `portfolio_chart_view` | `character varying(10)` | NO | 'all'::character varying | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |
| `monitor_view_mode` | `character varying(10)` | YES | 'tile'::character varying | |
| `monitor_sort_by` | `character varying(20)` | YES | 'name'::character varying | |
| `allocation_view` | `character varying(10)` | YES | 'pie'::character varying | |
| `portfolio_view` | `text` | YES | 'portfolio' | Which portfolio panel tab is active: `bankroll`, `portfolio`, or `pnl`. Persisted when user changes the tab. |

#### Constraints

- **Primary Key:** `dashboard_preferences_0001_pkey` on `id`
- **Unique:** `dashboard_preferences_0001_user_id_key` on `user_id`

#### Indexes

- `dashboard_preferences_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX dashboard_preferences_0001_pkey ON users.dashboard_preferences_0001 USING btree (id)
  ```
- `dashboard_preferences_0001_user_id_key`
  ```sql
  CREATE UNIQUE INDEX dashboard_preferences_0001_user_id_key ON users.dashboard_preferences_0001 USING btree (user_id)
  ```

---

### Table: `users.fills_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.fills_0001_id_seq'::regclass) | |
| `trade_id` | `text` | YES | - | |
| `ticker` | `text` | YES | - | |
| `order_id` | `text` | YES | - | |
| `side` | `text` | YES | - | |
| `action` | `text` | YES | - | |
| `count` | `integer(32)` | YES | - | |
| `count_fp` | `numeric(12,2)` | YES | - | Fixed-point contract count (Kalshi migration). |
| `yes_price_dollars` | `text` | YES | - | Fill price in dollars (Kalshi API yes_price_dollars). |
| `no_price_dollars` | `text` | YES | - | Fill price in dollars (Kalshi API no_price_dollars). |
| `is_taker` | `boolean` | YES | - | |
| `created_time` | `text` | YES | - | |
| `raw_json` | `text` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `fills_0001_pkey` on `id`
- **Unique:** `fills_0001_trade_id_key` on `trade_id`

#### Indexes

- `fills_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX fills_0001_pkey ON users.fills_0001 USING btree (id)
  ```
- `fills_0001_trade_id_key`
  ```sql
  CREATE UNIQUE INDEX fills_0001_trade_id_key ON users.fills_0001 USING btree (trade_id)
  ```
- `idx_fills_0001_ticker`
  ```sql
  CREATE INDEX idx_fills_0001_ticker ON users.fills_0001 USING btree (ticker)
  ```

---

### Table: `users.master_users`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `user_no` | `character varying(10)` | YES | - | |
| `user_id` | `character varying(50)` | YES | - | |
| `email` | `character varying(255)` | YES | - | |
| `first_name` | `character varying(50)` | YES | - | |
| `last_name` | `character varying(50)` | YES | - | |
| `phone` | `character varying(20)` | YES | - | |
| `account_type` | `character varying(20)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | - | |
| `last_login` | `timestamp with time zone` | YES | - | |
| `is_active` | `boolean` | YES | - | |
| `password_hash` | `character varying(255)` | YES | - | |
| `updated_at` | `timestamp with time zone` | YES | - | |
| `server_ip` | `character varying(45)` | YES | - | |

---

### Table: `users.monitor_cycle_performance_0001_10002`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `weekly_cycle` | `smallint(16)` | NO | - | |
| `day_name` | `text` | YES | - | |
| `contract_hour` | `text` | YES | - | |
| `trade_count` | `integer(32)` | NO | 0 | |
| `win_count` | `integer(32)` | NO | 0 | |
| `win_rate_pct` | `numeric(5,2)` | YES | - | |
| `avg_collateral_exposure` | `integer(32)` | YES | - | |
| `median_exposure` | `integer(32)` | YES | - | |
| `max_exposure` | `integer(32)` | YES | - | |
| `window_start` | `timestamp with time zone` | YES | - | |
| `window_end` | `timestamp with time zone` | YES | - | |
| `last_updated` | `timestamp with time zone` | NO | now() | |
| `performance_modifier` | `numeric(10,2)` | NO | 0 | |
| `max_pct_exposure` | `numeric(10,2)` | YES | - | |

#### Constraints

- **Primary Key:** `monitor_cycle_performance_0001_10002_pkey` on `weekly_cycle`

#### Indexes

- `monitor_cycle_performance_0001_10002_pkey`
  ```sql
  CREATE UNIQUE INDEX monitor_cycle_performance_0001_10002_pkey ON users.monitor_cycle_performance_0001_10002 USING btree (weekly_cycle)
  ```
- `monitor_cycle_performance_0001_10002_winrate_idx`
  ```sql
  CREATE INDEX monitor_cycle_performance_0001_10002_winrate_idx ON users.monitor_cycle_performance_0001_10002 USING btree (win_rate_pct DESC NULLS LAST)
  ```

---

### Table: `users.monitor_cycle_performance_0001_10009`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `weekly_cycle` | `smallint(16)` | NO | - | |
| `day_name` | `text` | YES | - | |
| `contract_hour` | `text` | YES | - | |
| `trade_count` | `integer(32)` | NO | 0 | |
| `win_count` | `integer(32)` | NO | 0 | |
| `win_rate_pct` | `numeric(5,2)` | YES | - | |
| `avg_collateral_exposure` | `integer(32)` | YES | - | |
| `median_exposure` | `integer(32)` | YES | - | |
| `max_exposure` | `integer(32)` | YES | - | |
| `window_start` | `timestamp with time zone` | YES | - | |
| `window_end` | `timestamp with time zone` | YES | - | |
| `last_updated` | `timestamp with time zone` | NO | now() | |
| `performance_modifier` | `numeric(10,2)` | NO | 0 | |
| `max_pct_exposure` | `numeric(10,2)` | YES | - | |

#### Constraints

- **Primary Key:** `monitor_cycle_performance_0001_10009_pkey` on `weekly_cycle`

#### Indexes

- `monitor_cycle_performance_0001_10009_pkey`
  ```sql
  CREATE UNIQUE INDEX monitor_cycle_performance_0001_10009_pkey ON users.monitor_cycle_performance_0001_10009 USING btree (weekly_cycle)
  ```
- `monitor_cycle_performance_0001_10009_winrate_idx`
  ```sql
  CREATE INDEX monitor_cycle_performance_0001_10009_winrate_idx ON users.monitor_cycle_performance_0001_10009 USING btree (win_rate_pct DESC NULLS LAST)
  ```

---

### Table: `users.monitor_cycle_performance_0001_10014`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `weekly_cycle` | `smallint(16)` | NO | - | |
| `day_name` | `text` | YES | - | |
| `contract_hour` | `text` | YES | - | |
| `trade_count` | `integer(32)` | NO | 0 | |
| `win_count` | `integer(32)` | NO | 0 | |
| `win_rate_pct` | `numeric(5,2)` | YES | - | |
| `avg_collateral_exposure` | `integer(32)` | YES | - | |
| `median_exposure` | `integer(32)` | YES | - | |
| `max_exposure` | `integer(32)` | YES | - | |
| `window_start` | `timestamp with time zone` | YES | - | |
| `window_end` | `timestamp with time zone` | YES | - | |
| `last_updated` | `timestamp with time zone` | NO | now() | |
| `performance_modifier` | `numeric(10,2)` | NO | 0 | |
| `max_pct_exposure` | `numeric(10,2)` | YES | - | |

#### Constraints

- **Primary Key:** `monitor_cycle_performance_0001_10014_pkey` on `weekly_cycle`

#### Indexes

- `monitor_cycle_performance_0001_10014_pkey`
  ```sql
  CREATE UNIQUE INDEX monitor_cycle_performance_0001_10014_pkey ON users.monitor_cycle_performance_0001_10014 USING btree (weekly_cycle)
  ```
- `monitor_cycle_performance_0001_10014_winrate_idx`
  ```sql
  CREATE INDEX monitor_cycle_performance_0001_10014_winrate_idx ON users.monitor_cycle_performance_0001_10014 USING btree (win_rate_pct DESC NULLS LAST)
  ```

---

### Table: `users.monitor_cycle_performance_0001_10018`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `weekly_cycle` | `smallint(16)` | NO | - | |
| `day_name` | `text` | YES | - | |
| `contract_hour` | `text` | YES | - | |
| `trade_count` | `integer(32)` | NO | 0 | |
| `win_count` | `integer(32)` | NO | 0 | |
| `win_rate_pct` | `numeric(5,2)` | YES | - | |
| `avg_collateral_exposure` | `integer(32)` | YES | - | |
| `median_exposure` | `integer(32)` | YES | - | |
| `max_exposure` | `integer(32)` | YES | - | |
| `performance_modifier` | `numeric(10,2)` | NO | 0 | |
| `window_start` | `timestamp with time zone` | YES | - | |
| `window_end` | `timestamp with time zone` | YES | - | |
| `last_updated` | `timestamp with time zone` | NO | now() | |
| `max_pct_exposure` | `numeric(10,2)` | YES | - | |

#### Constraints

- **Primary Key:** `monitor_cycle_performance_0001_10018_pkey` on `weekly_cycle`

#### Indexes

- `monitor_cycle_performance_0001_10018_pkey`
  ```sql
  CREATE UNIQUE INDEX monitor_cycle_performance_0001_10018_pkey ON users.monitor_cycle_performance_0001_10018 USING btree (weekly_cycle)
  ```
- `monitor_cycle_performance_0001_10018_winrate_idx`
  ```sql
  CREATE INDEX monitor_cycle_performance_0001_10018_winrate_idx ON users.monitor_cycle_performance_0001_10018 USING btree (win_rate_pct DESC NULLS LAST)
  ```

---

### Table: `users.monitor_list_0001`

#### Semantics (status vs auto_trade)

- **`status`** (`'active'` | `'inactive'`): **Script lifecycle.** Determines whether AES/ATS script iterations for this monitor are running. Active = scripts run; inactive = they are torn down. Activate/deactivate endpoints and supervisor config use this only.
- **`auto_trade`** / **`auto_trade_status`**:** Auto-trading only.** Whether the monitor may place trades automatically. Do not use for script lifecycle.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.monitor_list_0001_id_seq'::regcl... | |
| `name` | `character varying(255)` | NO | - | |
| `symbol` | `character varying(20)` | NO | - | |
| `market` | `text` | YES | 'hourly' | Market interval: 'hourly' or '15m'. |
| `strategy` | `character varying(100)` | YES | - | |
| `auto_trade` | `boolean` | YES | false | Auto-trading only (not script lifecycle). |
| `auto_trade_status` | `character varying(20)` | YES | 'inactive'::character varying | Auto-trading only (not script lifecycle). |
| `trades` | `integer(32)` | YES | 0 | |
| `win_loss` | `numeric(5,1)` | YES | 0.0 | |
| `ret_pct` | `numeric(5,1)` | YES | 0.0 | |
| `pnl` | `numeric(10,2)` | YES | 0.00 | |
| `bankroll_allotment` | `numeric(5,1)` | YES | 0.0 | |
| `bankroll_allotment_pct` | `real(24)` | YES | 0.00 | |
| `status` | `character varying(20)` | YES | 'active'::character varying | Script lifecycle: 'active' = AES/ATS run, 'inactive' = torn down. |
| `created` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `bankroll_allotment_total` | `integer(32)` | YES | 0 | |
| `position_size` | `integer(32)` | YES | 1 | |
| `multiplier` | `numeric(3,2)` | YES | 1.00 | |
| `total_position` | `integer(32)` | YES | 1 | |
| `position_type` | `character varying(20)` | YES | 'percent'::character varying | |
| `dashboard_order` | `integer(32)` | YES | 1 | |
| `cooldown_timer` | `integer(32)` | YES | 0 | |
| `cooldown_start_time` | `timestamp with time zone` | YES | - | |
| `min_cooldown_timer` | `integer(32)` | YES | 300 | Minimum cooldown timer value (in seconds) required for auto entry activation. Strategy will not activate if cooldown_timer is below this value. |
| `max_cooldown_timer` | `integer(32)` | YES | 3300 | Maximum cooldown timer value (in seconds) allowed for auto entry activation. Strategy will not activate if cooldown_timer is above this value. |
| `min_ask_range` | `numeric(18,4)` | YES | - | Rising Devil: min active-side ask range (strike `yes_ask_range_15m` / `no_ask_range_15m`) to fire; NULL disables. Migration `20260401_1500_rising_devil_min_ask_range`. |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `created_strategy` | `timestamp without time zone` | YES | - | |
| `updated_strategy` | `timestamp without time zone` | YES | - | |
| `default_strategy` | `boolean` | NO | false | |
| `min_probability` | `numeric(5,2)` | YES | 95.00 | |
| `min_differential` | `numeric(5,2)` | YES | 0.25 | |
| `min_time` | `integer(32)` | YES | 120 | |
| `max_time` | `integer(32)` | YES | 900 | |
| `allow_re_entry` | `boolean` | YES | false | |
| `spike_alert_enabled` | `boolean` | YES | true | |
| `spike_alert_momentum_threshold` | `integer(32)` | YES | 36 | |
| `spike_alert_cooldown_threshold` | `integer(32)` | YES | 30 | |
| `spike_alert_cooldown_minutes` | `integer(32)` | YES | 15 | |
| `current_probability` | `integer(32)` | YES | 40 | |
| `stop_loss_price` | `numeric(6,4)` | YES | 0.0000 | Ask-gate stop: **0 disables**. When opposite-side ask exceeds `(1 − stop_loss_price)`, ATS triggers immediate `trigger_auto_stop_close` (no verification). Migration `20260329_1100_monitor_strategy_stop_loss_price`. |
| `min_ttc_seconds` | `integer(32)` | YES | 60 | |
| `momentum_spike_enabled` | `boolean` | YES | true | |
| `momentum_spike_threshold` | `integer(32)` | YES | 36 | |
| `user_id_strategy` | `character varying(10)` | YES | '0001'::character varying | |
| `verification_period_enabled` | `boolean` | YES | false | |
| `verification_period_seconds` | `integer(32)` | YES | 15 | |
| `min_volume` | `integer(32)` | YES | 1000 | |
| `max_differential` | `numeric(5,2)` | YES | NULL::numeric | |
| `win_streak` | `integer(32)` | YES | 0 | |
| `loss_prevention` | `character varying(50)` | YES | 'none'::character varying | |
| `win_streak_threshold` | `integer(32)` | YES | 22 | |
| `last_processed_cycle` | `character varying(100)` | YES | - | |
| `momentum_scalp_entry_threshold` | `numeric(5,2)` | YES | NULL::numeric | |
| `momentum_scalp_trailing_stop_amount` | `numeric(5,2)` | YES | 0.10 | |
| `momentum_scalp_profit_target` | `numeric(5,2)` | YES | 0.99 | |
| `min_ask` | `numeric(6,4)` | YES | 0.0000 | |
| `max_ask` | `numeric(6,4)` | YES | 0.9800 | |
| `max_profit` | `numeric(6,4)` | YES | 0.9900 | |
| `loss_prevention_toggle` | `boolean` | YES | true | |
| `max_probability` | `numeric(5,2)` | YES | 100.00 | |
| `current_contract` | `text` | YES | - | |
| `current_weekly_cycle` | `smallint(16)` | YES | - | |
| `current_performance_modifier` | `numeric(10,2)` | YES | 1.00 | |
| `current_max_pct_exposure` | `numeric(10,2)` | YES | 0.25 | |
| `performance_based_allocation` | `boolean` | NO | false | |
| `max_price_spread` | `numeric(6,4)` | YES | 0.0300 | |
| `paper_trade` | `boolean` | YES | false | |
| `regime_monitor_enabled` | `boolean` | YES | false | Enable regime monitor auto-switch between LIVE/PAPER for this monitor. |
| `regime_window` | `text` | YES | 30d | Rolling lookback window for regime evaluation (allowed: 30d, 7d, 1d, 12h). |
| `prob_adj` | `numeric(5,2)` | YES | 5.00 | |

#### Constraints

- **Primary Key:** `monitor_list_0001_pkey` on `id`

#### Indexes

- `monitor_list_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX monitor_list_0001_pkey ON users.monitor_list_0001 USING btree (id)
  ```

---

### Table: `users.orders_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.orders_0001_id_seq'::regclass) | |
| `order_id` | `text` | YES | - | |
| `user_id` | `text` | YES | - | |
| `ticker` | `text` | YES | - | |
| `status` | `text` | YES | - | |
| `action` | `text` | YES | - | |
| `side` | `text` | YES | - | |
| `type` | `text` | YES | - | |
| `created_time` | `text` | YES | - | |
| `expiration_time` | `text` | YES | - | |
| `last_update_time` | `text` | YES | - | |
| `client_order_id` | `text` | YES | - | |
| `order_group_id` | `text` | YES | - | |
| `queue_position` | `integer(32)` | YES | - | |
| `self_trade_prevention_type` | `text` | YES | - | |
| `raw_json` | `text` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `yes_price_dollars` | `text` | YES | - | |
| `no_price_dollars` | `text` | YES | - | |
| `initial_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `initial_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `remaining_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `fill_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `taker_fees_dollars` | `text` | YES | - | Fixed-point (Kalshi migration). |
| `maker_fees_dollars` | `text` | YES | - | Fixed-point (Kalshi migration). |
| `taker_fill_cost_dollars` | `text` | YES | - | Fixed-point (Kalshi migration). |
| `maker_fill_cost_dollars` | `text` | YES | - | Fixed-point (Kalshi migration). |

#### Constraints

- **Primary Key:** `orders_0001_pkey` on `id`
- **Unique:** `orders_0001_order_id_key` on `order_id`

#### Indexes

- `orders_0001_order_id_key`
  ```sql
  CREATE UNIQUE INDEX orders_0001_order_id_key ON users.orders_0001 USING btree (order_id)
  ```
- `orders_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX orders_0001_pkey ON users.orders_0001 USING btree (id)
  ```

---

### Table: `users.positions_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.positions_0001_id_seq'::regclass) | |
| `ticker` | `text` | YES | - | |
| `total_traded` | `integer(32)` | YES | - | |
| `total_traded_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `position` | `integer(32)` | YES | - | |
| `position_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `market_exposure` | `integer(32)` | YES | - | |
| `realized_pnl` | `real(24)` | YES | - | |
| `fees_paid` | `real(24)` | YES | - | |
| `last_updated_ts` | `text` | YES | - | |
| `raw_json` | `text` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `total_traded_dollars` | `text` | YES | - | |
| `market_exposure_dollars` | `text` | YES | - | |
| `realized_pnl_dollars` | `text` | YES | - | |
| `fees_paid_dollars` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `positions_0001_pkey` on `id`

#### Indexes

- `idx_positions_0001_ticker`
  ```sql
  CREATE UNIQUE INDEX idx_positions_0001_ticker ON users.positions_0001 USING btree (ticker)
  ```
- `idx_positions_0001_ticker_unique`
  ```sql
  CREATE UNIQUE INDEX idx_positions_0001_ticker_unique ON users.positions_0001 USING btree (ticker)
  ```
- `positions_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX positions_0001_pkey ON users.positions_0001 USING btree (id)
  ```

---

### Table: `users.settlements_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.settlements_0001_id_seq1'::regcl... | |
| `ticker` | `text` | YES | - | |
| `market_result` | `text` | YES | - | |
| `yes_count` | `integer(32)` | YES | - | |
| `yes_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `yes_total_cost_dollars` | `numeric(10,2)` | YES | - | Total cost in dollars (Kalshi API yes_total_cost_dollars). |
| `no_count` | `integer(32)` | YES | - | |
| `no_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `no_total_cost_dollars` | `numeric(10,2)` | YES | - | Total cost in dollars (Kalshi API no_total_cost_dollars). |
| `revenue` | `numeric(10,2)` | YES | - | |
| `settled_time` | `text` | YES | - | |
| `raw_json` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `settlements_0001_pkey` on `id`
- **Unique:** `settlements_0001_ticker_settled_time_key` on `ticker`
- **Unique:** `settlements_0001_ticker_settled_time_key` on `ticker`
- **Unique:** `settlements_0001_ticker_settled_time_key` on `settled_time`
- **Unique:** `settlements_0001_ticker_settled_time_key` on `settled_time`

#### Indexes

- `idx_settlements_0001_ticker`
  ```sql
  CREATE INDEX idx_settlements_0001_ticker ON users.settlements_0001 USING btree (ticker)
  ```
- `settlements_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX settlements_0001_pkey ON users.settlements_0001 USING btree (id)
  ```
- `settlements_0001_ticker_settled_time_key`
  ```sql
  CREATE UNIQUE INDEX settlements_0001_ticker_settled_time_key ON users.settlements_0001 USING btree (ticker, settled_time)
  ```

---

### Table: `users.strategy_list_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.strategy_list_0001_id_seq'::regc... | |
| `name` | `text` | NO | '-'::text | |
| `created` | `timestamp without time zone` | YES | - | |
| `updated` | `timestamp without time zone` | YES | - | |
| `default` | `boolean` | NO | false | |
| `min_probability` | `numeric(5,2)` | YES | 95.00 | |
| `max_probability` | `numeric(5,2)` | YES | - | |
| `min_differential` | `numeric(5,2)` | YES | 0.25 | |
| `min_time` | `integer(32)` | YES | 120 | |
| `max_time` | `integer(32)` | YES | 900 | |
| `allow_re_entry` | `boolean` | YES | false | |
| `spike_alert_enabled` | `boolean` | YES | true | |
| `spike_alert_momentum_threshold` | `integer(32)` | YES | 36 | |
| `spike_alert_cooldown_threshold` | `integer(32)` | YES | 30 | |
| `spike_alert_cooldown_minutes` | `integer(32)` | YES | 15 | |
| `current_probability` | `integer(32)` | YES | 40 | |
| `stop_loss_price` | `numeric(6,4)` | YES | 0.0000 | Default for new monitors (from strategy). Same semantics as `users.monitor_list_0001.stop_loss_price`. Migration `20260329_1100_monitor_strategy_stop_loss_price`. |
| `min_ttc_seconds` | `integer(32)` | YES | 60 | |
| `momentum_spike_enabled` | `boolean` | YES | true | |
| `momentum_spike_threshold` | `integer(32)` | YES | 36 | |
| `user_id` | `character varying(10)` | YES | '0001'::character varying | |
| `verification_period_enabled` | `boolean` | YES | false | |
| `verification_period_seconds` | `integer(32)` | YES | 15 | |
| `min_volume` | `integer(32)` | YES | 1000 | |
| `max_differential` | `numeric(5,2)` | YES | NULL::numeric | |
| `momentum_scalp_entry_threshold` | `numeric(5,2)` | YES | NULL::numeric | |
| `momentum_scalp_trailing_stop_amount` | `numeric(5,2)` | YES | 0.10 | |
| `momentum_scalp_profit_target` | `numeric(5,2)` | YES | 0.99 | |
| `win_streak_threshold` | `integer(32)` | YES | 22 | |
| `loss_prevention` | `character varying(50)` | YES | 'none'::character varying | |
| `loss_prevention_toggle` | `boolean` | YES | true | |
| `performance_based_allocation` | `boolean` | NO | false | |
| `max_price_spread` | `numeric(6,4)` | YES | 0.0300 | |
| `paper_trade` | `boolean` | YES | false | |
| `prob_adj` | `numeric(5,2)` | YES | 5.00 | |
| `min_ask` | `numeric(6,4)` | YES | 0.0000 | |
| `max_ask` | `numeric(6,4)` | YES | 0.9800 | |
| `position_size` | `integer(32)` | YES | 1 | |
| `position_type` | `character varying(20)` | YES | 'percent'::character varying | |
| `multiplier` | `numeric(3,2)` | YES | 1.00 | |
| `max_profit` | `numeric(6,4)` | YES | 0.9900 | |
| `min_cooldown_timer` | `integer(32)` | YES | 300 | Minimum cooldown timer value (in seconds) required for auto entry activation. Strategy will not activate if cooldown_timer is below this value. |
| `max_cooldown_timer` | `integer(32)` | YES | 3300 | Maximum cooldown timer value (in seconds) allowed for auto entry activation. Strategy will not activate if cooldown_timer is above this value. |
| `min_ask_range` | `numeric(18,4)` | YES | - | Rising Devil: min active-side ask range (strike `yes_ask_range_15m` / `no_ask_range_15m`) to fire; NULL disables. Migration `20260401_1500_rising_devil_min_ask_range`. |

#### Constraints

- **Primary Key:** `strategy_list_0001_pkey` on `id`

#### Indexes

- `strategy_list_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX strategy_list_0001_pkey ON users.strategy_list_0001 USING btree (id)
  ```

---

### Table: `users.subaccounts_0001`

Internal allocation of portfolio: PRIMARY = total at Kalshi; other rows (e.g. Master Trading Bankroll, Cash Transfer) sum to PRIMARY. Updated by kalshi_account_sync when positions = 0; also on external deposits (add to Cash Transfer + PRIMARY) and external withdrawals (subtract from Cash Transfer, floor at 0, and reduce PRIMARY by same amount). Balances in cents.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.subaccounts_0001_id_seq'::regclass) | |
| `subaccount` | `text` | NO | '*** SUBACCOUNT NAME ***'::text | Name: PRIMARY, Master Trading Bankroll, Cash Transfer |
| `balance` | `integer(32)` | NO | 0 | Balance in cents. PRIMARY = total portfolio; MTB = PRIMARY − Cash Transfer |
| `base_value` | `integer(32)` | YES | - | Starting value in cents (MTB). Used for realized_pnl and rake reset |
| `realized_pnl` | `integer(32)` | YES | - | balance − base_value in cents (MTB) |
| `realized_pnl_pct` | `real(24)` | YES | - | (balance − base_value) / base_value as fraction, 4 decimal places (e.g. 0.0148) |
| `target_pnl__pct` | `real(24)` | YES | - | Target fraction (e.g. 0.01 = 1%). When realized_pnl_pct ≥ this, internal transfer runs (if automatic_transfers) |
| `transfer_amt` | `real(24)` | YES | - | Transfer as fraction of base_value (e.g. 0.005 = 0.5%). Amount raked = transfer_amt × base_value |
| `automatic_transfers` | `boolean` | NO | false | If TRUE, target-based internal transfers are initiated by account sync; user-definable per subaccount |

#### Constraints

- **Primary Key:** `subaccounts_0001_pkey` on `id`

#### Indexes

- `subaccounts_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX subaccounts_0001_pkey ON users.subaccounts_0001 USING btree (id)
  ```

---

### Table: `users.trade_history_preferences_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.trade_history_preferences_0001_i... | |
| `date_filter` | `character varying(20)` | YES | 'TODAY'::character varying | |
| `win_filter` | `boolean` | YES | true | |
| `loss_filter` | `boolean` | YES | true | |
| `sort_key` | `character varying(50)` | YES | - | |
| `sort_asc` | `boolean` | YES | true | |
| `page_size` | `integer(32)` | YES | 50 | |
| `last_search_timestamp` | `bigint(64)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `start_date` | `text` | YES | - | |
| `end_date` | `text` | YES | - | |
| `contract_9am` | `boolean` | YES | true | |
| `contract_10am` | `boolean` | YES | true | |
| `contract_11am` | `boolean` | YES | true | |
| `contract_12am` | `boolean` | YES | true | |
| `contract_1pm` | `boolean` | YES | true | |
| `contract_2pm` | `boolean` | YES | true | |
| `contract_3pm` | `boolean` | YES | true | |
| `contract_4pm` | `boolean` | YES | true | |
| `contract_5pm` | `boolean` | YES | true | |
| `contract_6pm` | `boolean` | YES | true | |
| `contract_7pm` | `boolean` | YES | true | |
| `contract_8pm` | `boolean` | YES | true | |
| `contract_9pm` | `boolean` | YES | true | |
| `contract_10pm` | `boolean` | YES | true | |
| `contract_11pm` | `boolean` | YES | true | |
| `symbol_btc` | `boolean` | YES | true | |
| `symbol_eth` | `boolean` | YES | true | |
| `symbol_spy` | `boolean` | YES | true | |
| `symbol_ndx` | `boolean` | YES | true | |
| `symbol_usd_eur` | `boolean` | YES | true | |
| `strategy_hourly_htc` | `boolean` | YES | true | |
| `strategy_momentum_scalp` | `boolean` | YES | true | |
| `strategy_test` | `boolean` | YES | true | |
| `analysis_interval` | `text` | YES | 'daily'::text | |
| `day_sunday` | `boolean` | YES | true | |
| `day_monday` | `boolean` | YES | true | |
| `day_tuesday` | `boolean` | YES | true | |
| `day_wednesday` | `boolean` | YES | true | |
| `day_thursday` | `boolean` | YES | true | |
| `day_friday` | `boolean` | YES | true | |
| `day_saturday` | `boolean` | YES | true | |
| `chart_view` | `text` | YES | 'pnl'::text | |
| `pct_mode` | `boolean` | YES | false | |
| `live_filter` | `boolean` | YES | true | |
| `paper_filter` | `boolean` | YES | false | |
| `strategy_selection` | `jsonb` | YES | '{}' | Strategy filter state (name -> checked) for trade history UI. |
| `symbol_selection` | `jsonb` | YES | '{}' | Symbol filter state (symbol -> checked) for trade history UI (from symbols_list). |

#### Constraints

- **Primary Key:** `trade_history_preferences_0001_pkey` on `id`

#### Indexes

- `trade_history_preferences_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX trade_history_preferences_0001_pkey ON users.trade_history_preferences_0001 USING btree (id)
  ```

---

### Table: `users.trade_logs_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.trade_logs_0001_id_seq'::regclass) | |
| `ticket_id` | `character varying(100)` | YES | - | |
| `message` | `text` | YES | - | |
| `timestamp` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `service` | `character varying(100)` | YES | - | |
| `user_id` | `character varying(100)` | YES | 'user_0001'::character varying | |

#### Constraints

- **Primary Key:** `trade_logs_0001_pkey` on `id`

#### Indexes

- `trade_logs_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX trade_logs_0001_pkey ON users.trade_logs_0001 USING btree (id)
  ```

---

### Table: `users.trades_0001`

**Schema sync:** When changing this table (columns, types, indexes), apply the same changes to `users.trades_simulated_0001` so both stay in sync. **Exception:** `symbol_expiration`, `win_loss_confirmed`, and `market_result` (venue resolution snapshot on the trade row) exist on **`trades_0001` only** (not on `trades_simulated_0001`; see migrations `20260328_1500_trades_symbol_expiration_win_loss_confirmed`, `20260331_2300_trades_kalshi_outcome_verified_at`, `20260401_1200_trades_rename_outcome_evaluated_column`, `20260401_1600_trades_0001_rec_io_db_notify` (real-time NOTIFY trigger → stream `trades`), `20260402_1000_trades_outcome_checked_at_short_name`, `20260402_1400_trades_market_result_from_outcome_check`, `20260403_1000_trades_drop_outcome_checked_at`). `market_result` is written from **Kalshi `market_lifecycle_v2`** in `market_watchdog_ws` for paper and live rows when the venue reports `determined` / `settled`. **`market` (cadence)** exists on both live and simulated tables (migration `20260330_1015_trades_market_cadence`). **Strike final-window ask snapshot** columns (`yes_ask_min_15m`, …, `no_ask_range_15m`) exist on both tables (migration `20260330_2200_trades_strike_final_quarter_asks`); `trade_manager` fills them at insert from the latest matching strike row when available.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.trades_0001_id_seq'::regclass) | |
| `status` | `text` | NO | - | |
| `date` | `text` | NO | - | |
| `time` | `text` | NO | - | |
| `symbol` | `text` | YES | - | |
| `exchange` | `text` | YES | - | Execution venue slug (e.g. `kalshi`). Migration `20260326_1000_venue_exchange_column_names` renames **`market` → `exchange`**. |
| `trade_strategy` | `text` | YES | 'Hourly HTC'::text | |
| `market` | `varchar(10)` | YES | `'hourly'` | Kalshi **cadence**: `hourly` or `15m`. Distinct from `exchange`. Set on insert from `monitor_list.market` when present, else from `trade_strategy`/`ticker` (`%15m%` / `15M`). Migration `20260330_1015_trades_market_cadence`. |
| `contract` | `text` | NO | - | |
| `strike` | `text` | NO | - | For **SOL/XRP**, `trade_manager` normalizes display to `$` + up to **5** decimal places (trim trailing zeros) so expiration settlement matches strike-table granularity. BTC/ETH unchanged. |
| `side` | `text` | NO | - | |
| `prob` | `real(24)` | YES | - | |
| `diff` | `text` | YES | - | |
| `buy_price` | `real(24)` | NO | - | |
| `position` | `integer(32)` | NO | - | |
| `sell_price` | `real(24)` | YES | - | |
| `closed_at` | `text` | YES | - | |
| `fees` | `real(24)` | YES | - | |
| `pnl` | `real(24)` | YES | - | |
| `symbol_open` | `numeric(18,5)` | YES | - | Spot at open. **5dp** for SOL/XRP; 2dp for BTC/ETH (`trade_manager.normalize_trade_spot_price`). Migration `20260324_1000_trades_symbol_spot_numeric_precision`. |
| `symbol_close` | `numeric(18,5)` | YES | - | Spot at close; same rules as `symbol_open`. |
| `symbol_expiration` | `numeric(18,5)` | YES | - | Spot at **contract cycle end** (`one_minute_avg` at expiration sweep). Same normalization as `symbol_close`. Written for **paper and live** rows when the ticker’s cycle is processed; for early closes, may be backfilled from `symbol_close` or historical price logs. Migration `20260328_1500_trades_symbol_expiration_win_loss_confirmed`. **Not** on `trades_simulated_0001`. |
| `win_loss_confirmed` | `boolean` | YES | - | If nullable: not yet computable. When set: `TRUE` if recorded `win_loss` (W/L) matches hypothetical W/L from `strike`+`side` vs `symbol_expiration` (hold-to-expiration); `FALSE` if they differ. **Paper and live** on `trades_0001`. Draws (`D`) and missing `win_loss` stay null. Migration `20260328_1500_trades_symbol_expiration_win_loss_confirmed`. |
| `market_result` | `text` | YES | - | Normalized `yes` / `no` from Kalshi **`market_lifecycle_v2`** (`market_watchdog_ws` on `determined` / `settled`). Distinct from `market` (cadence). Mismatch vs recorded `win_loss` on closed trades may set `win_loss_confirmed = FALSE`. Live **close/finalization** still uses settlement polling in `trade_manager`. Column added `20260402_1400_trades_market_result_from_outcome_check`; comment updated `20260403_1000_trades_drop_outcome_checked_at`. **`trades_0001` only.** |
| `momentum` | `integer(32)` | YES | - | |
| `volatility_percentile` | `numeric(5,1)` | YES | - | |
| `volatility` | `numeric(10,4)` | YES | - | Raw volatility at trade time (same format as momentum in price history). |
| `movement` | `numeric(10,4)` | YES | - | Composite intra-candle movement at trade time (same format as momentum). |
| `movement_percentile` | `numeric(5,1)` | YES | - | Movement percentile 0.5–99.5 (same format as momentum_percentile). |
| `win_loss` | `text` | YES | - | |
| `ticker` | `text` | YES | - | |
| `ticket_id` | `text` | YES | - | |
| `market_id` | `text` | YES | - | |
| `momentum_percentile` | `real(24)` | YES | - | |
| `entry_method` | `text` | YES | 'manual'::text | |
| `close_method` | `text` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `test_filter` | `boolean` | YES | false | |
| `notes` | `text` | YES | - | |
| `monitor` | `text` | YES | - | |
| `bankroll` | `real(24)` | YES | - | |
| `master_trading_bankroll` | `integer(32)` | YES | - | Snapshot of MTB balance in cents from account_balance at insert time. |
| `mtb_base_value` | `integer(32)` | YES | - | Snapshot of MTB base_value in cents from account_balance at insert time. |
| `ret_pct` | `real(24)` | YES | - | Return % vs bankroll at trade time (PnL / bankroll snapshot, net of fees). |
| `ret_pct_base` | `real(24)` | YES | - | Return % vs mtb_base_value (same formula as ret_pct but denominator = mtb_base_value in cents). |
| `roi_pct` | `real(24)` | YES | - | Per-trade return on investment (PnL / (buy_price × position) × 100), net of fees. |
| `momentum_5s_avg` | `numeric(10,4)` | YES | - | |
| `order_id` | `text` | YES | - | |
| `order_id_open` | `text` | YES | - | |
| `order_id_close` | `text` | YES | - | |
| `high_price` | `numeric(10,4)` | YES | NULL::numeric | |
| `low_price` | `numeric(10,4)` | YES | NULL::numeric | |
| `hour_idx` | `smallint(16)` | YES | - | Hour of contract (1–24). |
| `weekly_cycle` | `numeric(5,1)` | YES | - | Day+hour bucket with 15m specificity: integer part = 1–168 (Sunday 12am … Saturday 11pm); decimal: hourly = .4 (fourth quarter), 15m = .0 ( :00), .1 ( :15), .2 ( :30), .3 ( :45). Cycle performance logic uses FLOOR(weekly_cycle). |
| `loss_prevention` | `boolean` | YES | false | |
| `multiplier` | `numeric(10,2)` | YES | - | |
| `price_spread` | `numeric(6,4)` | YES | - | |
| `yes_ask_min_15m` | `numeric(18,4)` | YES | - | Snapshot from latest matching strike row at insert: final-window YES ask min (dollars). Migration `20260330_2200_trades_strike_final_quarter_asks`. |
| `yes_ask_max_15m` | `numeric(18,4)` | YES | - | Same snapshot: YES ask max. |
| `no_ask_min_15m` | `numeric(18,4)` | YES | - | Same snapshot: NO ask min. |
| `no_ask_max_15m` | `numeric(18,4)` | YES | - | Same snapshot: NO ask max. |
| `yes_ask_range_15m` | `numeric(18,4)` | YES | - | Same snapshot: YES ask range. |
| `no_ask_range_15m` | `numeric(18,4)` | YES | - | Same snapshot: NO ask range. |
| `paper_trade` | `boolean` | YES | false | |
| `cooldown_timer` | `integer(32)` | YES | - | |
| `monitor_confirmed` | `boolean` | YES | **NULL** | Default **NULL** on insert; app sets true/false when the trade is finalized. Migration `20260410_1000_trades_monitor_confirmed_default_null`. |
| `ats_updated` | `timestamptz` | YES | - | Last successful ATS strike-join telemetry refresh while **open**. Migration `20260402_2310_trades_ats_updated`. |
| `cycle_win_loss` | `text` | YES | - | |
| `cycle_pnl` | `real(24)` | YES | - | |
| `cycle_ret_pct` | `real(24)` | YES | - | |

**Note on cycle-level columns (`cycle_win_loss`, `cycle_pnl`, `cycle_ret_pct`):**
These columns store cycle-level metrics grouped by monitor + contract + date combination. For backfilling:
- `cycle_pnl` = SUM(pnl) for all trades in that monitor+contract+date cycle
- `cycle_ret_pct` = SUM(ret_pct) for all trades in that monitor+contract+date cycle (simple sum, not recalculated)
- `cycle_win_loss` = 'W' if cycle_pnl > 0, 'L' otherwise

Example backfill SQL:
```sql
WITH cycle_stats AS (
    SELECT 
        monitor,
        contract,
        date,
        SUM(pnl) as total_pnl,
        SUM(ret_pct) as total_ret_pct
    FROM users.trades_0001
    WHERE monitor IS NOT NULL 
      AND contract IS NOT NULL
      AND date IS NOT NULL
      AND status IN ('closed', 'expired')
      AND pnl IS NOT NULL
      AND ret_pct IS NOT NULL
    GROUP BY monitor, contract, date
)
UPDATE users.trades_0001 t
SET 
    cycle_pnl = cs.total_pnl,
    cycle_ret_pct = cs.total_ret_pct,
    cycle_win_loss = CASE WHEN cs.total_pnl > 0 THEN 'W' ELSE 'L' END
FROM cycle_stats cs
WHERE t.monitor = cs.monitor 
  AND t.contract = cs.contract
  AND t.date = cs.date
  AND t.status IN ('closed', 'expired');
```

#### Constraints

- **Primary Key:** `trades_0001_pkey` on `id`

#### Indexes

- `idx_trades_0001_date`
  ```sql
  CREATE INDEX idx_trades_0001_date ON users.trades_0001 USING btree (date)
  ```
- `idx_trades_0001_order_id`
  ```sql
  CREATE INDEX idx_trades_0001_order_id ON users.trades_0001 USING btree (order_id)
  ```
- `idx_trades_0001_order_id_close`
  ```sql
  CREATE INDEX idx_trades_0001_order_id_close ON users.trades_0001 USING btree (order_id_close)
  ```
- `idx_trades_0001_order_id_open`
  ```sql
  CREATE INDEX idx_trades_0001_order_id_open ON users.trades_0001 USING btree (order_id_open)
  ```
- `idx_trades_0001_status`
  ```sql
  CREATE INDEX idx_trades_0001_status ON users.trades_0001 USING btree (status)
  ```
- `idx_trades_0001_symbol`
  ```sql
  CREATE INDEX idx_trades_0001_symbol ON users.trades_0001 USING btree (symbol)
  ```
- `idx_trades_0001_ticker`
  ```sql
  CREATE INDEX idx_trades_0001_ticker ON users.trades_0001 USING btree (ticker)
  ```
- `idx_trades_0001_ticket_id`
  ```sql
  CREATE INDEX idx_trades_0001_ticket_id ON users.trades_0001 USING btree (ticket_id)
  ```
- `trades_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX trades_0001_pkey ON users.trades_0001 USING btree (id)
  ```
- `trades_0001_weekly_cycle_idx`
  ```sql
  CREATE INDEX trades_0001_weekly_cycle_idx ON users.trades_0001 USING btree (weekly_cycle)
  ```

#### Triggers

- **`trades_0001_rec_io_db_notify`** — `AFTER INSERT OR UPDATE OR DELETE` → `public.rec_io_db_notify()` on channel `rec_io_db_changes`. Switchboard maps `(users, trades_0001)` to stream **`trades`** (`backend/core/stream_registry.py`). Migration `20260401_1600_trades_0001_rec_io_db_notify`.

---

### Table: `users.trades_simulated_0001`

**Creation:** If the table does not exist, it is created by `init_database()` in `backend/core/config/database.py` with the same column set as `users.trades_0001`. No manual creation is required.

**Purpose:** Copy of `users.trades_0001` for storing simulated 15m-cycle trades (e.g. from the simulated path on hourly strike tables; SHS/calibration). **Any future schema changes to `users.trades_0001` (new columns, type changes, indexes, constraints) must be applied to `users.trades_simulated_0001` as well** so the two tables stay in sync.

**Nullable columns for simulated trades:** The simulated-trade path intentionally stores **NULL** for `buy_price`, `position`, `fees`, `bankroll`, `price_spread`, and leaves `sell_price` NULL (no execution). So on this table those columns are **nullable** even though `trades_0001` may define some as NOT NULL. `database.py` creates the table with `buy_price` and `position` nullable and migrates existing tables to drop NOT NULL on them when present.

Same column set as `users.trades_0001` (see that table for column descriptions). Empty until the simulated-trade path writes to it. Created with `id SERIAL PRIMARY KEY`; add indexes to mirror `trades_0001` (e.g. on `date`, `status`, `ticker`) when needed.

#### Columns (from DB)

| Column | Type |
|--------|------|
| `id` | integer |
| `status` | text |
| `date` | text |
| `time` | text |
| `symbol` | text |
| `exchange` | text |
| `trade_strategy` | text |
| `contract` | text |
| `strike` | text |
| `side` | text |
| `prob` | real |
| `diff` | text |
| `buy_price` | real |
| `position` | integer |
| `sell_price` | real |
| `closed_at` | text |
| `fees` | real |
| `pnl` | real |
| `symbol_open` | numeric(18,5) |
| `symbol_close` | numeric(18,5) |
| `momentum` | integer |
| `win_loss` | text |
| `ticker` | text |
| `ticket_id` | text |
| `market_id` | text |
| `momentum_percentile` | real |
| `entry_method` | text |
| `close_method` | text |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `test_filter` | boolean |
| `notes` | text |
| `monitor` | text |
| `bankroll` | real |
| `ret_pct` | real |
| `momentum_5s_avg` | numeric(10,4) |
| `order_id` | text |
| `order_id_open` | text |
| `order_id_close` | text |
| `high_price` | numeric(10,4) |
| `low_price` | numeric(10,4) |
| `hour_idx` | smallint |
| `weekly_cycle` | numeric(5,1) |
| `loss_prevention` | boolean |
| `multiplier` | numeric(10,2) |
| `price_spread` | numeric(6,4) |
| `yes_ask_min_15m` | numeric(18,4) |
| `yes_ask_max_15m` | numeric(18,4) |
| `no_ask_min_15m` | numeric(18,4) |
| `no_ask_max_15m` | numeric(18,4) |
| `yes_ask_range_15m` | numeric(18,4) |
| `no_ask_range_15m` | numeric(18,4) |
| `volatility_percentile` | numeric(5,1) |
| `paper_trade` | boolean |
| `cooldown_timer` | integer |
| `monitor_confirmed` | boolean |
| `cycle_win_loss` | text |
| `cycle_pnl` | real |
| `cycle_ret_pct` | real |
| `volatility` | numeric(10,4) |
| `movement` | numeric(10,4) |
| `movement_percentile` | numeric(5,1) |

#### Constraints

None defined as of last check. Add primary key on `id` (and any other constraints) to match `trades_0001` when needed.

#### Indexes

None as of last check. Add the same indexes as `users.trades_0001` (e.g. on `date`, `status`, `ticker`, `order_id_open`, `order_id_close`, `symbol`, `ticket_id`, `weekly_cycle`) when the table is used.

---

### Table: `users.transfers_0001`

Log of transfers: internal (between subaccounts, e.g. Master Trading Bankroll → Cash Transfer) or external (deposits/withdrawals from Kalshi). Internal rows are created by kalshi_account_sync when it runs an internal transfer. External rows are created when new entries appear in users.account_history_0001 (_ensure_external_transfers_from_account_history in kalshi_account_sync_ws.py). External deposits have positive amount; external withdrawals have negative amount. Status for external transfers is refreshed from account_history on each sync so later status changes (e.g. withdrawal pending → applied) are reflected via external_transfer_id.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.transfers_0001_id_seq'::regclass) | |
| `timestamp` | `text` | NO | - | When the transfer occurred; EST with date (e.g. YYYY-MM-DD HH:MM:SS) |
| `type` | `text` | YES | - | `internal` (between subaccounts) or `external` (deposit/withdrawal from Kalshi) |
| `from` | `text` | YES | - | Source (e.g. Master Trading Bankroll, Cash Transfer; external deposits: deposit type e.g. Crypto, ACH; external withdrawals: Cash Transfer) |
| `to` | `text` | YES | - | Destination (e.g. Cash Transfer for deposits; ACH for external withdrawals) |
| `amount` | `integer(32)` | YES | - | Transfer amount in cents. External deposits: positive (amount − fee). External withdrawals: negative. |
| `initiated` | `text` | YES | - | `automatic` (script) or `manual` |
| `status` | `character varying(50)` | YES | - | For external: from account_history.status (e.g. applied, pending). Refreshed from account_history on each sync so withdrawal status updates are reflected. |
| `external_transfer_id` | `integer` | YES | - | For external only: id of users.account_history_0001 row. Links transfer to account history so status (and future fields) can be updated when Kalshi updates the entry. |

#### Constraints

- **Primary Key:** `transfers_0001_pkey` on `id`

#### Indexes

- `transfers_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX transfers_0001_pkey ON users.transfers_0001 USING btree (id)
  ```

---

### Table: `users.account_history_0001`

Kalshi v1 /deposits and /withdrawals only (we do not use the account/history endpoint). Populated by kalshi_account_sync_ws (sync_account_history when balance is synced). One row per deposit or withdrawal; kalshi_id from API id, vendor/rail from API fields.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer` | NO | nextval('users.account_history_0001_id_seq'::regclass) | |
| `entry_type` | `character varying(20)` | NO | - | `Deposit` or `Withdrawal` |
| `amount` | `integer` | NO | - | Amount in cents |
| `fee` | `integer` | YES | 0 | Fee in cents |
| `created_at` | `timestamp with time zone` | NO | - | From Kalshi API |
| `updated_at` | `timestamp with time zone` | YES | - | From Kalshi API |
| `status` | `character varying(50)` | YES | - | e.g. `applied` |
| `returned_amount` | `integer` | YES | 0 | Returned amount in cents (withdrawals) |
| `deposit_type` | `character varying(50)` | YES | - | e.g. `crypto`, `ach` (deposits only; recorded in transfers as Crypto, ACH) |
| `immediate_amount` | `integer` | YES | - | Deposits only |
| `immediate_status` | `character varying(50)` | YES | - | Deposits only |
| `synced_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | When the row was inserted/updated by sync script |
| `kalshi_id` | `character varying(64)` | YES | - | Kalshi API id from /deposits or /withdrawals; used for upsert when present |
| `vendor` | `character varying(100)` | YES | - | From new API (e.g. venmo, plaid, zerohash) |
| `rail` | `character varying(100)` | YES | - | Withdrawals only (e.g. apm, ach) |

#### Constraints

- **Primary Key:** `account_history_0001_pkey` on `id`
- **Unique:** `account_history_0001_created_type_amount_key` on `(created_at, entry_type, amount)` for upsert deduplication (legacy)
- **Unique:** `account_history_0001_kalshi_id_key` on `(kalshi_id)` WHERE kalshi_id IS NOT NULL (for upsert from new /deposits and /withdrawals) for upsert deduplication

#### Indexes

- `account_history_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX account_history_0001_pkey ON users.account_history_0001 USING btree (id)
  ```
- `account_history_0001_created_type_amount_key` (unique constraint backing index)
  ```sql
  CREATE UNIQUE INDEX account_history_0001_created_type_amount_key ON users.account_history_0001 USING btree (created_at, entry_type, amount)
  ```

---

### Table: `users.user_info_0001`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `user_no` | `character varying(10)` | NO | - | |
| `user_id` | `character varying(50)` | NO | - | |
| `kalshi_user_id` | `character varying(50)` | YES | - | Kalshi API user UUID (e.g. for account/history and other v1 endpoints). |
| `email` | `character varying(255)` | YES | - | |
| `first_name` | `character varying(50)` | YES | - | |
| `last_name` | `character varying(50)` | YES | - | |
| `phone` | `character varying(20)` | YES | - | |
| `account_type` | `character varying(20)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | - | |
| `last_login` | `timestamp with time zone` | YES | - | |
| `is_active` | `boolean` | YES | - | |
| `password_hash` | `character varying(255)` | YES | - | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `user_info_0001_pkey` on `user_no`

#### Indexes

- `user_info_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX user_info_0001_pkey ON users.user_info_0001 USING btree (user_no)
  ```

---

## Schema: `work_progress`

### Table: `work_progress.ttc_0069_btc`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `buffer_points` | `integer(32)` | NO | - | |
| `momentum_bucket` | `integer(32)` | NO | - | |
| `prob_within_positive` | `numeric(5,2)` | NO | - | |
| `prob_within_negative` | `numeric(5,2)` | NO | - | |

#### Constraints

- **Primary Key:** `ttc_0069_btc_pkey` on `buffer_points`
- **Primary Key:** `ttc_0069_btc_pkey` on `buffer_points`
- **Primary Key:** `ttc_0069_btc_pkey` on `momentum_bucket`
- **Primary Key:** `ttc_0069_btc_pkey` on `momentum_bucket`

#### Indexes

- `ttc_0069_btc_pkey`
  ```sql
  CREATE UNIQUE INDEX ttc_0069_btc_pkey ON work_progress.ttc_0069_btc USING btree (buffer_points, momentum_bucket)
  ```

---

### Table: `work_progress.ttc_0070_btc`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `buffer_points` | `integer(32)` | NO | - | |
| `momentum_bucket` | `integer(32)` | NO | - | |
| `prob_within_positive` | `numeric(5,2)` | NO | - | |
| `prob_within_negative` | `numeric(5,2)` | NO | - | |

#### Constraints

- **Primary Key:** `ttc_0070_btc_pkey` on `buffer_points`
- **Primary Key:** `ttc_0070_btc_pkey` on `buffer_points`
- **Primary Key:** `ttc_0070_btc_pkey` on `momentum_bucket`
- **Primary Key:** `ttc_0070_btc_pkey` on `momentum_bucket`

#### Indexes

- `ttc_0070_btc_pkey`
  ```sql
  CREATE UNIQUE INDEX ttc_0070_btc_pkey ON work_progress.ttc_0070_btc USING btree (buffer_points, momentum_bucket)
  ```

---

### Table: `work_progress.ttc_progress`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | NO | - | |
| `status` | `character varying(20)` | YES | 'pending'::character varying | |
| `started_at` | `timestamp without time zone` | YES | - | |
| `completed_at` | `timestamp without time zone` | YES | - | |
| `rows_generated` | `integer(32)` | YES | 0 | |
| `error_message` | `text` | YES | - | |
| `table_name` | `character varying(100)` | YES | - | |

#### Constraints

- **Primary Key:** `ttc_progress_pkey` on `ttc_seconds`

#### Indexes

- `ttc_progress_pkey`
  ```sql
  CREATE UNIQUE INDEX ttc_progress_pkey ON work_progress.ttc_progress USING btree (ttc_seconds)
  ```

---

### Table: `work_progress.ttc_progress_btc`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | NO | - | |
| `status` | `character varying(20)` | YES | 'pending'::character varying | |
| `started_at` | `timestamp without time zone` | YES | - | |
| `completed_at` | `timestamp without time zone` | YES | - | |
| `rows_generated` | `integer(32)` | YES | 0 | |
| `error_message` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `ttc_progress_btc_pkey` on `ttc_seconds`

#### Indexes

- `ttc_progress_btc_pkey`
  ```sql
  CREATE UNIQUE INDEX ttc_progress_btc_pkey ON work_progress.ttc_progress_btc USING btree (ttc_seconds)
  ```

---

### Table: `work_progress.ttc_progress_eth`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | NO | - | |
| `status` | `character varying(20)` | YES | 'pending'::character varying | |
| `started_at` | `timestamp without time zone` | YES | - | |
| `completed_at` | `timestamp without time zone` | YES | - | |
| `rows_generated` | `integer(32)` | YES | 0 | |
| `error_message` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `ttc_progress_eth_pkey` on `ttc_seconds`

#### Indexes

- `ttc_progress_eth_pkey`
  ```sql
  CREATE UNIQUE INDEX ttc_progress_eth_pkey ON work_progress.ttc_progress_eth USING btree (ttc_seconds)
  ```

---

### Table: `work_progress.ttc_progress_incremental`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `ttc_seconds` | `integer(32)` | NO | - | |
| `status` | `character varying(20)` | YES | 'pending'::character varying | |
| `started_at` | `timestamp without time zone` | YES | - | |
| `completed_at` | `timestamp without time zone` | YES | - | |
| `rows_generated` | `integer(32)` | YES | 0 | |
| `error_message` | `text` | YES | - | |
| `table_name` | `character varying(100)` | YES | - | |

#### Constraints

- **Primary Key:** `ttc_progress_incremental_pkey` on `ttc_seconds`

#### Indexes

- `ttc_progress_incremental_pkey`
  ```sql
  CREATE UNIQUE INDEX ttc_progress_incremental_pkey ON work_progress.ttc_progress_incremental USING btree (ttc_seconds)
  ```

---

## Schema: `core`

### Table: `core.system_state`

Global system mode flag controlling whether new trades may be opened. This table is managed primarily by `scripts/MASTER_RESTART.sh` and read by `backend/trade_manager.py`.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | - | Primary key, always `1` for the singleton row. |
| `mode` | `text` | NO | 'normal' | System mode: `'normal'` (trading enabled) or `'maintenance'` (new trade opens blocked). |
| `updated_at` | `timestamp with time zone` | NO | now() | Last time the mode was updated. |

#### Constraints

- **Primary Key:** `system_state_pkey` on `id`
- **Check:** `system_state_mode_check` enforcing `mode IN ('normal', 'maintenance')`
