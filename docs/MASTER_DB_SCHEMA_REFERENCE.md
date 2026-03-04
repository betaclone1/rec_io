# Master Database Schema Reference

**Generated:** 2026-03-03 (schema review, includes maintenance-mode system_state)

This document provides a complete reference of all database schemas, tables, and columns.
Update this document whenever schema changes are made during development.

---

## How to Check and Update Your Database (No Scripts)

Use this document as the source of truth. Do both steps whenever you pull schema changes or need to sync the DB.

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

## Schema: `historical_data`

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

### Table: `live_data.eth_price_log`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.eth_price_log_id_seq'::regcl... | |
| `price` | `numeric(15,2)` | YES | - | |
| `timestamp` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `eth_price_log_pkey` on `id`

#### Indexes

- `eth_price_log_pkey`
  ```sql
  CREATE UNIQUE INDEX eth_price_log_pkey ON live_data.eth_price_log USING btree (id)
  ```

---

### Table: `live_data.live_price_log_1s_btc`

**Population (movement columns):** `move_1m` … `move_30m`, `movement`, and `movement_percentile` are written by `backend/symbol_price_watchdog.py` on each tick. High/low/open per window are derived from ticks in the same table; the weighted composite and percentile use `analytics.{symbol}_movement_profile` (which has column **movement_value** at each percentile). Same applies to `live_price_log_1s_eth`, `live_price_log_1s_spx`, and `live_price_log_1s_ndx`.

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

### Table: `live_data.live_price_log_1s_ndx`

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

- **Primary Key:** `live_price_log_1s_ndx_pkey` on `timestamp`

#### Indexes

- `live_price_log_1s_ndx_pkey`
  ```sql
  CREATE UNIQUE INDEX live_price_log_1s_ndx_pkey ON live_data.live_price_log_1s_ndx USING btree ("timestamp")
  ```
- `live_price_log_1s_ndx_timestamp_idx`
  ```sql
  CREATE INDEX live_price_log_1s_ndx_timestamp_idx ON live_data.live_price_log_1s_ndx USING btree ("timestamp")
  ```

---

### Table: `live_data.live_price_log_1s_spx`

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

- **Primary Key:** `live_price_log_1s_spx_pkey` on `timestamp`

#### Indexes

- `idx_live_price_log_1s_spx_timestamp`
  ```sql
  CREATE INDEX idx_live_price_log_1s_spx_timestamp ON live_data.live_price_log_1s_spx USING btree ("timestamp")
  ```
- `live_price_log_1s_spx_pkey`
  ```sql
  CREATE UNIQUE INDEX live_price_log_1s_spx_pkey ON live_data.live_price_log_1s_spx USING btree ("timestamp")
  ```

---

### Table: `live_data.live_symbol_status`

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

---

### Table: `live_data.market_kalshi_hourly_btc`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.market_kalshi_hourly_btc_id_seq'::r... | |
| `event_ticker` | `character varying(50)` | NO | - | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | 'hourly' | Interval: hourly or 15m |
| `strike` | `character varying(20)` | YES | - | |
| `yes_bid` | `integer(32)` | YES | - | |
| `yes_ask` | `integer(32)` | YES | - | |
| `no_bid` | `integer(32)` | YES | - | |
| `no_ask` | `integer(32)` | YES | - | |
| `last_price` | `integer(32)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `volume_24h` | `integer(32)` | YES | - | |
| `open_interest` | `integer(32)` | YES | - | |
| `liquidity` | `integer(32)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |
| `yes_bid_dollars` | `text` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `last_price_dollars` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `market_kalshi_btc_pkey` on `id`
- **Unique:** `market_kalshi_btc_event_market_unique` on `event_ticker`
- **Unique:** `market_kalshi_btc_event_market_unique` on `event_ticker`
- **Unique:** `market_kalshi_btc_event_market_unique` on `market_ticker`
- **Unique:** `market_kalshi_btc_event_market_unique` on `market_ticker`

#### Indexes

- `market_kalshi_btc_event_market_unique`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_btc_event_market_unique ON live_data.market_kalshi_hourly_btc USING btree (event_ticker, market_ticker)
  ```
- `market_kalshi_btc_pkey`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_btc_pkey ON live_data.market_kalshi_hourly_btc USING btree (id)
  ```

---

