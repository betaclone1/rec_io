-- Revert: re-seed paper from live names without copying ids (legacy separate-sequence behavior).
-- Destroys current paper id alignment and may change primary key values.

DELETE FROM users.subaccounts_paper_0001;

INSERT INTO users.subaccounts_paper_0001 (
    subaccount,
    balance,
    base_value,
    realized_pnl,
    realized_pnl_pct,
    target_pnl__pct,
    transfer_amt,
    automatic_transfers
)
SELECT
    s.subaccount,
    0,
    s.base_value,
    NULL,
    NULL,
    s.target_pnl__pct,
    s.transfer_amt,
    false
FROM users.subaccounts_0001 AS s;

INSERT INTO users.subaccounts_paper_0001 (subaccount, balance, automatic_transfers)
SELECT v.subaccount, 0, false
FROM (VALUES ('PRIMARY'), ('Master Trading Bankroll'), ('Cash Transfer')) AS v(subaccount)
WHERE NOT EXISTS (SELECT 1 FROM users.subaccounts_paper_0001 p WHERE p.subaccount = v.subaccount);

UPDATE users.subaccounts_paper_0001 SET automatic_transfers = false;

SELECT setval(
    'users.subaccounts_paper_0001_id_seq',
    COALESCE((SELECT MAX(id) FROM users.subaccounts_paper_0001), 1)
);
