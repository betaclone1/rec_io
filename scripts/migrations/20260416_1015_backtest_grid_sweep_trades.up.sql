-- Mirror tenant trades layout for grid-sweep / archive-replay synthetic trades (backtest schema only).
-- Requires template users_0001.trades_0001 (standard dev/prod tenant).

CREATE SCHEMA IF NOT EXISTS backtest;

CREATE SEQUENCE IF NOT EXISTS backtest.grid_sweep_trades_id_seq;

CREATE TABLE IF NOT EXISTS backtest.grid_sweep_trades (
    LIKE users_0001.trades_0001 INCLUDING DEFAULTS EXCLUDING INDEXES EXCLUDING CONSTRAINTS
);

ALTER TABLE backtest.grid_sweep_trades ALTER COLUMN id DROP DEFAULT;
ALTER TABLE backtest.grid_sweep_trades
    ALTER COLUMN id SET DEFAULT nextval('backtest.grid_sweep_trades_id_seq');

SELECT setval(
    'backtest.grid_sweep_trades_id_seq',
    COALESCE((SELECT MAX(id) + 1 FROM backtest.grid_sweep_trades), 1),
    false
);

ALTER TABLE backtest.grid_sweep_trades
    ADD COLUMN IF NOT EXISTS sweep_batch_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS synthetic_monitor_id INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_monitor_id INTEGER NOT NULL DEFAULT 0;

COMMENT ON TABLE backtest.grid_sweep_trades IS
    'Synthetic trades from archive grid sweeps; same column set as users_0001.trades_0001 plus sweep_batch_id, synthetic_monitor_id, source_monitor_id. No rec_io_db_notify.';

CREATE INDEX IF NOT EXISTS grid_sweep_trades_batch_synth_idx
    ON backtest.grid_sweep_trades (sweep_batch_id, synthetic_monitor_id);

CREATE INDEX IF NOT EXISTS grid_sweep_trades_batch_idx
    ON backtest.grid_sweep_trades (sweep_batch_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        JOIN pg_namespace n ON t.relnamespace = n.oid
        WHERE n.nspname = 'backtest' AND t.relname = 'grid_sweep_trades' AND c.contype = 'p'
    ) THEN
        ALTER TABLE backtest.grid_sweep_trades ADD PRIMARY KEY (id);
    END IF;
END $$;
