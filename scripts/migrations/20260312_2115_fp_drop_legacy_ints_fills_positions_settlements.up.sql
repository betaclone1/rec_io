-- Drop legacy integer/cents/count columns from fixed-point–migrated portfolio tables.
-- After the Kalshi fixed-point migration, all live logic reads *_fp and *_dollars fields.

-- Fills: keep count_fp and dollar prices only
ALTER TABLE users.fills_0001
    DROP COLUMN IF EXISTS count;

-- Positions: keep *_fp and *_dollars; legacy numeric columns are no longer read by live logic
ALTER TABLE users.positions_0001
    DROP COLUMN IF EXISTS total_traded,
    DROP COLUMN IF EXISTS position,
    DROP COLUMN IF EXISTS market_exposure,
    DROP COLUMN IF EXISTS realized_pnl,
    DROP COLUMN IF EXISTS fees_paid;

-- Settlements: keep *_fp and *_total_cost_dollars; legacy int counts are no longer read
ALTER TABLE users.settlements_0001
    DROP COLUMN IF EXISTS yes_count,
    DROP COLUMN IF EXISTS no_count;

