# REC.IO Installation Package Proposal

## Executive Summary

This proposal outlines the creation of a comprehensive installation package that will allow new users to clone the git repository and have a fully functional REC.IO trading system running within minutes. The installation will be guided, secure, and handle all system dependencies automatically.

## Current Repository Audit Results

### ✅ WHAT IS INCLUDED IN GIT REPOSITORY

#### Core System Files
- **Backend Application**: Complete Python trading system (`backend/`)
  - Main application (`main.py`)
  - All trading services and supervisors
  - Core configuration system
  - Database schema definitions
  - Port management system
  - Health monitoring

- **Frontend Application**: Complete web interface (`frontend/`)
  - Main dashboard (`index.html`)
  - Login system (`login.html`)
  - Mobile-responsive design
  - All JavaScript, CSS, and assets

- **Scripts**: Comprehensive management scripts (`scripts/`)
  - `MASTER_RESTART.sh` - Primary system control
  - `simple_deploy.sh` - Deployment reference
  - Database setup and migration scripts
  - User setup scripts
  - Supervisor configuration generators

- **Configuration**: System configuration files
  - `backend/core/config/` - All configuration templates
  - `MASTER_PORT_MANIFEST.json` - Port assignments
  - `config.default.json` - Default settings
  - Database schema definitions

- **Dependencies**: Package requirements
  - `requirements.txt` - Python dependencies
  - `requirements-core.txt` - Core dependencies

#### Data Structure (Empty but Ready)
- **User Directory Structure**: `backend/data/users/user_0001/`
  - Credentials directories (empty)
  - Trade history directories (empty)
  - Account directories (empty)
  - Monitor directories (empty)

- **Live Data Structure**: `backend/data/live_data/`
  - Market data directories (empty)
  - Price history directories (empty)
  - Strike table directories (empty)

- **Historical Data**: `backend/data/historical_data/`
  - Test data only (empty production data)

#### Documentation
- `README.md` - System overview
- `QUICK_INSTALL_GUIDE.md` - Installation guide
- `DEPLOYMENT_NOTE_FOR_AI.md` - Deployment notes
- Various deployment and setup guides

### ❌ WHAT IS NOT INCLUDED IN GIT REPOSITORY

#### User-Specific Data (Excluded for Security)
- **User Credentials**: Kalshi API credentials
- **User Information**: Personal user data
- **Trade History**: Actual trade records
- **Account Data**: Account balances and positions
- **Auth Tokens**: Session and device tokens

#### Live Data (Excluded for Size/Privacy)
- **Market Data**: Real-time price feeds
- **Historical Data**: Large CSV files with price history
- **Strike Tables**: Live market strike data
- **Analytics Data**: Computed indicators and metrics

#### System Runtime Data (Excluded)
- **Log Files**: Application logs
- **Database Files**: SQLite/PostgreSQL data files
- **Cache Files**: Temporary system data
- **Backup Files**: System backups

## Proposed Installation Package Design

### One-Command Installation Experience

The installation will be triggered by a single command after cloning:

```bash
# Clone the repository
git clone https://github.com/your-org/rec-io-server.git
cd rec-io-server

# Run the complete installation
./install.sh
```

### Phase 1: Pre-Installation Validation
1. **System Requirements Check**
   - Python 3.8+ verification
   - Operating system compatibility
   - Available disk space (10GB minimum)
   - Network connectivity test
   - Port availability check
   - Detect operating system and package manager

2. **Repository Validation**
   - Verify all required files are present
   - Check file permissions
   - Validate configuration templates
   - Confirm directory structure

### Phase 2: Interactive User Information Collection
1. **Basic User Information**
   - User ID (auto-generated or user-specified)
   - Full name
   - Email address
   - Phone number (optional)
   - Password (for system access)

2. **Kalshi Credentials** (Required for Trading)
   - Kalshi email address
   - Kalshi API key
   - Account type (demo/prod) selection
   - Credential validation test

3. **Installation Preferences**
   - Confirm system data cloning (analytics, historical_data, live_data)
   - Choose installation location
   - Set system access preferences