### Table: `live_data.market_kalshi_hourly_eth`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.market_kalshi_hourly_eth_id_seq'::r... | |
| `event_ticker` | `character varying(50)` | NO | - | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | - | Interval: 'hourly' or '15m' |
| `strike` | `character varying(20)` | YES | - | |
| `yes_bid` | `integer(32)` | YES | - | |
| `yes_ask` | `integer(32)` | YES | - | |
| `no_bid` | `integer(32)` | YES | - | |
| `no_ask` | `integer(32)` | YES | - | |
| `last_price` | `integer(32)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `volume_24h` | `integer(32)` | YES | - | |
| `open_interest` | `integer(32)` | YES | - | |
| `liquidity` | `integer(32)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |
| `yes_bid_dollars` | `text` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `last_price_dollars` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `market_kalshi_eth_pkey` on `id`
- **Unique:** `market_kalshi_eth_event_market_unique` on `event_ticker`
- **Unique:** `market_kalshi_eth_event_market_unique` on `event_ticker`
- **Unique:** `market_kalshi_eth_event_market_unique` on `market_ticker`
- **Unique:** `market_kalshi_eth_event_market_unique` on `market_ticker`

#### Indexes

- `market_kalshi_eth_event_market_unique`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_eth_event_market_unique ON live_data.market_kalshi_hourly_eth USING btree (event_ticker, market_ticker)
  ```
- `market_kalshi_eth_pkey`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_eth_pkey ON live_data.market_kalshi_hourly_eth USING btree (id)
  ```

---

### Table: `live_data.market_kalshi_hourly_ndx`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.market_kalshi_hourly_ndx_id_seq'::r... | |
| `event_ticker` | `character varying(50)` | NO | - | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | - | Interval: 'hourly' or '15m' |
| `strike` | `character varying(20)` | YES | - | |
| `yes_bid` | `integer(32)` | YES | - | |
| `yes_ask` | `integer(32)` | YES | - | |
| `no_bid` | `integer(32)` | YES | - | |
| `no_ask` | `integer(32)` | YES | - | |
| `last_price` | `integer(32)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `volume_24h` | `integer(32)` | YES | - | |
| `open_interest` | `integer(32)` | YES | - | |
| `liquidity` | `integer(32)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |
| `yes_bid_dollars` | `text` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `last_price_dollars` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `market_kalshi_ndx_pkey` on `id`
- **Unique:** `market_kalshi_ndx_event_market_unique` on `event_ticker`
- **Unique:** `market_kalshi_ndx_event_market_unique` on `market_ticker`
- **Unique:** `market_kalshi_ndx_event_market_unique` on `market_ticker`
- **Unique:** `market_kalshi_ndx_event_market_unique` on `event_ticker`
- **Unique:** `market_kalshi_ndx_event_ticker_market_ticker_key` on `event_ticker`
- **Unique:** `market_kalshi_ndx_event_ticker_market_ticker_key` on `market_ticker`
- **Unique:** `market_kalshi_ndx_event_ticker_market_ticker_key` on `market_ticker`
- **Unique:** `market_kalshi_ndx_event_ticker_market_ticker_key` on `event_ticker`

#### Indexes

- `market_kalshi_ndx_event_market_unique`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_ndx_event_market_unique ON live_data.market_kalshi_hourly_ndx USING btree (event_ticker, market_ticker)
  ```
- `market_kalshi_ndx_event_ticker_market_ticker_key`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_ndx_event_ticker_market_ticker_key ON live_data.market_kalshi_hourly_ndx USING btree (event_ticker, market_ticker)
  ```
- `market_kalshi_ndx_pkey`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_ndx_pkey ON live_data.market_kalshi_hourly_ndx USING btree (id)
  ```

---

### Table: `live_data.market_kalshi_hourly_spx`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.market_kalshi_hourly_spx_id_seq'::r... | |
| `event_ticker` | `character varying(50)` | NO | - | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | - | Interval: 'hourly' or '15m' |
| `strike` | `character varying(20)` | YES | - | |
| `yes_bid` | `integer(32)` | YES | - | |
| `yes_ask` | `integer(32)` | YES | - | |
| `no_bid` | `integer(32)` | YES | - | |
| `no_ask` | `integer(32)` | YES | - | |
| `last_price` | `integer(32)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `volume_24h` | `integer(32)` | YES | - | |
| `open_interest` | `integer(32)` | YES | - | |
| `liquidity` | `integer(32)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |
| `yes_bid_dollars` | `text` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `last_price_dollars` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `market_kalshi_spx_pkey` on `id`
- **Unique:** `market_kalshi_spx_event_market_unique` on `event_ticker`
- **Unique:** `market_kalshi_spx_event_market_unique` on `event_ticker`
- **Unique:** `market_kalshi_spx_event_market_unique` on `market_ticker`
- **Unique:** `market_kalshi_spx_event_market_unique` on `market_ticker`

#### Indexes

- `market_kalshi_spx_event_market_unique`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_spx_event_market_unique ON live_data.market_kalshi_hourly_spx USING btree (event_ticker, market_ticker)
  ```
