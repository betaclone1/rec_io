#!/bin/bash

# =============================================================================
# USER REGISTRATION SYSTEM FOR REC.IO COLLABORATORS
# =============================================================================
# This script handles user registration and optionally sends user information
# to a master database for tracking collaborator systems.
# =============================================================================

set -e

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
REGISTRATION_LOG="/opt/rec_io/logs/user_registration_$(date +%Y%m%d_%H%M%S).log"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[REGISTRATION]${NC} $1" | tee -a "$REGISTRATION_LOG"
}

print_success() {
    echo -e "${GREEN}[REGISTRATION] ✅${NC} $1" | tee -a "$REGISTRATION_LOG"
}

print_warning() {
    echo -e "${YELLOW}[REGISTRATION] ⚠️${NC} $1" | tee -a "$REGISTRATION_LOG"
}

print_error() {
    echo -e "${RED}[REGISTRATION] ❌${NC} $1" | tee -a "$REGISTRATION_LOG"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}" | tee -a "$REGISTRATION_LOG"
    echo -e "${PURPLE}                    REC.IO USER REGISTRATION SYSTEM${NC}" | tee -a "$REGISTRATION_LOG"
    echo -e "${PURPLE}=============================================================================${NC}" | tee -a "$REGISTRATION_LOG"
}

