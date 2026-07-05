#!/bin/bash

# =============================================================================
# GIT UPDATE SYSTEM FOR REC.IO COLLABORATORS
# =============================================================================
# This script allows collaborators to easily pull updates from the main
# repository and update their codebase without losing their local data.
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
PROJECT_ROOT="/opt/rec_io"
BACKUP_DIR="/opt/rec_io/backup"
UPDATE_LOG="/opt/rec_io/logs/git_update_$(date +%Y%m%d_%H%M%S).log"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[GIT_UPDATE]${NC} $1" | tee -a "$UPDATE_LOG"
}

print_success() {
    echo -e "${GREEN}[GIT_UPDATE] ✅${NC} $1" | tee -a "$UPDATE_LOG"
}

print_warning() {
    echo -e "${YELLOW}[GIT_UPDATE] ⚠️${NC} $1" | tee -a "$UPDATE_LOG"
}

print_error() {
    echo -e "${RED}[GIT_UPDATE] ❌${NC} $1" | tee -a "$UPDATE_LOG"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}" | tee -a "$UPDATE_LOG"
    echo -e "${PURPLE}                    REC.IO GIT UPDATE SYSTEM${NC}" | tee -a "$UPDATE_LOG"
    echo -e "${PURPLE}=============================================================================${NC}" | tee -a "$UPDATE_LOG"
}

_log_git_master_event() {
    local severity="$1"
    local message="$2"
    local py="python3"
    if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
        py="${PROJECT_ROOT}/.venv/bin/python"
    fi
    local detail_log
    detail_log="$(basename "$UPDATE_LOG")"
    if [[ -f "${PROJECT_ROOT}/scripts/ops/log_system_event.py" ]]; then
        "$py" "${PROJECT_ROOT}/scripts/ops/log_system_event.py" \
            --category DEPLOY --severity "$severity" \
            --message "$message" --source git_update \
            --detail-ref "$detail_log" 2>/dev/null || true
    fi
}

# Function to check if we're in a git repository
check_git_repository() {
    if [[ ! -d "$PROJECT_ROOT/.git" ]]; then
        print_error "Not a git repository. Cannot perform git operations."
        print_status "To enable git updates, run: git clone https://github.com/betaclone1/rec_io.git ."
        exit 1
    fi
}

# Function to create backup
create_backup() {
    print_status "Creating backup of current system..."
    
    # Create backup directory
    mkdir -p "$BACKUP_DIR"
    
    # Backup timestamp
    BACKUP_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_PATH="$BACKUP_DIR/pre_update_backup_$BACKUP_TIMESTAMP"
    
    # Create backup of critical files
    mkdir -p "$BACKUP_PATH"
    
    # Backup user data
    if [[ -d "$PROJECT_ROOT/backend/data/users" ]]; then
        cp -r "$PROJECT_ROOT/backend/data/users" "$BACKUP_PATH/"
        print_success "User data backed up"
    fi
    
    # Backup configuration files
    if [[ -f "$PROJECT_ROOT/backend/supervisord.conf" ]]; then
        cp "$PROJECT_ROOT/backend/supervisord.conf" "$BACKUP_PATH/"
    fi
    
    if [[ -f "$PROJECT_ROOT/.env" ]]; then
        cp "$PROJECT_ROOT/.env" "$BACKUP_PATH/"
    fi
    
    # Backup logs
    if [[ -d "$PROJECT_ROOT/logs" ]]; then
        cp -r "$PROJECT_ROOT/logs" "$BACKUP_PATH/"
    fi
    
    print_success "Backup created at: $BACKUP_PATH"
}

# Function to check git status
check_git_status() {
    print_status "Checking git repository status..."
    
    cd "$PROJECT_ROOT"
    
    # Check if there are local changes
    if [[ -n "$(git status --porcelain)" ]]; then
        print_warning "Local changes detected:"
        git status --short
        print_warning "Local changes will be stashed before pulling updates"
        return 1
    else
        print_success "No local changes detected"
        return 0
    fi
}

# Function to stash local changes
stash_local_changes() {
    print_status "Stashing local changes..."
    
    cd "$PROJECT_ROOT"
    
    # Stash any local changes
    if git stash push -m "Auto-stash before git pull $(date)" 2>/dev/null; then
        print_success "Local changes stashed successfully"
        return 0
    else
        print_warning "No changes to stash"
        return 0
    fi
}

