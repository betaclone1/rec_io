-- Paper subaccount row ids must equal live ids for the same subaccount name (parity for tooling/UI).
-- Original seed used a separate sequence; rebuild rows with live ids and preserve paper balances.

CREATE TEMP TABLE _subaccounts_paper_0001_align_backup (LIKE users.subaccounts_paper_0001 INCLUDING DEFAULTS);

INSERT INTO _subaccounts_paper_0001_align_backup
SELECT * FROM users.subaccounts_paper_0001;

DELETE FROM users.subaccounts_paper_0001;

INSERT INTO users.subaccounts_paper_0001 (
    id,
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
    s.id,
    s.subaccount,
    COALESCE(b.balance, 0)::integer,
    b.base_value,
    b.realized_pnl,
    b.realized_pnl_pct,
    s.target_pnl__pct,
    s.transfer_amt,
    false
FROM users.subaccounts_0001 s
LEFT JOIN _subaccounts_paper_0001_align_backup b ON b.subaccount = s.subaccount;

SELECT setval(
    'users.subaccounts_paper_0001_id_seq',
    COALESCE((SELECT MAX(id) FROM users.subaccounts_paper_0001), 1)
);

DROP TABLE IF EXISTS _subaccounts_paper_0001_align_backup;
