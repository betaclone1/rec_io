-- Statement-level NOTIFY for hourly rolling-rate upserts → stream `tail_backtest_rolling_rates`.
-- Row volume per wake can be large; FOR EACH STATEMENT keeps the firehose to one signal per SQL statement.
DROP TRIGGER IF EXISTS tail_backtest_rolling_rates_rec_io_db_notify_stmt
  ON historical_data.tail_backtest_rolling_rates;
CREATE TRIGGER tail_backtest_rolling_rates_rec_io_db_notify_stmt
  AFTER INSERT OR UPDATE OR DELETE ON historical_data.tail_backtest_rolling_rates
  FOR EACH STATEMENT
  EXECUTE PROCEDURE public.rec_io_db_notify_stmt();