- `market_kalshi_spx_pkey`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_spx_pkey ON live_data.market_kalshi_hourly_spx USING btree (id)
  ```

---

### Table: `live_data.market_kalshi_15m_btc`

Kalshi 15-minute market data for BTC. One row per current 15m window; truncated and repopulated on each rollover. `strike` is backfilled from `live_data.live_price_log_1s_btc`.`one_minute_avg` at the market's opening time (start of the 15m window).

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.market_kalshi_15m_btc_id_seq'::regclass) | |
| `event_ticker` | `character varying(50)` | NO | - | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | '15m' | Interval: 'hourly' or '15m' |
| `strike` | `character varying(20)` | YES | - | Backfilled from 1s price log at opening time |
| `yes_bid` | `integer(32)` | YES | - | |
| `yes_ask` | `integer(32)` | YES | - | |
| `no_bid` | `integer(32)` | YES | - | |
| `no_ask` | `integer(32)` | YES | - | |
| `last_price` | `integer(32)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `volume_24h` | `integer(32)` | YES | - | |
| `open_interest` | `integer(32)` | YES | - | |
| `liquidity` | `integer(32)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |
| `yes_bid_dollars` | `text` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `last_price_dollars` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `market_kalshi_15m_btc_pkey` on `id`
- **Unique:** `market_kalshi_15m_btc_event_market_unique` on `(event_ticker, market_ticker)`

#### Indexes

- `market_kalshi_15m_btc_event_market_unique`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_15m_btc_event_market_unique ON live_data.market_kalshi_15m_btc USING btree (event_ticker, market_ticker)
  ```
- `market_kalshi_15m_btc_pkey`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_15m_btc_pkey ON live_data.market_kalshi_15m_btc USING btree (id)
  ```

---

### Table: `live_data.market_kalshi_15m_eth`

Kalshi 15-minute market data for ETH. One row per current 15m window; truncated and repopulated on each rollover. `strike` is backfilled from `live_data.live_price_log_1s_eth`.`one_minute_avg` at the market's opening time (start of the 15m window).

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.market_kalshi_15m_eth_id_seq'::regclass) | |
| `event_ticker` | `character varying(50)` | NO | - | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | '15m' | Interval: 'hourly' or '15m' |
| `strike` | `character varying(20)` | YES | - | Backfilled from 1s price log at opening time |
| `yes_bid` | `integer(32)` | YES | - | |
| `yes_ask` | `integer(32)` | YES | - | |
| `no_bid` | `integer(32)` | YES | - | |
| `no_ask` | `integer(32)` | YES | - | |
| `last_price` | `integer(32)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `volume_24h` | `integer(32)` | YES | - | |
| `open_interest` | `integer(32)` | YES | - | |
| `liquidity` | `integer(32)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |
| `yes_bid_dollars` | `text` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `last_price_dollars` | `text` | YES | - | |

#### Constraints

- **Primary Key:** `market_kalshi_15m_eth_pkey` on `id`
- **Unique:** `market_kalshi_15m_eth_event_market_unique` on `(event_ticker, market_ticker)`

#### Indexes

- `market_kalshi_15m_eth_event_market_unique`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_15m_eth_event_market_unique ON live_data.market_kalshi_15m_eth USING btree (event_ticker, market_ticker)
  ```
