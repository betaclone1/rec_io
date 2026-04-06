ALTER TABLE users.account_balance_0001
  ALTER COLUMN balance TYPE real USING balance::real;

ALTER TABLE users.account_balance_paper_0001
  ALTER COLUMN balance TYPE real USING balance::real;