# Function to pull updates
pull_updates() {
    print_status "Pulling updates from remote repository..."
    
    cd "$PROJECT_ROOT"
    
    # Fetch latest changes
    print_status "Fetching latest changes..."
    if git fetch origin; then
        print_success "Fetched latest changes"
    else
        print_error "Failed to fetch changes"
        return 1
    fi
    
    # Check if there are updates
    LOCAL_COMMIT=$(git rev-parse HEAD)
    REMOTE_COMMIT=$(git rev-parse origin/main)
    
    if [[ "$LOCAL_COMMIT" == "$REMOTE_COMMIT" ]]; then
        print_success "Already up to date with remote repository"
        return 0
    fi
    
    # Show what's being updated
    print_status "Updates available:"
    git log --oneline "$LOCAL_COMMIT..$REMOTE_COMMIT"
    
    # Pull the updates
    print_status "Pulling updates..."
    if git pull origin main; then
        print_success "Successfully pulled updates"
        return 0
    else
        print_error "Failed to pull updates"
        return 1
    fi
}

# Function to update dependencies
update_dependencies() {
    print_status "Updating Python dependencies..."
    
    cd "$PROJECT_ROOT"
    
    # Activate virtual environment
    if [[ -f "venv/bin/activate" ]]; then
        source venv/bin/activate
        
        # Update pip
        pip install --upgrade pip
        
        # Install/update requirements
        if [[ -f "requirements.txt" ]]; then
            pip install -r requirements.txt --upgrade
            print_success "Python dependencies updated"
        else
            print_warning "No requirements.txt found"
        fi
    else
        print_warning "Virtual environment not found"
    fi
}

