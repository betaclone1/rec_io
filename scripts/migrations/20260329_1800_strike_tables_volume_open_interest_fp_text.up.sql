-- Strike rows: persist Kalshi depth only as TEXT volume_fp / open_interest_fp (parity with market tables).

-- --- strike_table_15m ---
ALTER TABLE live_data.strike_table_15m ADD COLUMN IF NOT EXISTS volume_fp TEXT;
ALTER TABLE live_data.strike_table_15m ADD COLUMN IF NOT EXISTS open_interest_fp TEXT;

DO $m15$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_15m' AND column_name = 'volume'
  ) THEN
    UPDATE live_data.strike_table_15m
    SET volume_fp = trim(both FROM to_char(round(volume::numeric, 2), 'FM999999999999999999990.00'))
    WHERE volume IS NOT NULL;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_15m' AND column_name = 'open_interest'
  ) THEN
    UPDATE live_data.strike_table_15m
    SET open_interest_fp = trim(both FROM to_char(round(open_interest::numeric, 2), 'FM999999999999999999990.00'))
    WHERE open_interest IS NOT NULL;
  END IF;
END $m15$;

ALTER TABLE live_data.strike_table_15m DROP COLUMN IF EXISTS volume;
ALTER TABLE live_data.strike_table_15m DROP COLUMN IF EXISTS open_interest;

-- --- strike_table_hourly_btc ---
ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS volume_fp TEXT;
ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS open_interest_fp TEXT;

DO $hbc$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc' AND column_name = 'volume'
  ) THEN
    UPDATE live_data.strike_table_hourly_btc
    SET volume_fp = trim(both FROM to_char(round(volume::numeric, 2), 'FM999999999999999999990.00'))
    WHERE volume IS NOT NULL;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc' AND column_name = 'open_interest'
  ) THEN
    UPDATE live_data.strike_table_hourly_btc
    SET open_interest_fp = trim(both FROM to_char(round(open_interest::numeric, 2), 'FM999999999999999999990.00'))
    WHERE open_interest IS NOT NULL;
  END IF;
END $hbc$;

ALTER TABLE live_data.strike_table_hourly_btc DROP COLUMN IF EXISTS volume;
ALTER TABLE live_data.strike_table_hourly_btc DROP COLUMN IF EXISTS open_interest;

-- --- strike_table_hourly_eth ---
ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS volume_fp TEXT;
ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS open_interest_fp TEXT;

DO $het$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth' AND column_name = 'volume'
  ) THEN
    UPDATE live_data.strike_table_hourly_eth
    SET volume_fp = trim(both FROM to_char(round(volume::numeric, 2), 'FM999999999999999999990.00'))
    WHERE volume IS NOT NULL;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth' AND column_name = 'open_interest'
  ) THEN
    UPDATE live_data.strike_table_hourly_eth
    SET open_interest_fp = trim(both FROM to_char(round(open_interest::numeric, 2), 'FM999999999999999999990.00'))
    WHERE open_interest IS NOT NULL;
  END IF;
END $het$;

ALTER TABLE live_data.strike_table_hourly_eth DROP COLUMN IF EXISTS volume;
ALTER TABLE live_data.strike_table_hourly_eth DROP COLUMN IF EXISTS open_interest;
