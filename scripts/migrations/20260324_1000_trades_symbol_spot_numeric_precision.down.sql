-- Revert spot columns to double precision (approximate; may lose sub-cent precision).

ALTER TABLE users.trades_0001
  ALTER COLUMN symbol_open TYPE double precision USING symbol_open::double precision,
  ALTER COLUMN symbol_close TYPE double precision USING symbol_close::double precision;

ALTER TABLE users.trades_simulated_0001
  ALTER COLUMN symbol_open TYPE double precision USING symbol_open::double precision,
  ALTER COLUMN symbol_close TYPE double precision USING symbol_close::double precision;
