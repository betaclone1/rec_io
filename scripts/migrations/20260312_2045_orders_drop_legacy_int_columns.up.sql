-- Drop legacy integer price/count/fee columns from users.orders_0001
-- After Kalshi fixed-point migration, we rely on *_fp and *_dollars fields.

ALTER TABLE users.orders_0001
    DROP COLUMN IF EXISTS yes_price,
    DROP COLUMN IF EXISTS no_price,
    DROP COLUMN IF EXISTS initial_count,
    DROP COLUMN IF EXISTS remaining_count,
    DROP COLUMN IF EXISTS fill_count,
    DROP COLUMN IF EXISTS maker_fees,
    DROP COLUMN IF EXISTS taker_fees,
    DROP COLUMN IF EXISTS maker_fill_cost,
    DROP COLUMN IF EXISTS taker_fill_cost;

