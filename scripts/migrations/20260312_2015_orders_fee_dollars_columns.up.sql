-- Add fixed-point dollar fee/cost columns to users.orders_0001
-- These mirror the Kalshi API *_dollars fields and complement the existing integer cent columns.

ALTER TABLE users.orders_0001
    ADD COLUMN IF NOT EXISTS taker_fees_dollars TEXT,
    ADD COLUMN IF NOT EXISTS maker_fees_dollars TEXT,
    ADD COLUMN IF NOT EXISTS taker_fill_cost_dollars TEXT,
    ADD COLUMN IF NOT EXISTS maker_fill_cost_dollars TEXT;

