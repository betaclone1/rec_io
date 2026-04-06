-- Paper-mode internal transfer log (user 0001). Same shape as users.transfers_0001;
-- no Kalshi / external rows. NOTIFY → stream transfers_paper.

CREATE SEQUENCE IF NOT EXISTS users.transfers_paper_0001_id_seq;

CREATE TABLE users.transfers_paper_0001 (
    id integer NOT NULL PRIMARY KEY DEFAULT nextval('users.transfers_paper_0001_id_seq'::regclass),
    timestamp text NOT NULL,
    type text,
    "from" text,
    "to" text,
    amount integer,
    initiated text,
    status character varying(50),
    external_transfer_id integer
);

ALTER SEQUENCE users.transfers_paper_0001_id_seq OWNED BY users.transfers_paper_0001.id;

CREATE TRIGGER transfers_paper_0001_db_notify
  AFTER INSERT OR UPDATE OR DELETE ON users.transfers_paper_0001
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();
