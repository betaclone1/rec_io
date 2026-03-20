#!/bin/bash

# =============================================================================
# DIGITALOCEAN DEPLOYMENT INSTALLATION SCRIPT
# =============================================================================
# 
# This script installs and configures the trading system on a fresh
# DigitalOcean Ubuntu droplet. It handles all dependencies, setup,
# and initial configuration.
#
# USAGE:
#   curl -sSL https://raw.githubusercontent.com/your-repo/main/scripts/install_digitalocean.sh | bash
#   OR
#   wget -O - https://raw.githubusercontent.com/your-repo/main/scripts/install_digitalocean.sh | bash
#
# PREREQUISITES:
# - Fresh Ubuntu 22.04+ droplet
# - Root or sudo access
# - Internet connectivity
# =============================================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="/var/log/trading_system_install.log"
INSTALL_DIR="/opt/trading_system"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
    exit 1
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root (use sudo)"
    fi
}

# Update system packages
update_system() {
    log "Updating system packages..."
    apt-get update
    apt-get upgrade -y
    log "System packages updated"
}

# Install system dependencies
install_dependencies() {
    log "Installing system dependencies..."
    
    # Essential packages
    apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        supervisor \
        ufw \
        curl \
        wget \
        git \
        sqlite3 \
        nginx \
        htop \
        unzip \
        cron \
        logrotate
    
    log "System dependencies installed"
}

# Install Python dependencies
install_python_deps() {
    log "Installing Python dependencies..."
    
    # Create virtual environment
    python3 -m venv /opt/trading_system/venv
    source /opt/trading_system/venv/bin/activate
    
    # Upgrade pip
    pip install --upgrade pip
    
    # Install requirements
    if [[ -f "$PROJECT_DIR/requirements.txt" ]]; then
        pip install -r "$PROJECT_DIR/requirements.txt"
    else
        # Install common trading dependencies
        pip install \
            fastapi \
            uvicorn \
            requests \
            websockets \
            sqlite3 \
            supervisor \
            python-dotenv \
            aiofiles \
            asyncio
    fi
    
    log "Python dependencies installed"
}

