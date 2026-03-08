#!/bin/bash

# =============================================================================
# SMART DEPLOYMENT SCRIPT
# =============================================================================
# This script deploys the REC.IO trading system with options to:
# 1. Set up a new user (fresh installation)
# 2. Restore existing user data from backup
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[DEPLOY]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[DEPLOY] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[DEPLOY] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[DEPLOY] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    REC.IO SMART DEPLOYMENT${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run as root"
        print_status "Please run: sudo $0"
        exit 1
    fi
}

# Update system packages
update_system() {
    print_status "Updating system packages..."
    apt update -y
    apt upgrade -y
    print_success "System packages updated"
}

# Install dependencies
install_dependencies() {
    print_status "Installing system dependencies..."
    apt install -y python3 python3-pip python3-venv postgresql postgresql-client supervisor git curl wget rsync
    print_success "Dependencies installed"
}

# Setup PostgreSQL
setup_postgresql() {
    print_status "Setting up PostgreSQL..."
    
    # Start and enable PostgreSQL
    systemctl start postgresql
    systemctl enable postgresql
    
    # Create database user and database
    sudo -u postgres psql -c "CREATE USER rec_io_user WITH PASSWORD '';" 2>/dev/null || print_warning "User may already exist"
    sudo -u postgres psql -c "CREATE DATABASE rec_io_db;" 2>/dev/null || print_warning "Database may already exist"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;" 2>/dev/null || print_warning "Privileges may already be granted"
    
    print_success "PostgreSQL setup completed"
}