- `market_kalshi_15m_eth_pkey`
  ```sql
  CREATE UNIQUE INDEX market_kalshi_15m_eth_pkey ON live_data.market_kalshi_15m_eth USING btree (id)
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

#### Constraints

- **Primary Key:** `price_change_eth_pkey` on `id`

#### Indexes

- `price_change_eth_pkey`
  ```sql
  CREATE UNIQUE INDEX price_change_eth_pkey ON live_data.price_change_eth USING btree (id)
  ```

---

### Table: `live_data.price_change_spx`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.price_change_spx_id_seq'::re... | |
| `change1h` | `numeric(10,6)` | YES | - | |
| `change3h` | `numeric(10,6)` | YES | - | |
| `change1d` | `numeric(10,6)` | YES | - | |
| `timestamp` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |

#### Constraints

- **Primary Key:** `price_change_spx_pkey` on `id`

#### Indexes

- `price_change_spx_pkey`
  ```sql
  CREATE UNIQUE INDEX price_change_spx_pkey ON live_data.price_change_spx USING btree (id)
  ```

---

### Table: `live_data.strike_table_hourly_btc`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.strike_table_hourly_btc_id_seq'::re... | |
| `timestamp` | `timestamp with time zone` | YES | now() | |
| `symbol` | `character varying(10)` | YES | - | |
| `market` | `text` | YES | 'hourly' | Interval: 'hourly' or '15m' |
| `current_price` | `numeric(10,2)` | YES | - | |
| `ttc_hourly` | `integer(32)` | YES | - | Time to close for the hourly contract, in seconds. |
| `ttc_15m` | `integer(32)` | YES | - | Time to close for the next 15-minute boundary, in seconds (simulated cycles). |
| `broker` | `character varying(20)` | YES | - | |
| `event_ticker` | `character varying(50)` | YES | - | |
| `market_title` | `text` | YES | - | |
| `strike_tier` | `integer(32)` | YES | - | |
| `market_status` | `character varying(20)` | YES | - | |
| `strike` | `integer(32)` | YES | - | |
| `buffer` | `numeric(10,2)` | YES | - | |
| `buffer_pct` | `numeric(5,2)` | YES | - | |
| `probability_hourly` | `numeric(5,2)` | YES | - | Hourly probability from TTC×buffer×momentum lookup. |
| `probability_15m` | `numeric(5,2)` | YES | - | 15m probability from TTC×buffer×momentum lookup (simulated cycles). |
| `yes_ask` | `numeric(5,2)` | YES | - | |
| `no_ask` | `numeric(5,2)` | YES | - | |
| `yes_diff` | `numeric(5,2)` | YES | - | |
| `no_diff` | `numeric(5,2)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `active_side` | `character varying(10)` | YES | - | |
| `momentum_weighted_score` | `numeric(5,3)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `yes_bid_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `yes_price_spread` | `numeric(6,4)` | YES | - | |
| `no_price_spread` | `numeric(6,4)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | From live price log; current-minute volatility. |
| `volatility_percentile` | `numeric(5,1)` | YES | - | From live price log; percentile vs analytics volatility profile. |
| `movement` | `numeric(10,4)` | YES | - | From live price log; weighted composite (H-L)/O. |
| `movement_percentile` | `numeric(5,1)` | YES | - | From live price log; percentile vs analytics movement profile. |

#### Constraints

- **Primary Key:** `strike_table_btc_pkey` on `id`
- **Unique:** `strike_table_btc_strike_unique` on `strike`

#### Indexes

- `idx_strike_table_btc_lookup`
  ```sql
  CREATE INDEX idx_strike_table_btc_lookup ON live_data.strike_table_hourly_btc USING btree ("timestamp", symbol, current_price)
  ```
- `strike_table_btc_pkey`
  ```sql
  CREATE UNIQUE INDEX strike_table_btc_pkey ON live_data.strike_table_hourly_btc USING btree (id)
  ```
- `strike_table_btc_strike_unique`
  ```sql
  CREATE UNIQUE INDEX strike_table_btc_strike_unique ON live_data.strike_table_hourly_btc USING btree (strike)
  ```

---

### Table: `live_data.strike_table_hourly_eth`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.strike_table_hourly_eth_id_seq'::re... | |
| `timestamp` | `timestamp with time zone` | YES | now() | |
| `symbol` | `character varying(10)` | YES | - | |
| `market` | `text` | YES | 'hourly' | Interval: 'hourly' or '15m' |
| `current_price` | `numeric(10,2)` | YES | - | |
| `ttc_hourly` | `integer(32)` | YES | - | Time to close for the hourly contract, in seconds. |
| `broker` | `character varying(20)` | YES | - | |
| `event_ticker` | `character varying(50)` | YES | - | |
| `market_title` | `text` | YES | - | |
| `strike_tier` | `integer(32)` | YES | - | |
| `market_status` | `character varying(20)` | YES | - | |
| `strike` | `integer(32)` | YES | - | |
| `buffer` | `numeric(10,2)` | YES | - | |
| `buffer_pct` | `numeric(5,2)` | YES | - | |
| `probability_hourly` | `numeric(5,2)` | YES | - | Hourly probability from TTC×buffer×momentum lookup. |
| `yes_ask` | `numeric(5,2)` | YES | - | |
| `no_ask` | `numeric(5,2)` | YES | - | |
| `yes_diff` | `numeric(5,2)` | YES | - | |
| `no_diff` | `numeric(5,2)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `active_side` | `character varying(10)` | YES | - | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `momentum_weighted_score` | `numeric(5,3)` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `yes_bid_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `yes_price_spread` | `numeric(6,4)` | YES | - | |
| `no_price_spread` | `numeric(6,4)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | From live price log; current-minute volatility. |
| `volatility_percentile` | `numeric(5,1)` | YES | - | From live price log; percentile vs analytics volatility profile. |
| `movement` | `numeric(10,4)` | YES | - | From live price log; weighted composite (H-L)/O. |
| `movement_percentile` | `numeric(5,1)` | YES | - | From live price log; percentile vs analytics movement profile. |