### Phase 3: Automated System Dependencies Installation
1. **Operating System Dependencies**
   - **macOS**: Homebrew, Python3, PostgreSQL, Supervisor
   - **Ubuntu/Debian**: apt packages for Python3, PostgreSQL, Supervisor
   - **CentOS/RHEL**: yum packages for Python3, PostgreSQL, Supervisor

2. **Python Environment Setup**
   - Virtual environment creation
   - Python package installation from `requirements.txt`
   - Dependency verification
   - Environment activation

### Phase 4: Database Setup
1. **PostgreSQL Installation**
   - Database server installation
   - Service configuration and startup
   - Database user creation (`rec_io_user`)
   - Database creation (`rec_io_db`)

2. **Schema Initialization**
   - Execute `backend/core/config/database.py` schema creation
   - Create all required tables:
     - `users.trades_0001`
     - `users.active_trades_0001`
     - `users.trade_preferences_0001`
     - `live_data.*` tables
     - `system.health_status`
   - Grant proper permissions

### Phase 4.5: Clone System Data (Optional)
1. **Remote Database Connection**
   - Connect using provided read-only credentials
   - Verify connection and permissions
   - Validate security (read-only access to 3 schemas only)
   - Test schema accessibility
   - **Log installation access** in system.installation_access_log

2. **Data Cloning**
   - Clone analytics schema (125+ tables) - Backtesting data
   - Clone historical_data schema (2+ tables) - Price history
   - Clone live_data schema (10+ tables) - Market data
   - Verify data integrity after cloning
   - **Track progress** (tables cloned, rows transferred, duration)

3. **Connection Management**
   - Temporary read-only connection only
   - Automatic connection termination after cloning
   - No persistent connection to remote system
   - **Complete audit trail** with installer details and timestamps

### Phase 5: User Profile Creation
1. **User Directory Setup**
   - Create user-specific directories
   - Set proper file permissions (700 for credentials)
   - Generate `user_info.json` with collected data

2. **Credential Storage**
   - Create Kalshi credential files
   - Store in `backend/data/users/{user_id}/credentials/kalshi-credentials/{prod|demo}/`
   - Set secure file permissions

3. **Default Preferences**
   - Create default trading preferences
   - Set up basic account configuration
   - Initialize empty trade history structure

### Phase 6: System Configuration
1. **Environment Configuration**
   - Create `.env` file with database connection
   - Set system host configurations
   - Configure port assignments

2. **Supervisor Configuration**
   - Generate `supervisord.conf` using existing scripts
   - Configure all service processes
   - Set up logging and monitoring

3. **Port Management**
   - Verify port availability using `MASTER_PORT_MANIFEST.json`
   - Configure firewall rules if needed
   - Test port accessibility

### Phase 7: System Startup and Verification
1. **Service Initialization**
   - Run `MASTER_RESTART.sh` to start all services
   - Monitor startup process
   - Handle any startup errors

2. **System Verification**
   - Test database connectivity
   - Verify all services are running
   - Check web interface accessibility
   - Test Kalshi API connectivity
   - Validate user authentication

3. **Final Configuration**
   - Display system access information
   - Provide login credentials
   - Show frontend URL
   - Display service status

### Phase 8: Installation Completion
1. **Success Verification**
   - Confirm all services operational
   - Verify data integrity
   - Test user login functionality
   - Generate installation completion report

2. **User Delivery**
   - Display system URL and login credentials
   - Provide system status summary
   - Show next steps for user
   - Create installation log file

## Implementation Strategy

### Primary Installation Script: `install.sh`

```bash
#!/bin/bash
"""
REC.IO Complete Installation Package
Handles full system setup from git repository clone
"""

# Key Features:
# 1. Guided user input collection
# 2. Comprehensive dependency installation
# 3. Database setup and schema creation
# 4. System data cloning (optional)
# 5. Complete system startup and verification
```

### Installation Flow

