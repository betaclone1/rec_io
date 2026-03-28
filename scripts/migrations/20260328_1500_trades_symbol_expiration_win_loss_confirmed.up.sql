-- Live trades only: end-of-cycle spot for counterfactual W/L vs early stops; not added to trades_simulated_0001.

ALTER TABLE users.trades_0001
  ADD COLUMN IF NOT EXISTS symbol_expiration NUMERIC(18,5);

ALTER TABLE users.trades_0001
  ADD COLUMN IF NOT EXISTS win_loss_confirmed BOOLEAN;