# Clone repository
clone_repository() {
    print_status "Cloning REC.IO repository..."
    
    DEPLOY_DIR="/opt/rec_io"
    mkdir -p "$DEPLOY_DIR"
    cd "$DEPLOY_DIR"
    
    # Clone the repository
    if [ -d ".git" ]; then
        print_warning "Repository already exists, pulling latest changes..."
        git pull origin main
    else
        git clone https://github.com/betaclone1/rec_io.git .
    fi
    
    # Make scripts executable
    chmod +x scripts/*.sh
    
    print_success "Repository cloned to $DEPLOY_DIR"
}

# Setup Python environment
setup_python() {
    print_status "Setting up Python environment..."
    
    cd /opt/rec_io
    
    # Create virtual environment
    python3 -m venv venv
    source venv/bin/activate
    
    # Install dependencies
    pip install --upgrade pip
    pip install -r requirements.txt
    
    print_success "Python environment setup completed"
}

# Generate supervisor configuration
generate_supervisor_config() {
    print_status "Generating supervisor configuration..."
    
    cd /opt/rec_io
    ./scripts/generate_supervisor_config.sh
    
    print_success "Supervisor configuration generated"
}

# Ask user about existing data
ask_about_existing_data() {
    echo ""
    print_status "Do you have existing user data to restore?"
    echo "1. No - Set up a new user (fresh installation)"
    echo "2. Yes - I have a backup file to restore"
    echo ""
    read -p "Enter your choice (1 or 2): " choice
    
    case $choice in
        1)
            setup_new_user
            ;;
        2)
            restore_existing_data
            ;;
        *)
            print_error "Invalid choice. Please run the script again."
            exit 1
            ;;
    esac
}

# Setup new user
setup_new_user() {
    print_status "Setting up new user..."
    
    cd /opt/rec_io
    
    # Create basic user structure
    mkdir -p backend/data/users/user_0001/credentials
    mkdir -p backend/data/users/user_0001/preferences
    
    # Create basic .env file
    cat > .env << EOF
# PostgreSQL Connection Settings
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rec_io_db
POSTGRES_USER=rec_io_user
POSTGRES_PASSWORD=

# Trading System Configuration
TRADING_SYSTEM_HOST=localhost
REC_BIND_HOST=localhost
REC_TARGET_HOST=localhost
EOF
    
    print_success "New user setup completed"
    print_status "You can add Kalshi credentials later to enable trading services"
}

# Restore existing data
restore_existing_data() {
    print_status "Restoring existing user data..."
    
    echo ""
    print_status "Please provide the path to your backup file:"
    print_status "Options:"
    print_status "  - Full path to backup directory (e.g., /root/complete_system_backup_20250101_120000)"
    print_status "  - Full path to compressed backup (e.g., /root/complete_system_backup_20250101_120000.tar.gz)"
    echo ""
    read -p "Enter backup path: " backup_path
    
    if [ ! -e "$backup_path" ]; then
        print_error "Backup path not found: $backup_path"
        exit 1
    fi
    
    cd /opt/rec_io
    
    # Handle compressed backup
    if [[ "$backup_path" == *.tar.gz ]]; then
        print_status "Extracting compressed backup..."
        tar -xzf "$backup_path" -C /tmp/
        backup_dir=$(find /tmp -name "complete_system_backup_*" -type d | head -1)
        if [ -z "$backup_dir" ]; then
            print_error "Could not find backup directory in compressed file"
            exit 1
        fi
    else
        backup_dir="$backup_path"
    fi
    
    # Restore database
    if [ -f "$backup_dir/database_backup.sql" ]; then
        print_status "Restoring database..."
        if psql -h localhost -U rec_io_user -d postgres < "$backup_dir/database_backup.sql"; then
            print_success "Database restored successfully"
        else
            print_error "Database restoration failed"
            exit 1
        fi
    else
        print_warning "No database backup found"
    fi
    
    # Restore user data (excluding credentials and personal info)
    if [ -d "$backup_dir/user_data" ]; then
        print_status "Restoring user data (excluding credentials)..."
        mkdir -p backend/data
        
        # Restore only non-sensitive user data
        if [ -d "$backup_dir/user_data/users" ]; then
            for user_dir in "$backup_dir/user_data/users"/*; do
                if [ -d "$user_dir" ]; then
                    user_name=$(basename "$user_dir")
                    mkdir -p "backend/data/users/$user_name"
                    
                    # Restore trade history, accounts, active trades, monitors
                    for subdir in trade_history accounts active_trades monitors; do
                        if [ -d "$user_dir/$subdir" ]; then
                            cp -r "$user_dir/$subdir" "backend/data/users/$user_name/"
                        fi
                    done
                fi
            done
        fi
        
        print_success "User data restored (credentials excluded - must be added manually)"
    else
        print_warning "No user data found"
    fi
    
    # Restore .env file
    if [ -f "$backup_dir/.env" ]; then
        print_status "Restoring environment configuration..."
        cp "$backup_dir/.env" .
        print_success "Environment configuration restored"
    else
        print_warning "No .env file found, creating default"
        setup_new_user
    fi
    
    # Clean up
    if [[ "$backup_path" == *.tar.gz ]]; then
        rm -rf "$backup_dir"
    fi
    
    print_success "Existing data restored successfully"
}

# Start core services
start_core_services() {
    print_status "Starting core services..."
    
    cd /opt/rec_io
    
    # Start supervisor
    supervisord -c backend/supervisord.conf
    
    # Wait for services to start
    sleep 5
    
    # Check status
    supervisorctl -c backend/supervisord.conf status
    
    print_success "Core services started"
}

# Provide next steps
show_next_steps() {
    echo ""
    print_success "Deployment completed successfully!"
    echo ""
    print_status "System Information:"
    print_status "  Installation Directory: /opt/rec_io"
    print_status "  Web Interface: http://$(hostname -I | awk '{print $1}'):3000"
    print_status "  Health Check: http://$(hostname -I | awk '{print $1}'):3000/health"
    echo ""
    print_status "Next Steps:"
    print_status "  1. Access the web interface to verify it's working"
    print_status "  2. If you want to enable trading services:"
    print_status "     - Add Kalshi credentials to /opt/rec_io/backend/data/users/user_0001/credentials/"
    print_status "     - Start trading services: supervisorctl -c backend/supervisord.conf start active_trade_supervisor kalshi_account_sync"
    echo ""
    print_status "Useful Commands:"
    print_status "  Check status: supervisorctl -c backend/supervisord.conf status"
    print_status "  View logs: tail -f /opt/rec_io/logs/*.out.log"
    print_status "  Restart: cd /opt/rec_io && ./scripts/MASTER_RESTART.sh"
    print_status "  Test DB: cd /opt/rec_io && ./scripts/test_database.sh"
}

# Main deployment function
deploy_system() {
    print_header
    print_status "Starting REC.IO smart deployment..."
    echo ""
    
    check_root
    update_system
    install_dependencies
    setup_postgresql
    clone_repository
    setup_python
    generate_supervisor_config
    ask_about_existing_data
    start_core_services
    show_next_steps
}

# Help function
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Smart deployment of the REC.IO trading system."
    echo ""
    echo "This script will:"
    echo "  - Update system packages"
    echo "  - Install required dependencies"
    echo "  - Setup PostgreSQL database"
    echo "  - Clone the repository"
    echo "  - Setup Python environment"
    echo "  - Ask about existing user data"
    echo "  - Start core services"
    echo ""
    echo "Options:"
    echo "  --help, -h     Show this help message"
    echo "  --new-user     Skip prompts and setup new user"
    echo "  --restore PATH Skip prompts and restore from backup path"
    echo ""
    echo "Prerequisites:"
    echo "  - Run as root (sudo)"
    echo "  - Internet connection"
    echo "  - Backup file (if restoring existing data)"
}

# Parse command line arguments
NEW_USER=false
RESTORE_PATH=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --new-user)
            NEW_USER=true
            shift
            ;;
        --restore)
            RESTORE_PATH="$2"
            shift 2
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Main execution
if [ "$NEW_USER" = true ]; then
    print_header
    check_root
    update_system
    install_dependencies
    setup_postgresql
    clone_repository
    setup_python
    generate_supervisor_config
    setup_new_user
    start_core_services
    show_next_steps
elif [ -n "$RESTORE_PATH" ]; then
    print_header
    check_root
    update_system
    install_dependencies
    setup_postgresql
    clone_repository
    setup_python
    generate_supervisor_config
    backup_path="$RESTORE_PATH"
    restore_existing_data
    start_core_services
    show_next_steps
else
    deploy_system
fi