```bash
# User experience will be:
git clone https://github.com/your-org/rec-io-server.git
cd rec-io-server
./install.sh

# The install.sh script will:
# 1. Check system requirements
# 2. Prompt for user information and credentials
# 3. Install all dependencies automatically
# 4. Set up PostgreSQL database
# 5. Clone system data (if requested)
# 6. Configure and start all services
# 7. Provide final system access information
```
# 4. User profile and credential setup
# 5. System configuration and startup
# 6. Verification and status reporting
```

### Supporting Scripts
1. **`scripts/validate_installation.py`** - Pre-installation validation
2. **`scripts/setup_database_complete.py`** - Database initialization
3. **`scripts/clone_system_data.py`** - Remote system data cloning
4. **`scripts/create_user_profile.py`** - User profile creation
5. **`scripts/verify_system.py`** - Post-installation verification
6. **`scripts/view_installation_logs.py`** - View installation access logs
7. **`scripts/setup_installer_user.sh`** - Set up read-only installer user
8. **`scripts/setup_installer_user.sql`** - SQL commands for installer user setup

### Configuration Templates
1. **User-specific configs** - Generated from user input
2. **Database connection strings** - Environment-based
3. **Service configurations** - Port and host assignments
4. **Credential files** - Secure storage with proper permissions
5. **Remote database credentials** - Read-only access for system data cloning

## Security Considerations

### Credential Security
- **File Permissions**: 600 for credential files
- **Directory Permissions**: 700 for credential directories
- **No Git Storage**: All credentials excluded from repository
- **Environment Variables**: Sensitive data in environment files

### User Data Protection
- **Isolation**: Each user has separate data directories
- **No Cross-Contamination**: Complete separation between users
- **Secure Storage**: Proper file permissions and access controls

### System Security
- **Local Access Only**: Default to localhost binding
- **Firewall Configuration**: Optional network access setup
- **Service Isolation**: Each service runs with minimal privileges
- **Installation Logging**: Complete audit trail of all installation access

## Success Criteria

### Installation Success
- ✅ All dependencies installed successfully
- ✅ PostgreSQL database running with complete schema
- ✅ System data cloned from remote (analytics, historical_data, live_data)
- ✅ User profile created with credentials
- ✅ All services started and running
- ✅ Web interface accessible
- ✅ Kalshi API connectivity verified

### User Experience
- ✅ Single command installation: `python3 install_package.py`
- ✅ Guided setup process with clear prompts
- ✅ Comprehensive error handling and recovery
- ✅ Clear success/failure indicators
- ✅ Complete documentation and next steps

### System Verification
- ✅ Database connectivity test passes
- ✅ System data integrity verified (analytics, historical_data, live_data)
- ✅ All supervisor services running
- ✅ Web interface responds correctly
- ✅ User authentication works
- ✅ Trading system ready for use

## Risk Mitigation

### Installation Failures
- **Rollback Capability**: Ability to undo changes
- **Error Recovery**: Detailed error messages and solutions
- **Partial Installation Handling**: Resume from failure point
- **Validation Steps**: Verify each phase before proceeding

### Data Loss Prevention
- **No Overwrite**: Never overwrite existing user data
- **Backup Creation**: Create backups before major changes
- **Validation**: Verify data integrity after operations
- **Safe Defaults**: Use safe default configurations

### System Conflicts
- **Port Checking**: Verify port availability before use
- **Service Detection**: Check for conflicting services
- **Graceful Handling**: Handle conflicts without breaking
- **Clear Reporting**: Report all conflicts and resolutions

## Next Steps

1. **Approve this proposal** - Confirm approach and requirements
2. **Complete remote database setup** - Create installer user and configure network access
3. **Verify installation logging** - Run `python3 scripts/test_installation_logging.py` to confirm setup
4. **Create installation script** - Implement `install_package.py`
5. **Test installation process** - Verify on clean systems
6. **Document user experience** - Create user guides
7. **Deploy to production** - Make available for new users

### Immediate Actions Required

**On Remote Database (137.184.224.94):**
1. Create `rec_io_installer` user with read-only permissions
2. Configure `pg_hba.conf` to allow installation client connections
3. Restart PostgreSQL service to apply changes

**After Setup:**
1. Run installation logging test to verify functionality
2. Confirm all installation access is properly logged
3. Proceed with installation package development

## Remote Database Setup

### Prerequisites

Before setting up the installation package, the remote database must be configured to allow installation access.

### 1. Create Installation Access Log Table

The installation logging table must exist on the remote database:

```sql
-- Create system schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS system;

-- Create installation access log table
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
```

### 2. Create Read-Only Installation User

**Execute the following SQL commands as a superuser on your remote PostgreSQL database:**

```sql
-- Create read-only user for installations
CREATE USER rec_io_installer WITH PASSWORD 'secure_installer_password_2025';

