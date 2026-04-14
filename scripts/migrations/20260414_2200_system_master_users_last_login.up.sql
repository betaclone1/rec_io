-- Last UI activity / login touch (throttled updates from POST /api/user/activity).
ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITHOUT TIME ZONE;
