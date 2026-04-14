#!/bin/bash

# =============================================================================
# MASTER USERS MANAGEMENT SCRIPT
# =============================================================================
# This script provides utilities for managing system.master_users
# (and helper views under the system schema).
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
DB_HOST="localhost"
DB_NAME="rec_io_db"
DB_USER="rec_io_user"
DB_PASSWORD="rec_io_password"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[MASTER_USERS]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[MASTER_USERS] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[MASTER_USERS] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[MASTER_USERS] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    REC.IO MASTER USERS MANAGEMENT${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Function to run database query
run_query() {
    local query="$1"
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -t -c "$query"
}

# Function to show all users
show_all_users() {
    print_status "Showing all master users..."
    echo ""
    run_query "SELECT user_id, name, email, server_ip, registration_date, status FROM system.master_users ORDER BY registration_date DESC;"
}

# Function to show active users
show_active_users() {
    print_status "Showing active master users..."
    echo ""
    run_query "SELECT user_id, name, email, server_ip, last_updated FROM system.active_master_users;"
}

# Function to show recent registrations
show_recent_registrations() {
    print_status "Showing recent registrations (last 30 days)..."
    echo ""
    run_query "SELECT user_id, name, email, server_ip, registration_date FROM system.recent_master_registrations;"
}

# Function to show summary
show_summary() {
    print_status "Showing master users summary..."
    echo ""
    run_query "SELECT * FROM system.master_users_summary;"
}

# Function to add a user
add_user() {
    local user_id="$1"
    local name="$2"
    local email="$3"
    local phone="$4"
    local server_ip="$5"
    local server_hostname="$6"
    
    if [[ -z "$user_id" || -z "$name" || -z "$email" ]]; then
        print_error "Usage: $0 add-user <user_id> <name> <email> [phone] [server_ip] [server_hostname]"
        exit 1
    fi
    
    print_status "Adding user: $user_id"
    
    # user_no: next 4-digit slot (same rule as /api/auth/register); account_type default for ops-added rows.
    local query="INSERT INTO system.master_users (user_no, user_id, name, email, phone, server_ip, server_hostname, system_version, status, account_type) SELECT LPAD((SELECT COALESCE(MAX(CAST(TRIM(user_no) AS INTEGER)), 0) + 1 FROM system.master_users WHERE TRIM(user_no) ~ E'^[0-9]+\$')::text, 4, '0'), '$user_id', '$name', '$email', '${phone:-}', '${server_ip:-}', '${server_hostname:-}', 'REC.IO v2', 'active', 'user_basic' ON CONFLICT (user_id) DO UPDATE SET name = EXCLUDED.name, email = EXCLUDED.email, phone = EXCLUDED.phone, server_ip = EXCLUDED.server_ip, server_hostname = EXCLUDED.server_hostname, last_updated = CURRENT_TIMESTAMP;"
    
    if run_query "$query" > /dev/null 2>&1; then
        print_success "User $user_id added/updated successfully"
    else
        print_error "Failed to add user $user_id"
        exit 1
    fi
}

# Function to update user status
update_user_status() {
    local user_id="$1"
    local status="$2"
    
    if [[ -z "$user_id" || -z "$status" ]]; then
        print_error "Usage: $0 update-status <user_id> <active|inactive>"
        exit 1
    fi
    
    if [[ "$status" != "active" && "$status" != "inactive" ]]; then
        print_error "Status must be 'active' or 'inactive'"
        exit 1
    fi
    
    print_status "Updating user $user_id status to $status"
    
    local query="UPDATE system.master_users SET status = '$status', last_updated = CURRENT_TIMESTAMP WHERE user_id = '$user_id';"
    
    if run_query "$query" > /dev/null 2>&1; then
        print_success "User $user_id status updated to $status"
    else
        print_error "Failed to update user $user_id status"
        exit 1
    fi
}

# Function to add notes to user
add_user_notes() {
    local user_id="$1"
    local notes="$2"
    
    if [[ -z "$user_id" || -z "$notes" ]]; then
        print_error "Usage: $0 add-notes <user_id> <notes>"
        exit 1
    fi
    
    print_status "Adding notes to user $user_id"
    
    local query="UPDATE system.master_users SET notes = '$notes', last_updated = CURRENT_TIMESTAMP WHERE user_id = '$user_id';"
    
    if run_query "$query" > /dev/null 2>&1; then
        print_success "Notes added to user $user_id"
    else
        print_error "Failed to add notes to user $user_id"
        exit 1
    fi
}

# Function to delete user
delete_user() {
    local user_id="$1"
    
    if [[ -z "$user_id" ]]; then
        print_error "Usage: $0 delete-user <user_id>"
        exit 1
    fi
    
    print_warning "Are you sure you want to delete user $user_id? (y/N)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        print_status "Deleting user $user_id"
        
        local query="DELETE FROM system.master_users WHERE user_id = '$user_id';"
        
        if run_query "$query" > /dev/null 2>&1; then
            print_success "User $user_id deleted successfully"
        else
            print_error "Failed to delete user $user_id"
            exit 1
        fi
    else
        print_status "User deletion cancelled"
    fi
}

# Function to search users
search_users() {
    local search_term="$1"
    
    if [[ -z "$search_term" ]]; then
        print_error "Usage: $0 search <search_term>"
        exit 1
    fi
    
    print_status "Searching for users matching: $search_term"
    echo ""
    
    local query="SELECT user_id, name, email, server_ip, status FROM system.master_users WHERE user_id ILIKE '%$search_term%' OR name ILIKE '%$search_term%' OR email ILIKE '%$search_term%' OR server_ip ILIKE '%$search_term%' ORDER BY registration_date DESC;"
    
    run_query "$query"
}

# Function to show user details
show_user_details() {
    local user_id="$1"
    
    if [[ -z "$user_id" ]]; then
        print_error "Usage: $0 user-details <user_id>"
        exit 1
    fi
    
    print_status "Showing details for user: $user_id"
    echo ""
    
    local query="SELECT user_id, name, email, phone, server_ip, server_hostname, registration_date, last_updated, system_version, status, notes FROM system.master_users WHERE user_id = '$user_id';"
    
    run_query "$query"
}

# Function to show help
show_help() {
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  list                    Show all master users"
    echo "  active                  Show active users only"
    echo "  recent                  Show recent registrations (last 30 days)"
    echo "  summary                 Show summary statistics"
    echo "  add-user <id> <name> <email> [phone] [ip] [hostname]"
    echo "                          Add a new user"
    echo "  update-status <id> <active|inactive>"
    echo "                          Update user status"
    echo "  add-notes <id> <notes>  Add notes to user"
    echo "  delete-user <id>        Delete a user"
    echo "  search <term>           Search for users"
    echo "  user-details <id>       Show detailed user information"
    echo "  help                    Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 list                 # Show all users"
    echo "  $0 active               # Show active users"
    echo "  $0 add-user user_0002 'John Doe' 'john@example.com'"
    echo "  $0 update-status user_0002 inactive"
    echo "  $0 search 'john'        # Search for users with 'john'"
    echo "  $0 user-details user_0002"
}

# Main function
main() {
    case "${1:-help}" in
        "list")
            show_all_users
            ;;
        "active")
            show_active_users
            ;;
        "recent")
            show_recent_registrations
            ;;
        "summary")
            show_summary
            ;;
        "add-user")
            shift
            add_user "$@"
            ;;
        "update-status")
            shift
            update_user_status "$@"
            ;;
        "add-notes")
            shift
            add_user_notes "$@"
            ;;
        "delete-user")
            shift
            delete_user "$@"
            ;;
        "search")
            shift
            search_users "$@"
            ;;
        "user-details")
            shift
            show_user_details "$@"
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            show_help
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
