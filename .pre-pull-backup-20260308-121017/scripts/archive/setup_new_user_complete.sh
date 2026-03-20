#!/bin/bash

# Complete New User Setup Script for REC.IO Trading System
# This script sets up everything needed for a new user on a fresh machine

set -e

echo "🚀 REC.IO Trading System - Complete New User Setup"
echo "=================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[SETUP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SETUP] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[SETUP] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[SETUP] ❌${NC} $1"
}

# Get project root
PROJECT_ROOT=$(pwd)

print_status "Project root: $PROJECT_ROOT"

# Step 1: Check system requirements
print_status "Checking system requirements..."

# Check Python
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed"
    exit 1
fi

# Check PostgreSQL
if ! command -v psql &> /dev/null; then
    print_error "PostgreSQL is not installed"
    print_warning "Please install PostgreSQL first:"
    echo "  Ubuntu: sudo apt install postgresql postgresql-client"
    echo "  macOS: brew install postgresql"
    exit 1
fi

# Check supervisor
if ! command -v supervisord &> /dev/null; then
    print_error "Supervisor is not installed"
    print_warning "Please install supervisor first:"
    echo "  Ubuntu: sudo apt install supervisor"
    echo "  macOS: brew install supervisor"
    exit 1
fi

print_success "System requirements met"

# Step 2: Setup PostgreSQL
print_status "Setting up PostgreSQL..."

# Start PostgreSQL service
if command -v systemctl &> /dev/null; then
    sudo systemctl start postgresql
    sudo systemctl enable postgresql
fi

# Create database and user
sudo -u postgres psql -c "CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';" 2>/dev/null || print_warning "User rec_io_user already exists"
sudo -u postgres psql -c "CREATE DATABASE rec_io_db OWNER rec_io_user;" 2>/dev/null || print_warning "Database rec_io_db already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;"

print_success "PostgreSQL setup completed"

# Step 3: Setup database schema
print_status "Setting up database schema..."

# Run the schema setup script
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -f scripts/setup_database_schema.sql

print_success "Database schema setup completed"

# Step 3.5: Verify database setup
print_status "Verifying database setup..."
python3 scripts/verify_database_setup.py
if [ $? -ne 0 ]; then
    print_error "Database setup verification failed"
    exit 1
fi
print_success "Database setup verified"

# Step 4: Setup Python environment
print_status "Setting up Python environment..."

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
print_status "Installing Python dependencies..."

# Try full requirements first
if pip install -r requirements.txt; then
    print_success "All dependencies installed successfully"
else
    print_warning "Some dependencies failed, trying core requirements..."
    pip install -r requirements-core.txt
    print_success "Core dependencies installed successfully"
fi

# Step 5: Create user directory structure
print_status "Creating user directory structure..."

mkdir -p backend/data/users/user_0001/{credentials/kalshi-credentials/{prod,demo},preferences,trade_history,active_trades,accounts}
chmod 700 backend/data/users/user_0001/credentials

# Create user info file
cat > backend/data/users/user_0001/user_info.json << EOF
{
  "user_id": "user_0001",
  "name": "New User",
  "email": "user@example.com",
  "account_type": "user",
  "created": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF

# Create credential files (user must fill in actual values)
touch backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt
touch backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.pem
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.pem

print_success "User directory structure created"

# Step 6: Generate supervisor configuration
print_status "Generating supervisor configuration..."

# Make the script executable and run it
chmod +x scripts/generate_supervisor_config.sh
./scripts/generate_supervisor_config.sh

print_success "Supervisor configuration generated"

# Step 7: Create logs directory
print_status "Creating logs directory..."

mkdir -p logs

print_success "Logs directory created"

# Step 8: Test database connection
print_status "Testing database connection..."

# Test the database connection
python3 -c "
from backend.core.config.database import test_database_connection
success, message = test_database_connection()
print(f'Database test: {message}')
if not success:
    exit(1)
"

print_success "Database connection test passed"

# Step 9: Start the system
print_status "Starting the trading system..."

# Start supervisor
supervisord -c backend/supervisord.conf

# Wait a moment for services to start
sleep 3

# Check service status
print_status "Checking service status..."

supervisorctl -c backend/supervisord.conf status

# Step 9.5: Verify service startup
print_status "Verifying service startup..."
sleep 5
supervisorctl -c backend/supervisord.conf status | grep -q "RUNNING"
if [ $? -ne 0 ]; then
    print_error "Some services failed to start"
    supervisorctl -c backend/supervisord.conf status
    exit 1
fi
print_success "All services started successfully"

print_success "Trading system started"

# Step 10: Final verification
print_status "Performing final verification..."

# Verify API endpoints
print_status "Verifying API endpoints..."
if curl -s http://localhost:3000/health > /dev/null; then
    print_success "Main API endpoint responding"
else
    print_error "Main API endpoint not responding"
    exit 1
fi

# Run comprehensive service verification
print_status "Running comprehensive service verification..."
python3 scripts/verify_services.py
if [ $? -ne 0 ]; then
    print_error "Service verification failed"
    exit 1
fi
print_success "All services verified successfully"

# Check port usage
print_status "Checking port usage..."
netstat -tlnp 2>/dev/null | grep -E "(3000|4000|8001|8007|8009|8004|8005|8010)" || print_warning "Some services may not be listening yet"

echo ""
echo "🎉 REC.IO Trading System setup completed successfully!"
echo ""
echo "📋 System Information:"
echo "   - Main Application: http://localhost:3000"
echo "   - Database: PostgreSQL (rec_io_db)"
echo "   - User: user_0001"
echo "   - Logs: $PROJECT_ROOT/logs/"
echo ""
echo "🔧 Management Commands:"
echo "   - Check status: supervisorctl -c backend/supervisord.conf status"
echo "   - View logs: tail -f logs/*.err.log"
echo "   - Restart system: ./scripts/MASTER_RESTART.sh"
echo ""
echo "⚠️  Next Steps:"
echo "   1. Add your Kalshi credentials to:"
echo "      backend/data/users/user_0001/credentials/kalshi-credentials/prod/"
echo "   2. Update user info in:"
echo "      backend/data/users/user_0001/user_info.json"
echo "   3. Access the web interface at http://localhost:3000"
echo ""
print_success "Setup completed successfully!"