#### Constraints

- **Primary Key:** `strike_table_eth_pkey` on `id`

#### Indexes

- `idx_strike_table_eth_lookup`
  ```sql
  CREATE INDEX idx_strike_table_eth_lookup ON live_data.strike_table_hourly_eth USING btree ("timestamp", symbol, current_price)
  ```
- `strike_table_eth_pkey`
  ```sql
  CREATE UNIQUE INDEX strike_table_eth_pkey ON live_data.strike_table_hourly_eth USING btree (id)
  ```

---

### Table: `live_data.strike_table_hourly_ndx`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.strike_table_hourly_ndx_id_seq'::re... | |
| `timestamp` | `timestamp with time zone` | YES | now() | |
| `symbol` | `character varying(10)` | YES | - | |
| `market` | `text` | YES | 'hourly' | Interval: 'hourly' or '15m' |
| `current_price` | `numeric(10,2)` | YES | - | |
| `ttc_seconds` | `integer(32)` | YES | - | |
| `broker` | `character varying(20)` | YES | - | |
| `event_ticker` | `character varying(50)` | YES | - | |
| `market_title` | `text` | YES | - | |
| `strike_tier` | `integer(32)` | YES | - | |
| `market_status` | `character varying(20)` | YES | - | |
| `strike` | `integer(32)` | YES | - | |
| `buffer` | `numeric(10,2)` | YES | - | |
| `buffer_pct` | `numeric(5,2)` | YES | - | |
| `probability` | `numeric(5,2)` | YES | - | |
| `yes_ask` | `numeric(5,2)` | YES | - | |
| `no_ask` | `numeric(5,2)` | YES | - | |
| `yes_diff` | `numeric(5,2)` | YES | - | |
| `no_diff` | `numeric(5,2)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `active_side` | `character varying(10)` | YES | - | |
| `momentum_weighted_score` | `numeric(5,3)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `yes_bid_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `yes_price_spread` | `numeric(6,4)` | YES | - | |
| `no_price_spread` | `numeric(6,4)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | From live price log; current-minute volatility. |
| `volatility_percentile` | `numeric(5,1)` | YES | - | From live price log; percentile vs analytics volatility profile. |
| `movement` | `numeric(10,4)` | YES | - | From live price log; weighted composite (H-L)/O. |
| `movement_percentile` | `numeric(5,1)` | YES | - | From live price log; percentile vs analytics movement profile. |

#### Constraints

- **Primary Key:** `strike_table_ndx_pkey` on `id`
- **Unique:** `strike_table_ndx_strike_key` on `strike`

#### Indexes

- `idx_strike_table_ndx_lookup`
  ```sql
  CREATE INDEX idx_strike_table_ndx_lookup ON live_data.strike_table_hourly_ndx USING btree ("timestamp", symbol, current_price)
  ```
- `strike_table_ndx_pkey`
  ```sql
  CREATE UNIQUE INDEX strike_table_ndx_pkey ON live_data.strike_table_hourly_ndx USING btree (id)
  ```
- `strike_table_ndx_strike_key`
  ```sql
  CREATE UNIQUE INDEX strike_table_ndx_strike_key ON live_data.strike_table_hourly_ndx USING btree (strike)
  ```
- `strike_table_ndx_timestamp_symbol_current_price_idx`
  ```sql
  CREATE INDEX strike_table_ndx_timestamp_symbol_current_price_idx ON live_data.strike_table_hourly_ndx USING btree ("timestamp", symbol, current_price)
  ```
- `strike_table_ndx_timestamp_symbol_current_price_idx1`
  ```sql
  CREATE INDEX strike_table_ndx_timestamp_symbol_current_price_idx1 ON live_data.strike_table_hourly_ndx USING btree ("timestamp", symbol, current_price)
  ```

---

