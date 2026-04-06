-- Cash balance in cents as integer (was real) — avoids float display/rounding on large values.
ALTER TABLE users.account_balance_0001
  ALTER COLUMN balance TYPE integer USING round(balance::numeric)::integer;

ALTER TABLE users.account_balance_paper_0001
  ALTER COLUMN balance TYPE integer USING round(balance::numeric)::integer;
