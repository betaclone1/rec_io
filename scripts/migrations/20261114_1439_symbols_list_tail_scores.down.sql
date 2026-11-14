ALTER TABLE live_data.symbols_list
  DROP COLUMN IF EXISTS upper_tail_score;

ALTER TABLE live_data.symbols_list
  DROP COLUMN IF EXISTS lower_tail_score;
