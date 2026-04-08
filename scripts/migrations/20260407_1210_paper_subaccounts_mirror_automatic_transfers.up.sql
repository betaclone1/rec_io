-- Undo legacy "force automatic_transfers = false on all paper rows" where paper still matched live
-- false. Do not overwrite paper MTB (or any row) that was explicitly set TRUE while live stays false:
-- use OR so either live or paper true wins.

UPDATE users.subaccounts_paper_0001 p
SET automatic_transfers = p.automatic_transfers OR COALESCE(s.automatic_transfers, false)
FROM users.subaccounts_0001 s
WHERE p.subaccount = s.subaccount;
