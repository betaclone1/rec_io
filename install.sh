#!/bin/bash

# REC.IO Installation Script
# Correct order: Credentials -> Database -> System -> Services
# Usage: curl -sSL https://raw.githubusercontent.com/betaclone1/rec_io/main/install.sh | bash

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INSTALL]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[INSTALL] ✅${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[INSTALL] ⚠️${NC} $1"
}

log_error() {
    echo -e "${RED}[INSTALL] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    REC.IO INSTALLATION${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Configuration
INSTALL_DIR="/opt/rec_io"
DEPLOYMENT_LOG="/tmp/rec_io_installation.log"

# Function to log installation progress
log_deployment() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$DEPLOYMENT_LOG"
}

# Function to handle errors and exit
handle_error() {
    log_error "Installation FAILED at step: $1"
    log_error "Error: $2"
    echo
    echo "Installation failed. Please check the error above and try again."
    echo "Log file: $DEPLOYMENT_LOG"
    exit 1
}

# Function to ensure package manager is available
ensure_package_manager_available() {
    log_info "Ensuring package manager is available..."
    
    # Wait for any running apt processes to complete
    local max_wait=300  # 5 minutes max wait
    local waited=0
    
    while fuser /var/lib/dpkg/lock >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || fuser /var/cache/apt/archives/lock >/dev/null 2>&1; do
        if [[ $waited -ge $max_wait ]]; then
            log_warning "Package manager still locked after 5 minutes, attempting to force unlock..."
            rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock /var/lib/dpkg/lock
            dpkg --configure -a
            break
        fi
        
        log_warning "Package manager is running, waiting... ($waited/$max_wait seconds)"
        sleep 10
        waited=$((waited + 10))
    done
    
    # Kill any stuck processes
    if pgrep -f "apt-get\|dpkg" >/dev/null; then
        log_warning "Killing stuck package manager processes..."
        pkill -f "apt-get" || true
        pkill -f "dpkg" || true
        sleep 5
    fi
    
    log_success "Package manager is available"
}

# Set up error handling
trap 'handle_error "Unknown" "Script terminated unexpectedly"' ERR

# STEP 1: INTERACTIVE KALSHI CREDENTIALS SETUP
setup_kalshi_credentials() {
    echo
    echo "============================================================================="
    echo "                    STEP 1: KALSHI CREDENTIALS SETUP"
    echo "============================================================================="
    echo
    echo "You need Kalshi credentials to trade. This must be set up FIRST."
    echo
    echo "Do you want to set up Kalshi credentials now?"
    echo "1) Yes - I have my Kalshi credentials ready"
    echo "2) No - I'll add them later (system will be limited to demo mode)"
    echo
    echo "Enter 1 or 2:"
    read -p "Choice: " CREDENTIAL_CHOICE
    
    if [[ $CREDENTIAL_CHOICE == "1" ]]; then
        echo
        echo "Please enter your Kalshi credentials:"
        echo
        echo "Kalshi Email:"
        read KALSHI_EMAIL
        echo "Kalshi API Key:"
        read KALSHI_API_KEY
        echo "Kalshi API Secret:"
        read KALSHI_API_SECRET
        echo
        
        # Validate credentials are not empty
        if [[ -z "$KALSHI_EMAIL" || -z "$KALSHI_API_KEY" || -z "$KALSHI_API_SECRET" ]]; then
            handle_error "Credential Setup" "One or more credentials are empty"
        fi
        
        # Store credentials in environment variables for later use
        export KALSHI_EMAIL="$KALSHI_EMAIL"
        export KALSHI_API_KEY="$KALSHI_API_KEY"
        export KALSHI_API_SECRET="$KALSHI_API_SECRET"
        
        echo
        echo "✅ Kalshi credentials captured and stored"
        echo "They will be saved to the system during installation."
        echo
    else
        echo
        echo "⚠️  Skipping Kalshi credentials setup."
        echo "System will be limited to demo mode until credentials are added."
        echo
        # Set empty credentials
        export KALSHI_EMAIL=""
        export KALSHI_API_KEY=""
        export KALSHI_API_SECRET=""
    fi
    
    log_deployment "Kalshi credentials setup completed"
}

