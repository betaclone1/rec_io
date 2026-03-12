-- Remove fixed-point dollar fee/cost columns from users.orders_0001

ALTER TABLE users.orders_0001
    DROP COLUMN IF EXISTS taker_fees_dollars,
    DROP COLUMN IF EXISTS maker_fees_dollars,
    DROP COLUMN IF EXISTS taker_fill_cost_dollars,
    DROP COLUMN IF EXISTS maker_fill_cost_dollars;

