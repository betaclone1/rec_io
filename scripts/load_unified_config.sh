#!/bin/bash

# UNIFIED CONFIGURATION LOADER
# Load unified configuration and set environment variables for use by other scripts

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[UNIFIED_CONFIG]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[UNIFIED_CONFIG] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[UNIFIED_CONFIG] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[UNIFIED_CONFIG] ❌${NC} $1"
}

# Function to detect script directory and project root
detect_paths() {
    # Get script directory (works regardless of where script is called from)
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    
    print_status "Detected paths:"
    print_status "  Script Directory: $SCRIPT_DIR"
    print_status "  Project Root: $PROJECT_ROOT"
}

# Function to load unified configuration
load_unified_config() {
    print_status "Loading unified configuration..."
    
    # Check if Python is available
    if ! command -v python3 &> /dev/null; then
        print_error "Python3 is not available"
        return 1
    fi
    
    # Use the test script to load configuration
    TEMP_SCRIPT="$SCRIPT_DIR/config/test_unified_config.py"
    
    # Run the Python script
    if python3 "$TEMP_SCRIPT" > /tmp/unified_config_output.json 2>/dev/null; then
        # Parse the JSON output
        if command -v jq &> /dev/null; then
            # Use jq if available
            REC_PROJECT_ROOT=$(jq -r '.project_root' /tmp/unified_config_output.json)
            REC_SYSTEM_HOST=$(jq -r '.system_host' /tmp/unified_config_output.json)
            REC_VENV_PATH=$(jq -r '.venv_path' /tmp/unified_config_output.json)
            REC_PYTHON_EXECUTABLE=$(jq -r '.python_executable' /tmp/unified_config_output.json)
            REC_ENVIRONMENT=$(jq -r '.environment' /tmp/unified_config_output.json)
            REC_DB_HOST=$(jq -r '.database_host' /tmp/unified_config_output.json)
            REC_DB_NAME=$(jq -r '.database_name' /tmp/unified_config_output.json)
            REC_DB_USER=$(jq -r '.database_user' /tmp/unified_config_output.json)
            REC_DB_PASSWORD=$(jq -r '.database_password' /tmp/unified_config_output.json)
            REC_DB_PORT=$(jq -r '.database_port' /tmp/unified_config_output.json)
            REC_VALIDATION_PASSED=$(jq -r '.validation_passed' /tmp/unified_config_output.json)
        else
            # Fallback to grep/sed if jq is not available
            REC_PROJECT_ROOT=$(grep '"project_root"' /tmp/unified_config_output.json | sed 's/.*"project_root": "\([^"]*\)".*/\1/')
            REC_SYSTEM_HOST=$(grep '"system_host"' /tmp/unified_config_output.json | sed 's/.*"system_host": "\([^"]*\)".*/\1/')
            REC_VENV_PATH=$(grep '"venv_path"' /tmp/unified_config_output.json | sed 's/.*"venv_path": "\([^"]*\)".*/\1/')
            REC_PYTHON_EXECUTABLE=$(grep '"python_executable"' /tmp/unified_config_output.json | sed 's/.*"python_executable": "\([^"]*\)".*/\1/')
            REC_ENVIRONMENT=$(grep '"environment"' /tmp/unified_config_output.json | sed 's/.*"environment": "\([^"]*\)".*/\1/')
            REC_DB_HOST=$(grep '"database_host"' /tmp/unified_config_output.json | sed 's/.*"database_host": "\([^"]*\)".*/\1/')
            REC_DB_NAME=$(grep '"database_name"' /tmp/unified_config_output.json | sed 's/.*"database_name": "\([^"]*\)".*/\1/')
            REC_DB_USER=$(grep '"database_user"' /tmp/unified_config_output.json | sed 's/.*"database_user": "\([^"]*\)".*/\1/')
            REC_DB_PASSWORD=$(grep '"database_password"' /tmp/unified_config_output.json | sed 's/.*"database_password": "\([^"]*\)".*/\1/')
            REC_DB_PORT=$(grep '"database_port"' /tmp/unified_config_output.json | sed 's/.*"database_port": \([0-9]*\).*/\1/')
            REC_VALIDATION_PASSED=$(grep '"validation_passed"' /tmp/unified_config_output.json | sed 's/.*"validation_passed": \(true\|false\).*/\1/')
        fi
        
        # Clean up temporary files
        rm -f /tmp/unified_config_output.json
        
        # Export environment variables
        export REC_PROJECT_ROOT
        export REC_SYSTEM_HOST
        export REC_VENV_PATH
        export REC_PYTHON_EXECUTABLE
        export REC_ENVIRONMENT
        export REC_DB_HOST
        export REC_DB_NAME
        export REC_DB_USER
        export REC_DB_PASSWORD
        export REC_DB_PORT
        export REC_VALIDATION_PASSED
        
        # Also set legacy variables for backward compatibility
        export PROJECT_ROOT="$REC_PROJECT_ROOT"
        export TRADING_SYSTEM_HOST="$REC_SYSTEM_HOST"
        export VENV_PATH="$REC_VENV_PATH"
        export PYTHON_PATH="$REC_PYTHON_EXECUTABLE"
        
        print_success "Unified configuration loaded successfully"
        print_status "Configuration Summary:"
        print_status "  Project Root: $REC_PROJECT_ROOT"
        print_status "  System Host: $REC_SYSTEM_HOST"
        print_status "  Virtual Env: $REC_VENV_PATH"
        print_status "  Python Executable: $REC_PYTHON_EXECUTABLE"
        print_status "  Environment: $REC_ENVIRONMENT"
        print_status "  Database Host: $REC_DB_HOST"
        print_status "  Database Name: $REC_DB_NAME"
        print_status "  Validation Passed: $REC_VALIDATION_PASSED"
        
        if [ "$REC_VALIDATION_PASSED" = "true" ]; then
            print_success "Configuration validation passed"
            return 0
        else
            print_warning "Configuration validation failed"
            return 1
        fi
        
    else
        print_error "Failed to load unified configuration"
        rm -f /tmp/unified_config_output.json
        return 1
    fi
}

