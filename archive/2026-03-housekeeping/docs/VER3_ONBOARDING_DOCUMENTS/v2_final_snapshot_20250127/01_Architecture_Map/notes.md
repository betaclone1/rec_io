# REC.IO v2 System Architecture - Final Snapshot

## System Overview

The REC.IO Trading System v2 is a comprehensive automated trading platform with real-time market data processing, trade execution, and portfolio management capabilities.

### Core Architecture Components

#### 1. Service Layer Architecture
- **Main Application** (Port 3000): Web interface and API gateway
- **Trade Manager** (Port 4000): Trade lifecycle management and database operations
- **Trade Executor** (Port 8001): Order execution and market interaction
- **Active Trade Supervisor** (Port 8007): Real-time trade monitoring and status updates
- **Auto Entry Supervisor** (Port 8009): Automated entry signals and indicators

#### 2. Watchdog Services
- **BTC Price Watchdog** (Port 8002): Bitcoin price monitoring and momentum calculation
- **Database Poller** (Port 8003): Real-time database change monitoring
- **Kalshi Account Sync** (Port 8004): Account synchronization and position tracking
- **Kalshi API Watchdog** (Port 8005): API health monitoring and market data collection
- **Unified Production Coordinator** (Port 8010): Data production and coordination

#### 3. Data Layer
- **PostgreSQL Database**: Primary data store for trades, positions, and market data
- **SQLite Databases**: Local price history and active trade monitoring
- **File-based Storage**: JSON snapshots and historical data archives

### Service Flow Architecture

#### Trade Execution Flow
1. **Signal Generation**: Auto Entry Supervisor generates trading signals
2. **Trade Creation**: Trade Manager creates trade records in PostgreSQL
3. **Execution**: Trade Executor places orders via Kalshi API
4. **Monitoring**: Active Trade Supervisor tracks trade status
5. **Settlement**: System monitors for trade expiration and settlement

#### Data Flow
1. **Market Data**: Kalshi API Watchdog collects real-time market data
2. **Price Data**: BTC Price Watchdog monitors Bitcoin prices
3. **Account Data**: Kalshi Account Sync updates positions and balances
4. **Database Updates**: All services write to centralized PostgreSQL database
5. **Frontend Updates**: WebSocket connections push real-time updates

### Port Management System

#### Universal Port Configuration
- **Centralized Control**: All ports managed via `MASTER_PORT_MANIFEST.json`
- **Dynamic Assignment**: Services retrieve ports from centralized system
- **Environment Agnostic**: Same configuration works across environments
- **Conflict Avoidance**: Safe port ranges avoiding macOS system services

#### Port Assignments
```
Core Services:
- main_app: 3000
- trade_manager: 4000
- trade_executor: 8001
- active_trade_supervisor: 8007
- auto_entry_supervisor: 8009

Watchdog Services:
- btc_price_watchdog: 8002
- db_poller: 8003
- kalshi_account_sync: 8004
- kalshi_api_watchdog: 8005
- unified_production_coordinator: 8010
```

### Process Management

#### Supervisor Configuration
- **Centralized Control**: All services managed by supervisord
- **Auto-restart**: Services automatically restart on failure
- **Log Management**: Centralized logging with rotation
- **Environment Variables**: Consistent environment across all services

#### Service Dependencies
1. **Database Layer**: PostgreSQL must be running
2. **Core Services**: Trade Manager and Executor are primary
3. **Watchdog Services**: Monitor and maintain system health
4. **Frontend**: Web interface connects to all services

### Legacy Components Still in Use

#### Temporary/Legacy Components
- **Symbol Price Watchdog**: Legacy price monitoring (BTC/ETH)
- **Old Scripts**: Some archived scripts still referenced
- **SQLite Fallbacks**: Local databases for specific functions
- **File-based Caching**: JSON files for data snapshots

#### Migration Status
- **PostgreSQL Migration**: 95% complete
- **Port System**: 100% centralized
- **Path System**: 100% unified
- **Authentication**: 100% implemented

### System Health Monitoring

#### Health Check Endpoints
- All services provide `/health` endpoints
- System Monitor aggregates health data
- Cascading Failure Detector monitors dependencies
- Real-time status reporting via WebSocket

#### Performance Metrics
- **Response Times**: Sub-second for most operations
- **Database Performance**: Optimized with proper indexing
- **Memory Usage**: Efficient caching and cleanup
- **CPU Usage**: Minimal impact on system resources

### Security Architecture

#### Authentication System
- **Login Page**: Secure authentication gateway
- **Token Management**: Cryptographically secure sessions
- **Device Remembering**: Long-term device tokens
- **Local Development**: Bypass for development workflow

#### Credential Management
- **User-based Storage**: Credentials in user-specific directories
- **Environment Variables**: Sensitive data via environment
- **File Permissions**: Secure credential file handling
- **No Hardcoded Secrets**: All secrets externalized

### Frontend Architecture

#### Web Interface
- **Single Page Application**: Modern responsive design
- **Real-time Updates**: WebSocket connections for live data
- **Mobile Support**: Responsive design for mobile devices
- **iOS App**: Native iOS webview application

#### Component Structure
- **Trade Monitor**: Real-time trade tracking
- **Trade History**: Historical trade analysis
- **Account Manager**: Portfolio and position management
- **Settings**: System configuration interface

### Data Architecture

#### Database Schema
- **User-specific Tables**: All data scoped to user_0001
- **Trade Management**: Complete trade lifecycle tracking
- **Market Data**: Real-time price and market information
- **Account Data**: Positions, balances, and settlements

#### File Organization
- **Unified Path System**: Centralized path management
- **User Data Isolation**: User-specific data directories
- **Historical Archives**: Long-term data storage
- **Live Data**: Real-time market data files

### Deployment Architecture

#### Current Deployment
- **Local Development**: Supervisor-based process management
- **Virtual Environment**: Python venv for dependencies
- **Static File Serving**: Direct file serving for frontend
- **Database**: Local PostgreSQL instance

#### Cloud Deployment Ready
- **Environment Variables**: All configuration externalized
- **Port Management**: Universal port system
- **Authentication**: Production-ready auth system
- **Logging**: Comprehensive logging system

### Technical Debt and Limitations

#### Known Issues
- **Legacy Scripts**: Some old scripts still in supervisor config
- **Hardcoded Values**: Some environment-specific values
- **File Dependencies**: Some services depend on file existence
- **Error Handling**: Inconsistent error handling patterns

#### Performance Considerations
- **Database Connections**: Connection pooling could be improved
- **Memory Usage**: Some services could optimize memory usage
- **Caching**: Redis integration planned for v3
- **Scalability**: Current architecture suitable for single-user deployment

### v3 Migration Path

#### Planned Improvements
- **Redis Integration**: Centralized caching and pub/sub
- **Microservices**: Service decomposition for scalability
- **Containerization**: Docker deployment for cloud
- **API Gateway**: Centralized API management
- **Monitoring**: Advanced monitoring and alerting

#### Backward Compatibility
- **Data Migration**: PostgreSQL schema will be preserved
- **API Compatibility**: Core APIs will remain stable
- **Configuration**: Universal config system will be extended
- **Authentication**: Current auth system will be enhanced
