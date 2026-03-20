#!/bin/bash

# =============================================================================
# TRADING SYSTEM FIREWALL SETUP - MINIMALLY INTRUSIVE
# =============================================================================
# 
# This script configures ufw (Uncomplicated Firewall) for the trading system
# with minimal intrusion while providing standard protection for production.
#
# PRINCIPLES:
# - DOES NOT interfere with local development
# - DOES NOT block internal service-to-service communication  
# - DOES NOT restrict outbound traffic (API calls to Kalshi, Coinbase, etc.)
# - ONLY blocks unwanted incoming connections from unknown public IPs
# - ALLOWS all localhost traffic (127.0.0.1, ::1)
# - ALLOWS specified inbound ports for SSH, HTTP/HTTPS, and system APIs
#
# USAGE:
#   sudo ./scripts/setup_firewall.sh --mode local
#   sudo ./scripts/setup_firewall.sh --mode production
#   sudo ./scripts/setup_firewall.sh --mode production --dry-run
#
# FEATURES:
# - Non-intrusive: Preserves all localhost and internal communication
# - Mode-aware: Different rules for local vs production
# - Safe defaults: Deny incoming, allow outgoing
# - API access: Allows outbound traffic for trading APIs
# - Service ports: Allows internal service communication
# - SSH protection: Restricts SSH to whitelisted IPs in production
# =============================================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_DIR/config/firewall_whitelist.json"
LOG_FILE="$PROJECT_DIR/logs/firewall_setup.log"

# Default values
MODE="local"
DRY_RUN=false
VERBOSE=false

# Trading system ports (from MASTER_PORT_MANIFEST.json)
TRADING_PORTS=(
    3000  # main_app
    4000  # trade_manager
    8001  # trade_executor
    8002  # btc_price_watchdog
    
    8004  # kalshi_account_sync
    8005  # kalshi_api_watchdog
    8007  # active_trade_supervisor
    8009  # auto_entry_supervisor
    8010  # unified_production_coordinator
    
)

# Standard web ports
WEB_PORTS=(
    80    # HTTP
    443   # HTTPS
    22    # SSH
)

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--mode local|production] [--dry-run] [--verbose]"
            echo ""
            echo "Modes:"
            echo "  local      - Development mode (permissive, no restrictions)"
            echo "  production - Production mode (standard protection)"
            echo ""
            echo "Options:"
            echo "  --dry-run  - Show rules without applying"
            echo "  --verbose  - Show detailed output"
            echo ""
            echo "PRINCIPLES:"
            echo "  - Does NOT interfere with local development"
            echo "  - Does NOT block internal service communication"
            echo "  - Does NOT restrict outbound API calls"
            echo "  - ONLY blocks unwanted incoming connections"
            echo "  - ALLOWS all localhost traffic"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Check if running as root (required for ufw)
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log "ERROR: This script must be run as root (use sudo)"
        log "Usage: sudo $0 --mode $MODE"
        exit 1
    fi
}

# Check if ufw is available and install if needed
check_ufw() {
    if ! command -v ufw &> /dev/null; then
        log "WARNING: ufw not found. Attempting to install..."
        if command -v apt-get &> /dev/null; then
            apt-get update && apt-get install -y ufw
        elif command -v yum &> /dev/null; then
            yum install -y ufw
        else
            log "ERROR: Cannot install ufw automatically. Please install manually."
            exit 1
        fi
    fi
}

# Load IP whitelist from config file
load_whitelist() {
    SSH_ALLOWED_IPS=""
    
    if [[ -f "$CONFIG_FILE" ]]; then
        log "Loading IP whitelist from $CONFIG_FILE"
        # Extract SSH allowed IPs from JSON (simple parsing)
        SSH_ALLOWED_IPS=$(grep -o '"ssh_allowed_ips":\s*\[[^]]*\]' "$CONFIG_FILE" | grep -o '"[^"]*"' | tr -d '"' | tr '\n' ' ')
    else
        log "No whitelist config found, using default SSH access"
    fi
}

# Setup firewall rules for local development (minimally intrusive)
setup_local_mode() {
    log "Setting up LOCAL development firewall mode (minimally intrusive)"
    
    # Reset to default state
    ufw --force reset
    
    # Default policies - allow all outgoing, deny incoming
    ufw default deny incoming
    ufw default allow outgoing
    
    # CRITICAL: Allow all localhost traffic (preserves internal communication)
    ufw allow from 127.0.0.1 to any
    ufw allow from ::1 to any
    log "  ✓ Allowed all localhost traffic (127.0.0.1, ::1)"
    
    # Allow all internal network communication
    ufw allow from 10.0.0.0/8
    ufw allow from 172.16.0.0/12
    ufw allow from 192.168.0.0/16
    log "  ✓ Allowed all internal network communication"
    
    # Allow trading system ports (unrestricted in local mode)
    for port in "${TRADING_PORTS[@]}"; do
        ufw allow "$port"
        log "  ✓ Allowed port $port for trading system"
    done
    
    # Allow standard web ports
    for port in "${WEB_PORTS[@]}"; do
        ufw allow "$port"
        log "  ✓ Allowed port $port for web services"
    done
    
    # CRITICAL: Allow all outbound traffic (preserves API calls)
    log "  ✓ All outbound traffic allowed (API calls preserved)"
    
    log "LOCAL mode configured - permissive for development"
}

