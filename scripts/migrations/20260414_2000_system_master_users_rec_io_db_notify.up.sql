-- Admin Tools + backbone: NOTIFY on registry changes → stream `master_users` (stream_registry).
DROP TRIGGER IF EXISTS system_master_users_rec_io_db_notify ON system.master_users;
CREATE TRIGGER system_master_users_rec_io_db_notify AFTER INSERT OR UPDATE OR DELETE ON system.master_users
    FOR EACH ROW
    EXECUTE PROCEDURE public.rec_io_db_notify();
