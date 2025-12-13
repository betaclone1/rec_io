"""
Centralized Database Configuration
Provides environment variable-based configuration for PostgreSQL connections.
"""

import os

def get_database_config():
    """Get database configuration from environment variables with defaults."""
    return {
        'host': os.getenv('DB_HOST', 'localhost'),
        'database': os.getenv('DB_NAME', 'rec_io_db'),
        'user': os.getenv('DB_USER', 'rec_io_user'),
        'password': os.getenv('DB_PASSWORD', 'rec_io_password'),
        'port': int(os.getenv('DB_PORT', '5432'))
    }

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
        
        # Create core tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users.trades_0001 (
                id SERIAL PRIMARY KEY,
                status VARCHAR(50) DEFAULT 'pending',
                date DATE,
                time TIME,
                symbol VARCHAR(50),
                market VARCHAR(50),
                trade_strategy VARCHAR(100),
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
                symbol_open DECIMAL(10,4),
                symbol_close DECIMAL(10,4),
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
                monitor VARCHAR(50),
                hour_idx INTEGER,
                weekly_cycle INTEGER,
                order_id_open TEXT,
                order_id_close TEXT,
                high_price DECIMAL(10,4),
                low_price DECIMAL(10,4),
                loss_prevention BOOLEAN DEFAULT FALSE,
                multiplier DECIMAL(10,2),
                price_spread DECIMAL(6,4),
                paper_trade BOOLEAN DEFAULT FALSE,
                cooldown_timer INTEGER,
                monitor_confirmed BOOLEAN DEFAULT FALSE,
                cycle_win_loss TEXT,
                cycle_pnl REAL,
                cycle_ret_pct REAL
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
                    ALTER TABLE users.trades_0001 ADD COLUMN monitor_confirmed BOOLEAN DEFAULT FALSE;
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
            END
            $$;
        """)
        
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
                prob_adj NUMERIC(5,2) DEFAULT 5.00,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.eth_price_log (
                id SERIAL PRIMARY KEY,
                price DECIMAL(15,2),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                delta_30m DECIMAL(10,4)
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
                delta_30m DECIMAL(10,4)
            );
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
        
        # New naming convention for strike table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.strike_table_btc (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
                symbol VARCHAR(10),
                current_price DECIMAL(10,2),
                ttc_seconds INTEGER,
                broker VARCHAR(20),
                event_ticker VARCHAR(50),
                market_title TEXT,
                strike_tier INTEGER,
                market_status VARCHAR(20),
                strike INTEGER,
                buffer DECIMAL(10,2),
                buffer_pct DECIMAL(5,2),
                probability DECIMAL(5,2),
                yes_ask DECIMAL(5,2),
                no_ask DECIMAL(5,2),
                yes_diff DECIMAL(5,2),
                no_diff DECIMAL(5,2),
                volume INTEGER,
                ticker VARCHAR(50),
                active_side VARCHAR(10),
                momentum_weighted_score DECIMAL(5,3),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            );
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

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'users'
                      AND table_name = 'monitor_list_0001'
                      AND column_name = 'prob_adj'
                ) THEN
                    ALTER TABLE users.monitor_list_0001 ADD COLUMN prob_adj NUMERIC(5,2) DEFAULT 5.00;
                    UPDATE users.monitor_list_0001 SET prob_adj = 5.00 WHERE prob_adj IS NULL;
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
                          AND column_name = 'prob_adj'
                    ) THEN
                        EXECUTE format('ALTER TABLE users.%I ADD COLUMN prob_adj NUMERIC(5,2) DEFAULT 5.00', '{table_name}');
                        EXECUTE format('UPDATE users.%I SET prob_adj = 5.00 WHERE prob_adj IS NULL', '{table_name}');
                    END IF;
                END
                $$;
            """)
        
        # Grant privileges
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA users TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA live_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA system TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON SCHEMA historical_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA users TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA live_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA system TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA historical_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA users TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA live_data TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA system TO rec_io_user;")
        cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA historical_data TO rec_io_user;")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Database initialized successfully")
        return True, "Database initialized successfully"
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return False, f"Database initialization error: {e}"