-- Grant read-only access to the three system schemas only
GRANT CONNECT ON DATABASE rec_io_db TO rec_io_installer;
GRANT USAGE ON SCHEMA analytics TO rec_io_installer;
GRANT USAGE ON SCHEMA historical_data TO rec_io_installer;
GRANT USAGE ON SCHEMA live_data TO rec_io_installer;

-- Grant SELECT on all tables in these schemas
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO rec_io_installer;
GRANT SELECT ON ALL TABLES IN SCHEMA historical_data TO rec_io_installer;
GRANT SELECT ON ALL TABLES IN SCHEMA live_data TO rec_io_installer;

-- Ensure future tables in these schemas are also readable
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO rec_io_installer;
ALTER DEFAULT PRIVILEGES IN SCHEMA historical_data GRANT SELECT ON TABLES TO rec_io_installer;
ALTER DEFAULT PRIVILEGES IN SCHEMA live_data GRANT SELECT ON TABLES TO rec_io_installer;

-- Grant access to installation logging table (for logging only)
GRANT USAGE ON SCHEMA system TO rec_io_installer;
GRANT INSERT, SELECT ON system.installation_access_log TO rec_io_installer;
```

### 3. Configure Network Access

**Update the PostgreSQL `pg_hba.conf` file on the remote server to allow connections from installation clients:**

```
# Allow rec_io_installer user from installation clients
host    rec_io_db    rec_io_installer    0.0.0.0/0    md5
```

**Note:** For production security, consider restricting to specific IP ranges instead of `0.0.0.0/0`.

### 4. Verify Setup

Test the installation user setup:

```bash
# Test connection with installer credentials
psql -h 137.184.224.94 -U rec_io_installer -d rec_io_db -c "SELECT current_user, current_database();"

# Test schema access
psql -h 137.184.224.94 -U rec_io_installer -d rec_io_db -c "SELECT schemaname, COUNT(*) FROM pg_tables WHERE schemaname IN ('analytics', 'historical_data', 'live_data') GROUP BY schemaname;"

# Test logging table access
psql -h 137.184.224.94 -U rec_io_installer -d rec_io_db -c "INSERT INTO system.installation_access_log (installer_user_id, installer_name, status) VALUES ('test', 'Test User', 'test');"
```

### Installation Package Credentials

The installation package will include these credentials:

```python
# Remote database credentials for system data cloning
REMOTE_DB_CONFIG = {
    'host': '137.184.224.94',
    'port': 5432,
    'database': 'rec_io_db',
    'user': 'rec_io_installer',
    'password': 'secure_installer_password_2025'
}
```

### Security Notes

- **Read-only access only** - Cannot modify any data
- **Schema isolation** - Can only access analytics, historical_data, live_data
- **No user data access** - Cannot see users schema or any user-specific data
- **Temporary use** - Credentials only used during installation
- **Audit logging** - All access is logged in system.installation_access_log
- **Non-superuser** - Installer user has no administrative privileges

### Current Status

- ✅ **Installation logging table created** - `system.installation_access_log` exists on remote database
- ❌ **Installer user not created** - `rec_io_installer` user needs to be created by superuser
- ❌ **Network access not configured** - `pg_hba.conf` needs to allow connections from installation clients
- ❌ **Test verification pending** - Installation logging test fails until setup is complete

## Questions for Approval

1. **User ID Generation**: Should user IDs be auto-generated or user-specified?
2. **Credential Validation**: Should we test Kalshi credentials during installation?
3. **Network Access**: Should the system be configured for remote access by default?
4. **System Data Cloning**: Should we include remote database credentials in the installation package?
5. **Backup Strategy**: Should we create system backups during installation?
6. **Network Security**: Should we restrict installer access to specific IP ranges or allow global access?

## Testing and Verification

### Installation Logging Test

The installation logging system can be tested using:

```bash
python3 scripts/test_installation_logging.py
```

**Expected Results:**
- ✅ Successful installation logging
- ✅ Failed installation logging  
- ✅ Database access verification
- ✅ Complete audit trail generation

**Current Status:** Test fails until remote database setup is complete

---

**Ready to proceed with implementation once approved.**
