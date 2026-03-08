#!/bin/bash

# =============================================================================
# SETUP WELCOME MESSAGE
# =============================================================================
# This script sets up a welcome message that appears when users SSH into
# the droplet, providing clear guidance on next steps.
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

# Function to print colored output
print_status() {
    echo -e "${BLUE}[SETUP_WELCOME]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SETUP_WELCOME] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[SETUP_WELCOME] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[SETUP_WELCOME] ❌${NC} $1"
}

# Function to create welcome message
create_welcome_message() {
    print_status "Creating welcome message for SSH sessions..."
    
    # Create the welcome message file
    cat > /etc/update-motd.d/99-rec-io-welcome << 'WELCOME_EOF'
#!/bin/bash

# REC.IO Welcome Message
echo ""
echo -e "\033[1;36m=============================================================================\033[0m"
echo -e "\033[1;36m                           REC.IO TRADING SYSTEM\033[0m"
echo -e "\033[1;36m=============================================================================\033[0m"
echo ""

# Check if system has been sanitized
if [[ -f "/opt/rec_io/.sanitization_complete" ]]; then
    echo -e "\033[1;32m✅ System has been automatically sanitized and is ready for setup\033[0m"
    echo ""
    echo -e "\033[1;33m📋 NEXT STEPS:\033[0m"
    echo "1. Navigate to the project directory:"
    echo "   cd /opt/rec_io"
    echo ""
    echo "2. Run the setup script:"
    echo "   ./scripts/install_deploy/collaborator_setup.sh"
    echo ""
    echo "3. Follow the interactive prompts to configure your system"
    echo ""
    echo -e "\033[1;33m📖 For detailed instructions, see:\033[0m"
    echo "   cat /opt/rec_io/SANITIZATION_WARNING.txt"
    echo ""
else
    echo -e "\033[1;31m⚠️  SYSTEM SETUP IN PROGRESS\033[0m"
    echo ""
    echo "The system is currently being automatically configured."
    echo "This process typically takes 2-3 minutes."
    echo ""
    echo -e "\033[1;33m⏳ Please wait for the setup to complete...\033[0m"
    echo ""
    echo "You can check the status with:"
    echo "   tail -f /var/log/first_boot_sanitize.log"
    echo ""
fi

echo -e "\033[1;36m=============================================================================\033[0m"
echo ""
WELCOME_EOF
    
    # Make the welcome script executable
    chmod +x /etc/update-motd.d/99-rec-io-welcome
    
    # Update the MOTD immediately
    /etc/update-motd.d/99-rec-io-welcome > /etc/motd
    
    print_success "Welcome message created"
}