# Setup directory structure
setup_directories() {
    log "Setting up directory structure..."
    
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR/logs"
    mkdir -p "$INSTALL_DIR/data"
    mkdir -p "$INSTALL_DIR/config"
    mkdir -p "$INSTALL_DIR/scripts"
    
    # Create user data directory structure
    mkdir -p "$INSTALL_DIR/user_data"/{credentials,databases,preferences,state}
    mkdir -p "$INSTALL_DIR/user_data/credentials/kalshi"/{demo,prod}
    mkdir -p "$INSTALL_DIR/user_data/databases"/{accounts,trade_history,price_history}
    mkdir -p "$INSTALL_DIR/user_data/preferences"/{trading,system,ui}
    
    # Copy project files
    cp -r "$PROJECT_DIR/backend" "$INSTALL_DIR/"
    cp -r "$PROJECT_DIR/frontend" "$INSTALL_DIR/"
    cp -r "$PROJECT_DIR/scripts" "$INSTALL_DIR/"
    cp -r "$PROJECT_DIR/config" "$INSTALL_DIR/"
    cp "$PROJECT_DIR/requirements.txt" "$INSTALL_DIR/"
    cp "$PROJECT_DIR/index.html" "$INSTALL_DIR/"
    
    # Set permissions
    chown -R root:root "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"
    chmod +x "$INSTALL_DIR/scripts"/*.sh
    
    # Set user data permissions
    chmod 700 "$INSTALL_DIR/user_data"
    chown -R trading_user:trading_user "$INSTALL_DIR/user_data" 2>/dev/null || chown -R root:root "$INSTALL_DIR/user_data"
    
    log "Directory structure setup complete"
}

# Configure supervisor
setup_supervisor() {
    log "Configuring supervisor..."
    
    # Copy supervisor config
    cp "$PROJECT_DIR/backend/supervisord.conf" /etc/supervisor/conf.d/trading_system.conf
    
    # Create supervisor log directory
    mkdir -p /var/log/supervisor
    
    # Reload supervisor
    supervisorctl reread
    supervisorctl update
    
    log "Supervisor configured"
}

# Setup firewall
setup_firewall() {
    log "Setting up firewall..."
    
    # Run firewall setup script
    if [[ -f "$INSTALL_DIR/scripts/setup_firewall.sh" ]]; then
        "$INSTALL_DIR/scripts/setup_firewall.sh" --mode production
    else
        warning "Firewall setup script not found, configuring manually..."
        
        # Basic firewall setup
        ufw default deny incoming
        ufw default allow outgoing
        ufw allow ssh
        ufw allow 80
        ufw allow 443
        ufw allow from 127.0.0.1 to any
        ufw --force enable
    fi
    
    log "Firewall configured"
}

# Setup log rotation
setup_log_rotation() {
    log "Setting up log rotation..."
    
    # Copy logrotate config
    cat > /etc/logrotate.d/trading_system << 'EOF'
/opt/trading_system/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 root root
    postrotate
        supervisorctl -c /opt/trading_system/backend/supervisord.conf reload > /dev/null 2>&1 || true
    endscript
}
EOF
    
    # Setup cron job for manual rotation
    if [[ -f "$INSTALL_DIR/scripts/setup_log_rotation_cron.sh" ]]; then
        "$INSTALL_DIR/scripts/setup_log_rotation_cron.sh"
    fi
    
    log "Log rotation configured"
}

# Setup nginx (optional)
setup_nginx() {
    log "Setting up nginx..."
    
    # Create nginx config
    cat > /etc/nginx/sites-available/trading_system << 'EOF'
server {
    listen 80;
    server_name _;
    
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /static/ {
        alias /opt/trading_system/frontend/;
    }
}
EOF
    
    # Enable site
    ln -sf /etc/nginx/sites-available/trading_system /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    # Test and reload nginx
    nginx -t && systemctl reload nginx
    
    log "Nginx configured"
}

# Setup systemd service
setup_systemd() {
    log "Setting up systemd service..."
    
    # Create systemd service file
    cat > /etc/systemd/system/trading_system.service << 'EOF'
[Unit]
Description=Trading System
After=network.target

[Service]
Type=forking
User=root
Group=root
WorkingDirectory=/opt/trading_system
ExecStart=/opt/trading_system/venv/bin/supervisord -c /opt/trading_system/backend/supervisord.conf
ExecStop=/opt/trading_system/venv/bin/supervisorctl -c /opt/trading_system/backend/supervisord.conf shutdown
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    # Enable and start service
    systemctl daemon-reload
    systemctl enable trading_system.service
    systemctl start trading_system.service
    
    log "Systemd service configured"
}

# Setup monitoring
setup_monitoring() {
    log "Setting up monitoring..."
    
    # Create monitoring script
    cat > /opt/trading_system/scripts/monitor_system.sh << 'EOF'
#!/bin/bash
# System monitoring script
LOG_FILE="/opt/trading_system/logs/system_monitor.log"

echo "[$(date)] System Status Check" >> "$LOG_FILE"
supervisorctl -c /opt/trading_system/backend/supervisord.conf status >> "$LOG_FILE" 2>&1
echo "---" >> "$LOG_FILE"
EOF
    
    chmod +x /opt/trading_system/scripts/monitor_system.sh
    
    # Add to crontab
    (crontab -l 2>/dev/null; echo "*/5 * * * * /opt/trading_system/scripts/monitor_system.sh") | crontab -
    
    log "Monitoring configured"
}

# Verify installation
verify_installation() {
    log "Verifying installation..."
    
    # Check supervisor status
    if supervisorctl -c /opt/trading_system/backend/supervisord.conf status > /dev/null 2>&1; then
        log "Supervisor is running"
    else
        error "Supervisor is not running"
    fi
    
    # Check web interface
    if curl -s http://localhost:3000/ > /dev/null 2>&1; then
        log "Web interface is responding"
    else
        warning "Web interface may not be responding yet"
    fi
    
    # Check firewall
    if ufw status | grep -q "Status: active"; then
        log "Firewall is active"
    else
        warning "Firewall may not be active"
    fi
    
    log "Installation verification complete"
}

# Main installation function
main() {
    log "=== DIGITALOCEAN TRADING SYSTEM INSTALLATION ==="
    log "Starting installation process..."
    
    # Check prerequisites
    check_root
    
    # Installation steps
    update_system
    install_dependencies
    install_python_deps
    setup_directories
    setup_supervisor
    setup_firewall
    setup_log_rotation
    setup_nginx
    setup_systemd
    setup_monitoring
    verify_installation
    
    log "=== INSTALLATION COMPLETE ==="
    log "Trading system has been installed successfully!"
    log "Access the web interface at: http://your-server-ip"
    log "Check logs at: /opt/trading_system/logs/"
    log "Supervisor status: supervisorctl -c /opt/trading_system/backend/supervisord.conf status"
    log "System service: systemctl status trading_system.service"
}

# Run main function
main "$@" 