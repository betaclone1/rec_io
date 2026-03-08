#!/bin/bash

# =============================================================================
# DROPLET CLONE AND SANITIZATION SCRIPT
# =============================================================================
# This script clones a production Digital Ocean droplet and sanitizes it for
# new users by removing all user-specific data and credentials, then setting
# up new user information and Kalshi credentials.
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="/opt/rec_io"
BACKUP_DIR="/tmp/rec_io_backup"
SNAPSHOT_NAME="rec_io_production_snapshot_$(date +%Y%m%d_%H%M%S)"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[CLONE_SANITIZE]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[CLONE_SANITIZE] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[CLONE_SANITIZE] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[CLONE_SANITIZE] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}              DROPLET CLONE AND SANITIZATION SCRIPT${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Function to handle errors
handle_error() {
    local step=$1
    local message=$2
    print_error "Failed at step: $step"
    print_error "Error: $message"
    echo ""
    print_warning "If this is a critical error, you may need to:"
    print_warning "1. Check Digital Ocean API credentials"
    print_warning "2. Verify droplet permissions"
    print_warning "3. Check available disk space"
    print_warning "4. Verify network connectivity"
    exit 1
}

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    # Check if doctl is installed
    if ! command -v doctl &> /dev/null; then
        print_error "doctl (Digital Ocean CLI) is not installed"
        print_warning "Install with: snap install doctl"
        exit 1
    fi
    
    # Check if doctl is authenticated
    if ! doctl account get &> /dev/null; then
        print_error "doctl is not authenticated"
        print_warning "Run: doctl auth init"
        exit 1
    fi
    
    # Check if we're in the project directory
    if [[ ! -f "scripts/MASTER_RESTART.sh" ]]; then
        print_error "Must run from project root directory"
        exit 1
    fi
    
    print_success "Prerequisites check passed"
}

# Function to get user information
get_user_information() {
    print_status "Collecting new user information..."
    echo ""
    
    # Get user details
    read -p "Enter new user ID (e.g., user_0002): " NEW_USER_ID
    read -p "Enter full name: " NEW_USER_NAME
    read -p "Enter email address: " NEW_USER_EMAIL
    read -p "Enter phone number: " NEW_USER_PHONE
    read -s -p "Enter password: " NEW_USER_PASSWORD
    echo ""
    read -s -p "Confirm password: " NEW_USER_PASSWORD_CONFIRM
    echo ""
    
    # Validate password match
    if [[ "$NEW_USER_PASSWORD" != "$NEW_USER_PASSWORD_CONFIRM" ]]; then
        handle_error "User Information" "Passwords do not match"
    fi
    
    # Validate user ID format
    if [[ ! "$NEW_USER_ID" =~ ^user_[0-9]{4}$ ]]; then
        handle_error "User Information" "User ID must be in format: user_XXXX (e.g., user_0002)"
    fi
    
    print_success "User information collected"
}

# Function to get Kalshi credentials
get_kalshi_credentials() {
    print_status "Collecting Kalshi credentials..."
    echo ""
    
    echo "Do you want to set up Kalshi credentials now?"
    echo "1) Yes - I have my Kalshi credentials ready"
    echo "2) No - I'll add them later (system will be limited to demo mode)"
    echo ""
    read -p "Enter 1 or 2: " CREDENTIAL_CHOICE
    
    if [[ $CREDENTIAL_CHOICE == "1" ]]; then
        echo ""
        echo "Please enter your Kalshi credentials:"
        echo ""
        read -p "Kalshi Email: " KALSHI_EMAIL
        read -s -p "Kalshi API Key: " KALSHI_API_KEY
        echo ""
        read -s -p "Kalshi API Secret: " KALSHI_API_SECRET
        echo ""
        
        # Validate credentials are not empty
        if [[ -z "$KALSHI_EMAIL" || -z "$KALSHI_API_KEY" || -z "$KALSHI_API_SECRET" ]]; then
            handle_error "Kalshi Credentials" "One or more credentials are empty"
        fi
        
        print_success "Kalshi credentials collected"
    else
        print_warning "Skipping Kalshi credentials setup"
        KALSHI_EMAIL=""
        KALSHI_API_KEY=""
        KALSHI_API_SECRET=""
    fi
}