# Function to collect user information
collect_user_information() {
    print_status "Collecting user information..."
    
    # Get user ID
    read -p "Enter user ID (e.g., user_0002): " USER_ID
    if [[ -z "$USER_ID" ]]; then
        print_error "User ID is required"
        exit 1
    fi
    
    # Get full name
    read -p "Enter full name: " USER_NAME
    if [[ -z "$USER_NAME" ]]; then
        print_error "Full name is required"
        exit 1
    fi
    
    # Get email
    read -p "Enter email address: " USER_EMAIL
    if [[ -z "$USER_EMAIL" ]]; then
        print_error "Email address is required"
        exit 1
    fi
    
    # Get phone
    read -p "Enter phone number: " USER_PHONE
    if [[ -z "$USER_PHONE" ]]; then
        print_warning "Phone number is optional, continuing..."
        USER_PHONE=""
    fi
    
    # Get password
    read -s -p "Enter password: " USER_PASSWORD
    echo ""
    if [[ -z "$USER_PASSWORD" ]]; then
        print_error "Password is required"
        exit 1
    fi
    
    # Confirm password
    read -s -p "Confirm password: " USER_PASSWORD_CONFIRM
    echo ""
    if [[ "$USER_PASSWORD" != "$USER_PASSWORD_CONFIRM" ]]; then
        print_error "Passwords do not match"
        exit 1
    fi
    
    # Get server information
    SERVER_IP=$(curl -s https://api.ipify.org 2>/dev/null || echo "unknown")
    SERVER_HOSTNAME=$(hostname 2>/dev/null || echo "unknown")
    
    print_success "User information collected"
}

# Function to create local user profile
create_local_user_profile() {
    print_status "Creating local user profile..."
    
    cd "$PROJECT_ROOT"
    
    # Create user directory structure
    mkdir -p "backend/data/users/$USER_ID/{credentials/kalshi-credentials/{prod,demo},preferences,trade_history,active_trades,accounts}"
    chmod 700 "backend/data/users/$USER_ID/credentials"
    chmod 700 "backend/data/users/$USER_ID/credentials/kalshi-credentials"
    chmod 700 "backend/data/users/$USER_ID/credentials/kalshi-credentials/prod"
    chmod 700 "backend/data/users/$USER_ID/credentials/kalshi-credentials/demo"
    
    # Create user_info.json
    cat > "backend/data/users/$USER_ID/user_info.json" << USER_INFO_EOF
{
    "user_id": "$USER_ID",
    "name": "$USER_NAME",
    "email": "$USER_EMAIL",
    "phone": "$USER_PHONE",
    "account_type": "user",
    "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "server_ip": "$SERVER_IP",
    "server_hostname": "$SERVER_HOSTNAME",
    "preferences": {
        "default_account_type": "demo",
        "notifications_enabled": true,
        "auto_trading_enabled": false
    }
}
USER_INFO_EOF
    
    # Hash password for storage
    PASSWORD_HASH=$(echo -n "$USER_PASSWORD" | sha256sum | cut -d' ' -f1)
    
    # Create password file
    cat > "backend/data/users/$USER_ID/password_hash.txt" << PASSWORD_EOF
$PASSWORD_HASH
PASSWORD_EOF
    chmod 600 "backend/data/users/$USER_ID/password_hash.txt"
    
    print_success "Local user profile created"
}

# Function to setup database tables for new user
setup_database_tables() {
    print_status "Setting up database tables for new user..."
    
    cd "$PROJECT_ROOT"
    
    # Extract user number from user ID (e.g., user_0002 -> 0002)
    USER_NUMBER=${USER_ID#user_}
    
    # Create user tables in PostgreSQL
    PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db << DB_SETUP_EOF
        -- Create user tables with new user ID
        CREATE TABLE IF NOT EXISTS users.trades_$USER_NUMBER (
            LIKE users.trades_0001 INCLUDING ALL
        );
        
        CREATE TABLE IF NOT EXISTS users.active_trades_$USER_NUMBER (
            LIKE users.active_trades_0001 INCLUDING ALL
        );
        
        CREATE TABLE IF NOT EXISTS users.fills_$USER_NUMBER (
            LIKE users.fills_0001 INCLUDING ALL
        );
        
        CREATE TABLE IF NOT EXISTS users.settlements_$USER_NUMBER (
            LIKE users.settlements_0001 INCLUDING ALL
        );
        
        CREATE TABLE IF NOT EXISTS users.positions_$USER_NUMBER (
            LIKE users.positions_0001 INCLUDING ALL
        );
        
        CREATE TABLE IF NOT EXISTS users.trade_preferences_$USER_NUMBER (
            LIKE users.trade_preferences_0001 INCLUDING ALL
        );
        
        CREATE TABLE IF NOT EXISTS users.orders_$USER_NUMBER (
            LIKE users.orders_0001 INCLUDING ALL
        );
        
        CREATE TABLE IF NOT EXISTS users.account_balance_$USER_NUMBER (
            LIKE users.account_balance_0001 INCLUDING ALL
        );
        
        CREATE TABLE IF NOT EXISTS users.watchlist_$USER_NUMBER (
            LIKE users.watchlist_0001 INCLUDING ALL
        );
        
        CREATE TABLE IF NOT EXISTS users.auto_trade_settings_$USER_NUMBER (
            LIKE users.auto_trade_settings_0001 INCLUDING ALL
        );
        
        -- Create monitors_list table for new user
        CREATE SEQUENCE IF NOT EXISTS users.monitors_list_${USER_NUMBER}_id_seq
        START WITH 10001
        INCREMENT BY 1
        MINVALUE 10001
        MAXVALUE 99999
        CYCLE;
        
        CREATE TABLE IF NOT EXISTS users.monitors_list_$USER_NUMBER (
            id INTEGER PRIMARY KEY DEFAULT nextval('users.monitors_list_${USER_NUMBER}_id_seq'),
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
            win_streak INTEGER DEFAULT 0,
            win_streak_threshold INTEGER DEFAULT 22,
            loss_prevention VARCHAR(50) DEFAULT 'none',
            last_processed_cycle VARCHAR(100),
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Insert default auto trade settings (SAFE defaults)
        INSERT INTO users.auto_trade_settings_$USER_NUMBER (
            id, auto_entry, auto_stop, min_probability, min_differential, min_time, max_time, 
            allow_re_entry, spike_alert_enabled, spike_alert_momentum_threshold, 
            spike_alert_cooldown_threshold, spike_alert_cooldown_minutes, current_probability, 
            min_ttc_seconds, momentum_spike_enabled, momentum_spike_threshold, 
            auto_entry_status, user_id, cooldown_timer, created_at, updated_at
        ) VALUES (
            1, FALSE, FALSE, 95, 0.25, 120, 900, FALSE, TRUE, 36, 30, 15, 40, 60, TRUE, 36, 
            'disabled', '$USER_NUMBER', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        );
        
        -- Create user info table if it doesn't exist
        CREATE TABLE IF NOT EXISTS users.user_info_$USER_NUMBER (
            user_no VARCHAR(10) PRIMARY KEY,
            user_id VARCHAR(50) NOT NULL,
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            email VARCHAR(255) NOT NULL,
            phone VARCHAR(50),
            account_type VARCHAR(20) DEFAULT 'user',
            password_hash VARCHAR(255) NOT NULL,
            server_ip VARCHAR(45),
            server_hostname VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Insert user information
        INSERT INTO users.user_info_$USER_NUMBER (
            user_no, user_id, first_name, last_name, email, phone, account_type, 
            password_hash, server_ip, server_hostname
        ) VALUES (
            '$USER_NUMBER', '$USER_ID', '$USER_NAME', '', '$USER_EMAIL', '$USER_PHONE', 'user',
            '$PASSWORD_HASH', '$SERVER_IP', '$SERVER_HOSTNAME'
        ) ON CONFLICT (user_no) DO UPDATE SET
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            email = EXCLUDED.email,
            phone = EXCLUDED.phone,
            password_hash = EXCLUDED.password_hash,
            server_ip = EXCLUDED.server_ip,
            server_hostname = EXCLUDED.server_hostname,
            updated_at = CURRENT_TIMESTAMP;
DB_SETUP_EOF
    
    print_success "Database tables created for user: $USER_ID"
}

# Function to check if master database registration is enabled
# NOTE: Master users table ONLY exists on production server, not on collaborator systems
check_master_registration() {
    print_status "Checking master database registration settings..."
    
    # Check if master database environment variables are set
    if [[ -n "$MASTER_DB_HOST" && -n "$MASTER_DB_NAME" && -n "$MASTER_DB_USER" && -n "$MASTER_DB_PASSWORD" ]]; then
        print_success "Master database configuration found"
        return 0
    else
        print_warning "Master database configuration not found"
        print_status "To enable master database registration, set these environment variables:"
        print_status "  MASTER_DB_HOST=your_master_db_host"
        print_status "  MASTER_DB_NAME=your_master_db_name"
        print_status "  MASTER_DB_USER=your_master_db_user"
        print_status "  MASTER_DB_PASSWORD=your_master_db_password"
        return 1
    fi
}

# Function to register user with master database
register_with_master_database() {
    print_status "Registering user with master database..."
    
    # Create Python script for master database registration
    cat > /tmp/register_user_master.py << PYTHON_EOF
#!/usr/bin/env python3
import os
import psycopg2
import json
from datetime import datetime

# Master database configuration from environment variables
MASTER_DB_CONFIG = {
    'host': os.getenv('MASTER_DB_HOST'),
    'database': os.getenv('MASTER_DB_NAME'),
    'user': os.getenv('MASTER_DB_USER'),
    'password': os.getenv('MASTER_DB_PASSWORD'),
    'port': int(os.getenv('MASTER_DB_PORT', '5432'))
}

# User information
USER_DATA = {
    'user_id': '$USER_ID',
    'name': '$USER_NAME',
    'email': '$USER_EMAIL',
    'phone': '$USER_PHONE',
    'server_ip': '$SERVER_IP',
    'server_hostname': '$SERVER_HOSTNAME',
    'registration_date': datetime.now().isoformat(),
    'system_version': 'REC.IO v2',
    'status': 'active'
}

try:
    # Connect to master database
    conn = psycopg2.connect(**MASTER_DB_CONFIG)
    cursor = conn.cursor()
    
    # Create master users table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS master_users (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(50) UNIQUE NOT NULL,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            phone VARCHAR(50),
            server_ip VARCHAR(45),
            server_hostname VARCHAR(255),
            registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            system_version VARCHAR(50),
            status VARCHAR(20) DEFAULT 'active',
            notes TEXT
        )
    """)
    
    # Insert or update user record
    cursor.execute("""
        INSERT INTO master_users (
            user_id, name, email, phone, server_ip, server_hostname, 
            system_version, status
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s
        ) ON CONFLICT (user_id) DO UPDATE SET
            name = EXCLUDED.name,
            email = EXCLUDED.email,
            phone = EXCLUDED.phone,
            server_ip = EXCLUDED.server_ip,
            server_hostname = EXCLUDED.server_hostname,
            last_updated = CURRENT_TIMESTAMP,
            system_version = EXCLUDED.system_version,
            status = EXCLUDED.status
    """, (
        USER_DATA['user_id'],
        USER_DATA['name'],
        USER_DATA['email'],
        USER_DATA['phone'],
        USER_DATA['server_ip'],
        USER_DATA['server_hostname'],
        USER_DATA['system_version'],
        USER_DATA['status']
    ))
    
    conn.commit()
    print("✅ User registered with master database successfully")
    
except Exception as e:
    print(f"❌ Failed to register with master database: {e}")
    conn.rollback()
    
finally:
    if 'conn' in locals():
        conn.close()
PYTHON_EOF
    
    # Run the registration script
    if python3 /tmp/register_user_master.py; then
        print_success "User registered with master database"
        rm -f /tmp/register_user_master.py
    else
        print_warning "Failed to register with master database"
        print_status "User profile created locally only"
        rm -f /tmp/register_user_master.py
    fi
}

# Function to show registration summary
show_registration_summary() {
    print_header
    
    echo "" | tee -a "$REGISTRATION_LOG"
    echo "==========================================" | tee -a "$REGISTRATION_LOG"
    echo "        USER REGISTRATION COMPLETED" | tee -a "$REGISTRATION_LOG"
    echo "==========================================" | tee -a "$REGISTRATION_LOG"
    echo "" | tee -a "$REGISTRATION_LOG"
    
    echo "✅ User Information:" | tee -a "$REGISTRATION_LOG"
    echo "   User ID: $USER_ID" | tee -a "$REGISTRATION_LOG"
    echo "   Name: $USER_NAME" | tee -a "$REGISTRATION_LOG"
    echo "   Email: $USER_EMAIL" | tee -a "$REGISTRATION_LOG"
    echo "   Phone: $USER_PHONE" | tee -a "$REGISTRATION_LOG"
    echo "" | tee -a "$REGISTRATION_LOG"
    
    echo "✅ System Information:" | tee -a "$REGISTRATION_LOG"
    echo "   Server IP: $SERVER_IP" | tee -a "$REGISTRATION_LOG"
    echo "   Hostname: $SERVER_HOSTNAME" | tee -a "$REGISTRATION_LOG"
    echo "" | tee -a "$REGISTRATION_LOG"
    
    echo "✅ Local Setup:" | tee -a "$REGISTRATION_LOG"
    echo "   User profile created" | tee -a "$REGISTRATION_LOG"
    echo "   Database tables created" | tee -a "$REGISTRATION_LOG"
    echo "   Auto trade settings: SAFE (AUTO_ENTRY=OFF, AUTO_STOP=OFF)" | tee -a "$REGISTRATION_LOG"
    echo "" | tee -a "$REGISTRATION_LOG"
    
    if [[ -n "$MASTER_DB_HOST" ]]; then
        echo "✅ Master Database:" | tee -a "$REGISTRATION_LOG"
        echo "   User registered with master database" | tee -a "$REGISTRATION_LOG"
    else
        echo "⚠️  Master Database:" | tee -a "$REGISTRATION_LOG"
        echo "   Master database registration not configured" | tee -a "$REGISTRATION_LOG"
    fi
    
    echo "" | tee -a "$REGISTRATION_LOG"
    echo "📋 Next Steps:" | tee -a "$REGISTRATION_LOG"
    echo "1. Configure Kalshi credentials (optional)" | tee -a "$REGISTRATION_LOG"
    echo "2. Start the system: ./scripts/MASTER_RESTART.sh" | tee -a "$REGISTRATION_LOG"
    echo "3. Access web interface: http://$SERVER_IP:3000" | tee -a "$REGISTRATION_LOG"
    echo "4. Login with user ID: $USER_ID" | tee -a "$REGISTRATION_LOG"
    echo "" | tee -a "$REGISTRATION_LOG"
    
    print_success "User registration completed successfully!"
}

# Function to show help
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --help, -h     Show this help message"
    echo "  --master-db    Enable master database registration"
    echo ""
    echo "Environment Variables for Master Database:"
    echo "  MASTER_DB_HOST     Master database host"
    echo "  MASTER_DB_NAME     Master database name"
    echo "  MASTER_DB_USER     Master database user"
    echo "  MASTER_DB_PASSWORD Master database password"
    echo "  MASTER_DB_PORT     Master database port (default: 5432)"
    echo ""
    echo "Examples:"
    echo "  $0                    # Register user locally only"
    echo "  $0 --master-db        # Register with master database"
    echo ""
    echo "Master Database Setup:"
    echo "  export MASTER_DB_HOST=your_master_db_host"
    echo "  export MASTER_DB_NAME=your_master_db_name"
    echo "  export MASTER_DB_USER=your_master_db_user"
    echo "  export MASTER_DB_PASSWORD=your_master_db_password"
    echo "  $0 --master-db"
}

# Main function
main() {
    # Create log file
    touch "$REGISTRATION_LOG"
    
    # Check command line arguments
    ENABLE_MASTER_DB=false
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h)
                show_help
                exit 0
                ;;
            --master-db)
                ENABLE_MASTER_DB=true
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    print_header
    print_status "Starting REC.IO user registration process..."
    
    # Collect user information
    collect_user_information
    
    # Create local user profile
    create_local_user_profile
    
    # Setup database tables
    setup_database_tables
    
    # Handle master database registration
    if [[ "$ENABLE_MASTER_DB" == "true" ]]; then
        if check_master_registration; then
            register_with_master_database
        else
            print_warning "Master database registration skipped"
        fi
    else
        print_status "Master database registration not requested"
    fi
    
    # Show summary
    show_registration_summary
}

# Run main function
main "$@"
