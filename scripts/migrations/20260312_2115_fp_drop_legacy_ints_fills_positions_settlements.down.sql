-- Recreate legacy integer/count columns (empty) for rollback.

ALTER TABLE users.fills_0001
    ADD COLUMN IF NOT EXISTS count INTEGER;

ALTER TABLE users.positions_0001
    ADD COLUMN IF NOT EXISTS total_traded INTEGER,
    ADD COLUMN IF NOT EXISTS position INTEGER,
    ADD COLUMN IF NOT EXISTS market_exposure INTEGER,
    ADD COLUMN IF NOT EXISTS realized_pnl REAL,
    ADD COLUMN IF NOT EXISTS fees_paid REAL;

ALTER TABLE users.settlements_0001
    ADD COLUMN IF NOT EXISTS yes_count INTEGER,
    ADD COLUMN IF NOT EXISTS no_count INTEGER;

