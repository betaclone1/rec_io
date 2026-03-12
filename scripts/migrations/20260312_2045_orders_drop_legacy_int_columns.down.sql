-- Recreate legacy integer price/count/fee columns on users.orders_0001 (empty) for rollback.

ALTER TABLE users.orders_0001
    ADD COLUMN IF NOT EXISTS yes_price INTEGER,
    ADD COLUMN IF NOT EXISTS no_price INTEGER,
    ADD COLUMN IF NOT EXISTS initial_count INTEGER,
    ADD COLUMN IF NOT EXISTS remaining_count INTEGER,
    ADD COLUMN IF NOT EXISTS fill_count INTEGER,
    ADD COLUMN IF NOT EXISTS maker_fees INTEGER,
    ADD COLUMN IF NOT EXISTS taker_fees INTEGER,
    ADD COLUMN IF NOT EXISTS maker_fill_cost INTEGER,
    ADD COLUMN IF NOT EXISTS taker_fill_cost INTEGER;