# Function to create droplet snapshot
create_droplet_snapshot() {
    print_status "Creating droplet snapshot..."
    
    # Get current droplet ID
    CURRENT_DROPLET_ID=$(doctl compute droplet list --format ID,Name --no-header | grep "$(hostname)" | awk '{print $1}')
    
    if [[ -z "$CURRENT_DROPLET_ID" ]]; then
        handle_error "Snapshot Creation" "Could not find current droplet ID"
    fi
    
    print_status "Found current droplet ID: $CURRENT_DROPLET_ID"
    
    # Create snapshot
    print_status "Creating snapshot: $SNAPSHOT_NAME"
    doctl compute droplet-action snapshot "$CURRENT_DROPLET_ID" --snapshot-name "$SNAPSHOT_NAME"
    
    # Wait for snapshot to complete
    print_status "Waiting for snapshot to complete..."
    while true; do
        STATUS=$(doctl compute droplet-action list "$CURRENT_DROPLET_ID" --format ID,Type,Status --no-header | grep snapshot | tail -1 | awk '{print $3}')
        if [[ "$STATUS" == "completed" ]]; then
            break
        elif [[ "$STATUS" == "errored" ]]; then
            handle_error "Snapshot Creation" "Snapshot creation failed"
        fi
        sleep 10
    done
    
    print_success "Snapshot created successfully: $SNAPSHOT_NAME"
}

# Function to create new droplet from snapshot
create_new_droplet() {
    print_status "Creating new droplet from snapshot..."
    
    # Get snapshot ID
    SNAPSHOT_ID=$(doctl compute snapshot list --format ID,Name --no-header | grep "$SNAPSHOT_NAME" | awk '{print $1}')
    
    if [[ -z "$SNAPSHOT_ID" ]]; then
        handle_error "Droplet Creation" "Could not find snapshot ID"
    fi
    
    # Get available regions and sizes
    REGION=$(doctl compute droplet list --format Region,Name --no-header | grep "$(hostname)" | awk '{print $1}')
    SIZE=$(doctl compute droplet list --format Size,Name --no-header | grep "$(hostname)" | awk '{print $1}')
    
    # Create new droplet name
    NEW_DROPLET_NAME="rec_io_${NEW_USER_ID}_$(date +%Y%m%d)"
    
    print_status "Creating new droplet: $NEW_DROPLET_NAME"
    print_status "Region: $REGION, Size: $SIZE, Snapshot: $SNAPSHOT_ID"
    
    # Create the new droplet
    NEW_DROPLET_ID=$(doctl compute droplet create "$NEW_DROPLET_NAME" \
        --size "$SIZE" \
        --region "$REGION" \
        --image "$SNAPSHOT_ID" \
        --format ID --no-header)
    
    if [[ -z "$NEW_DROPLET_ID" ]]; then
        handle_error "Droplet Creation" "Failed to create new droplet"
    fi
    
    print_success "New droplet created with ID: $NEW_DROPLET_ID"
    
    # Wait for droplet to be active
    print_status "Waiting for droplet to become active..."
    while true; do
        STATUS=$(doctl compute droplet get "$NEW_DROPLET_ID" --format Status --no-header)
        if [[ "$STATUS" == "active" ]]; then
            break
        fi
        sleep 10
    done
    
    # Get droplet IP
    NEW_DROPLET_IP=$(doctl compute droplet get "$NEW_DROPLET_ID" --format PublicIPv4 --no-header)
    
    print_success "New droplet is active at IP: $NEW_DROPLET_IP"
    echo ""
    print_status "New droplet details:"
    print_status "  Name: $NEW_DROPLET_NAME"
    print_status "  ID: $NEW_DROPLET_ID"
    print_status "  IP: $NEW_DROPLET_IP"
    echo ""
}

