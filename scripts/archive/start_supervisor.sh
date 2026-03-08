#!/bin/bash

# =============================================================================
# PORTABLE SUPERVISOR STARTUP SCRIPT
# =============================================================================
# This script sets up the environment variables needed for the supervisor
# configuration to work on any machine.
# =============================================================================

set -e  # Exit on any error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[SUPERVISOR_START]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUPERVISOR_START] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[SUPERVISOR_START] ⚠️${NC} $1"
}

# Get the project root directory (where this script is located)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
print_status "Project root: $PROJECT_ROOT"

# Find the virtual environment
if [ -d "$PROJECT_ROOT/venv" ]; then
    VENV_PATH="$PROJECT_ROOT/venv"
    print_success "Found virtual environment: $VENV_PATH"
elif [ -d "$PROJECT_ROOT/.venv" ]; then
    VENV_PATH="$PROJECT_ROOT/.venv"
    print_success "Found virtual environment: $VENV_PATH"
else
    print_warning "No virtual environment found in $PROJECT_ROOT/venv or $PROJECT_ROOT/.venv"
    print_warning "Please create a virtual environment first:"
    echo "  python -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Set environment variables for supervisor
export PROJECT_ROOT="$PROJECT_ROOT"
export VENV_PATH="$VENV_PATH"

print_status "Setting environment variables:"
print_status "  PROJECT_ROOT=$PROJECT_ROOT"
print_status "  VENV_PATH=$VENV_PATH"

# Ensure logs directory exists
mkdir -p "$PROJECT_ROOT/logs"
print_success "Ensured logs directory exists"

# Check if supervisor is already running
if [ -S "/tmp/supervisord.sock" ]; then
    print_warning "Supervisor appears to be already running"
    print_status "Use 'supervisorctl -c $PROJECT_ROOT/backend/supervisord.conf status' to check"
    print_status "Use 'supervisorctl -c $PROJECT_ROOT/backend/supervisord.conf shutdown' to stop"
    exit 0
fi

# Start supervisor
print_status "Starting supervisor..."
supervisord -c "$PROJECT_ROOT/backend/supervisord.conf"

# Wait a moment for supervisor to start
sleep 2

# Check if supervisor started successfully
if [ -S "/tmp/supervisord.sock" ]; then
    print_success "Supervisor started successfully!"
    print_status "Use 'supervisorctl -c $PROJECT_ROOT/backend/supervisord.conf status' to check services"
    print_status "Use 'supervisorctl -c $PROJECT_ROOT/backend/supervisord.conf shutdown' to stop"
else
    print_warning "Supervisor may not have started properly"
    print_status "Check logs at /tmp/supervisord.log for errors"
fi 