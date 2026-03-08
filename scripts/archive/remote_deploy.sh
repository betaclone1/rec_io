#!/bin/bash

# =============================================================================
# REMOTE DEPLOYMENT SCRIPT
# =============================================================================
# This script deploys the REC.IO trading system on a fresh Ubuntu 22.04 server.
# Run this script on the remote server after cloning the repository.
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
    echo -e "${PURPLE}                    REC.IO TRADING SYSTEM DEPLOYMENT${NC}"
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
    
    # Install required packages
    apt install -y python3 python3-pip python3-venv postgresql postgresql-client supervisor git curl wget
    
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

# Setup firewall (optional)
setup_firewall() {
    print_status "Setting up firewall..."
    
    # Allow SSH, HTTP, and our application ports
    ufw allow ssh
    ufw allow 3000/tcp  # Main app
    ufw allow 4000/tcp  # Trade manager
    ufw allow 8001/tcp  # Trade executor
    ufw allow 8007/tcp  # Active trade supervisor
    
    # Enable firewall
    ufw --force enable
    
    print_success "Firewall configured"
}

# Main deployment function
deploy_system() {
    print_header
    print_status "Starting REC.IO Trading System deployment..."
    echo ""
    
    # Check if we're in the project directory
    if [ ! -f "scripts/MASTER_RESTART.sh" ]; then
        print_error "Please run this script from the rec_io_20 project directory"
        print_status "Make sure you have cloned the repository first"
        exit 1
    fi
    
    # Make scripts executable
    print_status "Making scripts executable..."
    chmod +x scripts/*.sh
    print_success "Scripts made executable"
    
    # Run bootstrap script
    print_status "Running bootstrap script..."
    ./scripts/bootstrap_venv.sh
    print_success "Bootstrap completed"
    
    # Setup database
    print_status "Setting up database..."
    ./scripts/setup_database.sh
    print_success "Database setup completed"
    
    # Test database
    print_status "Testing database connectivity..."
    ./scripts/test_database.sh --quick
    print_success "Database test passed"
    
    # Generate supervisor config
    print_status "Generating supervisor configuration..."
    ./scripts/generate_supervisor_config.sh
    print_success "Supervisor configuration generated"
    
    # Start the system
    print_status "Starting all services..."
    ./scripts/MASTER_RESTART.sh
    print_success "Services started"
    
    # Wait a moment for services to initialize
    sleep 5
    
    # Check service status
    print_status "Checking service status..."
    supervisorctl -c backend/supervisord.conf status
    
    echo ""
    print_success "Deployment completed successfully!"
    echo ""
    print_status "System Information:"
    print_status "  Web Interface: http://$(hostname -I | awk '{print $1}'):3000"
    print_status "  Health Check: http://$(hostname -I | awk '{print $1}'):3000/health"
    print_status "  Logs Directory: $(pwd)/logs/"
    echo ""
    print_status "Useful Commands:"
    print_status "  Check status: supervisorctl -c backend/supervisord.conf status"
    print_status "  View logs: tail -f logs/unified_production_coordinator.out.log"
    print_status "  Restart: ./scripts/MASTER_RESTART.sh"
    print_status "  Test DB: ./scripts/test_database.sh"
}

# Help function
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Deploy the REC.IO trading system on Ubuntu 22.04"
    echo ""
    echo "Options:"
    echo "  --help, -h     Show this help message"
    echo "  --setup-only   Only setup system dependencies (don't deploy)"
    echo "  --no-firewall  Skip firewall configuration"
    echo ""
    echo "This script will:"
    echo "  - Update system packages"
    echo "  - Install required dependencies"
    echo "  - Setup PostgreSQL database"
    echo "  - Configure firewall (optional)"
    echo "  - Deploy the trading system"
    echo "  - Start all services"
    echo ""
    echo "Prerequisites:"
    echo "  - Run as root (sudo)"
    echo "  - Repository cloned to current directory"
    echo "  - Internet connection"
}

# Parse command line arguments
SETUP_ONLY=false
NO_FIREWALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --setup-only)
            SETUP_ONLY=true
            shift
            ;;
        --no-firewall)
            NO_FIREWALL=true
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Main execution
if [ "$SETUP_ONLY" = true ]; then
    print_header
    print_status "Running system setup only..."
    echo ""
    
    check_root
    update_system
    install_dependencies
    setup_postgresql
    
    if [ "$NO_FIREWALL" = false ]; then
        setup_firewall
    fi
    
    echo ""
    print_success "System setup completed!"
    print_status "You can now run the deployment script again without --setup-only"
else
    check_root
    update_system
    install_dependencies
    setup_postgresql
    
    if [ "$NO_FIREWALL" = false ]; then
        setup_firewall
    fi
    
    deploy_system
fi
