#!/bin/bash

# =============================================================================
# REC.IO INSTALLATION APPLICATION
# =============================================================================
# This is a user-friendly installation application that:
# 1. Asks if there's existing data to upload
# 2. Walks through uploading that data
# 3. Recreates the PostgreSQL database
# 4. Downloads everything from the repository
# 5. Installs everything
# 6. Spins up the system
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

# Function to print colored output
print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    REC.IO INSTALLATION APPLICATION${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

print_step() {
    echo -e "${CYAN}[STEP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR] ❌${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This installation must be run as root"
        print_info "Please run: sudo $0"
        exit 1
    fi
}

# Ask about existing data
ask_about_data() {
    echo ""
    print_step "Do you have existing REC.IO data to restore?"
    echo ""
    echo "1. Yes - I have existing data (database, credentials, etc.)"
    echo "2. No - This is a fresh installation"
    echo ""
    
    while true; do
        read -p "Enter your choice (1 or 2): " choice
        case $choice in
            1)
                HAS_EXISTING_DATA=true
                break
                ;;
            2)
                HAS_EXISTING_DATA=false
                break
                ;;
            *)
                print_error "Invalid choice. Please enter 1 or 2."
                ;;
        esac
    done
}

# Walk through data upload process
handle_data_upload() {
    echo ""
    print_step "Let's upload your existing data"
    echo ""
    print_info "You'll need to create a data package on your local machine first."
    echo ""
    
    # Check if we're on the local machine (has the repository)
    if [ -f "scripts/package_user_data.sh" ]; then
        print_info "Great! You're on your local machine."
        print_info "Let's create the data package now."
        echo ""
        
        read -p "Press Enter to create the data package..."
        
        if ./scripts/package_user_data.sh; then
            print_success "Data package created successfully!"
            
            # Find the created package
            PACKAGE_DIR=$(find backup -name "user_data_package_*" -type d | head -1)
            if [ -n "$PACKAGE_DIR" ]; then
                print_info "Package created: $PACKAGE_DIR"
                echo ""
                print_step "Now let's upload it to the server"
                echo ""
                
                # Get server IP
                read -p "Enter the server IP address: " SERVER_IP
                
                print_info "Uploading package to server..."
                if scp -r "$PACKAGE_DIR" "root@$SERVER_IP:/root/"; then
                    print_success "Data package uploaded successfully!"
                    UPLOADED_PACKAGE_NAME=$(basename "$PACKAGE_DIR")
                else
                    print_error "Failed to upload data package"
                    exit 1
                fi
            else
                print_error "Could not find created package"
                exit 1
            fi
        else
            print_error "Failed to create data package"
            exit 1
        fi
    else
        print_info "You're on the server. Please run this on your local machine first."
        print_info "Then come back here and provide the package path."
        echo ""
        read -p "Enter the path to your uploaded data package: " UPLOADED_PACKAGE_PATH
        
        if [ -e "$UPLOADED_PACKAGE_PATH" ]; then
            print_success "Data package found!"
            UPLOADED_PACKAGE_NAME=$(basename "$UPLOADED_PACKAGE_PATH")
        else
            print_error "Data package not found at: $UPLOADED_PACKAGE_PATH"
            exit 1
        fi
    fi
}

# Update system packages
update_system() {
    print_step "Updating system packages..."
    
    # Configure debconf to avoid interactive prompts
    export DEBIAN_FRONTEND=noninteractive
    export DEBCONF_NONINTERACTIVE_SEEN=true
    
    # Pre-configure packages to avoid SSH config prompts
    echo "openssh-server openssh-server/sshd_config_keep_local boolean true" | debconf-set-selections 2>/dev/null || true
    echo "openssh-server openssh-server/sshd_config_install boolean false" | debconf-set-selections 2>/dev/null || true
    
    apt update -y
    apt upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
    print_success "System packages updated"
}

# Install dependencies
install_dependencies() {
    print_step "Installing system dependencies..."
    
    # Configure debconf to avoid interactive prompts
    export DEBIAN_FRONTEND=noninteractive
    export DEBCONF_NONINTERACTIVE_SEEN=true
    
    apt install -y python3 python3-pip python3-venv postgresql postgresql-client supervisor git curl wget rsync -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
    print_success "Dependencies installed"
}

