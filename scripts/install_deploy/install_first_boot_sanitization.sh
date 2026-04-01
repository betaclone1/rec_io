#!/bin/bash

# =============================================================================
# INSTALL FIRST BOOT SANITIZATION
# =============================================================================
# Installs the first-boot systemd unit. OFF BY DEFAULT; use
# REC_ENABLE_FIRST_BOOT_SANITIZE_SETUP=1 when deliberately enabling.
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INSTALL_SANITIZE]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[INSTALL_SANITIZE] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[INSTALL_SANITIZE] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[INSTALL_SANITIZE] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}              INSTALLING FIRST BOOT SANITIZATION${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Function to install first boot sanitization
install_first_boot_sanitization() {
    print_header
    print_status "Installing first boot sanitization service..."

    if [[ "${REC_ENABLE_FIRST_BOOT_SANITIZE_SETUP:-}" != "1" ]]; then
        print_warning "Install aborted: set REC_ENABLE_FIRST_BOOT_SANITIZE_SETUP=1 to enable first-boot sanitization on this host."
        exit 0
    fi
    
    # Check if we're in the project directory
    if [[ ! -f "scripts/MASTER_RESTART.sh" ]]; then
        print_error "Must run from project root directory"
        exit 1
    fi
    
    # Make the first boot script executable
    print_status "Making first boot script executable..."
    chmod +x scripts/install_deploy/first_boot_sanitize.sh
    
    # Create systemd service
    print_status "Creating systemd service..."
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
    
    # Reload systemd and enable service
    print_status "Enabling systemd service..."
    systemctl daemon-reload
    systemctl enable first-boot-sanitize.service
    
    # Create a flag to indicate this is a production system
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /opt/rec_io/.production_system
    
    # Install welcome message system
    print_status "Installing welcome message system..."
    ./scripts/install_deploy/setup_welcome_message.sh
    
    print_success "First boot sanitization service installed"
    print_warning "This system is now configured for snapshot-based deployment"
    print_warning "Any droplet created from a snapshot will automatically sanitize on first boot"
    echo ""
    
    # Create documentation
    cat > /opt/rec_io/SNAPSHOT_DEPLOYMENT_README.md << 'README_EOF'
# Snapshot Deployment Configuration

This system has been configured for snapshot-based deployment with automatic
first-boot sanitization.

## What This Means

When you create a snapshot of this system and transfer it to a collaborator:

1. **The collaborator creates a droplet** from the snapshot
2. **On first boot**, the system automatically runs sanitization
3. **All user data and credentials are removed** for security
4. **The system is marked as sanitized** and ready for setup
5. **Collaborator must run setup script** to configure their user account

## Files Created

- `/etc/systemd/system/first-boot-sanitize.service` - Systemd service
- `/opt/rec_io/scripts/install_deploy/first_boot_sanitize.sh` - Sanitization script
- `/opt/rec_io/.production_system` - Production system flag
- `/opt/rec_io/SANITIZATION_WARNING.txt` - Warning file (created on first boot)

## Security Features

- **Automatic sanitization** on first boot
- **Complete data removal** from database and filesystem
- **Credential deletion** from all locations
- **System isolation** between users
- **Clear warnings** about required setup

## For Collaborators

After creating a droplet from this snapshot:

1. **Wait for first boot** to complete (automatic sanitization)
2. **SSH to the droplet** and check for warning files
3. **Run the setup script**: `./scripts/collaborator_setup.sh`
4. **Configure your user account** and credentials
5. **Start the system**: `./scripts/MASTER_RESTART.sh`

## Verification

To verify the service is installed:

```bash
systemctl status first-boot-sanitize.service
systemctl is-enabled first-boot-sanitize.service
```

## Removing the Service

If you need to remove this service:

```bash
systemctl disable first-boot-sanitize.service
rm /etc/systemd/system/first-boot-sanitize.service
systemctl daemon-reload
rm /opt/rec_io/.production_system
```
README_EOF
    
    print_success "Documentation created: /opt/rec_io/SNAPSHOT_DEPLOYMENT_README.md"
    print_success "First boot sanitization installation completed"
}

# Function to test the service
test_service() {
    print_status "Testing first boot sanitization service..."
    
    # Check if service exists
    if systemctl list-unit-files | grep -q "first-boot-sanitize"; then
        print_success "Service is installed"
    else
        print_error "Service is not installed"
        return 1
    fi
    
    # Check if service is enabled
    if systemctl is-enabled first-boot-sanitize.service &>/dev/null; then
        print_success "Service is enabled"
    else
        print_error "Service is not enabled"
        return 1
    fi
    
    # Check if script is executable
    if [[ -x "scripts/install_deploy/first_boot_sanitize.sh" ]]; then
        print_success "Script is executable"
    else
        print_error "Script is not executable"
        return 1
    fi
    
    print_success "All tests passed"
}

# Main function
main() {
    case "${1:-install}" in
        "install")
            install_first_boot_sanitization
            ;;
        "test")
            test_service
            ;;
        "help"|"-h"|"--help")
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  install    - Install first boot sanitization service (default)"
            echo "  test       - Test the installed service"
            echo "  help       - Show this help message"
            ;;
        *)
            print_error "Unknown command: $1"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
