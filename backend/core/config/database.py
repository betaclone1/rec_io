"""
Centralized Database Configuration
Provides environment variable-based configuration for PostgreSQL connections.

Single pattern: use DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT. If unset,
falls back to REC_DB_HOST, REC_DB_NAME, REC_DB_USER, REC_DB_PASS, REC_DB_PORT
so .env or deploy can use either convention. Scripts should use
get_postgresql_connection() or get_database_config() here; do not use POSTGRES_*
or hardcoded credentials.
"""

import os

from backend.core.time_eastern import merge_psycopg2_connect_kwargs


def get_database_config():
    """Get database configuration from environment variables. Prefer DB_*; fall back to REC_DB_*.
    In production (REC_ENVIRONMENT=production), DB_PASSWORD or REC_DB_PASS is required; no default.

    Includes ``options`` so PostgreSQL session ``TimeZone`` is America/New_York (naive TIMESTAMP
    columns and naive datetime adapters match project conventions)."""
    pw = os.getenv('DB_PASSWORD') or os.getenv('REC_DB_PASS')
    if os.getenv('REC_ENVIRONMENT') == 'production' and not pw:
        raise ValueError("DB_PASSWORD or REC_DB_PASS required in production")
    base = {
        'host': os.getenv('DB_HOST') or os.getenv('REC_DB_HOST') or 'localhost',
        'database': os.getenv('DB_NAME') or os.getenv('REC_DB_NAME') or 'rec_io_db',
        'user': os.getenv('DB_USER') or os.getenv('REC_DB_USER') or 'rec_io_user',
        'password': pw or 'rec_io_password',
        'port': int(os.getenv('DB_PORT') or os.getenv('REC_DB_PORT') or '5432'),
    }
    return merge_psycopg2_connect_kwargs(base)

def get_postgresql_connection():
    """Get a connection to the PostgreSQL database using environment configuration."""
    try:
        import psycopg2
        config = get_database_config()
        conn = psycopg2.connect(**config)
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return None

def test_database_connection():
    """Test the database connection and return status."""
    try:
        conn = get_postgresql_connection()
        if conn:
            conn.close()
            return True, "Database connection successful"
        else:
            return False, "Database connection failed"
    except Exception as e:
        return False, f"Database connection error: {e}"