# Function to validate required directories
validate_directories() {
    print_status "Validating required directories..."
    
    local missing_dirs=()
    
    # Check required directories
    if [ ! -d "$REC_PROJECT_ROOT" ]; then
        missing_dirs+=("Project root: $REC_PROJECT_ROOT")
    fi
    
    if [ ! -d "$REC_PROJECT_ROOT/backend" ]; then
        missing_dirs+=("Backend directory: $REC_PROJECT_ROOT/backend")
    fi
    
    if [ ! -d "$REC_PROJECT_ROOT/scripts" ]; then
        missing_dirs+=("Scripts directory: $REC_PROJECT_ROOT/scripts")
    fi
    
    if [ -n "$REC_VENV_PATH" ] && [ ! -d "$REC_VENV_PATH" ]; then
        missing_dirs+=("Virtual environment: $REC_VENV_PATH")
    fi
    
    if [ ${#missing_dirs[@]} -eq 0 ]; then
        print_success "All required directories exist"
        return 0
    else
        print_error "Missing required directories:"
        for dir in "${missing_dirs[@]}"; do
            print_error "  $dir"
        done
        return 1
    fi
}

# Prefer venv supervisor binaries. On macOS, PATH supervisord is often Homebrew supervisor
# 4.3.0 on Cellar Python 3.14; kqueue teardown during MASTER_RESTART can kill it and orphan children.
resolve_supervisor_binaries() {
    local venv_sup="${REC_VENV_PATH}/bin/supervisord"
    local venv_ctl="${REC_VENV_PATH}/bin/supervisorctl"

    if [ -x "$venv_sup" ] && [ -x "$venv_ctl" ]; then
        REC_SUPERVISORD="$venv_sup"
        REC_SUPERVISORCTL="$venv_ctl"
    elif command -v supervisord &> /dev/null && command -v supervisorctl &> /dev/null; then
        REC_SUPERVISORD="$(command -v supervisord)"
        REC_SUPERVISORCTL="$(command -v supervisorctl)"
        print_warning "Using PATH supervisord (venv binaries not found); prefer venv on macOS"
    else
        print_error "supervisord/supervisorctl not found"
        return 1
    fi

    export REC_SUPERVISORD REC_SUPERVISORCTL
    print_status "Supervisor binaries: $REC_SUPERVISORD"
    return 0
}

# Function to validate Python environment
validate_python_environment() {
    print_status "Validating Python environment..."
    
    if [ ! -f "$REC_PYTHON_EXECUTABLE" ]; then
        print_error "Python executable not found: $REC_PYTHON_EXECUTABLE"
        return 1
    fi
    
    # Try to run Python, but don't fail if it doesn't work (some systems have issues)
    if ! "$REC_PYTHON_EXECUTABLE" --version &> /dev/null; then
        print_warning "Python executable validation failed, but continuing: $REC_PYTHON_EXECUTABLE"
        print_warning "This may be due to system-specific Python configuration"
        return 0  # Don't fail, just warn
    fi
    
    print_success "Python environment validated"
    return 0
}

# Main function
main() {
    print_status "Loading unified configuration system..."
    
    # Detect paths
    detect_paths
    
    # Load unified configuration
    if ! load_unified_config; then
        print_error "Failed to load unified configuration"
        exit 1
    fi
    
    # Validate directories
    if ! validate_directories; then
        print_error "Directory validation failed"
        exit 1
    fi
    
    # Validate Python environment
    if ! validate_python_environment; then
        print_error "Python environment validation failed"
        exit 1
    fi

    if ! resolve_supervisor_binaries; then
        print_error "Supervisor binary resolution failed"
        exit 1
    fi
    
    print_success "Unified configuration system loaded successfully"
    print_status "Environment variables are now available for use by other scripts"
}

# Run main function
main "$@"
