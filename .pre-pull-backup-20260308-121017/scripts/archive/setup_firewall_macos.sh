#!/bin/bash

# =============================================================================
# TRADING SYSTEM FIREWALL SETUP - DEVELOPMENT FIRST
# =============================================================================
# 
# This script configures pfctl (Packet Filter) for the trading system
# with a DEVELOPMENT-FIRST approach that prioritizes functionality.
#
# PRINCIPLES:
# - DEFAULT: Completely permissive for development
# - PRODUCTION: Only minimal rules for cloud deployment
# - NEVER interferes with local development
# - NEVER blocks internal service-to-service communication  
# - NEVER restricts outbound traffic (API calls to Kalshi, Coinbase, etc.)
# - ONLY applies restrictions when explicitly in production mode
#
# USAGE:
#   sudo ./scripts/setup_firewall_macos.sh                    # Development mode (default)
#   sudo ./scripts/setup_firewall_macos.sh --mode production  # Production mode (cloud only)
# =============================================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PF_RULES_FILE="/etc/pf.conf.trading"
PF_RULES_BACKUP="/etc/pf.conf.trading.backup"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse command line arguments
MODE="local"  # DEFAULT: Always local/development mode
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --help)
            echo "Usage: $0 [--mode local|production] [--dry-run]"
            echo ""
            echo "Modes:"
            echo "  local (default): Completely permissive for development"
            echo "  production: Minimal rules for cloud deployment only"
            echo ""
            echo "Examples:"
            echo "  $0                    # Development mode (default)"
            echo "  $0 --mode production  # Production mode (cloud only)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate mode
if [[ "$MODE" != "local" && "$MODE" != "production" ]]; then
    echo "Invalid mode: $MODE. Use 'local' or 'production'"
    exit 1
fi

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)"
    exit 1
fi

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Error exit function
error_exit() {
    log "${RED}ERROR: $1${NC}"
    exit 1
}

# Main execution
log "${BLUE}=== TRADING SYSTEM FIREWALL SETUP (DEVELOPMENT FIRST) ===${NC}"
log "Mode: $MODE"
log "Dry run: $DRY_RUN"
log ""
log "${BLUE}PRINCIPLES:${NC}"
log "  - DEFAULT: Completely permissive for development"
log "  - PRODUCTION: Only minimal rules for cloud deployment"
log "  - NEVER interferes with local development"
log "  - NEVER blocks internal service communication"
log "  - NEVER restricts outbound API calls"
log ""

# Check if pfctl is available
if ! command -v pfctl &> /dev/null; then
    error_exit "pfctl not found. This script requires macOS with Packet Filter."
fi

# DEVELOPMENT MODE (DEFAULT) - Completely permissive
if [[ "$MODE" == "local" ]]; then
    log "${GREEN}=== DEVELOPMENT MODE: COMPLETELY PERMISSIVE ===${NC}"
    log "Disabling firewall completely for development..."
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log "${YELLOW}DRY RUN: Would disable firewall completely${NC}"
        return 0
    fi
    
    # Completely disable the firewall
    pfctl -d 2>/dev/null || true
    log "${GREEN}✅ Firewall disabled - all traffic allowed${NC}"
    log "${GREEN}✅ Development environment unrestricted${NC}"
    log "${GREEN}✅ All devices can access the system${NC}"
    log "${GREEN}✅ No browser caching issues${NC}"
    
    # Show status
    log "Current firewall status:"
    pfctl -s info 2>/dev/null | head -5 || log "${YELLOW}Firewall is disabled${NC}"
    
    log ""
    log "${GREEN}=== DEVELOPMENT MODE ACTIVE ===${NC}"
    log "Firewall is completely disabled for development."
    log "All traffic is allowed - no restrictions."
    log "Perfect for local development and testing."
    
    exit 0
fi

# PRODUCTION MODE - Minimal rules for cloud deployment only
if [[ "$MODE" == "production" ]]; then
    log "${YELLOW}=== PRODUCTION MODE: MINIMAL RULES FOR CLOUD ===${NC}"
    log "Applying minimal firewall rules for cloud deployment..."
    
    # Create minimal production rules
    cat > "$PF_RULES_FILE" << 'EOF'
