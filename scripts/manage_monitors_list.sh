#!/bin/bash

# Monitor List Management Script
# Supports multiple users (monitor_list_0001, monitor_list_0002, etc.)

set -e

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_HOST="${DB_HOST:-localhost}"
DB_NAME="${DB_NAME:-rec_io_db}"
DB_USER="${DB_USER:-rec_io_user}"
DB_PASSWORD="${DB_PASSWORD:-rec_io_password}"
DB_PORT="${DB_PORT:-5432}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to get user number from user ID
get_user_number() {
    local user_id="$1"
    echo "${user_id#user_}"
}

# Function to create monitor_list table for a user
create_monitors_table() {
    local user_id="$1"
    local user_number=$(get_user_number "$user_id")
    
    log_info "Creating monitor_list table for user $user_id (user_$user_number)..."
    
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" << EOF
        -- Create sequence for 5-digit IDs starting with 10001
        CREATE SEQUENCE IF NOT EXISTS users.monitor_list_${user_number}_id_seq
        START WITH 10001
        INCREMENT BY 1
        MINVALUE 10001
        MAXVALUE 99999
        CYCLE;
        
        -- Create monitor_list table
CREATE TABLE IF NOT EXISTS users.monitor_list_${user_number} (
    id INTEGER PRIMARY KEY DEFAULT nextval('users.monitor_list_${user_number}_id_seq'),
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
        
        -- Grant privileges
        GRANT ALL PRIVILEGES ON TABLE users.monitor_list_${user_number} TO rec_io_user;
GRANT USAGE, SELECT ON SEQUENCE users.monitor_list_${user_number}_id_seq TO rec_io_user;
EOF
    
    log_success "Created monitor_list_${user_number} table for user $user_id"
}

# Function to list all monitors for a user
list_monitors() {
    local user_id="$1"
    local user_number=$(get_user_number "$user_id")
    
    log_info "Listing monitors for user $user_id..."
    
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" -c "
        SELECT 
            id,
            name,
            symbol,
            strategy,
            auto_trade,
            auto_trade_status,
            trades,
            win_loss,
            ret_pct,
            pnl,
            bankroll_allotment,
            status,
            created
        FROM users.monitor_list_${user_number}
        ORDER BY id;
    "
}

# Function to add a new monitor
add_monitor() {
    local user_id="$1"
    local name="$2"
    local symbol="$3"
    local strategy="$4"
    local auto_trade="${5:-false}"
    local bankroll_allotment="${6:-0.0}"
    
    local user_number=$(get_user_number "$user_id")
    
    log_info "Adding monitor '$name' for user $user_id..."
    
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" -c "
        INSERT INTO users.monitor_list_${user_number} (
            name, symbol, strategy, auto_trade, bankroll_allotment
        ) VALUES (
            '$name', '$symbol', '$strategy', $auto_trade, $bankroll_allotment
        ) RETURNING id;
    "
    
    log_success "Added monitor '$name' for user $user_id"
}

# Function to update monitor status
update_monitor_status() {
    local user_id="$1"
    local monitor_id="$2"
    local status="$3"
    
    local user_number=$(get_user_number "$user_id")
    
    log_info "Updating monitor $monitor_id status to '$status' for user $user_id..."
    
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" -c "
        UPDATE users.monitors_list_${user_number}
        SET status = '$status'
        WHERE id = $monitor_id;
    "
    
    log_success "Updated monitor $monitor_id status to '$status'"
}

# Function to update auto trade status - REMOVED: now controlled by auto_entry_supervisor
# update_auto_trade_status() {
#     local user_id="$1"
#     local monitor_id="$2"
#     local auto_trade_status="$3"
#     
#     local user_number=$(get_user_number "$user_id")
#     
#     log_info "Updating monitor $monitor_id auto trade status to '$auto_trade_status' for user $user_id..."
#     
#     PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" -c "
#         UPDATE users.monitor_list_${user_number}
#         SET auto_trade_status = '$auto_trade_status'
#         WHERE id = $monitor_id;
#     "
#     
#     log_success "Updated monitor $monitor_id auto trade status to '$auto_trade_status'"
# }

# Function to delete a monitor
delete_monitor() {
    local user_id="$1"
    local monitor_id="$2"
    
    local user_number=$(get_user_number "$user_id")
    
    log_warning "Deleting monitor $monitor_id for user $user_id..."
    
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" -c "
        DELETE FROM users.monitor_list_${user_number}
        WHERE id = $monitor_id;
    "
    
    log_success "Deleted monitor $monitor_id for user $user_id"
}

# Function to show monitor details
show_monitor() {
    local user_id="$1"
    local monitor_id="$2"
    
    local user_number=$(get_user_number "$user_id")
    
    log_info "Showing details for monitor $monitor_id (user $user_id)..."
    
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" -c "
        SELECT 
            id,
            name,
            symbol,
            strategy,
            auto_trade,
            auto_trade_status,
            trades,
            win_loss,
            ret_pct,
            pnl,
            bankroll_allotment,
            status,
            created
        FROM users.monitor_list_${user_number}
        WHERE id = $monitor_id;
    "
}

# Function to show usage
show_usage() {
    echo "Monitor List Management Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  create-table <user_id>                    - Create monitor_list table for user"
    echo "  list <user_id>                            - List all monitors for user"
    echo "  add <user_id> <name> <symbol> <strategy> [auto_trade] [bankroll] - Add new monitor"
    echo "  update-status <user_id> <monitor_id> <status> - Update monitor status"
    echo "  # update-auto-trade command removed - auto_trade_status now controlled by auto_entry_supervisor"
    echo "  delete <user_id> <monitor_id>             - Delete monitor"
    echo "  show <user_id> <monitor_id>               - Show monitor details"
    echo "  help                                       - Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 create-table user_0001"
    echo "  $0 list user_0001"
    echo "  $0 add user_0001 'BTC Monitor' BTC momentum_based true 25.0"
    echo "  $0 update-status user_0001 10001 active"
    echo "  # $0 update-auto-trade user_0001 10001 paused  # Command removed"
    echo "  $0 delete user_0001 10001"
    echo "  $0 show user_0001 10001"
    echo ""
    echo "Status values: active, inactive, archived, paused, off"
    echo "Auto trade status values: active, inactive, paused, off"
}

# Main script logic
case "${1:-help}" in
    "create-table")
        if [ -z "$2" ]; then
            log_error "User ID required"
            show_usage
            exit 1
        fi
        create_monitors_table "$2"
        ;;
    "list")
        if [ -z "$2" ]; then
            log_error "User ID required"
            show_usage
            exit 1
        fi
        list_monitors "$2"
        ;;
    "add")
        if [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ] || [ -z "$5" ]; then
            log_error "User ID, name, symbol, and strategy required"
            show_usage
            exit 1
        fi
        add_monitor "$2" "$3" "$4" "$5" "${6:-false}" "${7:-0.0}"
        ;;
    "update-status")
        if [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ]; then
            log_error "User ID, monitor ID, and status required"
            show_usage
            exit 1
        fi
        update_monitor_status "$2" "$3" "$4"
        ;;
    # "update-auto-trade" command removed - auto_trade_status now controlled by auto_entry_supervisor
    "delete")
        if [ -z "$2" ] || [ -z "$3" ]; then
            log_error "User ID and monitor ID required"
            show_usage
            exit 1
        fi
        delete_monitor "$2" "$3"
        ;;
    "show")
        if [ -z "$2" ] || [ -z "$3" ]; then
            log_error "User ID and monitor ID required"
            show_usage
            exit 1
        fi
        show_monitor "$2" "$3"
        ;;
    "help"|*)
        show_usage
        ;;
esac
