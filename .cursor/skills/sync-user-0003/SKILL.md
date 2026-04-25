# Sync user 0003 (uniform production resync)

Run this when the user asks to manually resync tenant `0003` from tenant `0001` for testing.

## Non-negotiable safety

- `users_0001` is source-only. Never run mutating SQL against it.
- Only mutate `users_0003`.
- Run all table rebuild DDL/DML in a single transaction with `ON_ERROR_STOP=1`.
- If any step fails, rollback and report failure.

## Target and prerequisites

- SSH target: `root@$REC_PROD_SSH_HOST`
- DB: `rec_io_db` as `rec_io_user` (`PGPASSWORD=rec_io_password`)
- Run on prod host.

## Uniform rebuild set (always)

Rebuild these destination tables from `users_0001`:

1. `users_0003.monitor_list_0003` from `users_0001.monitor_list_0001`
2. `users_0003.trades_0003` from `users_0001.trades_0001`
3. `users_0003.trades_simulated_0003` from `users_0001.trades_simulated_0001`
4. `users_0003.account_balance_paper_0003` from `users_0001.account_balance_paper_0001`
5. `users_0003.subaccounts_paper_0003` from `users_0001.subaccounts_paper_0001`

## Critical paper-trade override (non-negotiable)

After rebuilding `users_0003.monitor_list_0003`, force:

- `paper_trade = TRUE` for **all** rows in `users_0003.monitor_list_0003`

This must happen regardless of the source values in `users_0001.monitor_list_0001`.

## Uniform transform rules

For rebuilt monitor/trade tables:

- `monitor_list_0003`:
  - remap monitor identity:
    - `id`: `100xx` -> `300xx` (`+20000`)
    - `name`: `mon_0001_100xx` -> `mon_0003_300xx`
    - `user_id_strategy`: force `0003`
  - force `paper_trade = TRUE` for all rows
- `trades_0003` and `trades_simulated_0003`:
  - replace monitor values:
    - `mon_0001_100` -> `mon_0003_300`
  - replace embedded tenant markers in text/json payloads:
    - `_0001_100` -> `_0003_300`
    - `mon_0001_100` -> `mon_0003_300`

## Uniform SQL execution template

Run one blocking SSH command that executes one `psql` transaction:

