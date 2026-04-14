-- Self-service email verification codes (latest code only; stored as bcrypt hash in app).

ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS email_verification_code_hash VARCHAR(255);
ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS email_verification_sent_at TIMESTAMP WITHOUT TIME ZONE;
