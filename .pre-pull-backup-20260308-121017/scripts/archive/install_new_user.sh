#!/bin/bash

# REC.IO New User Installation Script
# Wrapper for new_user_installation.py

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
if [ ! -f "scripts/new_user_installation.py" ]; then
    print_error "New user installation tool not found: scripts/new_user_installation.py"
    exit 1
fi

# Function to show usage
show_usage() {
    echo "REC.IO New User Installation Tool"
    echo ""
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --check-requirements    Only check system requirements"
    echo "  --non-interactive       Run installation with default settings"
    echo ""
    echo "Examples:"
    echo "  $0                      # Interactive installation"
    echo "  $0 --check-requirements # Check system requirements only"
    echo "  $0 --non-interactive    # Non-interactive installation"
    echo ""
    echo "This tool is for NEW USERS who want to set up a fresh REC.IO system."
    echo "For existing users with data, use: ./scripts/migrate_system.sh create"
}

# Parse command line arguments
CHECK_ONLY=false
NON_INTERACTIVE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --check-requirements)
            CHECK_ONLY=true
            shift
            ;;
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Main script logic
if [ "$CHECK_ONLY" = true ]; then
    print_status "Checking system requirements..."
    python scripts/new_user_installation.py --check-requirements
    if [ $? -eq 0 ]; then
        print_success "System requirements check passed!"
    else
        print_error "System requirements check failed!"
        exit 1
    fi
else
    print_status "Starting REC.IO new user installation..."
    
    if [ "$NON_INTERACTIVE" = true ]; then
        print_warning "Running non-interactive installation with default settings"
        python scripts/new_user_installation.py --non-interactive
    else
        print_status "Running interactive installation..."
        print_status "You will be prompted for user information and preferences"
        python scripts/new_user_installation.py
    fi
    
    if [ $? -eq 0 ]; then
        print_success "Installation completed successfully!"
        print_status "Next steps:"
        print_status "1. Start the system: ./scripts/MASTER_RESTART.sh"
        print_status "2. Access the web interface: http://localhost:3000"
        print_status "3. Configure your trading preferences"
    else
        print_error "Installation failed!"
        exit 1
    fi
fi