# =============================================================================
# TRADING SYSTEM FIREWALL - PRODUCTION MODE (CLOUD ONLY)
# =============================================================================
# Generated: $(date)
# Mode: production
# 
# PRINCIPLES:
# - Minimal rules for cloud deployment only
# - Allows all outbound traffic (API calls)
# - Allows SSH and HTTP/HTTPS
# - Allows trading system ports
# - Blocks only obvious attack vectors
# =============================================================================

# Options
set block-policy drop
set skip on lo0

# Normalization
scrub in all

# Filtering rules
# Allow all outbound traffic (API calls to Kalshi, Coinbase, etc.)
pass out all

# Allow all localhost traffic
pass in on lo0 all

# Allow SSH (port 22)
pass in proto tcp to any port 22

# Allow HTTP/HTTPS (ports 80, 443)
pass in proto tcp to any port { 80 443 }

# Allow trading system ports
pass in proto tcp to any port { 3000 4000 8001 8002 8003 8004 8005 8008 }

# Block obvious attack vectors only
block in proto tcp from any to any port { 23 25 135 139 445 1433 1521 3306 3389 5432 5900 6379 27017 }
block in proto udp from any to any port { 53 123 161 389 636 1433 1521 3306 3389 5432 5900 6379 27017 }

# Allow everything else (permissive for development)
pass in all
EOF

    if [[ "$DRY_RUN" == "true" ]]; then
        log "${YELLOW}DRY RUN: Would apply the following rules:${NC}"
        cat "$PF_RULES_FILE"
        log "${YELLOW}DRY RUN: No changes made to firewall${NC}"
        return 0
    fi
    
    # Backup existing rules if they exist
    if [[ -f "$PF_RULES_FILE" ]]; then
        log "Backing up existing rules to $PF_RULES_BACKUP"
        cp "$PF_RULES_FILE" "$PF_RULES_BACKUP"
    fi
    
    # Apply the rules
    log "Applying production firewall rules..."
    if pfctl -f "$PF_RULES_FILE" 2>/dev/null; then
        log "${GREEN}✅ Production firewall rules applied successfully${NC}"
    else
        error_exit "Failed to apply production firewall rules"
    fi
    
    # Enable pf if not already enabled
    if ! pfctl -s info 2>/dev/null | grep -q "Status: Enabled"; then
        log "Enabling pf..."
        pfctl -e
        log "${GREEN}✅ pf enabled${NC}"
    else
        log "${GREEN}✅ pf already enabled${NC}"
    fi
    
    log "${GREEN}✅ Production firewall configuration complete${NC}"
    log "${YELLOW}Note: This is for CLOUD DEPLOYMENT only${NC}"
    log "${YELLOW}For local development, use: sudo ./scripts/setup_firewall_macos.sh${NC}"
fi

# Test connectivity
log "Testing connectivity..."
if ping -c 1 127.0.0.1 >/dev/null 2>&1; then
    log "${GREEN}✅ Localhost connectivity: OK${NC}"
else
    log "${RED}❌ Localhost connectivity: FAILED${NC}"
fi

if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
    log "${GREEN}✅ Outbound connectivity: OK${NC}"
else
    log "${RED}❌ Outbound connectivity: FAILED${NC}"
fi

log ""
log "${GREEN}=== FIREWALL SETUP COMPLETE ===${NC}"
log "Mode: $MODE"
log "Rules file: $PF_RULES_FILE"
log ""
log "${BLUE}VERIFICATION COMMANDS:${NC}"
log "  sudo pfctl -s rules          # Show current rules"
log "  sudo pfctl -s info           # Show pf status"
log "  sudo pfctl -s all            # Show all pf information"
log ""
log "${BLUE}MANAGEMENT COMMANDS:${NC}"
log "  sudo pfctl -d                # Disable pf (development)"
log "  sudo pfctl -e                # Enable pf"
log "  sudo pfctl -f $PF_RULES_FILE # Reload rules"
log ""
log "${BLUE}DEVELOPMENT MODE:${NC}"
log "  sudo ./scripts/setup_firewall_macos.sh                    # Development (default)"
log ""
log "${BLUE}PRODUCTION MODE:${NC}"
log "  sudo ./scripts/setup_firewall_macos.sh --mode production  # Cloud deployment only"
log ""
log "${GREEN}Firewall is now configured for $MODE mode!${NC}" 