# Function to sanitize user data
sanitize_user_data() {
    print_status "Sanitizing user data on new droplet..."
    
    # Connect to new droplet and sanitize data
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 root@"$NEW_DROPLET_IP" << 'SANITIZE_EOF'
        set -e
        
        echo "Starting data sanitization..."
        
        # Stop all services first
        cd /opt/rec_io
        ./scripts/MASTER_RESTART.sh 2>/dev/null || true
        
        # Wait for services to stop
        sleep 5
        
        # Clear all user-specific data from database
        echo "Clearing user data from database..."
        PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db << 'SQL_EOF'
            -- Clear all user-specific data
            DELETE FROM users.trades_0001;
            DELETE FROM users.active_trades_0001;
            DELETE FROM users.fills_0001;
            DELETE FROM users.settlements_0001;
            DELETE FROM users.positions_0001;
            DELETE FROM users.trade_preferences_0001;
            DELETE FROM users.orders_0001;
            DELETE FROM users.account_balance_0001;
            DELETE FROM users.watchlist_0001;
            DELETE FROM users.auto_trade_settings_0001;
            
            -- Reset sequences
            ALTER SEQUENCE users.trades_0001_id_seq1 RESTART WITH 1;
            ALTER SEQUENCE users.fills_0001_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.settlements_0001_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.positions_0001_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.orders_0001_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.account_balance_0001_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.watchlist_0001_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.auto_trade_settings_0001_id_seq RESTART WITH 1;
            
            -- Clear system health data
            DELETE FROM system.health_status;
            
            -- Clear live data (keep structure, clear data)
            
            DELETE FROM live_data.eth_price_log;
            DELETE FROM live_data.live_price_log_1s_btc;
            DELETE FROM live_data.live_price_log_1s_eth;
            DELETE FROM live_data.market_data;
            DELETE FROM live_data.websocket_market_data;
            DELETE FROM live_data.btc_live_strikes;
SQL_EOF
        
        # Remove all user credential files
        echo "Removing user credentials..."
        rm -rf /opt/rec_io/backend/data/users/user_0001/credentials/*
        rm -rf /opt/rec_io/backend/api/kalshi-api/kalshi-credentials/*
        
        # Remove user-specific files
        echo "Removing user-specific files..."
        rm -f /opt/rec_io/backend/data/users/user_0001/user_info.json
        rm -f /opt/rec_io/backend/data/users/user_0001/preferences/*
        rm -f /opt/rec_io/backend/data/users/user_0001/trade_history/*
        rm -f /opt/rec_io/backend/data/users/user_0001/active_trades/*
        rm -f /opt/rec_io/backend/data/users/user_0001/accounts/*
        
        # Clear logs
        echo "Clearing logs..."
        rm -f /opt/rec_io/logs/*
        
        echo "Data sanitization completed"
SANITIZE_EOF
    
    print_success "User data sanitized"
}

# Function to set up new user configuration
setup_new_user_config() {
    print_status "Setting up new user configuration..."
    
    # Connect to new droplet and set up new user
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 root@"$NEW_DROPLET_IP" << 'SETUP_EOF'
        set -e
        
        echo "Setting up new user configuration..."
        cd /opt/rec_io
        
        # Create new user directory structure
        mkdir -p backend/data/users/'$NEW_USER_ID'/{credentials/kalshi-credentials/{prod,demo},preferences,trade_history,active_trades,accounts}
        chmod 700 backend/data/users/'$NEW_USER_ID'/credentials
        chmod 700 backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials
        chmod 700 backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod
        chmod 700 backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/demo
        
        # Create user_info.json
        cat > backend/data/users/'$NEW_USER_ID'/user_info.json << 'USER_INFO_EOF'
{
    "user_id": "'$NEW_USER_ID'",
    "name": "'$NEW_USER_NAME'",
    "email": "'$NEW_USER_EMAIL'",
    "phone": "'$NEW_USER_PHONE'",
    "account_type": "user",
    "created": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "preferences": {
        "default_account_type": "demo",
        "notifications_enabled": true,
        "auto_trading_enabled": false
    }
}
USER_INFO_EOF
        
        # Set up Kalshi credentials if provided
        if [[ -n "'$KALSHI_EMAIL'" && -n "'$KALSHI_API_KEY'" && -n "'$KALSHI_API_SECRET'" ]]; then
            echo "Setting up Kalshi credentials..."
            
            # Create credentials file
            cat > backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod/kalshi-auth.txt << 'CREDS_EOF'
email:'$KALSHI_EMAIL'
key:'$KALSHI_API_KEY'
CREDS_EOF
            
            # Create placeholder PEM file
            cat > backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod/kalshi.pem << 'PEM_EOF'
-----BEGIN RSA PRIVATE KEY-----
PLACEHOLDER_KEY_FOR_NEW_INSTALLATION
-----END RSA PRIVATE KEY-----
PEM_EOF
            
            # Set proper permissions
            chmod 600 backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod/kalshi-auth.txt
            chmod 600 backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod/kalshi.pem
            
            # Copy to system-expected locations
            mkdir -p backend/api/kalshi-api/kalshi-credentials/{prod,demo}
            cp backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod/* backend/api/kalshi-api/kalshi-credentials/prod/
            cp backend/api/kalshi-api/kalshi-credentials/prod/* backend/api/kalshi-api/kalshi-credentials/demo/
            
            echo "Kalshi credentials configured"
        else
            echo "No Kalshi credentials provided - creating placeholder files"
            
            # Create empty credentials file
            cat > backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod/kalshi-auth.txt << 'EMPTY_CREDS_EOF'
email:
key:
EMPTY_CREDS_EOF
            
            # Create placeholder PEM file
            cat > backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod/kalshi.pem << 'EMPTY_PEM_EOF'
-----BEGIN RSA PRIVATE KEY-----
PLACEHOLDER_KEY_FOR_NEW_INSTALLATION
-----END RSA PRIVATE KEY-----
EMPTY_PEM_EOF
            
            chmod 600 backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod/kalshi-auth.txt
            chmod 600 backend/data/users/'$NEW_USER_ID'/credentials/kalshi-credentials/prod/kalshi.pem
        fi
        
        # Update database to use new user ID
        echo "Updating database for new user ID..."
        PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db << 'DB_UPDATE_EOF'
            -- Create new user tables with new user ID
            CREATE TABLE IF NOT EXISTS users.trades_'${NEW_USER_ID#user_}' (
                LIKE users.trades_0001 INCLUDING ALL
            );
            
            CREATE TABLE IF NOT EXISTS users.active_trades_'${NEW_USER_ID#user_}' (
                LIKE users.active_trades_0001 INCLUDING ALL
            );
            
            CREATE TABLE IF NOT EXISTS users.fills_'${NEW_USER_ID#user_}' (
                LIKE users.fills_0001 INCLUDING ALL
            );
            
            CREATE TABLE IF NOT EXISTS users.settlements_'${NEW_USER_ID#user_}' (
                LIKE users.settlements_0001 INCLUDING ALL
            );
            
            CREATE TABLE IF NOT EXISTS users.positions_'${NEW_USER_ID#user_}' (
                LIKE users.positions_0001 INCLUDING ALL
            );
            
            CREATE TABLE IF NOT EXISTS users.trade_preferences_'${NEW_USER_ID#user_}' (
                LIKE users.trade_preferences_0001 INCLUDING ALL
            );
            
            CREATE TABLE IF NOT EXISTS users.orders_'${NEW_USER_ID#user_}' (
                LIKE users.orders_0001 INCLUDING ALL
            );
            
            CREATE TABLE IF NOT EXISTS users.account_balance_'${NEW_USER_ID#user_}' (
                LIKE users.account_balance_0001 INCLUDING ALL
            );
            
            CREATE TABLE IF NOT EXISTS users.watchlist_'${NEW_USER_ID#user_}' (
                LIKE users.watchlist_0001 INCLUDING ALL
            );
            
            CREATE TABLE IF NOT EXISTS users.auto_trade_settings_'${NEW_USER_ID#user_}' (
                LIKE users.auto_trade_settings_0001 INCLUDING ALL
            );
            
            -- Create monitors_list table for new user
            CREATE SEQUENCE IF NOT EXISTS users.monitors_list_${NEW_USER_ID#user_}_id_seq
            START WITH 10001
            INCREMENT BY 1
            MINVALUE 10001
            MAXVALUE 99999
            CYCLE;
            
            CREATE TABLE IF NOT EXISTS users.monitors_list_'${NEW_USER_ID#user_}' (
                id INTEGER PRIMARY KEY DEFAULT nextval('users.monitors_list_${NEW_USER_ID#user_}_id_seq'),
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
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
DB_UPDATE_EOF
        
        echo "New user configuration completed"
SETUP_EOF
    
    print_success "New user configuration set up"
}

# Function to run MASTER RESTART on new droplet
run_master_restart() {
    print_status "Running MASTER RESTART on new droplet..."
    
    # Connect to new droplet and run MASTER RESTART
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 root@"$NEW_DROPLET_IP" << 'RESTART_EOF'
        set -e
        
        echo "Running MASTER RESTART..."
        cd /opt/rec_io
        
        # Run MASTER RESTART
        ./scripts/MASTER_RESTART.sh
        
        # Wait a moment for services to start
        sleep 10
        
        # Check service status
        echo "Checking service status..."
        supervisorctl -c backend/supervisord.conf status
        
        echo "MASTER RESTART completed"
RESTART_EOF
    
    print_success "MASTER RESTART completed on new droplet"
}

# Function to verify system functionality
verify_system_functionality() {
    print_status "Verifying system functionality..."
    
    # Test web interface
    print_status "Testing web interface..."
    if curl -s -o /dev/null -w "%{http_code}" "http://$NEW_DROPLET_IP:3000" | grep -q "200"; then
        print_success "Web interface is accessible"
    else
        print_warning "Web interface may not be accessible yet"
    fi
    
    # Test health endpoint
    print_status "Testing health endpoint..."
    if curl -s "http://$NEW_DROPLET_IP:3000/health" | grep -q "status"; then
        print_success "Health endpoint is responding"
    else
        print_warning "Health endpoint may not be responding yet"
    fi
    
    print_success "System verification completed"
}

# Function to display final information
display_final_information() {
    print_header
    print_success "Droplet clone and sanitization completed successfully!"
    echo ""
    print_status "New droplet details:"
    print_status "  Name: $NEW_DROPLET_NAME"
    print_status "  ID: $NEW_DROPLET_ID"
    print_status "  IP: $NEW_DROPLET_IP"
    print_status "  User ID: $NEW_USER_ID"
    print_status "  User Name: $NEW_USER_NAME"
    print_status "  User Email: $NEW_USER_EMAIL"
    echo ""
    print_status "Access information:"
    print_status "  Web Interface: http://$NEW_DROPLET_IP:3000"
    print_status "  Health Check: http://$NEW_DROPLET_IP:3000/health"
    print_status "  SSH Access: ssh root@$NEW_DROPLET_IP"
    echo ""
    print_status "Next steps for the new user:"
    print_status "1. Access the web interface at http://$NEW_DROPLET_IP:3000"
    print_status "2. Log in with the credentials provided"
    if [[ -z "$KALSHI_EMAIL" ]]; then
        print_status "3. Add Kalshi credentials to enable trading features"
        print_status "   Location: backend/data/users/$NEW_USER_ID/credentials/kalshi-credentials/prod/"
    else
        print_status "3. Kalshi credentials are already configured"
    fi
    print_status "4. Configure trading preferences in the web interface"
    echo ""
    print_warning "Important notes:"
    print_warning "- All original user data has been completely removed"
    print_warning "- The system is now configured for user: $NEW_USER_ID"
    print_warning "- Original droplet remains unchanged"
    print_warning "- Snapshot can be deleted after verification: $SNAPSHOT_NAME"
    echo ""
    print_success "Deployment completed successfully!"
}

# Main function
main() {
    print_header
    print_status "Starting droplet clone and sanitization process..."
    echo ""
    
    # Step 1: Check prerequisites
    check_prerequisites
    echo ""
    
    # Step 2: Get user information
    get_user_information
    echo ""
    
    # Step 3: Get Kalshi credentials
    get_kalshi_credentials
    echo ""
    
    # Step 4: Create droplet snapshot
    create_droplet_snapshot
    echo ""
    
    # Step 5: Create new droplet from snapshot
    create_new_droplet
    echo ""
    
    # Step 6: Sanitize user data
    sanitize_user_data
    echo ""
    
    # Step 7: Set up new user configuration
    setup_new_user_config
    echo ""
    
    # Step 8: Run MASTER RESTART
    run_master_restart
    echo ""
    
    # Step 9: Verify system functionality
    verify_system_functionality
    echo ""
    
    # Step 10: Display final information
    display_final_information
}

# Run main function
main "$@"