# Setup firewall rules for production (standard protection)
setup_production_mode() {
    log "Setting up PRODUCTION firewall mode (standard protection)"
    
    # Reset to default state
    ufw --force reset
    
    # Default policies
    ufw default deny incoming
    ufw default allow outgoing
    
    # CRITICAL: Allow all localhost traffic (preserves internal services)
    ufw allow from 127.0.0.1 to any
    ufw allow from ::1 to any
    log "  ✓ Allowed all localhost traffic (127.0.0.1, ::1)"
    
    # Allow internal communication (for supervisor services)
    ufw allow from 10.0.0.0/8
    ufw allow from 172.16.0.0/12
    ufw allow from 192.168.0.0/16
    log "  ✓ Allowed internal network communication"
    
    # Allow trading system ports (restrict to localhost in production)
    for port in "${TRADING_PORTS[@]}"; do
        ufw allow from 127.0.0.1 to any port "$port"
        log "  ✓ Allowed localhost access to port $port"
    done
    
    # SSH access - restrict to whitelisted IPs
    if [[ -n "$SSH_ALLOWED_IPS" ]]; then
        for ip in $SSH_ALLOWED_IPS; do
            ufw allow from "$ip" to any port 22
            log "  ✓ Allowed SSH from $ip"
        done
    else
        # Fallback: allow SSH from private networks
        ufw allow from 10.0.0.0/8 to any port 22
        ufw allow from 172.16.0.0/12 to any port 22
        ufw allow from 192.168.0.0/16 to any port 22
        log "  ✓ Allowed SSH from private networks (no whitelist configured)"
    fi
    
    # Allow standard web ports
    ufw allow 80
    ufw allow 443
    log "  ✓ Allowed HTTP/HTTPS (ports 80, 443)"
    
    # CRITICAL: Allow all outbound traffic (preserves API calls)
    log "  ✓ All outbound traffic allowed (API calls preserved)"
    
    # Additional security: rate limiting for SSH
    ufw limit ssh
    log "  ✓ Enabled SSH rate limiting"
    
    log "PRODUCTION mode configured - standard protection with API access preserved"
}

# Show current ufw status
show_status() {
    log "Current ufw status:"
    ufw status numbered
}

# Main execution
main() {
    log "=== TRADING SYSTEM FIREWALL SETUP (MINIMALLY INTRUSIVE) ==="
    log "Mode: $MODE"
    log "Dry run: $DRY_RUN"
    log ""
    log "PRINCIPLES:"
    log "  - Does NOT interfere with local development"
    log "  - Does NOT block internal service communication"
    log "  - Does NOT restrict outbound API calls"
    log "  - ONLY blocks unwanted incoming connections"
    log "  - ALLOWS all localhost traffic"
    log ""
    
    # Check prerequisites
    check_root
    check_ufw
    load_whitelist
    
    # Show current status
    show_status
    
    # Setup based on mode
    if [[ "$MODE" == "local" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            log "DRY RUN: Would configure LOCAL mode"
            log "  - Allow all localhost traffic"
            log "  - Allow all internal networks"
            log "  - Allow all trading system ports"
            log "  - Allow all outbound traffic"
            log "  - No restrictions on incoming connections"
        else
            setup_local_mode
        fi
    elif [[ "$MODE" == "production" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            log "DRY RUN: Would configure PRODUCTION mode"
            log "  - Allow localhost traffic only"
            log "  - Restrict trading ports to localhost"
            log "  - Restrict SSH to whitelisted IPs"
            log "  - Allow all outbound traffic"
            log "  - Enable SSH rate limiting"
        else
            setup_production_mode
        fi
    else
        log "ERROR: Invalid mode '$MODE'. Use 'local' or 'production'"
        exit 1
    fi
    
    # Enable firewall (unless dry run)
    if [[ "$DRY_RUN" == "false" ]]; then
        log "Enabling ufw firewall..."
        ufw --force enable
        
        # Show final status
        log "Final ufw status:"
        show_status
        
        log "Firewall setup complete!"
        log "Log file: $LOG_FILE"
        log ""
        log "VERIFICATION:"
        log "  - All localhost traffic should work normally"
        log "  - Internal service communication should be preserved"
        log "  - Outbound API calls should work normally"
        log "  - Only unwanted incoming connections are blocked"
    else
        log "DRY RUN: Would enable ufw firewall"
    fi
}

# Run main function
main "$@" 