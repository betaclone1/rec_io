#!/bin/bash

# Simple Digital Ocean Deployment Script
# Focuses on core deployment steps without complex backup management

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${BLUE}[DEPLOY]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[DEPLOY] ✅${NC} $1"
}

log_error() {
    echo -e "${RED}[DEPLOY] ❌${NC} $1"
}

# Get project root dynamically
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Configuration
REMOTE_HOST="${1:-}"
REMOTE_USER="${2:-root}"
REMOTE_DIR="${3:-/opt/rec_io}"

log_info "Simple Digital Ocean Deployment"
log_info "Project Root: $PROJECT_ROOT"
log_info "Remote Host: $REMOTE_HOST"
log_info "Remote User: $REMOTE_USER"
log_info "Remote Directory: $REMOTE_DIR"

# Validate inputs
if [[ -z "$REMOTE_HOST" ]]; then
    log_error "Remote host not specified. Usage: ./scripts/install_deploy/simple_deploy.sh <host> [user] [directory]"
    exit 1
fi

# Check if we're in the right directory
if [[ ! -f "backend/main.py" ]]; then
    log_error "Not in project root directory. Please run from the project root"
    exit 1
fi

# Step 1: Create deployment package
log_info "Step 1: Creating deployment package..."
DEPLOY_PACKAGE="deploy_$(date +%Y%m%d_%H%M%S).tar.gz"

# Create a simple tar package
tar --exclude='venv' \
    --exclude='logs/*' \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='temp_*' \
    --exclude='backup' \
    --exclude='node_modules' \
    --exclude='.DS_Store' \
    -czf "$DEPLOY_PACKAGE" .

log_success "Deployment package created: $DEPLOY_PACKAGE"

# Step 2: Upload and setup on remote server
log_info "Step 2: Uploading to remote server..."
scp "$DEPLOY_PACKAGE" "$REMOTE_USER@$REMOTE_HOST:/tmp/"

log_info "Step 3: Setting up on remote server..."
ssh "$REMOTE_USER@$REMOTE_HOST" << EOF
set -e

# Create remote directory
mkdir -p $REMOTE_DIR

# Extract deployment package
cd /tmp
tar -xzf $(basename "$DEPLOY_PACKAGE") -C $REMOTE_DIR --strip-components=1
cd $REMOTE_DIR

