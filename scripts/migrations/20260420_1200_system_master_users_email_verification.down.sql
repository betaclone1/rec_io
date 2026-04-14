ALTER TABLE system.master_users DROP COLUMN IF EXISTS email_verification_sent_at;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS email_verification_code_hash;
