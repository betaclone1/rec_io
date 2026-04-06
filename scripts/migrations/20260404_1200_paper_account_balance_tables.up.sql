-- Parallel paper account: balance history + subaccounts (same shape as live _0001).
-- Used when trading_mode=paper; NOTIFY uses stream account_balance_paper per stream_registry.

CREATE SEQUENCE IF NOT EXISTS users.account_balance_paper_0001_id_seq;

CREATE TABLE users.account_balance_paper_0001 (
    id integer NOT NULL PRIMARY KEY DEFAULT nextval('users.account_balance_paper_0001_id_seq'::regclass),
    balance real NOT NULL,
    exposure integer,
    positions integer,
    portfolio integer,
    timestamp text NOT NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    bankroll_current integer,
    bankroll_prev integer,
    portfolio_value integer,
    master_trading_bankroll integer,
    mtb_base_value integer
);

ALTER SEQUENCE users.account_balance_paper_0001_id_seq OWNED BY users.account_balance_paper_0001.id;

CREATE SEQUENCE IF NOT EXISTS users.subaccounts_paper_0001_id_seq;

CREATE TABLE users.subaccounts_paper_0001 (
    id integer NOT NULL PRIMARY KEY DEFAULT nextval('users.subaccounts_paper_0001_id_seq'::regclass),
    subaccount text NOT NULL,
    balance integer NOT NULL DEFAULT 0,
    base_value integer,
    realized_pnl integer,
    realized_pnl_pct real,
    target_pnl__pct real,
    transfer_amt real,
    automatic_transfers boolean NOT NULL DEFAULT false
);

ALTER SEQUENCE users.subaccounts_paper_0001_id_seq OWNED BY users.subaccounts_paper_0001.id;

CREATE UNIQUE INDEX subaccounts_paper_0001_subaccount_key ON users.subaccounts_paper_0001 (subaccount);

-- Seed subaccount rows from live template (settings + zero balances) so UPDATEs in subaccounts_update never no-op.
INSERT INTO users.subaccounts_paper_0001 (
    subaccount, balance, base_value, realized_pnl, realized_pnl_pct,
    target_pnl__pct, transfer_amt, automatic_transfers
)
SELECT
    s.subaccount,
    0,
    s.base_value,
    NULL,
    NULL,
    s.target_pnl__pct,
    s.transfer_amt,
    COALESCE(s.automatic_transfers, false)
FROM users.subaccounts_0001 AS s
WHERE NOT EXISTS (
    SELECT 1 FROM users.subaccounts_paper_0001 p WHERE p.subaccount = s.subaccount
);

-- If live had no rows, minimal bootstrap.
INSERT INTO users.subaccounts_paper_0001 (subaccount, balance, automatic_transfers)
SELECT v.subaccount, 0, false
FROM (VALUES ('PRIMARY'), ('Master Trading Bankroll'), ('Cash Transfer')) AS v(subaccount)
WHERE NOT EXISTS (SELECT 1 FROM users.subaccounts_paper_0001 WHERE subaccount = v.subaccount);

CREATE TRIGGER account_balance_paper_0001_db_notify
  AFTER INSERT OR UPDATE OR DELETE ON users.account_balance_paper_0001
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();

-- Paper subaccounts: never auto-rake into transfers_0001 (live-only bookkeeping).
UPDATE users.subaccounts_paper_0001 SET automatic_transfers = false;