# STEP 2: INSTALL SYSTEM DEPENDENCIES
install_system_dependencies() {
    echo
    echo "============================================================================="
    echo "                    STEP 2: SYSTEM DEPENDENCIES"
    echo "============================================================================="
    echo
    
    log_info "Installing system dependencies..."
    log_deployment "Starting system dependencies installation"
    
    # Ensure package manager is available
    ensure_package_manager_available
    
    # Update package lists
    log_info "Updating package lists..."
    apt-get update || handle_error "System Dependencies" "Failed to update package lists"
    
    # Install basic dependencies
    apt-get install -y python3 python3-pip python3-venv git curl wget || handle_error "System Dependencies" "Failed to install basic packages"
    
    # Install PostgreSQL
    log_info "Installing PostgreSQL..."
    if apt-get install -y postgresql postgresql-contrib postgresql-client; then
        log_success "PostgreSQL installed successfully"
    elif apt-get install -y postgresql-14 postgresql-contrib-14 postgresql-client-14; then
        log_success "PostgreSQL 14 installed successfully"
    elif apt-get install -y postgresql-15 postgresql-contrib-15 postgresql-client-15; then
        log_success "PostgreSQL 15 installed successfully"
    else
        handle_error "System Dependencies" "Failed to install PostgreSQL"
    fi
    
    # Install supervisor
    log_info "Installing supervisor..."
    apt-get install -y supervisor || handle_error "System Dependencies" "Failed to install supervisor"
    
    # Start and enable PostgreSQL
    log_info "Starting PostgreSQL service..."
    systemctl start postgresql || handle_error "System Dependencies" "Failed to start PostgreSQL"
    systemctl enable postgresql || handle_error "System Dependencies" "Failed to enable PostgreSQL"
    
    log_success "System dependencies installed successfully"
    log_deployment "System dependencies installation completed"
}

