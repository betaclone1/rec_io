# Database Schema Mapping Analysis

## Overview
This document analyzes the differences between SQLite and PostgreSQL schemas and provides the mapping strategy for the migration.

## SQLite vs PostgreSQL Schema Comparison

### Trades Table Schema Mapping

#### SQLite Schema (Current)
```sql
CREATE TABLE "trades" (
    "id" INTEGER,
    "status" TEXT NOT NULL,
    "date" TEXT NOT NULL,
    "time" TEXT NOT NULL,
    "symbol" TEXT DEFAULT 'BTC',
    "market" TEXT DEFAULT 'Kalshi',
    "trade_strategy" TEXT DEFAULT 'Hourly HTC',
    "contract" TEXT NOT NULL,
    "strike" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "prob" REAL DEFAULT NULL,
    "diff" TEXT DEFAULT NULL,
    "buy_price" REAL NOT NULL,
    "position" INTEGER NOT NULL,
    "sell_price" REAL,
    "closed_at" TEXT,
    "fees" INTEGER,
    "pnl" INTEGER,
    "symbol_open" INTEGER,
    "symbol_close" INTEGER,
    "momentum" INTEGER,
    "volatility" INTEGER,
    "win_loss" TEXT,
    "ticker" TEXT,
    "ticket_id" INTEGER,
    "market_id" TEXT DEFAULT 'BTC-USD',
    "momentum_delta" REAL DEFAULT NULL,
    "entry_method" TEXT DEFAULT 'manual',
    "close_method" TEXT DEFAULT NULL,
    PRIMARY KEY("id" AUTOINCREMENT)
);
```

#### PostgreSQL Schema (Existing)
```sql
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    status VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    time TIME WITHOUT TIME ZONE NOT NULL,
    symbol VARCHAR(20) DEFAULT 'BTC',
    market VARCHAR(50) DEFAULT 'Kalshi',
    trade_strategy VARCHAR(50) DEFAULT 'Hourly HTC',
    contract VARCHAR(100) NOT NULL,
    strike VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    prob NUMERIC(10,4),
    diff VARCHAR(50),
    buy_price NUMERIC(10,4) NOT NULL,
    position INTEGER NOT NULL,
    sell_price NUMERIC(10,4),
    closed_at TIMESTAMP WITH TIME ZONE,
    fees INTEGER,
    pnl INTEGER,
    symbol_open INTEGER,
    symbol_close INTEGER,
    momentum INTEGER,
    volatility INTEGER,
    win_loss VARCHAR(1),
    ticker VARCHAR(50),
    ticket_id VARCHAR(100),
    market_id VARCHAR(50) DEFAULT 'BTC-USD',
    momentum_delta NUMERIC(10,4),
    entry_method VARCHAR(20) DEFAULT 'manual',
    close_method VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Active Trades Table Schema Mapping

#### SQLite Schema (Current)
```sql
CREATE TABLE active_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    ticket_id TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    strike TEXT NOT NULL,
    side TEXT NOT NULL,
    buy_price REAL NOT NULL,
    position INTEGER NOT NULL,
    contract TEXT,
    ticker TEXT,
    symbol TEXT,
    market TEXT,
    trade_strategy TEXT,
    symbol_open REAL,
    momentum REAL,
    prob REAL,
    fees REAL,
    diff TEXT,
    current_symbol_price REAL DEFAULT NULL,
    current_probability REAL DEFAULT NULL,
    buffer_from_entry REAL DEFAULT NULL,
    time_since_entry INTEGER DEFAULT NULL,
    current_close_price REAL DEFAULT NULL,
    current_pnl TEXT DEFAULT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active',
    notes TEXT DEFAULT NULL
);
```

#### PostgreSQL Schema (Existing)
```sql
CREATE TABLE active_trades (
    id SERIAL PRIMARY KEY,
    trade_id INTEGER NOT NULL,
    ticket_id VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    time TIME WITHOUT TIME ZONE NOT NULL,
    strike VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    buy_price NUMERIC(10,4) NOT NULL,
    position INTEGER NOT NULL,
    contract VARCHAR(100),
    ticker VARCHAR(50),
    symbol VARCHAR(20),
    market VARCHAR(50),
    trade_strategy VARCHAR(50),
    symbol_open NUMERIC(10,2),
    momentum VARCHAR(20),
    prob NUMERIC(10,4),
    fees NUMERIC(10,4),
    diff VARCHAR(20),
    current_symbol_price NUMERIC(10,2),
    current_probability NUMERIC(10,4),
    buffer_from_entry NUMERIC(10,4),
    time_since_entry INTEGER,
    current_close_price NUMERIC(10,4),
    current_pnl VARCHAR(20),
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'active',
    notes TEXT
);
```

## Data Type Mapping

### SQLite to PostgreSQL Type Conversions

| SQLite Type | PostgreSQL Type | Notes |
|-------------|-----------------|-------|
| INTEGER | INTEGER | Direct mapping |
| REAL | NUMERIC(10,4) | Precision for financial data |
| TEXT | VARCHAR(n) | Specify length for performance |
| TIMESTAMP | TIMESTAMP WITH TIME ZONE | Timezone awareness |
| AUTOINCREMENT | SERIAL | Auto-incrementing primary key |

### Key Differences Identified

1. **Date/Time Handling**
   - SQLite: TEXT fields for date/time
   - PostgreSQL: DATE, TIME, TIMESTAMP WITH TIME ZONE

2. **Numeric Precision**
   - SQLite: REAL (floating point)
   - PostgreSQL: NUMERIC(10,4) (fixed precision)

3. **String Length**
   - SQLite: TEXT (unlimited)
   - PostgreSQL: VARCHAR(n) (specified length)

4. **Primary Keys**
   - SQLite: INTEGER AUTOINCREMENT
   - PostgreSQL: SERIAL

5. **Additional Columns**
   - PostgreSQL has `created_at` and `updated_at` timestamps
   - PostgreSQL has additional indexes

## Migration Strategy

### Phase 1: Schema Alignment
1. **Update database abstraction layer** to match existing PostgreSQL schemas
2. **Create data type conversion functions** for SQLite to PostgreSQL migration
3. **Handle date/time conversions** from TEXT to proper PostgreSQL types
4. **Manage numeric precision** for financial data

### Phase 2: Data Migration
1. **Export SQLite data** with proper type handling
2. **Transform data** during import to PostgreSQL
3. **Validate data integrity** after migration
4. **Test all queries** with new data types

### Phase 3: Application Updates
1. **Update all database queries** to use new abstraction layer
2. **Handle date/time formatting** in application code
3. **Update numeric precision** handling
4. **Test all functionality** with PostgreSQL

## Critical Considerations

### Data Integrity
- **Date/time conversions** must preserve timezone information
- **Numeric precision** must maintain financial accuracy
- **String length limits** must not truncate important data

### Performance
- **PostgreSQL indexes** are more sophisticated than SQLite
- **Connection pooling** is essential for production
- **Query optimization** may be needed for complex operations

### Compatibility
- **Application code** must handle new data types
- **Frontend formatting** may need updates for new precision
- **API responses** must maintain backward compatibility

## Next Steps

1. **Update database abstraction layer** to match existing PostgreSQL schemas
2. **Create data migration scripts** with proper type conversions
3. **Test data migration** with sample data
4. **Update application code** to handle new data types
5. **Comprehensive testing** of all database operations 