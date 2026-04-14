-- Optional bcrypt hash for self-service registration (web /api/auth/register).
ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
