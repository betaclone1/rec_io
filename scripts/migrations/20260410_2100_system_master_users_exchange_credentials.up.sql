-- Per-tenant flags for which exchanges may use authenticated API calls (keys on disk are not enough).
-- Quote identifier "master_users" so tenant SQL rewrite does not treat "users." inside master_users.exchange as legacy users schema.
ALTER TABLE system."master_users"
  ADD COLUMN IF NOT EXISTS exchange_credentials JSONB NOT NULL
  DEFAULT '{"kalshi": false, "polymarket": false}'::jsonb;

COMMENT ON COLUMN system."master_users".exchange_credentials IS
  'JSON: kalshi / polymarket booleans. When kalshi is false, supervised workers must not perform authenticated Kalshi calls.';

-- Ops / primary admin: allow Kalshi when credentials are provisioned.
UPDATE system."master_users"
SET exchange_credentials = '{"kalshi": true, "polymarket": false}'::jsonb
WHERE LOWER(TRIM(COALESCE(account_type, ''))) = 'master_admin';

-- Legacy default primary slot (typical live install) — adjust via UPDATE if a different slot is the only live trader.
UPDATE system."master_users"
SET exchange_credentials = '{"kalshi": true, "polymarket": false}'::jsonb
WHERE LPAD(TRIM(user_no::text), 4, '0') = '0001'
  AND LOWER(TRIM(COALESCE(status, ''))) = 'active';