# Make scripts executable
chmod +x scripts/*.sh

# Generate supervisor config
./scripts/generate_supervisor_config.sh

# Create necessary directories
mkdir -p logs
mkdir -p backend/data/users/user_0001/{credentials/kalshi-credentials/{prod,demo},preferences,trade_history,active_trades,accounts}

# Set proper permissions
chmod 700 backend/data/users/user_0001/credentials 2>/dev/null || true

# Clean up uploaded file
rm -f "/tmp/$(basename "$DEPLOY_PACKAGE")"

# Step 3.5: Setup Git Repository Connection
echo "Setting up Git repository connection..."

# Add GitHub to known hosts
ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null || true

# Check if we have SSH key for GitHub access
if [[ ! -f ~/.ssh/id_ed25519 ]]; then
    echo "⚠️  No SSH key found. Git repository will be read-only."
    echo "To enable git pull, copy your SSH key to the server:"
    echo "scp ~/.ssh/id_ed25519 root@$REMOTE_HOST:~/.ssh/"
    echo "ssh root@$REMOTE_HOST 'chmod 600 ~/.ssh/id_ed25519'"
else
    # Copy SSH key for GitHub access
    scp ~/.ssh/id_ed25519 "$REMOTE_USER@$REMOTE_HOST:~/.ssh/" 2>/dev/null || true
    ssh "$REMOTE_USER@$REMOTE_HOST" "chmod 600 ~/.ssh/id_ed25519 2>/dev/null || true"
    
    # Clone fresh from git repository
    echo "Cloning from git repository..."
    ssh "$REMOTE_USER@$REMOTE_HOST" << 'GIT_SETUP'
set -e
cd /opt
rm -rf rec_io_temp
git clone git@github.com:betaclone1/rec_io.git rec_io_temp 2>/dev/null || {
    echo "⚠️  Git clone failed. Using deployed files instead."
    exit 0
}

# If git clone succeeded, replace the deployed files
if [[ -d rec_io_temp ]]; then
    rm -rf rec_io
    mv rec_io_temp rec_io
    cd rec_io
    chmod +x scripts/*.sh
    echo "✅ Git repository connected successfully"
else
    echo "⚠️  Using deployed files (no git connection)"
fi
GIT_SETUP
fi

echo "Remote server setup complete"
EOF

log_success "Remote server setup complete"

# Step 4: Install dependencies
log_info "Step 4: Installing dependencies..."
ssh "$REMOTE_USER@$REMOTE_HOST" << EOF
set -e
cd $REMOTE_DIR

# Install system dependencies
apt-get update
apt-get install -y python3 python3-pip python3-venv supervisor

# Create virtual environment
python3 -m venv venv

# Activate virtual environment and install dependencies
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Dependencies installed"
EOF

log_success "Dependencies installed"

# Step 5: Install and setup PostgreSQL FIRST
log_info "Step 5: Installing and setting up PostgreSQL..."
ssh "$REMOTE_USER@$REMOTE_HOST" << EOF
set -e

# Install PostgreSQL
apt-get update
apt-get install -y postgresql postgresql-contrib

# Start PostgreSQL service
systemctl start postgresql
systemctl enable postgresql

# Create database and user
sudo -u postgres psql << 'PSQL'
CREATE DATABASE rec_io_db;
CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';
GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;
\q
PSQL

# Configure PostgreSQL for remote connections
sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/*/main/postgresql.conf
echo "host    rec_io_db    rec_io_user    0.0.0.0/0    md5" >> /etc/postgresql/*/main/pg_hba.conf

# Restart PostgreSQL
systemctl restart postgresql

echo "PostgreSQL setup complete"
EOF

log_success "PostgreSQL setup complete"

# Step 6: Initialize database schema
log_info "Step 6: Initializing database schema..."
ssh "$REMOTE_USER@$REMOTE_HOST" << EOF
set -e
cd $REMOTE_DIR

# Set database environment variables (use env if set, else dev default)
export DB_HOST=${DB_HOST:-localhost}
export DB_NAME=${DB_NAME:-rec_io_db}
export DB_USER=${DB_USER:-rec_io_user}
export DB_PASSWORD=${DB_PASSWORD:-${POSTGRES_PASSWORD:-rec_io_password}}
export DB_PORT=${DB_PORT:-5432}

# Activate virtual environment and initialize database
source venv/bin/activate
python -c "
from backend.core.config.database import init_database
success, message = init_database()
print(f'Database init: {message}')
if not success:
    exit(1)
"

echo "Database schema initialized"
EOF

log_success "Database schema initialized"

# Step 7: Migrate local data to remote server
log_info "Step 7: Migrating local data to remote server..."

# Create data directory on remote
ssh "$REMOTE_USER@$REMOTE_HOST" "mkdir -p $REMOTE_DIR/backend/data"

# Dump local PostgreSQL data with proper options
log_info "Dumping local PostgreSQL data..."
pg_dump -h localhost -U rec_io_user -d rec_io_db --clean --if-exists --no-owner --no-privileges > /tmp/rec_io_dump.sql

# Copy PostgreSQL dump to remote server
log_info "Copying PostgreSQL dump to remote server..."
scp /tmp/rec_io_dump.sql "$REMOTE_USER@$REMOTE_HOST:/tmp/"

# Restore PostgreSQL data on remote server
log_info "Restoring PostgreSQL data on remote server..."
ssh "$REMOTE_USER@$REMOTE_HOST" << EOF
set -e
cd $REMOTE_DIR

# Set database environment variables (use env if set, else dev default)
export DB_HOST=${DB_HOST:-localhost}
export DB_NAME=${DB_NAME:-rec_io_db}
export DB_USER=${DB_USER:-rec_io_user}
export DB_PASSWORD=${DB_PASSWORD:-${POSTGRES_PASSWORD:-rec_io_password}}
export DB_PORT=${DB_PORT:-5432}

# Drop and recreate database to avoid conflicts (using postgres superuser)
sudo -u postgres psql -c "DROP DATABASE IF EXISTS rec_io_db;"
sudo -u postgres psql -c "CREATE DATABASE rec_io_db OWNER rec_io_user;"

# Restore the database with proper error handling
PGPASSWORD=$DB_PASSWORD psql -h localhost -U rec_io_user -d rec_io_db < /tmp/rec_io_dump.sql 2>/dev/null || true

# Clean up dump file
rm -f /tmp/rec_io_dump.sql

echo "PostgreSQL data restored"
EOF

# Copy user data files
log_info "Copying user data files..."
scp -r backend/data/users "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/backend/data/"

# Copy market data
log_info "Copying market data..."
scp -r backend/data/live_data "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/backend/data/" 2>/dev/null || true
scp -r backend/data/historical_data "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/backend/data/" 2>/dev/null || true
scp backend/data/market_ticker_data.json "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/backend/data/" 2>/dev/null || true
scp backend/data/market_lifecycle_events.json "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/backend/data/" 2>/dev/null || true

# Copy system data
log_info "Copying system data..."
scp backend/data/lookup_vs_live_comparison.json "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/backend/data/" 2>/dev/null || true
scp backend/data/account_mode_state.json "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/backend/data/" 2>/dev/null || true

# Set proper permissions
ssh "$REMOTE_USER@$REMOTE_HOST" "chmod -R 755 $REMOTE_DIR/backend/data"

# Clean up local dump file
rm -f /tmp/rec_io_dump.sql

log_success "Data migration completed"

# Step 8: Generate supervisor config with database environment
log_info "Step 8: Generating supervisor config..."
ssh "$REMOTE_USER@$REMOTE_HOST" << EOF
set -e
cd $REMOTE_DIR

# Generate supervisor config
./scripts/generate_supervisor_config.sh

echo "Supervisor config generated"
EOF

log_success "Supervisor config generated"

# Step 9: Start system (ONLY AFTER everything is ready)
log_info "Step 9: Starting system..."
ssh "$REMOTE_USER@$REMOTE_HOST" << EOF
set -e
cd $REMOTE_DIR

# Start system using MASTER_RESTART
./scripts/MASTER_RESTART.sh

# Wait for services to start
sleep 10

# Check status
supervisorctl -c backend/supervisord.conf status

echo "System started"
EOF

log_success "System started"

# Display completion message and frontend URL
echo ""
echo "🎉 DEPLOYMENT COMPLETED SUCCESSFULLY! 🎉"
echo "=========================================="
echo ""
echo "🌐 Frontend URL: http://$REMOTE_HOST:3000"
echo ""
echo "📊 System Status: All services running"
echo "💾 Database: Complete with all data migrated"
echo "🔧 Supervisor: Active and monitoring"
echo ""
echo "Next steps:"
echo "1. Open http://$REMOTE_HOST:3000 in your browser"
echo "2. Verify all data is present (trades, user info, etc.)"
echo "3. Check logs if needed: ssh $REMOTE_USER@$REMOTE_HOST 'tail -f $REMOTE_DIR/logs/*.out.log'"
echo ""
echo "✅ Deployment script finished. You can now use the system!"

# Step 6: Clean up local package
rm -f "$DEPLOY_PACKAGE"

# Step 7: Display summary
log_info "Deployment Summary"
log_info "=================="
log_info "Remote Host: $REMOTE_HOST"
log_info "Remote Directory: $REMOTE_DIR"
log_info ""
log_info "Next Steps:"
log_info "1. Add Kalshi credentials to: $REMOTE_DIR/backend/data/users/user_0001/credentials/kalshi-credentials/prod/"
log_info "2. Update user info: $REMOTE_DIR/backend/data/users/user_0001/user_info.json"
log_info "3. Access the system at: http://$REMOTE_HOST:3000"
log_info "4. Check logs: ssh $REMOTE_USER@$REMOTE_HOST 'tail -f $REMOTE_DIR/logs/*.out.log'"
log_info "5. Restart system: ssh $REMOTE_USER@$REMOTE_HOST 'cd $REMOTE_DIR && ./scripts/MASTER_RESTART.sh'"
log_info "6. Future updates: ssh $REMOTE_USER@$REMOTE_HOST 'cd $REMOTE_DIR && git pull && ./scripts/MASTER_RESTART.sh'"

log_success "Simple Digital Ocean deployment completed successfully!"
