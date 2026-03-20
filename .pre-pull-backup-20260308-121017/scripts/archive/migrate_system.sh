#!/bin/bash

# REC.IO System Migration Script
# Wrapper for system_migration_tool.py

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the project directory
if [ ! -f "backend/main.py" ]; then
    print_error "Please run this script from the REC.IO project root directory"
    exit 1
fi

# Check if Python script exists
if [ ! -f "scripts/system_migration_tool.py" ]; then
    print_error "System migration tool not found: scripts/system_migration_tool.py"
    exit 1
fi

# Check if PostgreSQL is running
if ! pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
    print_error "PostgreSQL is not running. Please start PostgreSQL first."
    exit 1
fi

# Check if database exists
if ! psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT 1;" > /dev/null 2>&1; then
    print_error "Cannot connect to rec_io_db database. Please check your database configuration."
    exit 1
fi

# Function to show usage
show_usage() {
    echo "REC.IO System Migration Tool"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  create              Create a complete system migration package"
    echo ""
    echo "Examples:"
    echo "  $0 create"
    echo ""
    echo "Migration packages are stored in: backup/system_migrations/"
    echo ""
    echo "Next steps after creating migration package:"
    echo "1. Upload the package to cloud storage (Google Drive, Dropbox, etc.)"
    echo "2. On new machine: git clone <your-repo-url>"
    echo "3. Download and extract the migration package"
    echo "4. Run: ./install_on_new_machine.sh"
}

# Main script logic
case "$1" in
    create)
        print_status "Creating system migration package..."
        print_warning "This will create a large package (500MB+) with all your data"
        print_warning "Make sure you have enough disk space available"
        
        # Confirm creation
        read -p "Continue with migration package creation? (yes/no): " confirm
        if [ "$confirm" != "yes" ]; then
            print_error "Migration cancelled"
            exit 1
        fi
        
        python scripts/system_migration_tool.py create
        if [ $? -eq 0 ]; then
            print_success "Migration package created successfully!"
            print_status "Next steps:"
            print_status "1. Upload the package to cloud storage"
            print_status "2. On new machine: git clone <your-repo-url>"
            print_status "3. Download and extract the migration package"
            print_status "4. Run: ./install_on_new_machine.sh"
        else
            print_error "Migration package creation failed!"
            exit 1
        fi
        ;;
    
    *)
        show_usage
        exit 1
        ;;
esac