# Function to create setup completion message
create_setup_completion_message() {
    print_status "Creating setup completion message..."
    
    # Create a message that appears after setup is complete
    cat > /opt/rec_io/SETUP_COMPLETE_MESSAGE.txt << 'COMPLETE_EOF'
=============================================================================
                           REC.IO SETUP COMPLETE
=============================================================================

🎉 Congratulations! Your REC.IO trading system is now ready.

📊 ACCESS YOUR SYSTEM:
   Web Interface: http://$(curl -s ifconfig.me):3000
   Health Check:  http://$(curl -s ifconfig.me):3000/health

🔧 SYSTEM MANAGEMENT:
   Check status:    supervisorctl status
   View logs:       tail -f logs/*.out.log
   Restart system:  ./scripts/MASTER_RESTART.sh

📚 USEFUL COMMANDS:
   cd /opt/rec_io                    # Navigate to project
   supervisorctl status              # Check service status
   tail -f logs/main_app.out.log     # View main app logs
   tail -f logs/trade_manager.out.log # View trade manager logs

🔒 SECURITY NOTES:
   - Your system is completely isolated from other users
   - All original user data has been removed
   - Your credentials are stored securely
   - Keep your Kalshi API keys private

📞 SUPPORT:
   If you need help, contact the REC.IO team with:
   - Your droplet IP: $(curl -s ifconfig.me)
   - Any error messages from logs
   - Steps you've already tried

=============================================================================
COMPLETE_EOF
    
    print_success "Setup completion message created"
}

# Function to create interactive setup script
create_interactive_setup() {
    print_status "Creating interactive setup script..."
    
    cat > /opt/rec_io/quick_setup.sh << 'QUICK_SETUP_EOF'
#!/bin/bash

# =============================================================================
# QUICK SETUP SCRIPT
# =============================================================================
# Interactive setup script for REC.IO collaborators
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

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    REC.IO QUICK SETUP${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}❌${NC} $1"
}

print_status() {
    echo -e "${BLUE}📋${NC} $1"
}

# Check if system is ready
check_system_ready() {
    if [[ ! -f "/opt/rec_io/.sanitization_complete" ]]; then
        print_error "System is not ready for setup"
        print_warning "Please wait for automatic sanitization to complete"
        print_status "Check status with: tail -f /var/log/first_boot_sanitize.log"
        exit 1
    fi
    
    print_success "System is ready for setup"
}

# Main setup function
main_setup() {
    print_header
    echo ""
    
    # Check system readiness
    check_system_ready
    
    print_status "Starting REC.IO setup..."
    echo ""
    
    # Change to project directory
    cd /opt/rec_io
    
    # Run the full setup script
    if ./scripts/install_deploy/collaborator_setup.sh; then
        echo ""
        print_success "Setup completed successfully!"
        echo ""
        print_status "Starting the trading system..."
        
        # Start the system
        if ./scripts/MASTER_RESTART.sh; then
            echo ""
            print_success "Trading system started successfully!"
            echo ""
            
            # Show completion message
            if [[ -f "SETUP_COMPLETE_MESSAGE.txt" ]]; then
                cat SETUP_COMPLETE_MESSAGE.txt
            else
                print_status "Your REC.IO system is now ready!"
                print_status "Access it at: http://$(curl -s ifconfig.me):3000"
            fi
        else
            print_error "Failed to start trading system"
            print_status "Check logs and try again"
        fi
    else
        print_error "Setup failed"
        print_status "Check the error messages above"
        exit 1
    fi
}

# Show help
show_help() {
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  setup    - Run the complete setup (default)"
    echo "  status   - Check system status"
    echo "  help     - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0        # Run complete setup"
    echo "  $0 status # Check system status"
}

# Check system status
check_status() {
    print_header
    echo ""
    
    print_status "System Status:"
    
    # Check sanitization
    if [[ -f "/opt/rec_io/.sanitization_complete" ]]; then
        print_success "System has been sanitized"
    else
        print_warning "System has not been sanitized"
    fi
    
    # Check if setup script exists
    if [[ -f "/opt/rec_io/scripts/install_deploy/collaborator_setup.sh" ]]; then
        print_success "Setup script is available"
    else
        print_error "Setup script not found"
    fi
    
    # Check if system is running
    if command -v supervisorctl &> /dev/null; then
        echo ""
        print_status "Service Status:"
        supervisorctl -c /opt/rec_io/backend/supervisord.conf status 2>/dev/null || print_warning "Services not running"
    fi
    
    echo ""
    print_status "Next steps:"
    print_status "1. Run: $0 setup"
    print_status "2. Follow the interactive prompts"
    print_status "3. Access your system at: http://$(curl -s ifconfig.me):3000"
}

# Main script logic
case "${1:-setup}" in
    "setup")
        main_setup
        ;;
    "status")
        check_status
        ;;
    "help"|"-h"|"--help")
        show_help
        ;;
    *)
        print_error "Unknown option: $1"
        show_help
        exit 1
        ;;
esac
QUICK_SETUP_EOF
    
    # Make the quick setup script executable
    chmod +x /opt/rec_io/quick_setup.sh
    
    print_success "Interactive setup script created"
}

# Function to create desktop notification (if possible)
create_desktop_notification() {
    print_status "Setting up desktop notification system..."
    
    # Create a notification script
    cat > /opt/rec_io/notify_setup_complete.sh << 'NOTIFY_EOF'
#!/bin/bash

# Simple notification system for setup completion
# This can be called from the setup script

MESSAGE="REC.IO setup is complete! Access your system at: http://$(curl -s ifconfig.me):3000"

# Try different notification methods
if command -v wall &> /dev/null; then
    echo "$MESSAGE" | wall
fi

# Create a simple status file
echo "$(date): Setup completed successfully" > /opt/rec_io/setup_status.txt

# Show message in terminal
echo ""
echo "============================================================================="
echo "                           SETUP COMPLETE!"
echo "============================================================================="
echo ""
echo "🎉 Your REC.IO trading system is ready!"
echo ""
echo "📊 Access your system:"
echo "   Web Interface: http://$(curl -s ifconfig.me):3000"
echo "   Health Check:  http://$(curl -s ifconfig.me):3000/health"
echo ""
echo "🔧 Quick commands:"
echo "   cd /opt/rec_io"
echo "   supervisorctl status"
echo "   tail -f logs/*.out.log"
echo ""
echo "============================================================================="
NOTIFY_EOF
    
    chmod +x /opt/rec_io/notify_setup_complete.sh
    
    print_success "Notification system created"
}

# Main function
main() {
    print_status "Setting up welcome message system..."
    
    # Create all components
    create_welcome_message
    create_setup_completion_message
    create_interactive_setup
    create_desktop_notification
    
    print_success "Welcome message system setup completed"
    echo ""
    print_status "Components created:"
    print_status "  - SSH welcome message (/etc/update-motd.d/99-rec-io-welcome)"
    print_status "  - Setup completion message (/opt/rec_io/SETUP_COMPLETE_MESSAGE.txt)"
    print_status "  - Quick setup script (/opt/rec_io/quick_setup.sh)"
    print_status "  - Notification system (/opt/rec_io/notify_setup_complete.sh)"
    echo ""
    print_success "Users will now see helpful messages when they SSH in"
}

# Run main function
main "$@"