# Function to regenerate configurations
regenerate_configurations() {
    print_status "Regenerating system configurations..."
    
    cd "$PROJECT_ROOT"
    
    # Make scripts executable
    chmod +x scripts/*.sh 2>/dev/null || true
    
    # Regenerate supervisor configuration if script exists
    if [[ -f "scripts/generate_supervisor_config.sh" ]]; then
        print_status "Regenerating supervisor configuration..."
        ./scripts/generate_supervisor_config.sh
        print_success "Supervisor configuration regenerated"
    fi
    
    # Regenerate system configurations if script exists
    if [[ -f "scripts/generate_system_configs.sh" ]]; then
        print_status "Regenerating system configurations..."
        ./scripts/generate_system_configs.sh
        print_success "System configurations regenerated"
    fi
}

# Function to restart services
restart_services() {
    print_status "Restarting services..."
    
    cd "$PROJECT_ROOT"
    
    # Stop all services
    print_status "Stopping all services..."
    if [[ -f "scripts/MASTER_RESTART.sh" ]]; then
        ./scripts/MASTER_RESTART.sh
        print_success "Services restarted successfully"
    else
        print_warning "MASTER_RESTART.sh not found"
    fi
}

# Function to verify update
verify_update() {
    print_status "Verifying update..."
    
    cd "$PROJECT_ROOT"
    
    # Check if services are running
    sleep 10  # Wait for services to start
    
    if command -v supervisorctl &> /dev/null; then
        print_status "Checking service status..."
        supervisorctl status 2>/dev/null || print_warning "Could not check supervisor status"
    fi
    
    # Check web interface
    print_status "Checking web interface..."
    if curl -f http://localhost:3000/health 2>/dev/null; then
        print_success "Web interface is responding"
    else
        print_warning "Web interface may not be responding"
    fi
    
    print_success "Update verification completed"
}

# Function to show update summary
show_update_summary() {
    print_header
    
    echo "" | tee -a "$UPDATE_LOG"
    echo "==========================================" | tee -a "$UPDATE_LOG"
    echo "        GIT UPDATE COMPLETED" | tee -a "$UPDATE_LOG"
    echo "==========================================" | tee -a "$UPDATE_LOG"
    echo "" | tee -a "$UPDATE_LOG"
    
    # Show what was updated
    cd "$PROJECT_ROOT"
    LOCAL_COMMIT=$(git rev-parse HEAD)
    echo "✅ Updated to commit: $(git log --oneline -1)" | tee -a "$UPDATE_LOG"
    _log_git_master_event info "Git update completed — $(git log --oneline -1)"
    echo "✅ Backup created at: $BACKUP_PATH" | tee -a "$UPDATE_LOG"
    echo "✅ Update log: $UPDATE_LOG" | tee -a "$UPDATE_LOG"
    echo "" | tee -a "$UPDATE_LOG"
    
    echo "📋 Next Steps:" | tee -a "$UPDATE_LOG"
    echo "1. Check the web interface: http://$(curl -s ifconfig.me):3000" | tee -a "$UPDATE_LOG"
    echo "2. Verify all features work correctly" | tee -a "$UPDATE_LOG"
    echo "3. Check logs if needed: tail -f logs/*.out.log" | tee -a "$UPDATE_LOG"
    echo "4. If issues occur, restore from backup: $BACKUP_PATH" | tee -a "$UPDATE_LOG"
    echo "" | tee -a "$UPDATE_LOG"
    
    print_success "Git update completed successfully!"
}

# Function to restore from backup
restore_from_backup() {
    print_status "Restoring from backup..."
    
    if [[ -z "$1" ]]; then
        print_error "Backup path not specified"
        print_status "Usage: $0 restore <backup_path>"
        exit 1
    fi
    
    BACKUP_PATH="$1"
    
    if [[ ! -d "$BACKUP_PATH" ]]; then
        print_error "Backup directory not found: $BACKUP_PATH"
        exit 1
    fi
    
    print_status "Restoring from: $BACKUP_PATH"
    
    # Stop services first
    cd "$PROJECT_ROOT"
    if [[ -f "scripts/MASTER_RESTART.sh" ]]; then
        ./scripts/MASTER_RESTART.sh 2>/dev/null || true
    fi
    
    # Restore user data
    if [[ -d "$BACKUP_PATH/users" ]]; then
        rm -rf backend/data/users
        cp -r "$BACKUP_PATH/users" backend/data/
        print_success "User data restored"
    fi
    
    # Restore configuration files
    if [[ -f "$BACKUP_PATH/supervisord.conf" ]]; then
        cp "$BACKUP_PATH/supervisord.conf" backend/
        print_success "Supervisor configuration restored"
    fi
    
    if [[ -f "$BACKUP_PATH/.env" ]]; then
        cp "$BACKUP_PATH/.env" .
        print_success "Environment configuration restored"
    fi
    
    # Restart services
    restart_services
    
    print_success "Restore completed successfully"
}

# Function to show help
show_help() {
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  update   - Pull latest updates and restart services (default)"
    echo "  check    - Check for available updates without applying them"
    echo "  backup   - Create backup of current system"
    echo "  restore  - Restore from backup (requires backup path)"
    echo "  help     - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0              # Update system"
    echo "  $0 check        # Check for updates"
    echo "  $0 backup       # Create backup"
    echo "  $0 restore /path/to/backup  # Restore from backup"
    echo ""
    echo "The update process will:"
    echo "1. Create a backup of your current system"
    echo "2. Stash any local changes"
    echo "3. Pull latest updates from the repository"
    echo "4. Update Python dependencies"
    echo "5. Regenerate system configurations"
    echo "6. Restart all services"
    echo "7. Verify the update was successful"
}

# Main function
main() {
    # Create log file
    touch "$UPDATE_LOG"
    
    # Check command line arguments
    case "${1:-update}" in
        "update")
            print_header
            print_status "Starting REC.IO git update process..."
            _log_git_master_event info "Git update started"
            
            # Check if we're in a git repository
            check_git_repository
            
            # Create backup
            create_backup
            
            # Check git status
            check_git_status || stash_local_changes
            
            # Pull updates
            pull_updates || {
                print_error "Failed to pull updates"
                _log_git_master_event critical "Git pull failed"
                exit 1
            }
            
            # Update dependencies
            update_dependencies
            
            # Regenerate configurations
            regenerate_configurations
            
            # Restart services
            restart_services
            
            # Verify update
            verify_update
            
            # Show summary
            show_update_summary
            ;;
        "check")
            print_header
            print_status "Checking for available updates..."
            
            check_git_repository
            
            cd "$PROJECT_ROOT"
            
            # Fetch latest changes
            git fetch origin
            
            # Check if there are updates
            LOCAL_COMMIT=$(git rev-parse HEAD)
            REMOTE_COMMIT=$(git rev-parse origin/main)
            
            if [[ "$LOCAL_COMMIT" == "$REMOTE_COMMIT" ]]; then
                print_success "System is up to date"
            else
                print_warning "Updates available:"
                git log --oneline "$LOCAL_COMMIT..$REMOTE_COMMIT"
                echo ""
                print_status "Run '$0 update' to apply these updates"
            fi
            ;;
        "backup")
            print_header
            create_backup
            ;;
        "restore")
            print_header
            restore_from_backup "$2"
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