```bash
ssh root@$REC_PROD_SSH_HOST "export PGPASSWORD=rec_io_password; psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U rec_io_user -d rec_io_db <<'SQL'
BEGIN;

-- 0) monitor_list_0003 (critical: force paper_trade=true for all rows)
DROP TABLE IF EXISTS users_0003.monitor_list_0003;
CREATE TABLE users_0003.monitor_list_0003 (LIKE users_0001.monitor_list_0001 INCLUDING ALL);
INSERT INTO users_0003.monitor_list_0003 SELECT * FROM users_0001.monitor_list_0001;
UPDATE users_0003.monitor_list_0003 SET id = id + 20000 WHERE id BETWEEN 10000 AND 19999;
UPDATE users_0003.monitor_list_0003
SET name = regexp_replace(name, '^mon_0001_100', 'mon_0003_300')
WHERE name LIKE 'mon_0001_100%';
UPDATE users_0003.monitor_list_0003 SET user_id_strategy = '0003' WHERE user_id_strategy IS DISTINCT FROM '0003';
UPDATE users_0003.monitor_list_0003 SET paper_trade = TRUE;

-- 1) trades_0003
DROP TABLE IF EXISTS users_0003.trades_0003;
CREATE TABLE users_0003.trades_0003 (LIKE users_0001.trades_0001 INCLUDING ALL);
INSERT INTO users_0003.trades_0003 SELECT * FROM users_0001.trades_0001;
UPDATE users_0003.trades_0003
SET monitor = regexp_replace(monitor, '^mon_0001_100', 'mon_0003_300')
WHERE monitor LIKE 'mon_0001_100%';
UPDATE users_0003.trades_0003
SET notes = REPLACE(REPLACE(notes, '_0001_100', '_0003_300'), 'mon_0001_100', 'mon_0003_300')
WHERE notes IS NOT NULL AND (POSITION('_0001_100' IN notes) > 0 OR POSITION('mon_0001_100' IN notes) > 0);
UPDATE users_0003.trades_0003
SET monitor_confirm_detail = REPLACE(REPLACE(monitor_confirm_detail, '_0001_100', '_0003_300'), 'mon_0001_100', 'mon_0003_300')
WHERE monitor_confirm_detail IS NOT NULL AND (POSITION('_0001_100' IN monitor_confirm_detail) > 0 OR POSITION('mon_0001_100' IN monitor_confirm_detail) > 0);

-- 2) trades_simulated_0003
DROP TABLE IF EXISTS users_0003.trades_simulated_0003;
CREATE TABLE users_0003.trades_simulated_0003 (LIKE users_0001.trades_simulated_0001 INCLUDING ALL);
INSERT INTO users_0003.trades_simulated_0003 SELECT * FROM users_0001.trades_simulated_0001;
UPDATE users_0003.trades_simulated_0003
SET monitor = regexp_replace(monitor, '^mon_0001_100', 'mon_0003_300')
WHERE monitor LIKE 'mon_0001_100%';
UPDATE users_0003.trades_simulated_0003
SET notes = REPLACE(REPLACE(notes, '_0001_100', '_0003_300'), 'mon_0001_100', 'mon_0003_300')
WHERE notes IS NOT NULL AND (POSITION('_0001_100' IN notes) > 0 OR POSITION('mon_0001_100' IN notes) > 0);
UPDATE users_0003.trades_simulated_0003
SET monitor_confirm_detail = REPLACE(REPLACE(monitor_confirm_detail, '_0001_100', '_0003_300'), 'mon_0001_100', 'mon_0003_300')
WHERE monitor_confirm_detail IS NOT NULL AND (POSITION('_0001_100' IN monitor_confirm_detail) > 0 OR POSITION('mon_0001_100' IN monitor_confirm_detail) > 0);

-- 3) account_balance_paper_0003
DROP TABLE IF EXISTS users_0003.account_balance_paper_0003;
CREATE TABLE users_0003.account_balance_paper_0003 (LIKE users_0001.account_balance_paper_0001 INCLUDING ALL);
INSERT INTO users_0003.account_balance_paper_0003 SELECT * FROM users_0001.account_balance_paper_0001;

-- 4) subaccounts_paper_0003
DROP TABLE IF EXISTS users_0003.subaccounts_paper_0003;
CREATE TABLE users_0003.subaccounts_paper_0003 (LIKE users_0001.subaccounts_paper_0001 INCLUDING ALL);
INSERT INTO users_0003.subaccounts_paper_0003 SELECT * FROM users_0001.subaccounts_paper_0001;

-- 5) destination-owned sequences
CREATE SEQUENCE IF NOT EXISTS users_0003.monitor_list_0003_id_seq;
ALTER TABLE users_0003.monitor_list_0003 ALTER COLUMN id SET DEFAULT nextval('users_0003.monitor_list_0003_id_seq'::regclass);
ALTER SEQUENCE users_0003.monitor_list_0003_id_seq OWNED BY users_0003.monitor_list_0003.id;
SELECT setval('users_0003.monitor_list_0003_id_seq', COALESCE((SELECT MAX(id) FROM users_0003.monitor_list_0003), 1), true);

CREATE SEQUENCE IF NOT EXISTS users_0003.trades_0003_id_seq;
ALTER TABLE users_0003.trades_0003 ALTER COLUMN id SET DEFAULT nextval('users_0003.trades_0003_id_seq'::regclass);
ALTER SEQUENCE users_0003.trades_0003_id_seq OWNED BY users_0003.trades_0003.id;
SELECT setval('users_0003.trades_0003_id_seq', COALESCE((SELECT MAX(id) FROM users_0003.trades_0003), 1), true);

CREATE SEQUENCE IF NOT EXISTS users_0003.trades_simulated_0003_id_seq;
ALTER TABLE users_0003.trades_simulated_0003 ALTER COLUMN id SET DEFAULT nextval('users_0003.trades_simulated_0003_id_seq'::regclass);
ALTER SEQUENCE users_0003.trades_simulated_0003_id_seq OWNED BY users_0003.trades_simulated_0003.id;
SELECT setval('users_0003.trades_simulated_0003_id_seq', COALESCE((SELECT MAX(id) FROM users_0003.trades_simulated_0003), 1), true);

CREATE SEQUENCE IF NOT EXISTS users_0003.account_balance_paper_0003_id_seq;
ALTER TABLE users_0003.account_balance_paper_0003 ALTER COLUMN id SET DEFAULT nextval('users_0003.account_balance_paper_0003_id_seq'::regclass);
ALTER SEQUENCE users_0003.account_balance_paper_0003_id_seq OWNED BY users_0003.account_balance_paper_0003.id;
SELECT setval('users_0003.account_balance_paper_0003_id_seq', COALESCE((SELECT MAX(id) FROM users_0003.account_balance_paper_0003), 1), true);

CREATE SEQUENCE IF NOT EXISTS users_0003.subaccounts_paper_0003_id_seq;
ALTER TABLE users_0003.subaccounts_paper_0003 ALTER COLUMN id SET DEFAULT nextval('users_0003.subaccounts_paper_0003_id_seq'::regclass);
ALTER SEQUENCE users_0003.subaccounts_paper_0003_id_seq OWNED BY users_0003.subaccounts_paper_0003.id;
SELECT setval('users_0003.subaccounts_paper_0003_id_seq', COALESCE((SELECT MAX(id) FROM users_0003.subaccounts_paper_0003), 1), true);

COMMIT;
SQL"
```

## Mandatory verification block

After commit, run and report:

1. Row count parity:
   - `users_0001.monitor_list_0001` vs `users_0003.monitor_list_0003`
   - `users_0001.trades_0001` vs `users_0003.trades_0003`
   - `users_0001.trades_simulated_0001` vs `users_0003.trades_simulated_0003`
   - `users_0001.account_balance_paper_0001` vs `users_0003.account_balance_paper_0003`
   - `users_0001.subaccounts_paper_0001` vs `users_0003.subaccounts_paper_0003`
2. Paper-trade critical check (must pass):
   - `SELECT COUNT(*) FROM users_0003.monitor_list_0003 WHERE paper_trade IS DISTINCT FROM TRUE` -> must be `0`
   - `SELECT COUNT(*) FROM users_0003.monitor_list_0003 WHERE id BETWEEN 10000 AND 19999` -> must be `0`
   - `SELECT COUNT(*) FROM users_0003.monitor_list_0003 WHERE name LIKE 'mon_0001_%'` -> must be `0`
   - `SELECT COUNT(*) FROM users_0003.monitor_list_0003 WHERE user_id_strategy IS DISTINCT FROM '0003'` -> must be `0`
3. Pattern checks (must be zero):
   - `monitor LIKE 'mon_0001_%'` in both destination trade tables
   - `monitor LIKE '%_0001_100%'` in both destination trade tables
4. Explicit statement in output:
   - `users_0001 was not modified`
