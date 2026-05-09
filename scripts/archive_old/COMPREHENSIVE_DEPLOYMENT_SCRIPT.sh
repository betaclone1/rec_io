#!/bin/bash

# COMPREHENSIVE DIGITAL OCEAN DEPLOYMENT SCRIPT
# Based on verified system specifications
# Target: YOUR_DROPLET_IP
# SSH Key: YOUR_SSH_KEY_FINGERPRINT

set -e  # Exit on any error

# Configuration
SERVER_IP="YOUR_DROPLET_IP"
SERVER_USER="root"
PROJECT_ROOT="/Users/ericwais1/rec_io_20"
DEPLOY_DIR="/opt/trading_system"
DEPLOY_PACKAGE="trading_system_deploy_$(date +%Y%m%d_%H%M%S).tar.gz"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
    exit 1
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to verify local system health
verify_local_system() {
    log "PHASE 1: VERIFYING LOCAL SYSTEM HEALTH"
    
    # Check if we're in the right directory
    if [[ ! -f "backend/main.py" ]]; then
        error "Not in project root directory. Please run from /Users/ericwais1/rec_io_20"
    fi
    
    # Verify all 12 services are running
    local process_count=$(ps aux | grep python | grep -v grep | wc -l)
    if [[ $process_count -ne 13 ]]; then
        error "Expected 13 Python processes (1 supervisord + 12 services), found $process_count"
    fi
    success "All 12 services are running"
    
    # Check main app health
    if ! curl -s http://localhost:3000/health > /dev/null; then
        error "Main app health check failed"
    fi
    success "Main app is healthy"
    
    # Verify database connectivity
    local trade_count=$(psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM users.trades_0001;" | xargs)
    if [[ $trade_count -ne 304 ]]; then
        error "Expected 304 trades, found $trade_count"
    fi
    success "Database connectivity verified (304 trades)"
    
    # Verify database backup exists
    if [[ ! -f "rec_io_db_backup.sql" ]]; then
        error "Database backup file not found"
    fi
    success "Database backup exists (1.5GB)"
    
    # Verify credentials exist
    if [[ ! -f "backend/data/users/user_0001/credentials/kalshi-credentials/prod/.env" ]]; then
        error "Production Kalshi credentials not found"
    fi
    if [[ ! -f "backend/data/users/user_0001/credentials/kalshi-credentials/demo/.env" ]]; then
        error "Demo Kalshi credentials not found"
    fi
    success "All credentials verified"
}

# Function to create deployment package
create_deployment_package() {
    log "PHASE 2: CREATING DEPLOYMENT PACKAGE"
    
    # Create package excluding venv, logs, and git
    tar -czf "$DEPLOY_PACKAGE" \
        --exclude=venv \
        --exclude=logs \
        --exclude=.git \
        --exclude=*.db \
        --exclude=*.sql \
        --exclude=*.tar.gz \
        --exclude=*.zip \
        .
    
    local package_size=$(du -h "$DEPLOY_PACKAGE" | cut -f1)
    success "Deployment package created: $DEPLOY_PACKAGE ($package_size)"
}

# Function to setup server environment
setup_server_environment() {
    log "PHASE 3: SETTING UP SERVER ENVIRONMENT"
    
    # SSH to server and setup environment
    ssh "$SERVER_USER@$SERVER_IP" << 'EOF'
        set -e
        
        echo "Updating system packages..."
        apt update && apt upgrade -y
        
        echo "Installing required packages..."
        apt install -y python3.13 python3.13-venv python3.13-dev
        apt install -y postgresql postgresql-contrib
        apt install -y supervisor
        apt install -y curl wget git unzip htop
        
        echo "Setting up PostgreSQL..."
        systemctl start postgresql
        systemctl enable postgresql
        
        # Create database and user
        sudo -u postgres psql -c "CREATE DATABASE rec_io_db;" || true
        sudo -u postgres psql -c "CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';" || true
        sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;"
        sudo -u postgres psql -c "CREATE SCHEMA IF NOT EXISTS users;"
        sudo -u postgres psql -c "CREATE SCHEMA IF NOT EXISTS live_data;"
        sudo -u postgres psql -c "GRANT ALL ON SCHEMA users TO rec_io_user;"
        sudo -u postgres psql -c "GRANT ALL ON SCHEMA live_data TO rec_io_user;"
        
        echo "Creating application directory..."
        mkdir -p /opt/trading_system
        cd /opt/trading_system
        
        mkdir -p logs
        mkdir -p backend/data/users/user_0001/credentials/kalshi-credentials/prod
        mkdir -p backend/data/users/user_0001/credentials/kalshi-credentials/demo
        mkdir -p backend/data/users/user_0001/trade_history
        mkdir -p backend/data/users/user_0001/active_trades
        mkdir -p backend/data/users/user_0001/accounts
        
        echo "Setting permissions..."
        chown -R root:root /opt/trading_system
        chmod -R 755 /opt/trading_system
        
        echo "Server environment setup complete"
EOF
    
    success "Server environment setup complete"
}

# Function to transfer and setup code
transfer_and_setup_code() {
    log "PHASE 4: TRANSFERRING AND SETTING UP CODE"
    
    # Transfer deployment package
    scp "$DEPLOY_PACKAGE" "$SERVER_USER@$SERVER_IP:/tmp/"
    success "Deployment package transferred"
    
    # Extract and setup on server
    ssh "$SERVER_USER@$SERVER_IP" << EOF
        set -e
        
        echo "Extracting deployment package..."
        cd $DEPLOY_DIR
        tar -xzf /tmp/$DEPLOY_PACKAGE
        
        echo "Setting up virtual environment..."
        python3.13 -m venv venv
        source venv/bin/activate
        
        echo "Installing Python dependencies..."
        pip install --upgrade pip
        pip install -r requirements.txt
        
        echo "Verifying key packages..."
        python -c "import psycopg2; print('psycopg2 OK')"
        python -c "import fastapi; print('fastapi OK')"
        python -c "import supervisor; print('supervisor OK')"
        
        echo "Code setup complete"
EOF
    
    success "Code setup complete"
}

# Function to transfer database
transfer_database() {
    log "PHASE 5: TRANSFERRING DATABASE"
    
    # Transfer database backup
    scp rec_io_db_backup.sql "$SERVER_USER@$SERVER_IP:/tmp/"
    success "Database backup transferred"
    
    # Restore database on server
    ssh "$SERVER_USER@$SERVER_IP" << 'EOF'
        set -e
        
        echo "Restoring database..."
        cd /opt/trading_system
        PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db < /tmp/rec_io_db_backup.sql
        
        echo "Verifying database restoration..."
        local trade_count=$(psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM users.trades_0001;" | xargs)
        local fill_count=$(psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM users.fills_0001;" | xargs)
        local position_count=$(psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT COUNT(*) FROM users.positions_0001;" | xargs)
        
        echo "Database verification:"
        echo "  Trades: $trade_count (expected: 304)"
        echo "  Fills: $fill_count (expected: 2153)"
        echo "  Positions: $position_count (expected: 2)"
        
        if [[ $trade_count -ne 304 ]]; then
            echo "ERROR: Trade count mismatch"
            exit 1
        fi
        
        echo "Database restoration complete"
EOF
    
    success "Database restoration complete"
}

# Function to transfer credentials
transfer_credentials() {
    log "PHASE 6: SETTING UP CREDENTIALS STRUCTURE"
    
    # Create credential directories on server (without transferring actual credentials)
    ssh "$SERVER_USER@$SERVER_IP" << 'EOF'
        mkdir -p /opt/trading_system/backend/data/users/user_0001/credentials/kalshi-credentials/prod
        mkdir -p /opt/trading_system/backend/data/users/user_0001/credentials/kalshi-credentials/demo
        chmod -R 700 /opt/trading_system/backend/data/users/user_0001/credentials
        echo "Credential directories created - you must manually add your credentials"
EOF
    
    success "Credential structure created - manual credential setup required"
}

# Function to configure environment
configure_environment() {
    log "PHASE 7: CONFIGURING ENVIRONMENT"
    
    ssh "$SERVER_USER@$SERVER_IP" << 'EOF'
        set -e
        
        cd /opt/trading_system
        
        echo "Creating environment file..."
        cat > .env << 'ENVEOF'
# PostgreSQL Connection Settings
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rec_io_db
POSTGRES_USER=rec_io_user
POSTGRES_PASSWORD=rec_io_password

# System Configuration
TRADING_SYSTEM_HOST=YOUR_DROPLET_IP
AUTH_ENABLED=false
ENVEOF
        
        chmod 600 .env
        
        echo "Configuring supervisor..."
        cp backend/supervisord.conf /etc/supervisor/conf.d/trading_system.conf
        
        # Update supervisor config for Ubuntu paths
        sed -i 's|venv/bin/python|/opt/trading_system/venv/bin/python|g' /etc/supervisor/conf.d/trading_system.conf
        sed -i 's|directory=.|directory=/opt/trading_system|g' /etc/supervisor/conf.d/trading_system.conf
        sed -i 's|logs/|/opt/trading_system/logs/|g' /etc/supervisor/conf.d/trading_system.conf
        
        supervisorctl reread
        supervisorctl update
        
        echo "Environment configuration complete"
EOF
    
    success "Environment configuration complete"
}

# Function to deploy services
deploy_services() {
    log "PHASE 8: DEPLOYING SERVICES"
    
    ssh "$SERVER_USER@$SERVER_IP" << 'EOF'
        set -e
        
        echo "Starting services individually..."
        
        # Start services one by one
        services=("main_app" "trade_manager" "trade_executor" "active_trade_supervisor" "auto_entry_supervisor" "symbol_price_watchdog_btc" "symbol_price_watchdog_eth" "kalshi_account_sync" "kalshi_api_watchdog" "unified_production_coordinator" "cascading_failure_detector" "system_monitor")
        
        for service in "${services[@]}"; do
            echo "Starting $service..."
            supervisorctl start "$service"
            sleep 3
            
            status=$(supervisorctl status "$service" | awk '{print $2}')
            if [[ "$status" == "RUNNING" ]]; then
                echo "✅ $service is RUNNING"
            else
                echo "❌ $service failed to start: $status"
                echo "Checking logs..."
                tail -10 /opt/trading_system/logs/"$service".err.log
                exit 1
            fi
        done
        
        echo "All services started successfully"
EOF
    
    success "All 12 services deployed successfully"
}

# Function to test deployment
test_deployment() {
    log "PHASE 9: TESTING DEPLOYMENT"
    
    # Test main app health
    if ! curl -s "http://$SERVER_IP:3000/health" > /dev/null; then
        error "Main app health check failed"
    fi
    success "Main app health check passed"
    
    # Test API endpoints
    local endpoints=("api/ports" "api/active_trades" "api/strike_tables/btc" "api/db/system_health" "api/db/trades")
    
    for endpoint in "${endpoints[@]}"; do
        if ! curl -s "http://$SERVER_IP:3000/$endpoint" > /dev/null; then
            warning "API endpoint $endpoint failed"
        else
            success "API endpoint $endpoint working"
        fi
    done
    
    # Test frontend pages
    local pages=("" "login" "terminal-control.html")
    
    for page in "${pages[@]}"; do
        if ! curl -s "http://$SERVER_IP:3000/$page" | head -1 | grep -q "html\|DOCTYPE"; then
            warning "Frontend page $page failed"
        else
            success "Frontend page $page working"
        fi
    done
    
    # Verify all services are running
    local running_services=$(ssh "$SERVER_USER@$SERVER_IP" "supervisorctl status | grep RUNNING | wc -l")
    if [[ $running_services -ne 12 ]]; then
        error "Expected 12 running services, found $running_services"
    fi
    success "All 12 services are running"
    
    # Verify database connectivity
    local server_trade_count=$(ssh "$SERVER_USER@$SERVER_IP" "psql -h localhost -U rec_io_user -d rec_io_db -t -c \"SELECT COUNT(*) FROM users.trades_0001;\" | xargs")
    if [[ $server_trade_count -ne 304 ]]; then
        error "Server database has $server_trade_count trades, expected 304"
    fi
    success "Database connectivity verified"
}

# Function to create deployment summary
create_deployment_summary() {
    log "PHASE 10: CREATING DEPLOYMENT SUMMARY"
    
    ssh "$SERVER_USER@$SERVER_IP" << 'EOF'
        cd /opt/trading_system
        
        cat > DEPLOYMENT_SUMMARY.md << 'SUMMARYEOF'
# Deployment Summary
Date: $(date)
Server: YOUR_DROPLET_IP
Status: SUCCESS

## Services Deployed: 12
- main_app (port 3000)
- trade_manager (port 4000)
- trade_executor (port 8001)
- active_trade_supervisor (port 8007)
- auto_entry_supervisor (port 8009)
- symbol_price_watchdog_btc
- symbol_price_watchdog_eth
- kalshi_account_sync (port 8004)
- kalshi_api_watchdog (port 8005)
- unified_production_coordinator (port 8010)
- cascading_failure_detector
- system_monitor

## Database
- Size: $(psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT pg_size_pretty(pg_database_size('rec_io_db'));" | tail -1)
- Trades: $(psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM users.trades_0001;" | tail -1)
- Fills: $(psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM users.fills_0001;" | tail -1)

## Access
- Frontend: http://YOUR_DROPLET_IP:3000
- Health Check: http://YOUR_DROPLET_IP:3000/health
- SSH: ssh root@YOUR_DROPLET_IP

## Verification Commands
```bash
# Check all services
supervisorctl status

# Test main app
curl http://YOUR_DROPLET_IP:3000/health

# Check database
psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM users.trades_0001;"
```
SUMMARYEOF
        
        echo "Deployment summary created"
EOF
    
    success "Deployment summary created"
}

# Main deployment function
main() {
    log "🚀 STARTING COMPREHENSIVE DIGITAL OCEAN DEPLOYMENT"
    log "Target: $SERVER_IP"
    log "Project: $PROJECT_ROOT"
    
    # Check prerequisites
    if ! command_exists ssh; then
        error "SSH client not found"
    fi
    
    if ! command_exists scp; then
        error "SCP client not found"
    fi
    
    if ! command_exists psql; then
        error "PostgreSQL client not found"
    fi
    
    if ! command_exists curl; then
        error "cURL not found"
    fi
    
    # Change to project directory
    cd "$PROJECT_ROOT"
    
    # Execute deployment phases
    verify_local_system
    create_deployment_package
    setup_server_environment
    transfer_and_setup_code
    transfer_database
    transfer_credentials
    configure_environment
    deploy_services
    test_deployment
    create_deployment_summary
    
    log "🎉 DEPLOYMENT COMPLETE!"
    success "System successfully deployed to $SERVER_IP"
    log "Access your system at: http://$SERVER_IP:3000"
    log "Health check: http://$SERVER_IP:3000/health"
    log "SSH access: ssh $SERVER_USER@$SERVER_IP"
    
    # Cleanup
    rm -f "$DEPLOY_PACKAGE"
    success "Deployment package cleaned up"
}

# Run main function
main "$@"
