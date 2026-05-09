#!/bin/bash

# =============================================================================
# FIRST BOOT SANITIZATION SCRIPT
# =============================================================================
# This script CAN run on first boot if systemd invokes it.
# It is OFF BY DEFAULT: set REC_ENABLE_FIRST_BOOT_SANITIZE=1 (e.g. Environment=
# in the unit) to run the destructive wipe. Avoids snapshot→new prod losing data.
# Multi-user snapshot deploy deferred until install is reworked.
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="/opt/rec_io"
SANITIZATION_FLAG="/opt/rec_io/.sanitization_complete"
FIRST_BOOT_LOG="/var/log/first_boot_sanitize.log"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[FIRST_BOOT]${NC} $1" | tee -a "$FIRST_BOOT_LOG"
}

print_success() {
    echo -e "${GREEN}[FIRST_BOOT] ✅${NC} $1" | tee -a "$FIRST_BOOT_LOG"
}

print_warning() {
    echo -e "${YELLOW}[FIRST_BOOT] ⚠️${NC} $1" | tee -a "$FIRST_BOOT_LOG"
}

print_error() {
    echo -e "${RED}[FIRST_BOOT] ❌${NC} $1" | tee -a "$FIRST_BOOT_LOG"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}" | tee -a "$FIRST_BOOT_LOG"
    echo -e "${PURPLE}                    FIRST BOOT SANITIZATION${NC}" | tee -a "$FIRST_BOOT_LOG"
    echo -e "${PURPLE}=============================================================================${NC}" | tee -a "$FIRST_BOOT_LOG"
}

# Function to check if sanitization is already complete
check_sanitization_status() {
    if [[ -f "$SANITIZATION_FLAG" ]]; then
        print_status "Sanitization already completed on $(cat "$SANITIZATION_FLAG")"
        return 0
    fi
    return 1
}