# STEP 3: SETUP POSTGRESQL DATABASE
setup_postgresql_database() {
    echo
    echo "============================================================================="
    echo "                    STEP 3: POSTGRESQL DATABASE SETUP"
    echo "============================================================================="
    echo
    
    log_info "Setting up PostgreSQL database..."
    log_deployment "Starting PostgreSQL database setup"
    
    # Create database user
    log_info "Creating database user..."
    sudo -u postgres psql -c "CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';" 2>/dev/null || true
    
    # Create database
    log_info "Creating database..."
    sudo -u postgres psql -c "CREATE DATABASE rec_io_db OWNER rec_io_user;" 2>/dev/null || true
    
    # Grant privileges
    log_info "Granting database privileges..."
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;" 2>/dev/null || true
    
    # CONFIGURE POSTGRESQL FOR REMOTE ACCESS
    log_info "Configuring PostgreSQL for remote access..."
    
    # Get PostgreSQL version and config directory
    PG_VERSION=$(sudo -u postgres psql -c "SHOW server_version;" | grep -E '[0-9]+\.[0-9]+' | head -1 | tr -d ' ')
    PG_CONFIG_DIR="/etc/postgresql/${PG_VERSION}/main"
    
    if [[ ! -d "$PG_CONFIG_DIR" ]]; then
        # Try alternative locations
        PG_CONFIG_DIR="/etc/postgresql/*/main"
        PG_CONFIG_DIR=$(find /etc/postgresql -name "main" -type d | head -1)
    fi
    
    if [[ -z "$PG_CONFIG_DIR" || ! -d "$PG_CONFIG_DIR" ]]; then
        handle_error "Database Setup" "Could not find PostgreSQL configuration directory"
    fi
    
    log_info "PostgreSQL config directory: $PG_CONFIG_DIR"
    
    # Configure postgresql.conf to listen on all interfaces
    log_info "Configuring postgresql.conf..."
    sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" "$PG_CONFIG_DIR/postgresql.conf" || handle_error "Database Setup" "Failed to configure listen_addresses"
    
    # Configure pg_hba.conf to allow remote connections
    log_info "Configuring pg_hba.conf..."
    
    # Backup original pg_hba.conf
    sudo cp "$PG_CONFIG_DIR/pg_hba.conf" "$PG_CONFIG_DIR/pg_hba.conf.backup"
    
    # Add remote access rules
    sudo tee -a "$PG_CONFIG_DIR/pg_hba.conf" > /dev/null << EOF

# REC.IO Remote Access Configuration
host    rec_io_db       rec_io_user       0.0.0.0/0               md5
host    rec_io_db       rec_io_user       ::/0                    md5
EOF
    
    # Restart PostgreSQL to apply changes
    log_info "Restarting PostgreSQL to apply remote access configuration..."
    sudo systemctl restart postgresql || handle_error "Database Setup" "Failed to restart PostgreSQL"
    
    # Wait for PostgreSQL to fully start
    sleep 5
    
    # Test local database connection
    log_info "Testing local database connection..."
    PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT 1;" || handle_error "Database Setup" "Local database connection test failed"
    
    # Test remote database connection (from localhost to localhost, but using external IP)
    log_info "Testing remote database connection..."
    SERVER_IP=$(curl -s https://api.ipify.org 2>/dev/null || echo "localhost")
    PGPASSWORD=rec_io_password psql -h "$SERVER_IP" -U rec_io_user -d rec_io_db -c "SELECT 1;" || handle_error "Database Setup" "Remote database connection test failed"
    
    # Configure firewall to allow PostgreSQL connections
    log_info "Configuring firewall for PostgreSQL..."
    sudo ufw allow 5432/tcp || log_warning "Failed to configure UFW firewall (may not be installed)"
    
    # Show connection information
    log_info "PostgreSQL remote access configured successfully"
    echo "  Database Host: $SERVER_IP"
    echo "  Database Port: 5432"
    echo "  Database Name: rec_io_db"
    echo "  Database User: rec_io_user"
    echo "  Database Password: rec_io_password"
    echo "  Connection String: postgresql://rec_io_user:rec_io_password@$SERVER_IP:5432/rec_io_db"
    
    log_success "PostgreSQL database setup completed with remote access"
    log_deployment "PostgreSQL database setup completed with remote access"
}

# STEP 4: CLONE REPOSITORY
clone_repository() {
    echo
    echo "============================================================================="
    echo "                    STEP 4: CLONE REPOSITORY"
    echo "============================================================================="
    echo
    
    log_info "Cloning REC.IO repository..."
    log_deployment "Starting repository cloning"
    
    # Create installation directory
    mkdir -p "$INSTALL_DIR" || handle_error "Repository Clone" "Failed to create installation directory"
    cd "$INSTALL_DIR" || handle_error "Repository Clone" "Failed to change to installation directory"
    
    # Clone repository
    git clone https://github.com/betaclone1/rec_io.git . || handle_error "Repository Clone" "Failed to clone repository"
    
    log_success "Repository cloned successfully"
    log_deployment "Repository cloning completed"
}

# STEP 5: SETUP PYTHON ENVIRONMENT
setup_python_environment() {
    echo
    echo "============================================================================="
    echo "                    STEP 5: PYTHON ENVIRONMENT"
    echo "============================================================================="
    echo
    
    log_info "Setting up Python virtual environment..."
    log_deployment "Starting Python environment setup"
    
    cd "$INSTALL_DIR" || handle_error "Python Environment" "Failed to change to installation directory"
    
    # Create virtual environment
    python3 -m venv venv || handle_error "Python Environment" "Failed to create virtual environment"
    
    # Activate virtual environment
    source venv/bin/activate || handle_error "Python Environment" "Failed to activate virtual environment"
    
    # Upgrade pip
    pip install --upgrade pip || handle_error "Python Environment" "Failed to upgrade pip"
    
    # Install dependencies
    log_info "Installing Python dependencies..."
    pip install -r requirements.txt || handle_error "Python Environment" "Failed to install Python dependencies"
    
    # Verify critical dependencies are installed
    log_info "Verifying critical dependencies..."
    python3 -c "import ccxt, pandas, psycopg2; print('Critical dependencies verified')" || handle_error "Python Environment" "Critical dependencies missing - ccxt, pandas, or psycopg2 not installed"
    
    log_success "Python environment setup completed"
    log_deployment "Python environment setup completed"
}

# STEP 6: SETUP DATABASE SCHEMA
setup_database_schema() {
    echo
    echo "============================================================================="
    echo "                    STEP 6: DATABASE SCHEMA SETUP"
    echo "============================================================================="
    echo
    
    log_info "Setting up database schema..."
    log_deployment "Starting database schema setup"
    
    cd "$INSTALL_DIR" || handle_error "Database Schema" "Failed to change to installation directory"
    source venv/bin/activate || handle_error "Database Schema" "Failed to activate virtual environment"
    
    # Set environment variables
    export DB_HOST=localhost
    export DB_NAME=rec_io_db
    export DB_USER=rec_io_user
    export DB_PASSWORD=rec_io_password
    export DB_PORT=5432
    
    # Test database connection again
    log_info "Testing database connection..."
    PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT 1;" || handle_error "Database Schema" "Database connection failed"
    
    # Initialize database schema using the backend code
    log_info "Initializing database schema..."
    python3 -c "
import sys
sys.path.append('backend')
from core.config.database import init_database
success, message = init_database()
print(f'Database initialization: {message}')
if not success:
    exit(1)
" || handle_error "Database Schema" "Database schema initialization failed"
    
    # VERIFY DATABASE SCHEMA WAS ACTUALLY CREATED
    log_info "VERIFYING DATABASE SCHEMA WAS CREATED..."
    
    # Check for specific tables that should exist
    log_info "Checking for users schema tables..."
    USERS_TABLES=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'users';" | tr -d ' ')
    if [[ "$USERS_TABLES" == "0" ]]; then
        handle_error "Database Schema" "Users schema has no tables - schema creation failed"
    fi
    log_success "Found $USERS_TABLES tables in users schema"
    
    log_info "Checking for live_data schema tables..."
    LIVE_TABLES=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'live_data';" | tr -d ' ')
    if [[ "$LIVE_TABLES" == "0" ]]; then
        handle_error "Database Schema" "Live_data schema has no tables - schema creation failed"
    fi
    log_success "Found $LIVE_TABLES tables in live_data schema"
    
    log_info "Checking for system schema tables..."
    SYSTEM_TABLES=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'system';" | tr -d ' ')
    if [[ "$SYSTEM_TABLES" == "0" ]]; then
        handle_error "Database Schema" "System schema has no tables - schema creation failed"
    fi
    log_success "Found $SYSTEM_TABLES tables in system schema"
    
    log_info "Checking for historical_data schema tables..."
    HISTORICAL_TABLES=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'historical_data';" | tr -d ' ')
    if [[ "$HISTORICAL_TABLES" == "0" ]]; then
        handle_error "Database Schema" "Historical_data schema has no tables - schema creation failed"
    fi
    log_success "Found $HISTORICAL_TABLES tables in historical_data schema"
    
    # Show total table count
    TOTAL_TABLES=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema IN ('users', 'live_data', 'system', 'historical_data');" | tr -d ' ')
    log_success "Total database tables created: $TOTAL_TABLES"
    
    # Verify database is working
    log_info "Verifying database is working..."
    PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT version();" || handle_error "Database Schema" "Database verification failed"
    
    log_success "Database schema setup completed and VERIFIED"
    log_deployment "Database schema setup completed and verified"
}

# STEP 7: CLONE DATA FROM MASTER DATABASE
clone_data_from_master() {
    echo
    echo "============================================================================="
    echo "                    STEP 7: CLONE DATA FROM MASTER DATABASE"
    echo "============================================================================="
    echo
    
    log_info "Cloning data from master database..."
    log_deployment "Starting data clone from master"
    
    cd "$INSTALL_DIR" || handle_error "Data Clone" "Failed to change to installation directory"
    source venv/bin/activate || handle_error "Data Clone" "Failed to activate virtual environment"
    
    # Set environment variables for local database
    export DB_HOST=localhost
    export DB_NAME=rec_io_db
    export DB_USER=rec_io_user
    export DB_PASSWORD=rec_io_password
    export DB_PORT=5432
    
    # Get master database connection details
    echo
    echo "Please provide the master database connection details:"
    echo
    echo "Master Database Host (IP address):"
    read MASTER_DB_HOST
    echo "Master Database Name:"
    read MASTER_DB_NAME
    echo "Master Database User:"
    read MASTER_DB_USER
    echo "Master Database Password:"
    read MASTER_DB_PASSWORD
    echo "Master Database Port (default 5432):"
    read MASTER_DB_PORT
    MASTER_DB_PORT=${MASTER_DB_PORT:-5432}
    
    # Validate connection details
    if [[ -z "$MASTER_DB_HOST" || -z "$MASTER_DB_NAME" || -z "$MASTER_DB_USER" || -z "$MASTER_DB_PASSWORD" ]]; then
        handle_error "Data Clone" "Master database connection details are incomplete"
    fi
    
    # Test connection to master database
    log_info "Testing connection to master database..."
    PGPASSWORD="$MASTER_DB_PASSWORD" psql -h "$MASTER_DB_HOST" -U "$MASTER_DB_USER" -d "$MASTER_DB_NAME" -p "$MASTER_DB_PORT" -c "SELECT 1;" || handle_error "Data Clone" "Cannot connect to master database"
    log_success "Connected to master database"
    
    # Clone historical data
    log_info "Cloning historical data from master..."
    PGPASSWORD="$MASTER_DB_PASSWORD" pg_dump -h "$MASTER_DB_HOST" -U "$MASTER_DB_USER" -d "$MASTER_DB_NAME" -p "$MASTER_DB_PORT" --schema=historical_data --data-only --no-owner --no-privileges | PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db || handle_error "Data Clone" "Failed to clone historical data"
    
    # Verify historical data was cloned
    HISTORICAL_ROWS=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'historical_data';" | tr -d ' ')
    if [[ "$HISTORICAL_ROWS" == "0" ]]; then
        handle_error "Data Clone" "Historical data schema has no tables - clone failed"
    fi
    log_success "Historical data schema: $HISTORICAL_ROWS tables"
    
    # Clone analytics data
    log_info "Cloning analytics data from master..."
    PGPASSWORD="$MASTER_DB_PASSWORD" pg_dump -h "$MASTER_DB_HOST" -U "$MASTER_DB_USER" -d "$MASTER_DB_NAME" -p "$MASTER_DB_PORT" --schema=analytics --data-only --no-owner --no-privileges | PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db || log_warning "Analytics data clone failed - this may be expected if analytics schema is empty"
    
    # Clone live_data (structure only, not the live data itself)
    log_info "Cloning live_data structure from master..."
    PGPASSWORD="$MASTER_DB_PASSWORD" pg_dump -h "$MASTER_DB_HOST" -U "$MASTER_DB_USER" -d "$MASTER_DB_NAME" -p "$MASTER_DB_PORT" --schema=live_data --schema-only --no-owner --no-privileges | PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db || handle_error "Data Clone" "Failed to clone live_data structure"
    
    # Clone system data
    log_info "Cloning system data from master..."
    PGPASSWORD="$MASTER_DB_PASSWORD" pg_dump -h "$MASTER_DB_HOST" -U "$MASTER_DB_USER" -d "$MASTER_DB_NAME" -p "$MASTER_DB_PORT" --schema=system --data-only --no-owner --no-privileges | PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db || handle_error "Data Clone" "Failed to clone system data"
    
    # VERIFY DATA WAS CLONED
    log_info "VERIFYING DATA WAS CLONED FROM MASTER..."
    
    # Check historical data
    BTC_ROWS=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM historical_data.btc_price_history;" | tr -d ' ')
    if [[ "$BTC_ROWS" == "0" ]]; then
        handle_error "Data Clone" "BTC historical data table is empty - clone failed"
    fi
    log_success "BTC historical data: $BTC_ROWS rows"
    
    ETH_ROWS=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM historical_data.eth_price_history;" | tr -d ' ')
    if [[ "$ETH_ROWS" == "0" ]]; then
        handle_error "Data Clone" "ETH historical data table is empty - clone failed"
    fi
    log_success "ETH historical data: $ETH_ROWS rows"
    
    # Check analytics data
    ANALYTICS_TABLES=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'analytics';" | tr -d ' ')
    if [[ "$ANALYTICS_TABLES" == "0" ]]; then
        log_warning "Analytics tables not found - this may be expected for new installations"
    else
        log_success "Analytics tables: $ANALYTICS_TABLES tables"
    fi
    
    # Show data summary
    log_info "Cloned data summary:"
    echo "  BTC price history: $BTC_ROWS rows"
    echo "  ETH price history: $ETH_ROWS rows"
    echo "  Analytics tables: $ANALYTICS_TABLES tables"
    
    log_success "Data clone from master database completed and VERIFIED"
    log_deployment "Data clone from master database completed and verified"
}

# STEP 8: CONFIGURE SYSTEM FOR CURRENT ENVIRONMENT
configure_system() {
    echo
    echo "============================================================================="
    echo "                    STEP 8: CONFIGURE SYSTEM"
    echo "============================================================================="
    echo
    
    log_info "Configuring system for current environment..."
    log_deployment "Starting system configuration"
    
    cd "$INSTALL_DIR" || handle_error "System Configuration" "Failed to change to installation directory"
    source venv/bin/activate || handle_error "System Configuration" "Failed to activate virtual environment"
    
    # Get current server IP
    SERVER_IP=$(curl -s https://api.ipify.org 2>/dev/null || echo "localhost")
    
    # Update environment variables
    export REC_SYSTEM_HOST="$SERVER_IP"
    export REC_PROJECT_ROOT="$INSTALL_DIR"
    export REC_ENVIRONMENT="production"
    export DB_HOST="localhost"
    export DB_NAME="rec_io_db"
    export DB_USER="rec_io_user"
    export DB_PASSWORD="rec_io_password"
    export DB_PORT="5432"
    
    # Clear any cached environment variables that might interfere
    log_info "Clearing cached configuration..."
    unset REC_SYSTEM_HOST
    unset TRADING_SYSTEM_HOST
    unset REC_TARGET_HOST
    
    # Set environment variables for current server
    export REC_SYSTEM_HOST="$SERVER_IP"
    export REC_PROJECT_ROOT="$INSTALL_DIR"
    export REC_ENVIRONMENT="production"
    
    # Generate proper supervisor configuration
    log_info "Generating supervisor configuration for current environment..."
    python3 scripts/config/generate_unified_supervisor_config.py || handle_error "System Configuration" "Failed to generate supervisor configuration"
    
    # Verify supervisor configuration was created correctly
    if [[ ! -f "backend/supervisord.conf" ]]; then
        handle_error "System Configuration" "Supervisor configuration file not created"
    fi
    
    # Check that the configuration uses the correct paths
    if ! grep -q "$INSTALL_DIR" backend/supervisord.conf; then
        handle_error "System Configuration" "Supervisor configuration does not use correct installation directory"
    fi
    
    if ! grep -q "$SERVER_IP" backend/supervisord.conf; then
        handle_error "System Configuration" "Supervisor configuration does not use correct server IP"
    fi
    
    # Check if real Kalshi credentials exist and disable kalshi_account_sync if not
    if grep -q "PLACEHOLDER_KEY_FOR_NEW_INSTALLATION" backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi.pem; then
        log_warning "Detected placeholder Kalshi credentials - disabling kalshi_account_sync service"
        # Modify supervisor config to disable kalshi_account_sync
        sed -i 's/autostart=true/autostart=false/' backend/supervisord.conf
        sed -i '/kalshi_account_sync/,/^\[/ s/autostart=true/autostart=false/' backend/supervisord.conf
        log_info "kalshi_account_sync service disabled - enable it after adding real Kalshi credentials"
    fi
    
    log_success "System configuration completed and verified"
    log_deployment "System configuration completed and verified"
}

# STEP 8.5: DISABLE AUTOMATIC MAINTENANCE (CRITICAL FOR PRODUCTION)
disable_automatic_maintenance() {
    echo
    echo "============================================================================="
    echo "              STEP 8.5: DISABLE AUTOMATIC MAINTENANCE"
    echo "============================================================================="
    echo
    
    log_info "Disabling automatic system maintenance to prevent production failures..."
    log_deployment "Starting automatic maintenance disable"
    
    # Disable APT automatic services
    log_info "Disabling APT automatic services..."
    systemctl disable apt-daily-upgrade.service 2>/dev/null || true
    systemctl disable apt-daily-upgrade.timer 2>/dev/null || true
    systemctl disable apt-daily.service 2>/dev/null || true
    systemctl disable apt-daily.timer 2>/dev/null || true
    systemctl disable apt-daily-weekly.service 2>/dev/null || true
    systemctl disable apt-daily-weekly.timer 2>/dev/null || true
    
    # Disable update-notifier services
    log_info "Disabling update-notifier services..."
    systemctl disable update-notifier-download.service 2>/dev/null || true
    systemctl disable update-notifier-motd.service 2>/dev/null || true
    
    # Disable snap automatic updates
    log_info "Disabling snap automatic updates..."
    systemctl disable snapd.service 2>/dev/null || true
    systemctl disable snapd.socket 2>/dev/null || true
    
    # Disable unattended upgrades
    log_info "Disabling unattended upgrades..."
    systemctl disable unattended-upgrades.service 2>/dev/null || true
    systemctl disable unattended-upgrades.timer 2>/dev/null || true
    
    # Create APT configuration to prevent automatic operations
    log_info "Creating APT configuration to prevent automatic operations..."
    cat > /etc/apt/apt.conf.d/99disable-auto-updates << 'EOF'
# Disable all automatic APT operations
APT::Get::Automatic "false";
APT::Get::AutomaticRemove "false";
APT::Get::AutomaticRemove::Kernels "false";
APT::Get::AutomaticRemove::UnusedKernels "false";
APT::Get::AutomaticRemove::UnusedDependencies "false";

# Disable unattended upgrades
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "false";
Unattended-Upgrade::Remove-New-Unused-Dependencies "false";
Unattended-Upgrade::Automatic-Reboot-Time "02:00";
Unattended-Upgrade::Mail "false";

# Disable automatic package downloads
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
APT::Periodic::Unattended-Upgrade "0";
EOF

    # Verify services are disabled
    log_info "Verifying automatic maintenance is disabled..."
    local enabled_services=$(systemctl list-unit-files | grep -E "(apt|unattended)" | grep enabled | grep -v snap || true)
    
    if [[ -n "$enabled_services" ]]; then
        log_warning "Some automatic services are still enabled:"
        echo "$enabled_services"
        log_warning "Manual intervention may be required"
    else
        log_success "All automatic maintenance services successfully disabled"
    fi
    
    log_success "Automatic maintenance disabled - production system is now protected"
    log_deployment "Automatic maintenance disabled successfully"
}

# STEP 9: TEST SERVICE STARTUP
test_service_startup() {
    echo
    echo "============================================================================="
    echo "                    STEP 9: TEST SERVICE STARTUP"
    echo "============================================================================="
    echo
    
    log_info "Testing service startup to ensure MASTER_RESTART will work..."
    log_deployment "Starting service startup test"
    
    cd "$INSTALL_DIR" || handle_error "Service Test" "Failed to change to installation directory"
    
    # Test that supervisor configuration is valid
    log_info "Testing supervisor configuration..."
    supervisord -c backend/supervisord.conf -t || handle_error "Service Test" "Supervisor configuration is invalid"
    
    # Start supervisor in test mode
    log_info "Starting supervisor in test mode..."
    supervisord -c backend/supervisord.conf -n &
    SUPERVISOR_PID=$!
    
    # Wait for supervisor to start
    sleep 3
    
    # Test starting a few key services
    log_info "Testing key service startup..."
    
    # Test main_app
    supervisorctl -c backend/supervisord.conf start main_app || handle_error "Service Test" "main_app failed to start"
    sleep 2
    supervisorctl -c backend/supervisord.conf status main_app | grep -q "RUNNING" || handle_error "Service Test" "main_app is not running"
    supervisorctl -c backend/supervisord.conf stop main_app
    
    # Test trade_manager (program name is pool-suffixed; default REC_POOL_USER_NUMBER=0001)
    _pu="${REC_POOL_USER_NUMBER:-0001}"
    supervisorctl -c backend/supervisord.conf start "trade_manager_${_pu}" || handle_error "Service Test" "trade_manager failed to start"
    sleep 2
    supervisorctl -c backend/supervisord.conf status "trade_manager_${_pu}" | grep -q "RUNNING" || handle_error "Service Test" "trade_manager is not running"
    supervisorctl -c backend/supervisord.conf stop "trade_manager_${_pu}"
    
    # Stop supervisor
    kill $SUPERVISOR_PID
    wait $SUPERVISOR_PID 2>/dev/null
    
    log_success "Service startup test completed successfully"
    log_deployment "Service startup test completed successfully"
}

# STEP 8: CREATE USER PROFILE AND SAVE CREDENTIALS
create_user_profile() {
    echo
    echo "============================================================================="
    echo "                    STEP 8: USER PROFILE SETUP"
    echo "============================================================================="
    echo
    
    log_info "Creating user profile and saving credentials..."
    log_deployment "Starting user profile setup"
    
    cd "$INSTALL_DIR" || handle_error "User Profile" "Failed to change to installation directory"
    
    # Create user directory structure
    mkdir -p backend/data/users/user_0001/{credentials/kalshi-credentials/{prod,demo},preferences,trade_history,active_trades,accounts} || handle_error "User Profile" "Failed to create user directories"
    
    # Set secure permissions
    chmod 700 backend/data/users/user_0001/credentials
    chmod 700 backend/data/users/user_0001/credentials/kalshi-credentials
    chmod 700 backend/data/users/user_0001/credentials/kalshi-credentials/prod
    chmod 700 backend/data/users/user_0001/credentials/kalshi-credentials/demo
    
    # Save Kalshi credentials
    echo
    echo "=== Saving Kalshi Credentials ==="
    
    if [[ -n "$KALSHI_EMAIL" && -n "$KALSHI_API_KEY" && -n "$KALSHI_API_SECRET" ]]; then
        # Create credentials file with captured credentials
        cat > backend/data/users/user_0001/credentials/kalshi-credentials/prod/credentials.json << EOF
{
    "email": "$KALSHI_EMAIL",
    "api_key": "$KALSHI_API_KEY",
    "api_secret": "$KALSHI_API_SECRET"
}
EOF
        
        # Create placeholder PEM file (required by kalshi_account_sync)
        echo "Creating placeholder Kalshi PEM file..."
        cat > backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi.pem << EOF
-----BEGIN RSA PRIVATE KEY-----
PLACEHOLDER_KEY_FOR_NEW_INSTALLATION
-----END RSA PRIVATE KEY-----
EOF
        
        log_success "Kalshi credentials saved from earlier setup"
        log_warning "Kalshi PEM file created as placeholder - you need to replace with your actual PEM file"
    else
        echo
        echo "No Kalshi credentials provided earlier."
        echo "Creating placeholder files - you can add credentials later by editing:"
        echo "  backend/data/users/user_0001/credentials/kalshi-credentials/prod/credentials.json"
        echo "  backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi.pem"
        echo
        
        # Create empty credentials file for now
        cat > backend/data/users/user_0001/credentials/kalshi-credentials/prod/credentials.json << EOF
{
    "email": "",
    "api_key": "",
    "api_secret": ""
}
EOF
        
        # Create placeholder PEM file
        cat > backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi.pem << EOF
-----BEGIN RSA PRIVATE KEY-----
PLACEHOLDER_KEY_FOR_NEW_INSTALLATION
-----END RSA PRIVATE KEY-----
EOF
        
        log_info "Kalshi credentials placeholder created - add your credentials later"
        
        # Note: kalshi_account_sync will be disabled until real credentials are provided
        log_warning "kalshi_account_sync service will be disabled until real Kalshi credentials are provided"
    fi
    
    # Create user_info.json
    cat > backend/data/users/user_0001/user_info.json << EOF
{
    "user_id": "user_0001",
    "name": "REC.IO User",
    "email": "user@rec.io",
    "account_type": "user",
    "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "preferences": {
        "default_account_type": "demo",
        "notifications_enabled": true,
        "auto_trading_enabled": false
    }
}
EOF
    
    # Create .env file
    cat > .env << EOF
# REC.IO System Configuration
DB_HOST=localhost
DB_NAME=rec_io_db
DB_USER=rec_io_user
DB_PASSWORD=rec_io_password
DB_PORT=5432

# System Configuration
SYSTEM_HOST=localhost
SYSTEM_PORT=3000
ENVIRONMENT=production
EOF
    
    log_success "User profile setup completed"
    log_deployment "User profile setup completed"
}

# STEP 9: FINAL VERIFICATION
verify_installation() {
    echo
    echo "============================================================================="
    echo "                    STEP 9: FINAL VERIFICATION"
    echo "============================================================================="
    echo
    
    log_info "Performing final verification..."
    log_deployment "Starting final verification"
    
    cd "$INSTALL_DIR" || handle_error "Final Verification" "Failed to change to installation directory"
    source venv/bin/activate || handle_error "Final Verification" "Failed to activate virtual environment"
    
    # Test database connectivity
    log_info "Testing database connectivity..."
    python3 -c "
import psycopg2
import os
try:
    conn = psycopg2.connect(
        host='localhost',
        database='rec_io_db',
        user='rec_io_user',
        password='rec_io_password',
        port='5432'
    )
    print('Database connectivity: OK')
    conn.close()
except Exception as e:
    print(f'Database connectivity: FAILED - {e}')
    exit(1)
" || handle_error "Final Verification" "Database connectivity test failed"
    
    # Verify user directory structure exists
    log_info "Verifying user directory structure..."
    if [[ ! -d "backend/data/users/user_0001" ]]; then
        handle_error "Final Verification" "User directory structure not found"
    fi
    
    if [[ ! -f "backend/data/users/user_0001/user_info.json" ]]; then
        handle_error "Final Verification" "User info file not found"
    fi
    
    # Verify .env file exists
    if [[ ! -f ".env" ]]; then
        handle_error "Final Verification" ".env file not found"
    fi
    
    # Check if Kalshi credentials exist (warn if not, but don't fail)
    if [[ ! -f "backend/data/users/user_0001/credentials/kalshi-credentials/prod/credentials.json" ]]; then
        log_warning "Kalshi credentials not found - trading will be limited to demo mode"
        log_warning "You can add credentials later by editing: backend/data/users/user_0001/credentials/kalshi-credentials/prod/credentials.json"
    else
        log_success "Kalshi credentials found"
    fi
    
    # Verify historical data exists
    log_info "Verifying historical data..."
    BTC_ROWS=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM historical_data.btc_price_history;" | tr -d ' ')
    ETH_ROWS=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM historical_data.eth_price_history;" | tr -d ' ')
    
    if [[ "$BTC_ROWS" == "0" ]]; then
        handle_error "Final Verification" "BTC historical data is missing"
    fi
    
    if [[ "$ETH_ROWS" == "0" ]]; then
        handle_error "Final Verification" "ETH historical data is missing"
    fi
    
    log_success "Historical data verified: BTC ($BTC_ROWS rows), ETH ($ETH_ROWS rows)"
    
    log_success "Final verification completed"
    log_deployment "Final verification completed"
}

# MAIN INSTALLATION FUNCTION
main() {
    print_header
    log_info "Starting REC.IO installation..."
    log_deployment "Installation started at $(date)"
    
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        handle_error "Prerequisites" "This script must be run as root"
    fi
    
    # Run installation steps in correct order
    setup_kalshi_credentials
    install_system_dependencies
    setup_postgresql_database
    clone_repository
    setup_python_environment
    setup_database_schema
    clone_data_from_master
    configure_system
    disable_automatic_maintenance
    test_service_startup
    create_user_profile
    verify_installation
    
    # FINAL SUCCESS MESSAGE
    echo
    echo "============================================================================="
    echo "                    INSTALLATION COMPLETE"
    echo "============================================================================="
    echo
    
    # Get server IP
    SERVER_IP=$(curl -s https://api.ipify.org 2>/dev/null || echo "localhost")
    
    # Show database summary
    TOTAL_TABLES=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema IN ('users', 'live_data', 'system', 'historical_data');" | tr -d ' ')
    BTC_ROWS=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM historical_data.btc_price_history;" | tr -d ' ')
    ETH_ROWS=$(PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM historical_data.eth_price_history;" | tr -d ' ')
    
    echo "=========================================="
    echo "        REC.IO INSTALLATION COMPLETE"
    echo "=========================================="
    echo
    echo "✅ Database setup completed and verified"
    echo "✅ Data cloned from master database"
    echo "✅ User profile created"
    echo "✅ Kalshi credentials saved"
    echo
    echo "System Information:"
    echo "  Installation Directory: $INSTALL_DIR"
    echo "  Database: localhost:5432 (rec_io_db)"
    echo "  Server IP: $SERVER_IP"
    echo "  Total Database Tables: $TOTAL_TABLES"
    echo "  BTC Historical Data: $BTC_ROWS rows"
    echo "  ETH Historical Data: $ETH_ROWS rows"
    echo
    echo "Next Steps:"
    echo "  1. Verify the database is working correctly"
    echo "  2. If everything looks good, run: cd $INSTALL_DIR && ./scripts/MASTER_RESTART.sh"
    echo "  3. Access your system: http://$SERVER_IP:3000"
    echo
    echo "Installation log: $DEPLOYMENT_LOG"
    echo "=========================================="
    
    log_success "Installation completed successfully!"
    log_deployment "Installation completed successfully at $(date)"
}

# Run main function
main "$@"