def init_database():
    """Initialize database schema and tables."""
    try:
        conn = get_postgresql_connection()
        if not conn:
            print("❌ Cannot initialize database - connection failed")
            return False, "Database connection failed"
        
        cursor = conn.cursor()
        
        # Create schemas if they don't exist
        cursor.execute("CREATE SCHEMA IF NOT EXISTS users;")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS live_data;")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS system;")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS testing;")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS backtest;")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS archive;")

        # Redis switchboard pilot: minimal testing table for DB -> NOTIFY -> Redis -> WS.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS testing.redis_basic_test (
                id SERIAL PRIMARY KEY,
                test_value_1 NUMERIC,
                test_value_2 NUMERIC,
                test_value_3 NUMERIC,
                test_value_4 NUMERIC,
                test_value_5 NUMERIC,
                test_value_6 NUMERIC,
                test_value_7 NUMERIC,
                test_value_8 NUMERIC,
                test_value_9 NUMERIC,
                test_value_10 NUMERIC,
                test_value_11 NUMERIC,
                test_value_12 NUMERIC,
                test_value_13 NUMERIC,
                test_value_14 NUMERIC,
                test_value_15 NUMERIC,
                test_value_16 NUMERIC,
                test_value_17 NUMERIC,
                test_value_18 NUMERIC,
                test_value_19 NUMERIC,
                test_value_20 NUMERIC
            );
        """)
        
        # Create core tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users.trades_0001 (
                id SERIAL PRIMARY KEY,
                status VARCHAR(50) DEFAULT 'pending',
                date DATE,
                time TIME,
                symbol VARCHAR(50),
                exchange VARCHAR(50),
                trade_strategy VARCHAR(100),
                market VARCHAR(10) DEFAULT 'hourly',
                contract VARCHAR(255),
                strike VARCHAR(50),
                side VARCHAR(10),
                prob DECIMAL(10,4),
                diff VARCHAR(50),
                buy_price DECIMAL(10,4),
                position INTEGER,
                sell_price DECIMAL(10,4),
                closed_at TIMESTAMP,
                fees DECIMAL(10,4),
                pnl DECIMAL(10,4),
                symbol_open NUMERIC(18,5),
                symbol_close NUMERIC(18,5),
                symbol_expiration NUMERIC(18,5),
                win_loss_confirmed BOOLEAN,
                momentum INTEGER,
                volatility_percentile NUMERIC(5,1),
                win_loss VARCHAR(10),
                ticker VARCHAR(100),
                ticket_id VARCHAR(100) UNIQUE,
                market_id VARCHAR(100),
                momentum_percentile DECIMAL(10,4),
                entry_method VARCHAR(50),
                close_method VARCHAR(50),
                bankroll DECIMAL(12,2),
                master_trading_bankroll INTEGER,
                mtb_base_value INTEGER,
                monitor VARCHAR(50),
                hour_idx INTEGER,
                weekly_cycle NUMERIC(5,1),
                order_id TEXT,
                order_id_open TEXT,
                order_id_close TEXT,
                high_price DECIMAL(10,4),
                low_price DECIMAL(10,4),
                loss_prevention BOOLEAN DEFAULT FALSE,
                multiplier DECIMAL(10,2),
                price_spread DECIMAL(6,4),
                yes_ask_min_15m NUMERIC(18,4),
                yes_ask_max_15m NUMERIC(18,4),
                no_ask_min_15m NUMERIC(18,4),
                no_ask_max_15m NUMERIC(18,4),
                yes_ask_range_15m NUMERIC(18,4),
                no_ask_range_15m NUMERIC(18,4),
                paper_trade BOOLEAN DEFAULT FALSE,
                cooldown_timer INTEGER,
                monitor_confirmed BOOLEAN DEFAULT NULL,
                cycle_win_loss TEXT,
                cycle_pnl REAL,
                cycle_ret_pct REAL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                test_filter BOOLEAN DEFAULT FALSE,
                notes TEXT,
                ret_pct REAL,
                ret_pct_base REAL,
                roi_pct REAL,
                momentum_5s_avg NUMERIC,
                volatility NUMERIC(10,4),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                ats_updated TIMESTAMPTZ
            );
        """)

        # Simulated trades table: same column set as trades_0001, but buy_price, position, fees, bankroll, price_spread (and sell_price) are nullable by design—the simulated path inserts NULL for those. See MASTER_DB_SCHEMA_REFERENCE.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users.trades_simulated_0001 (
                id SERIAL PRIMARY KEY,
                status TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                symbol TEXT,
                exchange TEXT DEFAULT 'kalshi',
                trade_strategy TEXT DEFAULT 'Hourly HTC',
                market VARCHAR(10) DEFAULT 'hourly',
                contract TEXT NOT NULL,
                strike TEXT NOT NULL,
                side TEXT NOT NULL,
                prob REAL,
                diff TEXT,
                buy_price REAL,
                position INTEGER,
                sell_price REAL,
                closed_at TEXT,
                fees REAL,
                pnl REAL,
                symbol_open NUMERIC(18,5),
                symbol_close NUMERIC(18,5),
                momentum INTEGER,
                volatility_percentile NUMERIC(5,1),
                volatility NUMERIC(10,4),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                win_loss TEXT,
                ticker TEXT,
                ticket_id TEXT,
                market_id TEXT,
                momentum_percentile REAL,
                entry_method TEXT DEFAULT 'manual',
                close_method TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                test_filter BOOLEAN DEFAULT FALSE,
                notes TEXT,
                monitor TEXT,
                bankroll REAL,
                master_trading_bankroll INTEGER,
                mtb_base_value INTEGER,
                ret_pct REAL,
                ret_pct_base REAL,
                roi_pct REAL,
                momentum_5s_avg NUMERIC(10,4),
                order_id TEXT,
                order_id_open TEXT,
                order_id_close TEXT,
                high_price NUMERIC(10,4),
                low_price NUMERIC(10,4),
                hour_idx SMALLINT,
                weekly_cycle NUMERIC(5,1),
                loss_prevention BOOLEAN DEFAULT FALSE,
                multiplier NUMERIC(10,2),
                price_spread NUMERIC(6,4),
                yes_ask_min_15m NUMERIC(18,4),
                yes_ask_max_15m NUMERIC(18,4),
                no_ask_min_15m NUMERIC(18,4),
                no_ask_max_15m NUMERIC(18,4),
                yes_ask_range_15m NUMERIC(18,4),
                no_ask_range_15m NUMERIC(18,4),
                paper_trade BOOLEAN DEFAULT FALSE,
                cooldown_timer INTEGER,
                monitor_confirmed BOOLEAN DEFAULT NULL,
                cycle_win_loss TEXT,
                cycle_pnl REAL,
                cycle_ret_pct REAL,
                ats_updated TIMESTAMPTZ
            );
        """)

        # Ensure new columns exist for legacy databases
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'loss_prevention'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN loss_prevention BOOLEAN DEFAULT FALSE;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'multiplier'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN multiplier DECIMAL(10,2);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'price_spread'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN price_spread DECIMAL(6,4);
                END IF;

                -- weekly_cycle: migrate INTEGER to NUMERIC(5,1) for 15m-window record-keeping (hourly=.4, 15m :00/.15/.30/.45 = .0/.1/.2/.3)
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns c
                    WHERE c.table_schema = 'users' AND c.table_name = 'trades_0001' AND c.column_name = 'weekly_cycle'
                      AND c.data_type IN ('integer', 'smallint', 'bigint')
                ) THEN
                    ALTER TABLE users.trades_0001 ALTER COLUMN weekly_cycle TYPE NUMERIC(5,1) USING weekly_cycle::numeric(5,1);
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001')
                  AND EXISTS (
                    SELECT 1 FROM information_schema.columns c
                    WHERE c.table_schema = 'users' AND c.table_name = 'trades_simulated_0001' AND c.column_name = 'weekly_cycle'
                      AND c.data_type IN ('integer', 'smallint', 'bigint')
                ) THEN
                    ALTER TABLE users.trades_simulated_0001 ALTER COLUMN weekly_cycle TYPE NUMERIC(5,1) USING weekly_cycle::numeric(5,1);
                END IF;

                -- symbol_open / symbol_close: NUMERIC(18,5) for low-priced spots (SOL/XRP); legacy was REAL or DECIMAL(10,4)
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns c
                    WHERE c.table_schema = 'users' AND c.table_name = 'trades_0001' AND c.column_name = 'symbol_open'
                      AND (
                           c.data_type IN ('double precision', 'real')
                        OR (c.data_type = 'numeric' AND (
                             COALESCE(c.numeric_precision, 0) < 18 OR COALESCE(c.numeric_scale, 0) < 5
                           ))
                      )
                ) THEN
                    ALTER TABLE users.trades_0001
                      ALTER COLUMN symbol_open TYPE NUMERIC(18,5) USING symbol_open::numeric,
                      ALTER COLUMN symbol_close TYPE NUMERIC(18,5) USING symbol_close::numeric;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns c
                    WHERE c.table_schema = 'users' AND c.table_name = 'trades_simulated_0001' AND c.column_name = 'symbol_open'
                      AND (
                           c.data_type IN ('double precision', 'real')
                        OR (c.data_type = 'numeric' AND (
                             COALESCE(c.numeric_precision, 0) < 18 OR COALESCE(c.numeric_scale, 0) < 5
                           ))
                      )
                ) THEN
                    ALTER TABLE users.trades_simulated_0001
                      ALTER COLUMN symbol_open TYPE NUMERIC(18,5) USING symbol_open::numeric,
                      ALTER COLUMN symbol_close TYPE NUMERIC(18,5) USING symbol_close::numeric;
                END IF;

                -- Live record-keeping: end-of-cycle spot and counterfactual W/L confirmation (not on trades_simulated_0001)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'symbol_expiration'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN symbol_expiration NUMERIC(18,5);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'win_loss_confirmed'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN win_loss_confirmed BOOLEAN;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'market_result'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN market_result TEXT;
                END IF;

                -- Kalshi cadence: hourly vs 15m (not venue; see `exchange`)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'market'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN market VARCHAR(10) DEFAULT 'hourly';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_simulated_0001'
                      AND column_name = 'market'
                ) THEN
                    ALTER TABLE users.trades_simulated_0001 ADD COLUMN market VARCHAR(10) DEFAULT 'hourly';
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_0001' AND column_name = 'ats_updated'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN ats_updated TIMESTAMPTZ;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001' AND column_name = 'ats_updated'
                ) THEN
                    ALTER TABLE users.trades_simulated_0001 ADD COLUMN ats_updated TIMESTAMPTZ;
                END IF;

                -- Strike-table final-window ask snapshot at trade insert (migration 20260330_2200_trades_strike_final_quarter_asks)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'yes_ask_min_15m'
                ) THEN
                    ALTER TABLE users.trades_0001
                      ADD COLUMN yes_ask_min_15m NUMERIC(18,4),
                      ADD COLUMN yes_ask_max_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_min_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_max_15m NUMERIC(18,4),
                      ADD COLUMN yes_ask_range_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_range_15m NUMERIC(18,4);
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_simulated_0001'
                      AND column_name = 'yes_ask_min_15m'
                ) THEN
                    ALTER TABLE users.trades_simulated_0001
                      ADD COLUMN yes_ask_min_15m NUMERIC(18,4),
                      ADD COLUMN yes_ask_max_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_min_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_max_15m NUMERIC(18,4),
                      ADD COLUMN yes_ask_range_15m NUMERIC(18,4),
                      ADD COLUMN no_ask_range_15m NUMERIC(18,4);
                END IF;

                -- Ensure trades_simulated_0001.id has a sequence default so INSERT ... RETURNING id returns a value
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001') THEN
                    CREATE SEQUENCE IF NOT EXISTS users.trades_simulated_0001_id_seq;
                    ALTER TABLE users.trades_simulated_0001 ALTER COLUMN id SET DEFAULT nextval('users.trades_simulated_0001_id_seq'::regclass);
                    PERFORM setval('users.trades_simulated_0001_id_seq', (SELECT COALESCE(MAX(id), 0) + 1 FROM users.trades_simulated_0001 WHERE id IS NOT NULL));
                    -- Add primary key if missing (enables row delete in TablePlus and other GUIs)
                    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON c.conrelid = t.oid JOIN pg_namespace n ON t.relnamespace = n.oid WHERE n.nspname = 'users' AND t.relname = 'trades_simulated_0001' AND c.contype = 'p') THEN
                        ALTER TABLE users.trades_simulated_0001 ADD PRIMARY KEY (id);
                    END IF;
                    -- Simulated trades insert NULL for buy_price, position (and fees, bankroll, price_spread): ensure columns are nullable
                    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001' AND column_name = 'buy_price' AND is_nullable = 'NO') THEN
                        ALTER TABLE users.trades_simulated_0001 ALTER COLUMN buy_price DROP NOT NULL;
                    END IF;
                    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001' AND column_name = 'position' AND is_nullable = 'NO') THEN
                        ALTER TABLE users.trades_simulated_0001 ALTER COLUMN position DROP NOT NULL;
                    END IF;
                END IF;

                -- Migrate from volatility to volatility_percentile
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'volatility'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'volatility_percentile'
                ) THEN
                    ALTER TABLE users.trades_0001 DROP COLUMN volatility;
                    ALTER TABLE users.trades_0001 ADD COLUMN volatility_percentile NUMERIC(5,1);
                END IF;

                -- Ensure volatility_percentile exists (for new databases)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'volatility_percentile'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN volatility_percentile NUMERIC(5,1);
                END IF;

                -- Add paper_trade column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'paper_trade'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE;
                END IF;

                -- Add cooldown_timer column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'cooldown_timer'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN cooldown_timer INTEGER;
                END IF;

                -- Add monitor_confirmed column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'monitor_confirmed'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN monitor_confirmed BOOLEAN DEFAULT NULL;
                END IF;

                -- Add cycle_win_loss column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'cycle_win_loss'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN cycle_win_loss TEXT;
                END IF;

                -- Add cycle_pnl column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'cycle_pnl'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN cycle_pnl REAL;
                END IF;

                -- Add cycle_ret_pct column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'cycle_ret_pct'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN cycle_ret_pct REAL;
                END IF;

                -- Add created_at column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'created_at'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
                END IF;

                -- Add updated_at column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'updated_at'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
                END IF;

                -- Add test_filter column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'test_filter'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN test_filter BOOLEAN DEFAULT FALSE;
                END IF;

                -- Add notes column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'notes'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN notes TEXT;
                END IF;

                -- Add ret_pct column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'ret_pct'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN ret_pct REAL;
                END IF;

                -- Add momentum_5s_avg column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'momentum_5s_avg'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN momentum_5s_avg NUMERIC;
                END IF;

                -- Add volatility (raw), movement, movement_percentile - same format as momentum / momentum_percentile
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'volatility'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN volatility NUMERIC(10,4);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'movement'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN movement NUMERIC(10,4);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'movement_percentile'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN movement_percentile NUMERIC(5,1);
                END IF;

                -- Add order_id column if it doesn't exist (legacy, before order_id_open/order_id_close)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'trades_0001'
                      AND column_name = 'order_id'
                ) THEN
                    ALTER TABLE users.trades_0001 ADD COLUMN order_id TEXT;
                END IF;
            END
            $$;
        """)
        
        # Legacy generic table kept for backwards compatibility with older tooling.
        # Unified ATS pool tables are users.active_trades_15m_0001 and users.active_trades_hourly_0001.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users.active_trades_0001 (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                side VARCHAR(10) NOT NULL,
                quantity DECIMAL(20,8),
                entry_price DECIMAL(20,8),
                current_price DECIMAL(20,8),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20)
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users.trade_preferences_0001 (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                symbol VARCHAR(20),
                risk_level VARCHAR(20),
                trade_strategy VARCHAR(100),
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users.account_history_0001 (
                id SERIAL PRIMARY KEY,
                entry_type VARCHAR(20) NOT NULL,
                amount INTEGER NOT NULL,
                fee INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE,
                status VARCHAR(50),
                returned_amount INTEGER DEFAULT 0,
                deposit_type VARCHAR(50),
                immediate_amount INTEGER,
                immediate_status VARCHAR(50),
                synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                master_trading_bankroll INTEGER,
                mtb_base_value INTEGER,
                CONSTRAINT account_history_0001_created_type_amount_key UNIQUE (created_at, entry_type, amount)
            );
        """)
        # Ensure account_history_0001 columns and constraint exist (for tables created manually)
        cursor.execute("""
            DO $$
            DECLARE
                col TEXT;
                cols_add TEXT[] := ARRAY[
                    'entry_type', 'amount', 'fee', 'created_at', 'updated_at', 'status',
                    'returned_amount', 'deposit_type', 'immediate_amount', 'immediate_status',
                    'synced_at', 'kalshi_id', 'vendor', 'rail', 'master_trading_bankroll', 'mtb_base_value'
                ];
                col_defs TEXT[] := ARRAY[
                    'VARCHAR(20) NOT NULL', 'INTEGER NOT NULL', 'INTEGER DEFAULT 0', 'TIMESTAMP WITH TIME ZONE NOT NULL',
                    'TIMESTAMP WITH TIME ZONE', 'VARCHAR(50)', 'INTEGER DEFAULT 0', 'VARCHAR(50)', 'INTEGER', 'VARCHAR(50)',
                    'TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP', 'VARCHAR(64)', 'VARCHAR(100)', 'VARCHAR(100)',
                    'INTEGER', 'INTEGER'
                ];
                i INT;
            BEGIN
                FOR i IN 1..array_length(cols_add, 1) LOOP
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users' AND table_name = 'account_history_0001' AND column_name = cols_add[i]
                    ) THEN
                        EXECUTE format('ALTER TABLE users.account_history_0001 ADD COLUMN %I ' || col_defs[i], cols_add[i]);
                    END IF;
                END LOOP;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'account_history_0001_created_type_amount_key') THEN
                    ALTER TABLE users.account_history_0001 ADD CONSTRAINT account_history_0001_created_type_amount_key UNIQUE (created_at, entry_type, amount);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'users' AND tablename = 'account_history_0001' AND indexname = 'account_history_0001_kalshi_id_key'
                ) THEN
                    CREATE UNIQUE INDEX account_history_0001_kalshi_id_key ON users.account_history_0001 (kalshi_id) WHERE kalshi_id IS NOT NULL;
                END IF;
            EXCEPTION WHEN OTHERS THEN
                NULL;
            END $$;
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.strike_pipeline_health (
                exchange VARCHAR(20) NOT NULL,
                market VARCHAR(20) NOT NULL,
                symbol VARCHAR(10) NOT NULL,
                pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
                pipeline_health_reason TEXT,
                pipeline_health_checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 900,
                ws_transport_ok_at TIMESTAMP WITH TIME ZONE,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                PRIMARY KEY (exchange, market, symbol)
            );
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS strike_pipeline_health_checked_idx
            ON live_data.strike_pipeline_health USING btree (pipeline_health_checked_at DESC);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS strike_pipeline_health_transport_idx
            ON live_data.strike_pipeline_health USING btree (ws_transport_ok_at DESC NULLS LAST);
        """)
        # Add status and external_transfer_id to transfers_0001 if table exists
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'transfers_0001') THEN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'transfers_0001' AND column_name = 'status') THEN
                        ALTER TABLE users.transfers_0001 ADD COLUMN status VARCHAR(50);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'transfers_0001' AND column_name = 'external_transfer_id') THEN
                        ALTER TABLE users.transfers_0001 ADD COLUMN external_transfer_id INTEGER;
                    END IF;
                END IF;
            END $$;
        """)
        # Add kalshi_user_id to user_info_0001 if table exists (MASTER_DB_SCHEMA_REFERENCE)
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = 'user_info_0001') THEN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'user_info_0001' AND column_name = 'kalshi_user_id') THEN
                        ALTER TABLE users.user_info_0001 ADD COLUMN kalshi_user_id VARCHAR(50);
                    END IF;
                END IF;
            END $$;
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users.system_settings_0001 (
                id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                drawdown_trading_halt BOOLEAN NOT NULL DEFAULT TRUE,
                drawdown_reset_threshold_pct NUMERIC(5, 2) NOT NULL DEFAULT 50.00
                    CHECK (drawdown_reset_threshold_pct > 0 AND drawdown_reset_threshold_pct < 100),
                trading_halt_active BOOLEAN NOT NULL DEFAULT FALSE,
                drawdown_halt_monitor_snapshot JSONB,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'system_settings_0001'
                      AND column_name = 'trading_halt_active'
                ) THEN
                    ALTER TABLE users.system_settings_0001
                        ADD COLUMN trading_halt_active BOOLEAN NOT NULL DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users' AND table_name = 'system_settings_0001'
                      AND column_name = 'drawdown_halt_monitor_snapshot'
                ) THEN
                    ALTER TABLE users.system_settings_0001
                        ADD COLUMN drawdown_halt_monitor_snapshot JSONB;
                END IF;
            END $$;
        """)
        cursor.execute("""
            INSERT INTO users.system_settings_0001 (id, drawdown_trading_halt, drawdown_reset_threshold_pct)
            VALUES (1, TRUE, 50.00)
            ON CONFLICT (id) DO NOTHING;
        """)

        # Create sequence for 5-digit IDs starting with 10001
        cursor.execute("""
            CREATE SEQUENCE IF NOT EXISTS users.monitor_list_0001_id_seq
            START WITH 10001
            INCREMENT BY 1
            MINVALUE 10001
            MAXVALUE 99999
            CYCLE;
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users.monitor_list_0001 (
                id INTEGER PRIMARY KEY DEFAULT nextval('users.monitor_list_0001_id_seq'),
                name VARCHAR(255) NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                market TEXT DEFAULT 'hourly',
                strategy VARCHAR(100),
                auto_trade BOOLEAN DEFAULT FALSE,
                auto_trade_status VARCHAR(20) DEFAULT 'inactive',
                trades INTEGER DEFAULT 0,
                win_loss DECIMAL(5,1) DEFAULT 0.0,
                ret_pct DECIMAL(5,1) DEFAULT 0.0,
                pnl DECIMAL(10,2) DEFAULT 0.00,
                bankroll_allotment DECIMAL(5,1) DEFAULT 0.0,
                status VARCHAR(20) DEFAULT 'active',
                dashboard_order INTEGER DEFAULT 0,
                win_streak INTEGER DEFAULT 0,
                win_streak_threshold INTEGER DEFAULT 22,
                loss_prevention VARCHAR(50) DEFAULT 'none',
                loss_prevention_toggle BOOLEAN DEFAULT TRUE,
                last_processed_cycle VARCHAR(100),
                current_contract TEXT,
                current_weekly_cycle SMALLINT,
                current_performance_modifier NUMERIC(10,2) DEFAULT 1.00,
                current_max_pct_exposure NUMERIC(10,2) DEFAULT 0.25,
                performance_based_allocation BOOLEAN NOT NULL DEFAULT FALSE,
                max_price_spread NUMERIC(6,4) DEFAULT 0.0300,
                paper_trade BOOLEAN DEFAULT FALSE,
                test_filter BOOLEAN DEFAULT FALSE,
                prob_adj NUMERIC(5,2) DEFAULT 5.00,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # New naming convention tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_btc (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,2),
                one_minute_avg DECIMAL(10,2),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1)
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_eth (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,2),
                one_minute_avg DECIMAL(10,2),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_sol (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,6),
                one_minute_avg DECIMAL(10,6),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                momentum_percentile DECIMAL(5,1),
                momentum_5s_avg DECIMAL(5,1),
                momentum_30s_avg DECIMAL(5,1),
                volatility DECIMAL(10,6),
                volatility_percentile DECIMAL(5,1),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_xrp (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,6),
                one_minute_avg DECIMAL(10,6),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                momentum_percentile DECIMAL(5,1),
                momentum_5s_avg DECIMAL(5,1),
                momentum_30s_avg DECIMAL(5,1),
                volatility DECIMAL(10,6),
                volatility_percentile DECIMAL(5,1),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1)
            );
        """)
        
        # Ensure movement columns exist on live_price_log tables
        cursor.execute("""
            DO $$
            DECLARE
                t text;
                c text;
                ty text;
                tbl regclass;
            BEGIN
                FOREACH t IN ARRAY ARRAY['live_price_log_1s_btc','live_price_log_1s_eth','live_price_log_1s_sol','live_price_log_1s_xrp'] LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = t) THEN
                        FOREACH c IN ARRAY ARRAY['move_1m','move_2m','move_3m','move_4m','move_15m','move_30m','movement','movement_percentile'] LOOP
                            IF c = 'movement_percentile' THEN ty := 'DECIMAL(5,1)'; ELSE ty := 'DECIMAL(10,4)'; END IF;
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = c) THEN
                                EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN %I ' || ty, t, c);
                            END IF;
                        END LOOP;
                    END IF;
                END LOOP;
            END $$;
        """)

        # Watchdog insert_tick requires momentum/volatility percentile columns (same as BTC/ETH).
        cursor.execute("""
            DO $$
            DECLARE
                t text;
            BEGIN
                FOREACH t IN ARRAY ARRAY['live_price_log_1s_btc','live_price_log_1s_eth','live_price_log_1s_sol','live_price_log_1s_xrp'] LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = t) THEN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'momentum_percentile') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN momentum_percentile DECIMAL(5,1)', t);
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'momentum_5s_avg') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN momentum_5s_avg DECIMAL(5,1)', t);
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'momentum_30s_avg') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN momentum_30s_avg DECIMAL(5,1)', t);
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'volatility') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN volatility DECIMAL(10,6)', t);
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'volatility_percentile') THEN
                            EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN volatility_percentile DECIMAL(5,1)', t);
                        END IF;
                    END IF;
                END LOOP;
            END $$;
        """)
        
        # Add volatility and movement columns to hourly strike tables (btc, eth)
        cursor.execute("""
            DO $$
            DECLARE
                t text;
                r record;
            BEGIN
                FOREACH t IN ARRAY ARRAY['strike_table_hourly'] LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = t) THEN
                        FOR r IN (SELECT unnest(ARRAY['volatility','volatility_percentile','movement','movement_percentile']) AS col,
                                         unnest(ARRAY['NUMERIC(10,6)','NUMERIC(5,1)','NUMERIC(10,4)','NUMERIC(5,1)']) AS typ) LOOP
                            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = t AND column_name = r.col) THEN
                                EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN %I ' || r.typ, t, r.col);
                            END IF;
                        END LOOP;
                    END IF;
                END LOOP;
            END $$;
        """)
        
        # Add market column (TEXT: 'hourly' or '15m') to all market_kalshi_* and strike_table_* tables
        cursor.execute("""
            DO $$
            DECLARE
                r record;
                tbl text;
                def text;
            BEGIN
                FOR r IN (
                    SELECT unnest(ARRAY['market_kalshi_hourly']) AS t, 'hourly' AS d
                    UNION ALL SELECT 'market_kalshi_15m', '15m'
                    UNION ALL SELECT 'strike_table_hourly', 'hourly'
                    UNION ALL SELECT 'strike_table_15m', '15m'
                ) LOOP
                    tbl := r.t;
                    def := r.d;
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = tbl)
                       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = tbl AND column_name = 'market') THEN
                        EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN market TEXT DEFAULT %L', tbl, def);
                    END IF;
                END LOOP;
            END $$;
        """)
        
        # Rename momentum_value -> movement_value in all analytics movement profile tables
        cursor.execute("""
            DO $$
            DECLARE
                r record;
            BEGIN
                FOR r IN (SELECT table_name FROM information_schema.tables
                          WHERE table_schema = 'analytics' AND table_name LIKE '%_movement_profile%') LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_schema = 'analytics' AND table_name = r.table_name AND column_name = 'momentum_value') THEN
                        EXECUTE format('ALTER TABLE analytics.%I RENAME COLUMN momentum_value TO movement_value', r.table_name);
                    END IF;
                END LOOP;
            END $$;
        """)
        
        # live_symbol_status: one row per symbol; columns mirror live_price_log_1s_* (latest tick per symbol)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.live_symbol_status (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20),
                "timestamp" TEXT,
                price DECIMAL(10,2),
                one_minute_avg DECIMAL(10,2),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4),
                momentum_percentile DECIMAL(5,1),
                momentum_5s_avg DECIMAL(5,1),
                volatility DECIMAL(10,6),
                volatility_percentile DECIMAL(5,1),
                momentum_30s_avg DECIMAL(5,1),
                move_1m DECIMAL(10,4),
                move_2m DECIMAL(10,4),
                move_3m DECIMAL(10,4),
                move_4m DECIMAL(10,4),
                move_15m DECIMAL(10,4),
                move_30m DECIMAL(10,4),
                movement DECIMAL(10,4),
                movement_percentile DECIMAL(5,1),
                prev_day_avg_momentum_percentile DECIMAL(5,1),
                prev_day_avg_volatility_percentile DECIMAL(5,1),
                prev_day_avg_movement_percentile DECIMAL(5,1),
                daily_update TEXT
            );
        """)

        # Trigger-driven live_symbol_status sync depends on a deterministic uniqueness guarantee per symbol.
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS live_symbol_status_symbol_uniq_all
            ON live_data.live_symbol_status USING btree (symbol);
        """)
        # Trigger-driven sync from live_price_log_1s_* into live_symbol_status (BTC/ETH/SOL/XRP).
        cursor.execute("""
            CREATE OR REPLACE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                sym text := TG_ARGV[0];
            BEGIN
                INSERT INTO live_data.live_symbol_status (
                    symbol, "timestamp", price, one_minute_avg, momentum,
                    delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m,
                    momentum_percentile, momentum_5s_avg, volatility, volatility_percentile, momentum_30s_avg,
                    move_1m, move_2m, move_3m, move_4m, move_15m, move_30m, movement, movement_percentile
                )
                VALUES (
                    sym, NEW.timestamp, NEW.price, NEW.one_minute_avg, NEW.momentum,
                    NEW.delta_1m, NEW.delta_2m, NEW.delta_3m, NEW.delta_4m, NEW.delta_15m, NEW.delta_30m,
                    NEW.momentum_percentile, NEW.momentum_5s_avg, NEW.volatility, NEW.volatility_percentile, NEW.momentum_30s_avg,
                    NEW.move_1m, NEW.move_2m, NEW.move_3m, NEW.move_4m, NEW.move_15m, NEW.move_30m, NEW.movement, NEW.movement_percentile
                )
                ON CONFLICT (symbol) DO UPDATE SET
                    "timestamp" = EXCLUDED."timestamp",
                    price = EXCLUDED.price,
                    one_minute_avg = EXCLUDED.one_minute_avg,
                    momentum = EXCLUDED.momentum,
                    delta_1m = EXCLUDED.delta_1m,
                    delta_2m = EXCLUDED.delta_2m,
                    delta_3m = EXCLUDED.delta_3m,
                    delta_4m = EXCLUDED.delta_4m,
                    delta_15m = EXCLUDED.delta_15m,
                    delta_30m = EXCLUDED.delta_30m,
                    momentum_percentile = EXCLUDED.momentum_percentile,
                    momentum_5s_avg = EXCLUDED.momentum_5s_avg,
                    volatility = EXCLUDED.volatility,
                    volatility_percentile = EXCLUDED.volatility_percentile,
                    momentum_30s_avg = EXCLUDED.momentum_30s_avg,
                    move_1m = EXCLUDED.move_1m,
                    move_2m = EXCLUDED.move_2m,
                    move_3m = EXCLUDED.move_3m,
                    move_4m = EXCLUDED.move_4m,
                    move_15m = EXCLUDED.move_15m,
                    move_30m = EXCLUDED.move_30m,
                    movement = EXCLUDED.movement,
                    movement_percentile = EXCLUDED.movement_percentile;
                RETURN NEW;
            END;
            $$;
        """)
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_price_log_1s_btc') THEN
                    DROP TRIGGER IF EXISTS sync_live_symbol_status_btc_from_price_log ON live_data.live_price_log_1s_btc;
                    CREATE TRIGGER sync_live_symbol_status_btc_from_price_log
                    AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_btc
                    FOR EACH ROW EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log('BTC');
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_price_log_1s_eth') THEN
                    DROP TRIGGER IF EXISTS sync_live_symbol_status_eth_from_price_log ON live_data.live_price_log_1s_eth;
                    CREATE TRIGGER sync_live_symbol_status_eth_from_price_log
                    AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_eth
                    FOR EACH ROW EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log('ETH');
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_price_log_1s_sol') THEN
                    DROP TRIGGER IF EXISTS sync_live_symbol_status_sol_from_price_log ON live_data.live_price_log_1s_sol;
                    CREATE TRIGGER sync_live_symbol_status_sol_from_price_log
                    AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_sol
                    FOR EACH ROW EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log('SOL');
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_price_log_1s_xrp') THEN
                    DROP TRIGGER IF EXISTS sync_live_symbol_status_xrp_from_price_log ON live_data.live_price_log_1s_xrp;
                    CREATE TRIGGER sync_live_symbol_status_xrp_from_price_log
                    AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_xrp
                    FOR EACH ROW EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_from_price_log('XRP');
                END IF;
            END $$;
        """)
        cursor.execute("""
            DO $$
            DECLARE
                col text;
                ty text;
                cols text[] := ARRAY['timestamp','price','one_minute_avg','momentum','delta_1m','delta_2m','delta_3m','delta_4m','delta_15m','delta_30m','momentum_percentile','momentum_5s_avg','volatility','volatility_percentile','momentum_30s_avg','move_1m','move_2m','move_3m','move_4m','move_15m','move_30m','movement','movement_percentile','prev_day_avg_momentum_percentile','prev_day_avg_volatility_percentile','prev_day_avg_movement_percentile','daily_update'];
                types text[] := ARRAY['TEXT','DECIMAL(10,2)','DECIMAL(10,2)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(5,1)','DECIMAL(5,1)','DECIMAL(10,6)','DECIMAL(5,1)','DECIMAL(5,1)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(10,4)','DECIMAL(5,1)','DECIMAL(5,1)','DECIMAL(5,1)','DECIMAL(5,1)','TEXT'];
                i int;
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status') THEN
                    FOR i IN 1..array_length(cols, 1) LOOP
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status' AND column_name = cols[i]) THEN
                            EXECUTE format('ALTER TABLE live_data.live_symbol_status ADD COLUMN %I ' || types[i], cols[i]);
                        END IF;
                    END LOOP;
                END IF;
            END $$;
        """)
        # Migrate daily_update from timestamptz to TEXT (same format as timestamp column)
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status' AND column_name = 'daily_update')
                   AND (SELECT data_type FROM information_schema.columns
                        WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status' AND column_name = 'daily_update') = 'timestamp with time zone' THEN
                    ALTER TABLE live_data.live_symbol_status
                    ALTER COLUMN daily_update TYPE TEXT USING to_char(daily_update AT TIME ZONE 'America/New_York', 'YYYY-MM-DD"T"HH24:MI:SS');
                END IF;
            END $$;
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.btc_price_change (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.eth_price_change (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # New naming convention for price change tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_btc (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_eth (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_sol (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_xrp (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Unified hourly strike table (BTC+ETH rows); same column types as strike_table_15m / migration 20260331_1530.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.strike_table_hourly (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
                symbol VARCHAR(10) NOT NULL,
                exchange VARCHAR(20) NOT NULL DEFAULT 'kalshi',
                market TEXT DEFAULT 'hourly',
                current_price NUMERIC(18,5),
                ttc_hourly INTEGER,
                ttc_15m INTEGER,
                event_ticker VARCHAR(50),
                market_title TEXT,
                strike_tier INTEGER,
                market_status VARCHAR(20),
                strike NUMERIC(18,5),
                buffer NUMERIC(18,5),
                buffer_pct NUMERIC(12,6),
                probability_hourly DECIMAL(5,2),
                probability_15m DECIMAL(5,2),
                yes_ask_dollars TEXT,
                no_ask_dollars TEXT,
                yes_bid_dollars TEXT,
                no_bid_dollars TEXT,
                yes_price_spread NUMERIC(6,4),
                no_price_spread NUMERIC(6,4),
                yes_diff DECIMAL(5,2),
                no_diff DECIMAL(5,2),
                volume_fp TEXT,
                open_interest_fp TEXT,
                ticker VARCHAR(50),
                active_side VARCHAR(10),
                momentum_weighted_score DECIMAL(5,3),
                momentum_percentile DECIMAL(5,1),
                volatility NUMERIC(10,6),
                volatility_percentile NUMERIC(5,1),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                yes_ask_min_15m NUMERIC(18,4),
                yes_ask_max_15m NUMERIC(18,4),
                no_ask_min_15m NUMERIC(18,4),
                no_ask_max_15m NUMERIC(18,4),
                yes_ask_range_15m NUMERIC(18,4),
                no_ask_range_15m NUMERIC(18,4),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            );
        """)

        # Backward-compatible column changes for existing hourly strike tables:
        # - Rename ttc_seconds -> ttc_hourly, probability -> probability_hourly.
        # - Add ttc_15m and probability_15m for simulated 15m cycles (initially NULL).
        cursor.execute("""
            DO $$
            DECLARE
                tbl TEXT;
            BEGIN
                FOR tbl IN SELECT unnest(ARRAY[
                    'strike_table_hourly'
                ]) LOOP
                    -- Rename ttc_seconds to ttc_hourly if old column exists and new one does not
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'ttc_seconds'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'ttc_hourly'
                    ) THEN
                        EXECUTE format('ALTER TABLE live_data.%I RENAME COLUMN ttc_seconds TO ttc_hourly;', tbl);
                    END IF;

                    -- Rename probability to probability_hourly if old column exists and new one does not
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'probability'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'probability_hourly'
                    ) THEN
                        EXECUTE format('ALTER TABLE live_data.%I RENAME COLUMN probability TO probability_hourly;', tbl);
                    END IF;

                    -- Add 15m TTC/probability columns for simulated cycles if missing
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'ttc_15m'
                    ) THEN
                        EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN ttc_15m INTEGER;', tbl);
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'live_data'
                          AND table_name = tbl
                          AND column_name = 'probability_15m'
                    ) THEN
                        EXECUTE format('ALTER TABLE live_data.%I ADD COLUMN probability_15m DECIMAL(5,2);', tbl);
                    END IF;
                END LOOP;
            END
            $$;
        """)

        # Final-quarter (15m window) YES/NO ask extrema in dollars — matches migration
        # 20260328_2115_strike_table_final_quarter_ask_tracking.
        cursor.execute("""
            DO $$
            DECLARE
              t TEXT;
              tables TEXT[] := ARRAY[
                'strike_table_15m',
                'strike_table_hourly'
              ];
            BEGIN
              FOREACH t IN ARRAY tables LOOP
                IF EXISTS (
                  SELECT 1 FROM information_schema.tables
                  WHERE table_schema = 'live_data' AND table_name = t
                ) THEN
                  EXECUTE format(
                    'ALTER TABLE live_data.%I
                       ADD COLUMN IF NOT EXISTS yes_ask_min_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS yes_ask_max_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS no_ask_min_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS no_ask_max_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS yes_ask_range_15m NUMERIC(18,4),
                       ADD COLUMN IF NOT EXISTS no_ask_range_15m NUMERIC(18,4);',
                    t
                  );
                END IF;
              END LOOP;
            END
            $$;
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system.health_status (
                id SERIAL PRIMARY KEY,
                service_name VARCHAR(100),
                status VARCHAR(50),
                last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                details JSONB
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system.installation_access_log (
                id SERIAL PRIMARY KEY,
                installer_user_id VARCHAR(100) NOT NULL,
                installer_name VARCHAR(200),
                installer_email VARCHAR(200),
                installer_ip_address INET,
                connection_start TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                connection_end TIMESTAMP WITH TIME ZONE,
                schemas_accessed TEXT[],
                tables_cloned INTEGER,
                total_rows_cloned BIGINT,
                clone_duration_seconds INTEGER,
                status VARCHAR(50) DEFAULT 'in_progress',
                error_message TEXT,
                user_agent TEXT,
                installation_package_version VARCHAR(50),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        
        # Create historical_data schema and tables
        cursor.execute("CREATE SCHEMA IF NOT EXISTS historical_data;")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_data.btc_price_history (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                open DECIMAL(15,2),
                high DECIMAL(15,2),
                low DECIMAL(15,2),
                close DECIMAL(15,2),
                volume DECIMAL(20,8),
                momentum DECIMAL(10,4),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_data.eth_price_history (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                open DECIMAL(15,2),
                high DECIMAL(15,2),
                low DECIMAL(15,2),
                close DECIMAL(15,2),
                volume DECIMAL(20,8),
                momentum DECIMAL(10,4),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        
        # Ensure loss_prevention_toggle column exists for monitor_list_0001
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'loss_prevention_toggle'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN loss_prevention_toggle BOOLEAN DEFAULT TRUE;
                    UPDATE users.monitor_list_0001 SET loss_prevention_toggle = TRUE WHERE loss_prevention_toggle IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'max_price_spread'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN max_price_spread NUMERIC(6,4) DEFAULT 0.0300;
                    UPDATE users.monitor_list_0001 SET max_price_spread = 0.0300 WHERE max_price_spread IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'paper_trade'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE;
                    UPDATE users.monitor_list_0001 SET paper_trade = FALSE WHERE paper_trade IS NULL;
                END IF;

                -- Regime Monitor settings columns (optional feature toggle + window)
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'regime_monitor_enabled'
                ) THEN
                    ALTER TABLE users.monitor_list_0001
                    ADD COLUMN regime_monitor_enabled BOOLEAN DEFAULT FALSE;
                    UPDATE users.monitor_list_0001
                    SET regime_monitor_enabled = FALSE
                    WHERE regime_monitor_enabled IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'regime_window'
                ) THEN
                    ALTER TABLE users.monitor_list_0001
                    ADD COLUMN regime_window TEXT DEFAULT '30d';
                    UPDATE users.monitor_list_0001
                    SET regime_window = '30d'
                    WHERE regime_window IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'prob_adj'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN prob_adj NUMERIC(5,2) DEFAULT 5.00;
                    UPDATE users.monitor_list_0001 SET prob_adj = 5.00 WHERE prob_adj IS NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'min_cooldown_timer'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN min_cooldown_timer INTEGER DEFAULT 300;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'max_cooldown_timer'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN max_cooldown_timer INTEGER DEFAULT 3300;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'min_ask_range'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN min_ask_range NUMERIC(18,4);
                END IF;
            END
            $$;
        """)
        
        # Add market column to all monitor_list tables (hourly vs 15m); backfill existing rows to 'hourly'
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'users' 
            AND table_name LIKE 'monitor_list_%'
            ORDER BY table_name
        """)
        monitor_list_tables_market = [row[0] for row in cursor.fetchall()]
        for table_name in monitor_list_tables_market:
            cursor.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'market'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN market TEXT DEFAULT %L', '{table_name}', 'hourly');
                        EXECUTE format('UPDATE users.%I SET market = %L WHERE market IS NULL', '{table_name}', 'hourly');
                    END IF;
                END
                $$;
            """)
        
        # Create strategy_list_0001 table with all default settings columns (matching monitor_list structure)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users.strategy_list_0001 (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated TIMESTAMP,
                -- Strategy default settings (matching monitor_list columns, excluding monitor-specific ones)
                win_streak_threshold INTEGER DEFAULT 22,
                loss_prevention VARCHAR(50) DEFAULT 'none',
                loss_prevention_toggle BOOLEAN DEFAULT TRUE,
                performance_based_allocation BOOLEAN NOT NULL DEFAULT FALSE,
                max_price_spread NUMERIC(6,4) DEFAULT 0.0300,
                paper_trade BOOLEAN DEFAULT FALSE,
                prob_adj NUMERIC(5,2) DEFAULT 5.00,
                -- Position sizing defaults
                position_size INTEGER DEFAULT 1,
                position_type VARCHAR(20) DEFAULT 'percent',
                multiplier NUMERIC(3,2) DEFAULT 1.00,
                -- Auto entry settings
                min_probability NUMERIC(5,2),
                max_probability NUMERIC(5,2),
                min_differential NUMERIC(5,2) DEFAULT 0.25,
                max_differential NUMERIC(5,2),
                min_time INTEGER,
                max_time INTEGER,
                allow_re_entry BOOLEAN DEFAULT FALSE,
                spike_alert_enabled BOOLEAN DEFAULT FALSE,
                spike_alert_momentum_threshold INTEGER,
                spike_alert_cooldown_threshold INTEGER,
                spike_alert_cooldown_minutes INTEGER,
                current_probability INTEGER,
                min_ttc_seconds INTEGER,
                momentum_spike_enabled BOOLEAN DEFAULT FALSE,
                momentum_spike_threshold INTEGER,
                verification_period_enabled BOOLEAN DEFAULT FALSE,
                verification_period_seconds INTEGER,
                min_volume INTEGER,
                momentum_scalp_entry_threshold NUMERIC(5,2),
                momentum_scalp_trailing_stop_amount NUMERIC(5,2) DEFAULT 0.10,
                momentum_scalp_profit_target NUMERIC(5,2) DEFAULT 0.99,
                min_ask NUMERIC(6,4) DEFAULT 0.0000,
                max_ask NUMERIC(6,4) DEFAULT 0.9800,
                max_profit NUMERIC(6,4) DEFAULT 0.9900,
                stop_loss_price NUMERIC(6,4) DEFAULT 0.0000,
                min_ask_range NUMERIC(18,4),
                min_cooldown_timer INTEGER DEFAULT 300,
                max_cooldown_timer INTEGER DEFAULT 3300
            );
        """)
        
        # Add any missing columns to strategy_list_0001 (for existing tables)
        cursor.execute("""
            DO $$
            BEGIN
                -- Add columns that might not exist in older versions
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'updated'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN updated TIMESTAMP;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'win_streak_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN win_streak_threshold INTEGER DEFAULT 22;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'loss_prevention'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN loss_prevention VARCHAR(50) DEFAULT 'none';
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'loss_prevention_toggle'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN loss_prevention_toggle BOOLEAN DEFAULT TRUE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'performance_based_allocation'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN performance_based_allocation BOOLEAN NOT NULL DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_price_spread'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_price_spread NUMERIC(6,4) DEFAULT 0.0300;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'paper_trade'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'prob_adj'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN prob_adj NUMERIC(5,2) DEFAULT 5.00;
                END IF;
                
                -- Auto entry settings columns
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_probability'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_probability NUMERIC(5,2);
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_probability'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_probability NUMERIC(5,2);
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_differential'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_differential NUMERIC(5,2) DEFAULT 0.25;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_differential'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_differential NUMERIC(5,2);
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_time'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_time INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_time'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_time INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'allow_re_entry'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN allow_re_entry BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'spike_alert_enabled'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN spike_alert_enabled BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'spike_alert_momentum_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN spike_alert_momentum_threshold INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'spike_alert_cooldown_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN spike_alert_cooldown_threshold INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'spike_alert_cooldown_minutes'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN spike_alert_cooldown_minutes INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'current_probability'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN current_probability INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_ttc_seconds'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_ttc_seconds INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_spike_enabled'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_spike_enabled BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_spike_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_spike_threshold INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'verification_period_enabled'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN verification_period_enabled BOOLEAN DEFAULT FALSE;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'verification_period_seconds'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN verification_period_seconds INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_volume'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_volume INTEGER;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_scalp_entry_threshold'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_scalp_entry_threshold NUMERIC(5,2);
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_scalp_trailing_stop_amount'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_scalp_trailing_stop_amount NUMERIC(5,2) DEFAULT 0.10;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'momentum_scalp_profit_target'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN momentum_scalp_profit_target NUMERIC(5,2) DEFAULT 0.99;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_ask'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_ask NUMERIC(6,4) DEFAULT 0.0000;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_ask'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_ask NUMERIC(6,4) DEFAULT 0.9800;
                END IF;
                
                -- Position sizing defaults
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'position_size'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN position_size INTEGER DEFAULT 1;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'position_type'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN position_type VARCHAR(20) DEFAULT 'percent';
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'multiplier'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN multiplier NUMERIC(3,2) DEFAULT 1.00;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_profit'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_profit NUMERIC(6,4) DEFAULT 0.9900;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'stop_loss_price'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN stop_loss_price NUMERIC(6,4) DEFAULT 0.0000;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_ask_range'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_ask_range NUMERIC(18,4);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'min_cooldown_timer'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN min_cooldown_timer INTEGER DEFAULT 300;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'strategy_list_0001'
                      AND column_name = 'max_cooldown_timer'
                ) THEN
                    ALTER TABLE users.strategy_list_0001 ADD COLUMN max_cooldown_timer INTEGER DEFAULT 3300;
                END IF;
            END
            $$;
        """)
        
        # Add paper_trade column to all monitor_list tables (not just 0001)
        # Find all monitor_list tables and add the column if it doesn't exist
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'users' 
            AND table_name LIKE 'monitor_list_%'
            ORDER BY table_name
        """)
        monitor_list_tables = [row[0] for row in cursor.fetchall()]
        
        for table_name in monitor_list_tables:
            cursor.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'paper_trade'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN paper_trade BOOLEAN DEFAULT FALSE', '{table_name}');
                        EXECUTE format('UPDATE users.%I SET paper_trade = FALSE WHERE paper_trade IS NULL', '{table_name}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'test_filter'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN test_filter BOOLEAN DEFAULT FALSE', '{table_name}');
                        EXECUTE format('UPDATE users.%I SET test_filter = FALSE WHERE test_filter IS NULL', '{table_name}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'regime_monitor_enabled'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN regime_monitor_enabled BOOLEAN DEFAULT FALSE', '{table_name}');
                        EXECUTE format('UPDATE users.%I SET regime_monitor_enabled = FALSE WHERE regime_monitor_enabled IS NULL', '{table_name}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'regime_window'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN regime_window TEXT DEFAULT %L', '{table_name}', '30d');
                        EXECUTE format('UPDATE users.%I SET regime_window = %L WHERE regime_window IS NULL', '{table_name}', '30d');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'prob_adj'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN prob_adj NUMERIC(5,2) DEFAULT 5.00', '{table_name}');
                        EXECUTE format('UPDATE users.%I SET prob_adj = 5.00 WHERE prob_adj IS NULL', '{table_name}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'stop_loss_price'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN stop_loss_price NUMERIC(6,4) DEFAULT 0.0000', '{table_name}');
                        EXECUTE format('UPDATE users.%I SET stop_loss_price = 0.0000 WHERE stop_loss_price IS NULL', '{table_name}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'flip_sell_prob'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN flip_sell_prob BOOLEAN NOT NULL DEFAULT FALSE', '{table_name}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'flip_sell_floor'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN flip_sell_floor BOOLEAN NOT NULL DEFAULT FALSE', '{table_name}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'flip_sell_prob_mult'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN flip_sell_prob_mult VARCHAR(32)', '{table_name}');
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'users'
                          AND table_name = '{table_name}'
                          AND column_name = 'flip_sell_floor_mult'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN flip_sell_floor_mult VARCHAR(32)', '{table_name}');
                    END IF;
                END
                $$;
            """)
        
        # Grant privileges
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA users TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA live_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA system TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA historical_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA backtest TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA archive TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA users TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA live_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA system TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA historical_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA backtest TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA users TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA live_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA system TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA historical_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA backtest TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA archive TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA archive TO rec_io_user;")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Database initialized successfully")
        return True, "Database initialized successfully"
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return False, f"Database initialization error: {e}"
