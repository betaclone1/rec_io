-- Best-effort revert; may fail if values longer than 50 characters.

ALTER TABLE system.master_users ALTER COLUMN first_name TYPE VARCHAR(50);
ALTER TABLE system.master_users ALTER COLUMN last_name TYPE VARCHAR(50);
