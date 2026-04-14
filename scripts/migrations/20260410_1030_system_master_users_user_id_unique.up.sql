-- Required for INSERT ... ON CONFLICT (user_id) in manage_master_users.sh and registration script.
CREATE UNIQUE INDEX IF NOT EXISTS master_users_user_id_key ON system.master_users (user_id);