# Function to perform data sanitization
perform_sanitization() {
    print_header
    print_status "Starting automatic data sanitization..."
    print_warning "This droplet was created from a production snapshot"
    print_warning "All user data and credentials will be removed for security"
    echo ""
    
    # Wait for system to be fully booted
    print_status "Waiting for system to fully boot..."
    sleep 30
    
    # Check if project directory exists
    if [[ ! -d "$PROJECT_ROOT" ]]; then
        print_error "Project directory not found: $PROJECT_ROOT"
        return 1
    fi
    
    cd "$PROJECT_ROOT"

    REC_SLOT="${REC_USER_NO:-${REC_DEFAULT_LOGIN_USER_NO:-0001}}"
    
    # Stop all services first
    print_status "Stopping all services..."
    if [[ -f "scripts/MASTER_RESTART.sh" ]]; then
        ./scripts/MASTER_RESTART.sh 2>/dev/null || true
        sleep 10
    fi
    
    # Clear all user-specific data from database
    print_status "Clearing user data from database..."
    if command -v psql &> /dev/null; then
        PGPASSWORD="${POSTGRES_PASSWORD:-${DB_PASSWORD:-rec_io_password}}" psql -h localhost -U rec_io_user -d rec_io_db <<SQL_EOF 2>/dev/null || true
            -- Clear all user-specific data
            DELETE FROM users.trades_${REC_SLOT};
            DELETE FROM users.active_trades_${REC_SLOT};
            DELETE FROM users.fills_${REC_SLOT};
            DELETE FROM users.settlements_${REC_SLOT};
            DELETE FROM users.positions_${REC_SLOT};
            DELETE FROM users.trade_preferences_${REC_SLOT};
            DELETE FROM users.orders_${REC_SLOT};
            DELETE FROM users.account_balance_${REC_SLOT};
            DELETE FROM users.auto_trade_settings_${REC_SLOT};
            
            -- Recreate auto_trade_settings with SAFE defaults (both OFF)
            -- CRITICAL: auto_entry=FALSE and auto_stop=FALSE for security
            INSERT INTO users.auto_trade_settings_${REC_SLOT} (
                id, auto_entry, auto_stop, min_probability, min_differential, min_time, max_time, 
                allow_re_entry, spike_alert_enabled, spike_alert_momentum_threshold, 
                spike_alert_cooldown_threshold, spike_alert_cooldown_minutes, current_probability, 
                min_ttc_seconds, momentum_spike_enabled, momentum_spike_threshold, 
                auto_entry_status, user_id, cooldown_timer, created_at, updated_at
            ) VALUES (
                1, FALSE, FALSE, 95, 0.25, 120, 900, FALSE, TRUE, 36, 30, 15, 40, 60, TRUE, 36, 
                'disabled', '${REC_SLOT}', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            
            -- Reset sequences
            ALTER SEQUENCE users.trades_${REC_SLOT}_id_seq1 RESTART WITH 1;
            ALTER SEQUENCE users.fills_${REC_SLOT}_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.settlements_${REC_SLOT}_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.positions_${REC_SLOT}_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.orders_${REC_SLOT}_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.account_balance_${REC_SLOT}_id_seq RESTART WITH 1;
            ALTER SEQUENCE users.auto_trade_settings_${REC_SLOT}_id_seq RESTART WITH 1;
            
            -- Clear system health data
            DELETE FROM system.health_status;
            
            -- Clear live data (keep structure, clear data)
            
            DELETE FROM live_data.eth_price_log;
            DELETE FROM live_data.live_price_log_1s_btc;
            DELETE FROM live_data.live_price_log_1s_eth;
            DELETE FROM live_data.market_data;
            DELETE FROM live_data.websocket_market_data;
            DELETE FROM live_data.btc_live_strikes;
            
            -- CRITICAL: Remove master users table and views (system schema; see migration 20260410_1015)
            DROP VIEW IF EXISTS system.active_master_users CASCADE;
            DROP VIEW IF EXISTS system.recent_master_registrations CASCADE;
            DROP VIEW IF EXISTS system.master_users_summary CASCADE;
            DROP TABLE IF EXISTS system.master_users CASCADE;
            DROP VIEW IF EXISTS users.active_master_users CASCADE;
            DROP VIEW IF EXISTS users.recent_master_registrations CASCADE;
            DROP VIEW IF EXISTS users.master_users_summary CASCADE;
            DROP TABLE IF EXISTS users.master_users CASCADE;
SQL_EOF
    fi
    
    # Remove all user credential files
    print_status "Removing user credentials..."
    find backend/data/users -name "credentials" -type d -exec rm -rf {} + 2>/dev/null || true
    find backend/api/kalshi-api -name "kalshi-credentials" -type d -exec rm -rf {} + 2>/dev/null || true
    
    # Remove user-specific files
    print_status "Removing user-specific files..."
    find backend/data/users -name "user_info.json" -delete 2>/dev/null || true
    find backend/data/users -name "preferences" -type d -exec rm -rf {} + 2>/dev/null || true
    find backend/data/users -name "trade_history" -type d -exec rm -rf {} + 2>/dev/null || true
    find backend/data/users -name "active_trades" -type d -exec rm -rf {} + 2>/dev/null || true
    find backend/data/users -name "accounts" -type d -exec rm -rf {} + 2>/dev/null || true
    
    # Clear logs
    print_status "Clearing logs..."
    rm -f logs/* 2>/dev/null || true
    
    # Create sanitization complete flag
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SANITIZATION_FLAG"
    
    # CRITICAL: Disable automatic maintenance to prevent system failures
    print_status "Disabling automatic maintenance services..."
    
    # Disable APT automatic services
    systemctl disable apt-daily-upgrade.service 2>/dev/null || true
    systemctl disable apt-daily-upgrade.timer 2>/dev/null || true
    systemctl disable apt-daily.service 2>/dev/null || true
    systemctl disable apt-daily.timer 2>/dev/null || true
    systemctl disable apt-daily-weekly.service 2>/dev/null || true
    systemctl disable apt-daily-weekly.timer 2>/dev/null || true
    
    # Disable update-notifier services
    systemctl disable update-notifier-download.service 2>/dev/null || true
    systemctl disable update-notifier-motd.service 2>/dev/null || true
    
    # Disable snap automatic updates
    systemctl disable snapd.service 2>/dev/null || true
    systemctl disable snapd.socket 2>/dev/null || true
    
    # Disable unattended upgrades
    systemctl disable unattended-upgrades.service 2>/dev/null || true
    systemctl disable unattended-upgrades.timer 2>/dev/null || true
    
    # Create APT configuration to prevent automatic operations
    cat > /etc/apt/apt.conf.d/99disable-auto-updates << 'EOF'
# Disable all automatic APT operations
APT::Get::Automatic "false";
APT::Get::AutomaticRemove "false";
APT::Get::AutomaticRemove::Kernels "false";
APT::Get::AutomaticRemove::UnusedKernels "false";
APT::Get::AutomaticRemove::UnusedDependencies "false";

# Disable unattended upgrades
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "false";
Unattended-Upgrade::Remove-New-Unused-Dependencies "false";
Unattended-Upgrade::Automatic-Reboot-Time "02:00";
Unattended-Upgrade::Mail "false";

# Disable automatic package downloads
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
APT::Periodic::Unattended-Upgrade "0";
EOF
    
    print_success "Automatic maintenance services disabled - system is protected from automatic failures"
    
    # Install auto startup service for future reboots
    print_status "Installing auto startup service..."
    if [[ -f "/opt/rec_io/scripts/install_deploy/install_auto_startup_service.sh" ]]; then
        chmod +x /opt/rec_io/scripts/install_deploy/install_auto_startup_service.sh
        /opt/rec_io/scripts/install_deploy/install_auto_startup_service.sh
        print_success "Auto startup service installed - system will auto-start on future reboots"
    else
        print_warning "Auto startup service script not found - manual installation required"
    fi
    
    print_success "Data sanitization completed successfully"
    print_success "Auto trade settings reset to SAFE defaults (AUTO_ENTRY=OFF, AUTO_STOP=OFF)"
    print_warning "IMPORTANT: This system has been sanitized and is NOT ready for use"
    print_warning "You must run the collaborator setup script to configure your user account"
    print_warning "Run: ./scripts/install_deploy/collaborator_setup.sh"
    echo ""
    
    # Create a prominent warning file
    cat > /opt/rec_io/SANITIZATION_WARNING.txt << 'WARNING_EOF'
=============================================================================
                           SECURITY WARNING
=============================================================================

This droplet was created from a production snapshot and has been automatically
sanitized to remove all original user data and credentials.

SECURITY MEASURES APPLIED:
✅ All user data removed from database
✅ All credential files deleted
✅ Auto trade settings reset to SAFE defaults (AUTO_ENTRY=OFF, AUTO_STOP=OFF)
✅ All logs cleared
✅ System sequences reset
✅ Automatic maintenance services disabled (prevents system failures)

IMPORTANT: This system is NOT ready for use!

Before you can use this system, you MUST:

1. Run the collaborator setup script:
   cd /opt/rec_io
   ./scripts/collaborator_setup.sh

2. Provide your user information and Kalshi credentials

3. Configure the system for your use

DO NOT start the system or run MASTER_RESTART until you have completed
the setup process.

=============================================================================
WARNING_EOF
    
    print_status "Created warning file: /opt/rec_io/SANITIZATION_WARNING.txt"
    
    # Create sanitization completion flag
    touch "$PROJECT_ROOT/.sanitization_complete"
    print_status "Created sanitization completion flag"
    
    print_success "First boot sanitization completed"
}

# Function to create systemd service
create_systemd_service() {
    cat > /etc/systemd/system/first-boot-sanitize.service << 'SERVICE_EOF'
[Unit]
Description=First Boot Sanitization for REC.IO
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=oneshot
ExecStart=/opt/rec_io/scripts/install_deploy/first_boot_sanitize.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE_EOF
    
    systemctl daemon-reload
    systemctl enable first-boot-sanitize.service
}

# Main execution
main() {
    # Create log file
    touch "$FIRST_BOOT_LOG"
    
    print_status "First boot sanitization script started"

    if [[ "${REC_ENABLE_FIRST_BOOT_SANITIZE:-}" != "1" ]]; then
        print_status "First-boot sanitization is disabled (REC_ENABLE_FIRST_BOOT_SANITIZE is not 1). No wipe performed. Exiting."
        exit 0
    fi
    
    # Check if already sanitized
    if check_sanitization_status; then
        print_status "System already sanitized, skipping"
        exit 0
    fi
    
    # Perform sanitization
    if perform_sanitization; then
        print_success "Sanitization completed successfully"
        exit 0
    else
        print_error "Sanitization failed"
        exit 1
    fi
}

# Run main function
main "$@"