### Table: `live_data.strike_table_hourly_spx`

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('live_data.strike_table_hourly_spx_id_seq'::re... | |
| `timestamp` | `timestamp with time zone` | YES | now() | |
| `symbol` | `character varying(10)` | YES | - | |
| `market` | `text` | YES | 'hourly' | Interval: 'hourly' or '15m' |
| `current_price` | `numeric(10,2)` | YES | - | |
| `ttc_seconds` | `integer(32)` | YES | - | |
| `broker` | `character varying(20)` | YES | - | |
| `event_ticker` | `character varying(50)` | YES | - | |
| `market_title` | `text` | YES | - | |
| `strike_tier` | `integer(32)` | YES | - | |
| `market_status` | `character varying(20)` | YES | - | |
| `strike` | `integer(32)` | YES | - | |
| `buffer` | `numeric(10,2)` | YES | - | |
| `buffer_pct` | `numeric(5,2)` | YES | - | |
| `probability` | `numeric(5,2)` | YES | - | |
| `yes_ask` | `numeric(5,2)` | YES | - | |
| `no_ask` | `numeric(5,2)` | YES | - | |
| `yes_diff` | `numeric(5,2)` | YES | - | |
| `no_diff` | `numeric(5,2)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `ticker` | `character varying(50)` | YES | - | |
| `active_side` | `character varying(10)` | YES | - | |
| `momentum_weighted_score` | `numeric(5,3)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `momentum_percentile` | `numeric(5,1)` | YES | - | |
| `yes_ask_dollars` | `text` | YES | - | |
| `no_ask_dollars` | `text` | YES | - | |
| `yes_bid_dollars` | `text` | YES | - | |
| `no_bid_dollars` | `text` | YES | - | |
| `yes_price_spread` | `numeric(6,4)` | YES | - | |
| `no_price_spread` | `numeric(6,4)` | YES | - | |
| `volatility` | `numeric(10,6)` | YES | - | From live price log; current-minute volatility. |
| `volatility_percentile` | `numeric(5,1)` | YES | - | From live price log; percentile vs analytics volatility profile. |
| `movement` | `numeric(10,4)` | YES | - | From live price log; weighted composite (H-L)/O. |
| `movement_percentile` | `numeric(5,1)` | YES | - | From live price log; percentile vs analytics movement profile. |

#### Constraints

- **Primary Key:** `strike_table_spx_pkey` on `id`
- **Unique:** `strike_table_spx_strike_key` on `strike`

#### Indexes

- `idx_strike_table_spx_lookup`
  ```sql
  CREATE INDEX idx_strike_table_spx_lookup ON live_data.strike_table_hourly_spx USING btree ("timestamp", symbol, current_price)
  ```
- `strike_table_spx_pkey`
  ```sql
  CREATE UNIQUE INDEX strike_table_spx_pkey ON live_data.strike_table_hourly_spx USING btree (id)
  ```
- `strike_table_spx_strike_key`
  ```sql
  CREATE UNIQUE INDEX strike_table_spx_strike_key ON live_data.strike_table_hourly_spx USING btree (strike)
  ```
- `strike_table_spx_timestamp_symbol_current_price_idx`
  ```sql
  CREATE INDEX strike_table_spx_timestamp_symbol_current_price_idx ON live_data.strike_table_hourly_spx USING btree ("timestamp", symbol, current_price)
  ```

---

### Table: `live_data.strike_table_15m_btc`

15-minute strike table for BTC. Single strike per table; `market` = '15m'. Same column set as `strike_table_hourly_btc`: `ttc_hourly`, `ttc_15m`, `probability_hourly`, `probability_15m`. For 15m tables `ttc_hourly` and `probability_hourly` are NULL; readers use `ttc_15m` and `probability_15m` only. Legacy columns `ttc_seconds` and `probability` have been removed.

#### Columns

Same as `live_data.strike_table_hourly_btc` (including `ttc_hourly`, `ttc_15m`, `probability_hourly`, `probability_15m`); `market` TEXT DEFAULT '15m'. 15m-specific values are in `ttc_15m` and `probability_15m`.

---

### Table: `live_data.strike_table_15m_eth`

15-minute strike table for ETH. Single strike per table; `market` = '15m'. Same column set as hourly; 15m readers use `ttc_15m` and `probability_15m` only. Legacy `ttc_seconds` and `probability` removed.

#### Columns

Same as `live_data.strike_table_hourly_eth`; `market` TEXT DEFAULT '15m'. 15m values in `ttc_15m` and `probability_15m`.

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

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('testing.market_kalshi_btc_websocket_id... | |
| `event_ticker` | `character varying(50)` | NO | - | |
| `market_ticker` | `character varying(100)` | NO | - | |
| `market` | `text` | YES | - | Interval: 'hourly' or '15m' |
| `strike` | `character varying(20)` | YES | - | |
| `yes_bid` | `integer(32)` | YES | - | |
| `yes_ask` | `integer(32)` | YES | - | |
| `no_bid` | `integer(32)` | YES | - | |
| `no_ask` | `integer(32)` | YES | - | |
| `last_price` | `integer(32)` | YES | - | |
| `volume` | `integer(32)` | YES | - | |
| `volume_24h` | `integer(32)` | YES | - | |
| `open_interest` | `integer(32)` | YES | - | |
| `liquidity` | `integer(32)` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | now() | |
| `updated_at` | `timestamp with time zone` | YES | now() | |
| `yes_volume` | `integer(32)` | YES | - | |
| `no_volume` | `integer(32)` | YES | - | |

#### Constraints

- **Primary Key:** `market_kalshi_btc_websocket_pkey` on `id`
- **Unique:** `market_kalshi_btc_websocket_event_ticker_market_ticker_key` on `event_ticker`
- **Unique:** `market_kalshi_btc_websocket_event_ticker_market_ticker_key` on `event_ticker`
- **Unique:** `market_kalshi_btc_websocket_event_ticker_market_ticker_key` on `market_ticker`
- **Unique:** `market_kalshi_btc_websocket_event_ticker_market_ticker_key` on `market_ticker`

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

#### Constraints

- **Primary Key:** `account_balance_0001_final_pkey` on `id`

#### Indexes

- `account_balance_0001_final_pkey`
  ```sql
  CREATE UNIQUE INDEX account_balance_0001_final_pkey ON users.account_balance_0001 USING btree (id)
  ```

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
| `market` | `character varying(50)` | YES | - | |
| `trade_strategy` | `character varying(50)` | YES | - | |
| `symbol_open` | `numeric(10,2)` | YES | - | |
| `momentum` | `numeric(5,2)` | YES | - | |
| `prob` | `numeric(5,2)` | YES | - | |
| `fees` | `numeric(10,4)` | YES | - | |
| `diff` | `numeric(10,4)` | YES | - | |
| `status` | `character varying(20)` | YES | 'active'::character varying | |
| `current_symbol_price` | `numeric(10,2)` | YES | - | |
| `current_probability` | `numeric(5,2)` | YES | - | |
| `buffer_from_entry` | `numeric(10,2)` | YES | - | |
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
| `market` | `character varying(50)` | YES | - | |
| `trade_strategy` | `character varying(50)` | YES | - | |
| `symbol_open` | `numeric(10,2)` | YES | - | |
| `momentum` | `numeric(5,2)` | YES | - | |
| `prob` | `numeric(5,2)` | YES | - | |
| `fees` | `numeric(10,4)` | YES | - | |
| `diff` | `numeric(10,4)` | YES | - | |
| `status` | `character varying(20)` | YES | 'active'::character varying | |
| `current_symbol_price` | `numeric(10,2)` | YES | - | |
| `current_probability` | `numeric(5,2)` | YES | - | |
| `buffer_from_entry` | `numeric(10,2)` | YES | - | |
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
| `yes_price` | `real(24)` | YES | - | |
| `no_price` | `real(24)` | YES | - | |
| `is_taker` | `boolean` | YES | - | |
| `created_time` | `text` | YES | - | |
| `raw_json` | `text` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `yes_price_fixed` | `text` | YES | - | |
| `no_price_fixed` | `text` | YES | - | |

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

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.monitor_list_0001_id_seq'::regcl... | |
| `name` | `character varying(255)` | NO | - | |
| `symbol` | `character varying(20)` | NO | - | |
| `market` | `text` | YES | 'hourly' | Market interval: 'hourly' or '15m'. |
| `strategy` | `character varying(100)` | YES | - | |
| `auto_trade` | `boolean` | YES | false | |
| `auto_trade_status` | `character varying(20)` | YES | 'inactive'::character varying | |
| `trades` | `integer(32)` | YES | 0 | |
| `win_loss` | `numeric(5,1)` | YES | 0.0 | |
| `ret_pct` | `numeric(5,1)` | YES | 0.0 | |
| `pnl` | `numeric(10,2)` | YES | 0.00 | |
| `bankroll_allotment_pct` | `real(24)` | YES | 0.00 | |
| `status` | `character varying(20)` | YES | 'active'::character varying | |
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
| `yes_price` | `integer(32)` | YES | - | |
| `no_price` | `integer(32)` | YES | - | |
| `initial_count` | `integer(32)` | YES | - | |
| `initial_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `remaining_count` | `integer(32)` | YES | - | |
| `remaining_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `fill_count` | `integer(32)` | YES | - | |
| `fill_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `created_time` | `text` | YES | - | |
| `expiration_time` | `text` | YES | - | |
| `last_update_time` | `text` | YES | - | |
| `client_order_id` | `text` | YES | - | |
| `order_group_id` | `text` | YES | - | |
| `queue_position` | `integer(32)` | YES | - | |
| `self_trade_prevention_type` | `text` | YES | - | |
| `maker_fees` | `integer(32)` | YES | - | |
| `taker_fees` | `integer(32)` | YES | - | |
| `maker_fill_cost` | `integer(32)` | YES | - | |
| `taker_fill_cost` | `integer(32)` | YES | - | |
| `raw_json` | `text` | YES | - | |
| `created_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `updated_at` | `timestamp with time zone` | YES | CURRENT_TIMESTAMP | |
| `yes_price_dollars` | `text` | YES | - | |
| `no_price_dollars` | `text` | YES | - | |

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
| `yes_total_cost` | `numeric(10,2)` | YES | - | |
| `no_count` | `integer(32)` | YES | - | |
| `no_count_fp` | `numeric(12,2)` | YES | - | Fixed-point (Kalshi migration). |
| `no_total_cost` | `numeric(10,2)` | YES | - | |
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
| `min_differential` | `numeric(5,2)` | YES | 0.25 | |
| `min_time` | `integer(32)` | YES | 120 | |
| `max_time` | `integer(32)` | YES | 900 | |
| `allow_re_entry` | `boolean` | YES | false | |
| `spike_alert_enabled` | `boolean` | YES | true | |
| `spike_alert_momentum_threshold` | `integer(32)` | YES | 36 | |
| `spike_alert_cooldown_threshold` | `integer(32)` | YES | 30 | |
| `spike_alert_cooldown_minutes` | `integer(32)` | YES | 15 | |
| `current_probability` | `integer(32)` | YES | 40 | |
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
| `ticket_id` | `character varying(50)` | YES | - | |
| `message` | `text` | YES | - | |
| `timestamp` | `timestamp without time zone` | YES | CURRENT_TIMESTAMP | |
| `service` | `character varying(50)` | YES | - | |
| `user_id` | `character varying(50)` | YES | 'user_0001'::character varying | |

#### Constraints

- **Primary Key:** `trade_logs_0001_pkey` on `id`

#### Indexes

- `trade_logs_0001_pkey`
  ```sql
  CREATE UNIQUE INDEX trade_logs_0001_pkey ON users.trade_logs_0001 USING btree (id)
  ```

---

### Table: `users.trades_0001`

**Schema sync:** When changing this table (columns, types, indexes), apply the same changes to `users.trades_simulated_0001` so both stay in sync.

#### Columns

| Column Name | Data Type | Nullable | Default | Description |
|-------------|-----------|----------|---------|-------------|
| `id` | `integer(32)` | NO | nextval('users.trades_0001_id_seq'::regclass) | |
| `status` | `text` | NO | - | |
| `date` | `text` | NO | - | |
| `time` | `text` | NO | - | |
| `symbol` | `text` | YES | - | |
| `market` | `text` | YES | 'Kalshi'::text | |
| `trade_strategy` | `text` | YES | 'Hourly HTC'::text | |
| `contract` | `text` | NO | - | |
| `strike` | `text` | NO | - | |
| `side` | `text` | NO | - | |
| `prob` | `real(24)` | YES | - | |
| `diff` | `text` | YES | - | |
| `buy_price` | `real(24)` | NO | - | |
| `position` | `integer(32)` | NO | - | |
| `sell_price` | `real(24)` | YES | - | |
| `closed_at` | `text` | YES | - | |
| `fees` | `real(24)` | YES | - | |
| `pnl` | `real(24)` | YES | - | |
| `symbol_open` | `real(24)` | YES | - | |
| `symbol_close` | `real(24)` | YES | - | |
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
| `ret_pct` | `real(24)` | YES | - | |
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
| `paper_trade` | `boolean` | YES | false | |
| `cooldown_timer` | `integer(32)` | YES | - | |
| `monitor_confirmed` | `boolean` | YES | false | |
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

---

### Table: `users.trades_simulated_0001`

**Maintenance note:** This table was created as a copy of `users.trades_0001` for storing simulated 15m-cycle trades (e.g. from the simulated path on hourly strike tables). **Any future schema changes to `users.trades_0001` (new columns, type changes, indexes, constraints) must be applied to `users.trades_simulated_0001` as well** so the two tables stay in sync.

Same column set as `users.trades_0001` (see that table for column descriptions). Currently empty; will be written to by the simulated-trade path. As of the last DB check, this table has no primary key or indexes; add them to mirror `trades_0001` when needed (e.g. `id` as primary key, indexes on `date`, `status`, `ticker`, etc.).

#### Columns (from DB)

| Column | Type |
|--------|------|
| `id` | integer |
| `status` | text |
| `date` | text |
| `time` | text |
| `symbol` | text |
| `market` | text |
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
| `symbol_open` | real |
| `symbol_close` | real |
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

Kalshi v1 account/history entries (deposits and withdrawals) synced from the API. Populated by kalshi_account_sync_ws (sync_account_history when balance is synced). One row per Deposit or Withdrawal; columns match the API response.

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

#### Constraints

- **Primary Key:** `account_history_0001_pkey` on `id`
- **Unique:** `account_history_0001_created_type_amount_key` on `(created_at, entry_type, amount)` for upsert deduplication

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
