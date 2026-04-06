-- Flip Sell: probability-stop and floor-stop toggles and multiplier strings (e.g. 1x, future max).
-- Booleans default FALSE; mults NULL until first enable (app sets 1x) or user sets explicitly.

DO $$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'users'
      AND table_name LIKE 'monitor_list_%'
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'users' AND table_name = tbl AND column_name = 'flip_sell_prob'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN flip_sell_prob BOOLEAN NOT NULL DEFAULT FALSE',
        tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'users' AND table_name = tbl AND column_name = 'flip_sell_floor'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN flip_sell_floor BOOLEAN NOT NULL DEFAULT FALSE',
        tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'users' AND table_name = tbl AND column_name = 'flip_sell_prob_mult'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN flip_sell_prob_mult VARCHAR(32)',
        tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'users' AND table_name = tbl AND column_name = 'flip_sell_floor_mult'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN flip_sell_floor_mult VARCHAR(32)',
        tbl
      );
    END IF;
  END LOOP;
END
$$;

COMMENT ON COLUMN users.monitor_list_0001.flip_sell_prob IS 'When true, allow flip-sell sizing for probability-based auto stops.';
COMMENT ON COLUMN users.monitor_list_0001.flip_sell_floor IS 'When true, allow flip-sell sizing for floor-price stops.';
COMMENT ON COLUMN users.monitor_list_0001.flip_sell_prob_mult IS 'Flip-sell size token for prob stops (e.g. 1x); NULL until enabled or set.';
COMMENT ON COLUMN users.monitor_list_0001.flip_sell_floor_mult IS 'Flip-sell size token for floor stops (e.g. 1x); NULL until enabled or set.';