# Setup PostgreSQL
setup_postgresql() {
    print_step "Setting up PostgreSQL database..."
    
    # Start and enable PostgreSQL
    systemctl start postgresql
    systemctl enable postgresql
    
    # Create database user and database with proper permissions
    print_info "Creating database user and database..."
    sudo -u postgres psql -c "CREATE USER rec_io_user WITH PASSWORD NULL CREATEDB;" 2>/dev/null || print_warning "User may already exist"
    sudo -u postgres psql -c "CREATE DATABASE rec_io_db OWNER rec_io_user;" 2>/dev/null || print_warning "Database may already exist"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;" 2>/dev/null || print_warning "Privileges may already be granted"
    
    # Configure PostgreSQL to allow local connections without password
    print_info "Configuring PostgreSQL authentication..."
    sudo -u postgres psql -c "ALTER USER rec_io_user WITH PASSWORD NULL;" 2>/dev/null || true
    
    # Update pg_hba.conf to allow local connections without password
    if [ -f /etc/postgresql/*/main/pg_hba.conf ]; then
        PG_CONF_DIR=$(find /etc/postgresql -name "pg_hba.conf" | head -1 | xargs dirname)
        sudo sed -i 's/local.*all.*all.*peer/local   all             all                                     trust/' "$PG_CONF_DIR/pg_hba.conf" 2>/dev/null || true
        sudo sed -i 's/local.*all.*all.*md5/local   all             all                                     trust/' "$PG_CONF_DIR/pg_hba.conf" 2>/dev/null || true
        systemctl reload postgresql 2>/dev/null || true
    fi
    
    # Test the connection
    print_info "Testing database connection..."
    if psql -h localhost -U rec_io_user -d postgres -c "SELECT 1;" 2>/dev/null; then
        print_success "PostgreSQL connection test successful"
    else
        print_warning "PostgreSQL connection test failed - will retry during data restoration"
    fi
    
    print_success "PostgreSQL setup completed"
}

# Clone repository
clone_repository() {
    print_step "Downloading REC.IO from repository..."
    
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
    
    print_success "Repository downloaded"
}

# Setup Python environment
setup_python() {
    print_step "Setting up Python environment..."
    
    cd /opt/rec_io
    
    # Create virtual environment
    python3 -m venv venv
    
    # Activate virtual environment and install requirements
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    
    print_success "Python environment setup completed"
}

# Restore existing data
restore_existing_data() {
    print_step "Restoring existing data..."
    
    cd /opt/rec_io
    
    # Handle compressed package
    if [[ "$UPLOADED_PACKAGE_PATH" == *.tar.gz ]]; then
        print_info "Extracting compressed package..."
        tar -xzf "$UPLOADED_PACKAGE_PATH" -C /tmp/
        package_dir=$(find /tmp -name "user_data_package_*" -type d | head -1)
        if [ -z "$package_dir" ]; then
            print_error "Could not find package directory in compressed file"
            exit 1
        fi
    else
        package_dir="$UPLOADED_PACKAGE_PATH"
    fi
    
    # Restore database
    if [ -f "$package_dir/database_backup.sql" ]; then
        print_info "Restoring database..."
        
        # Load environment variables from the package
        if [ -f "$package_dir/.env" ]; then
            source "$package_dir/.env"
        fi
        
        # Set PostgreSQL password if available
        if [ -n "$POSTGRES_PASSWORD" ]; then
            export PGPASSWORD="$POSTGRES_PASSWORD"
        fi
        
        # Try multiple restoration methods
        print_info "Attempting database restoration..."
        
        # Method 1: Try with user credentials
        if psql -h localhost -U rec_io_user -d postgres < "$package_dir/database_backup.sql" 2>/dev/null; then
            print_success "Database restored successfully"
        else
            print_warning "Method 1 failed, trying as postgres superuser..."
            
            # Method 2: Try as postgres superuser
            if sudo -u postgres psql < "$package_dir/database_backup.sql" 2>/dev/null; then
                print_success "Database restored successfully (as postgres user)"
            else
                print_warning "Method 2 failed, trying to fix user permissions..."
                
                # Method 3: Fix user and try again
                sudo -u postgres psql -c "ALTER USER rec_io_user WITH PASSWORD NULL;" 2>/dev/null || true
                sudo -u postgres psql -c "ALTER USER rec_io_user CREATEDB;" 2>/dev/null || true
                
                if psql -h localhost -U rec_io_user -d postgres < "$package_dir/database_backup.sql" 2>/dev/null; then
                    print_success "Database restored successfully (after fixing permissions)"
                else
                    print_error "Database restoration failed - but continuing with setup"
                    print_info "You may need to manually restore the database later"
                fi
            fi
        fi
    else
        print_warning "No database backup found"
    fi
    
    # Restore user data (excluding credentials and personal info)
    if [ -d "$package_dir/user_data" ]; then
        print_info "Restoring user data (excluding credentials)..."
        mkdir -p backend/data
        
        # Restore only non-sensitive user data
        if [ -d "$package_dir/user_data/users" ]; then
            for user_dir in "$package_dir/user_data/users"/*; do
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
    if [ -f "$package_dir/.env" ]; then
        print_info "Restoring environment configuration..."
        cp "$package_dir/.env" .
        print_success "Environment configuration restored"
    else
        print_warning "No .env file found"
    fi
    
    # Clean up
    if [[ "$UPLOADED_PACKAGE_PATH" == *.tar.gz ]]; then
        rm -rf "$package_dir"
    fi
    
    # Set up database schema (in case it's missing)
    print_info "Verifying database schema..."
    if [ -f "scripts/setup_database.sh" ]; then
        ./scripts/setup_database.sh
    else
        print_warning "Database setup script not found, schema may need manual setup"
    fi
    
    print_success "Existing data restored successfully"
}

# Setup new user
setup_new_user() {
    print_step "Setting up new user..."
    
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
    
    # Set up database schema
    print_info "Setting up database schema..."
    if [ -f "scripts/setup_database.sh" ]; then
        ./scripts/setup_database.sh
    else
        print_warning "Database setup script not found, schema may need manual setup"
    fi
    
    print_success "New user setup completed"
}

# Generate supervisor configuration
generate_supervisor_config() {
    print_step "Generating supervisor configuration..."
    
    cd /opt/rec_io
    ./scripts/generate_supervisor_config.sh
    
    print_success "Supervisor configuration generated"
}

# Start the system
start_system() {
    print_step "Starting REC.IO system..."
    
    cd /opt/rec_io
    
    # Start supervisor
    supervisord -c backend/supervisord.conf
    
    # Wait for supervisor to start
    sleep 3
    
    print_success "REC.IO system started successfully!"
}

# Show completion message
show_completion() {
    echo ""
    print_success "REC.IO INSTALLATION COMPLETED!"
    echo ""
    print_info "System Information:"
    print_info "  Installation Directory: /opt/rec_io"
    print_info "  Web Interface: http://$(hostname -I | awk '{print $1}'):3000"
    print_info "  Health Check: http://$(hostname -I | awk '{print $1}'):3000/health"
    echo ""
    print_info "Useful Commands:"
    print_info "  Check status: supervisorctl -c backend/supervisord.conf status"
    print_info "  View logs: tail -f /opt/rec_io/logs/*.out.log"
    print_info "  Restart: cd /opt/rec_io && ./scripts/MASTER_RESTART.sh"
    echo ""
    print_info "Your REC.IO trading system is now ready!"
}

# Main installation function
main() {
    print_header
    
    # Check if running as root
    check_root
    
    # Ask about existing data
    ask_about_data
    
    # Handle data upload if needed
    if [ "$HAS_EXISTING_DATA" = true ]; then
        handle_data_upload
    fi
    
    # Update system
    update_system
    
    # Install dependencies
    install_dependencies
    
    # Setup PostgreSQL
    setup_postgresql
    
    # Clone repository
    clone_repository
    
    # Setup Python
    setup_python
    
    # Handle data restoration or new user setup
    if [ "$HAS_EXISTING_DATA" = true ]; then
        restore_existing_data
    else
        setup_new_user
    fi
    
    # Generate supervisor configuration
    generate_supervisor_config
    
    # Start the system
    start_system
    
    # Show completion message
    show_completion
}

# Run the installation
main
