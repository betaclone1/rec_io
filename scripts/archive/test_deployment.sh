#!/bin/bash

# Test script for Digital Ocean deployment
# Validates the deployment process without actually deploying

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[TEST] ✅${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[TEST] ⚠️${NC} $1"
}

log_error() {
    echo -e "${RED}[TEST] ❌${NC} $1"
}

# Get project root dynamically
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

log_info "Testing Digital Ocean deployment process..."

# Test 1: Check if we're in the right directory
log_info "Test 1: Checking project structure..."
if [[ -f "backend/main.py" ]]; then
    log_success "Project root is correct"
else
    log_error "Not in project root directory"
    exit 1
fi

# Test 2: Check if required scripts exist
log_info "Test 2: Checking required scripts..."
REQUIRED_SCRIPTS=(
    "scripts/deploy_digital_ocean.sh"
    "scripts/generate_supervisor_config.sh"
    "scripts/MASTER_RESTART.sh"
)

for script in "${REQUIRED_SCRIPTS[@]}"; do
    if [[ -f "$script" ]]; then
        log_success "Found $script"
    else
        log_error "Missing $script"
        exit 1
    fi
done

# Test 3: Check if scripts are executable
log_info "Test 3: Checking script permissions..."
for script in "${REQUIRED_SCRIPTS[@]}"; do
    if [[ -x "$script" ]]; then
        log_success "$script is executable"
    else
        log_warning "$script is not executable, making it executable..."
        chmod +x "$script"
    fi
done

# Test 4: Test supervisor config generation
log_info "Test 4: Testing supervisor config generation..."
if ./scripts/generate_supervisor_config.sh; then
    log_success "Supervisor config generation works"
else
    log_error "Supervisor config generation failed"
    exit 1
fi

# Test 5: Check if supervisor config is valid
log_info "Test 5: Validating supervisor config..."
if [[ -f "backend/supervisord.conf" ]]; then
    # Check if config file has basic required sections
    if grep -q "\[supervisord\]" backend/supervisord.conf && \
       grep -q "\[unix_http_server\]" backend/supervisord.conf && \
       grep -q "\[supervisorctl\]" backend/supervisord.conf; then
        log_success "Supervisor config structure is valid"
    else
        log_error "Supervisor config is missing required sections"
        exit 1
    fi
else
    log_error "Supervisor config not found"
    exit 1
fi

# Test 6: Check if backup directory can be created
log_info "Test 6: Testing backup directory creation..."
mkdir -p backup
if [[ -d "backup" ]]; then
    log_success "Backup directory can be created"
else
    log_error "Cannot create backup directory"
    exit 1
fi

# Test 7: Test deployment script syntax
log_info "Test 7: Testing deployment script syntax..."
if bash -n scripts/deploy_digital_ocean.sh; then
    log_success "Deployment script syntax is valid"
else
    log_error "Deployment script has syntax errors"
    exit 1
fi

# Test 8: Check if required files exist
log_info "Test 8: Checking required files..."
REQUIRED_FILES=(
    "requirements.txt"
    "backend/main.py"
    "backend/trade_manager.py"
    "backend/trade_executor.py"
    "backend/active_trade_supervisor.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [[ -f "$file" ]]; then
        log_success "Found $file"
    else
        log_error "Missing $file"
        exit 1
    fi
done

# Test 9: Check if virtual environment exists
log_info "Test 9: Checking virtual environment..."
if [[ -d "venv" ]]; then
    log_success "Virtual environment exists"
else
    log_warning "Virtual environment not found - will be created during deployment"
fi

# Test 10: Check if user data directories exist
log_info "Test 10: Checking user data directories..."
USER_DIRS=(
    "backend/data/users/user_0001"
    "backend/data/users/user_0001/credentials"
    "backend/data/users/user_0001/trade_history"
    "backend/data/users/user_0001/active_trades"
)

for dir in "${USER_DIRS[@]}"; do
    if [[ -d "$dir" ]]; then
        log_success "Found $dir"
    else
        log_warning "Missing $dir - will be created during deployment"
    fi
done

log_success "All deployment tests passed!"
log_info "The system is ready for Digital Ocean deployment."
log_info ""
log_info "To deploy, run:"
log_info "  ./scripts/deploy_digital_ocean.sh <your_droplet_ip>"

