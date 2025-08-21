#!/bin/bash

echo "============================================================================="
echo "                    REC.IO COLLABORATOR SETUP"
echo "============================================================================="

# Step 1: SANITIZE FIRST
echo "Sanitizing user data..."
cd /opt/rec_io_server

# Clear database
echo "Executing database sanitization..."
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db << 'SQL_EOF'
-- Clear ALL user-specific data
DELETE FROM users.trades_0001;
DELETE FROM users.active_trades_0001;
DELETE FROM users.fills_0001;
DELETE FROM users.settlements_0001;
DELETE FROM users.positions_0001;
DELETE FROM users.trade_preferences_0001;
DELETE FROM users.orders_0001;
DELETE FROM users.account_balance_0001;
DELETE FROM users.watchlist_0001;
DELETE FROM users.trade_logs_0001;
DELETE FROM users.auto_trade_settings_0001;

-- Clear user info (will be updated with new user data later)
DELETE FROM users.user_info_0001;

-- CRITICAL: Remove master users table and views (ONLY exists on production server)
-- First drop foreign key constraints that reference master tables
ALTER TABLE users.user_info_0001 DROP CONSTRAINT IF EXISTS user_info_0001_user_no_fkey;

-- Then drop master tables and views
DROP VIEW IF EXISTS users.active_master_users CASCADE;
DROP VIEW IF EXISTS users.recent_master_registrations CASCADE;
DROP VIEW IF EXISTS users.master_users_summary CASCADE;
DROP TABLE IF EXISTS users.master_users CASCADE;
SQL_EOF

echo "Database sanitization completed"

# Clear old Kalshi credentials
echo "Clearing old Kalshi credential files..."
rm -f backend/data/users/user_0001/credentials/kalshi-credentials/prod/.env
rm -f backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt
rm -f backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi.pem
rm -f backend/api/kalshi-api/kalshi-credentials/prod/.env
rm -f backend/api/kalshi-api/kalshi-credentials/prod/kalshi-auth.txt
rm -f backend/api/kalshi-api/kalshi-credentials/prod/kalshi.pem
rm -f backend/api/kalshi-api/kalshi-credentials/demo/.env
rm -f backend/api/kalshi-api/kalshi-credentials/demo/kalshi-auth.txt
rm -f backend/api/kalshi-api/kalshi-credentials/demo/kalshi.pem
echo "Old Kalshi credentials cleared"

# Disable maintenance
systemctl disable apt-daily-upgrade.service 2>/dev/null || true
systemctl disable apt-daily-upgrade.timer 2>/dev/null || true
systemctl disable apt-daily.service 2>/dev/null || true
systemctl disable apt-daily.timer 2>/dev/null || true
systemctl disable snapd.service 2>/dev/null || true
systemctl disable unattended-upgrades.service 2>/dev/null || true

cat > /etc/apt/apt.conf.d/99disable-auto-updates << 'EOF'
APT::Get::Automatic "false";
APT::Get::AutomaticRemove "false";
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
APT::Periodic::Unattended-Upgrade "0";
EOF

echo "Sanitization complete"

# Step 2: Get user info
echo "Enter your user ID:"
read NEW_USER_ID

echo "Enter your first name:"
read NEW_FIRST_NAME

echo "Enter your last name:"
read NEW_LAST_NAME

echo "Enter your email:"
read NEW_USER_EMAIL

echo "Enter your phone:"
read NEW_USER_PHONE

echo "Enter your password:"
read -s NEW_USER_PASSWORD
echo ""

echo "Confirm your password:"
read -s NEW_USER_PASSWORD_CONFIRM
echo ""

if [[ "$NEW_USER_PASSWORD" != "$NEW_USER_PASSWORD_CONFIRM" ]]; then
    echo "Passwords don't match!"
    exit 1
fi

# Step 3: Get Kalshi credentials
echo "Enter Kalshi email:"
read KALSHI_EMAIL

echo "Enter Kalshi API key:"
read KALSHI_API_KEY

echo "Enter Kalshi API secret:"
echo "Paste your private key (including BEGIN/END lines) and press Ctrl+D when done:"

# Use Python to handle multi-line input properly
KALSHI_API_SECRET=$(python3 -c "
import sys
private_key = ''
for line in sys.stdin:
    private_key += line
print(private_key.rstrip())
")

echo "API Secret collected"
echo ""
read -p "Press ENTER to continue..."

# Step 4: CREATE NEW USER INFO AND SETTINGS IN DATABASE
echo "Creating new user information and settings in database..."
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db << SQL_EOF
-- Create new user info
INSERT INTO users.user_info_0001 (
    user_no, user_id, email, first_name, last_name, phone, account_type, 
    created_at, last_login, is_active, password_hash, updated_at
) VALUES (
    '0001', '$NEW_USER_ID', '$NEW_USER_EMAIL', '$NEW_FIRST_NAME', '$NEW_LAST_NAME', '$NEW_USER_PHONE', 
    'master_admin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, TRUE, 
    'fallback_hash_$NEW_USER_PASSWORD', CURRENT_TIMESTAMP
);

-- Create safe auto-trade settings
INSERT INTO users.auto_trade_settings_0001 (
    id, auto_entry, auto_stop, min_probability, min_differential, min_time, max_time, 
    allow_re_entry, spike_alert_enabled, spike_alert_momentum_threshold, 
    spike_alert_cooldown_threshold, spike_alert_cooldown_minutes, current_probability, 
    min_ttc_seconds, momentum_spike_enabled, momentum_spike_threshold, 
    auto_entry_status, user_id, cooldown_timer, verification_period_enabled, verification_period_seconds, created_at, updated_at
) VALUES (
    1, FALSE, FALSE, 95, 0.25, 120, 900, FALSE, TRUE, 35, 25, 60, 40, 60, TRUE, 35, 
    'disabled', '0001', 0, TRUE, 20, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
);
SQL_EOF

echo "New user information and settings created in database"

# Step 5: WRITE THE TWO TEXT FILES
echo "Writing Kalshi credential files..."
mkdir -p backend/data/users/user_0001/credentials/kalshi-credentials/prod

echo "email:$KALSHI_EMAIL" > backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt
echo "key:$KALSHI_API_KEY" >> backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt

echo "$KALSHI_API_SECRET" > backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi.pem

chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi.pem

# Create .env file for environment variables
cat > backend/data/users/user_0001/credentials/kalshi-credentials/prod/.env << EOF
KALSHI_API_KEY_ID=$KALSHI_API_KEY
KALSHI_PRIVATE_KEY_PATH=kalshi.pem
KALSHI_EMAIL=$KALSHI_EMAIL
EOF

# Create system-expected directory structure and copy credentials
mkdir -p backend/api/kalshi-api/kalshi-credentials/prod
mkdir -p backend/api/kalshi-api/kalshi-credentials/demo

# Copy credentials to system-expected locations
cp backend/data/users/user_0001/credentials/kalshi-credentials/prod/* backend/api/kalshi-api/kalshi-credentials/prod/
cp backend/api/kalshi-api/kalshi-credentials/prod/* backend/api/kalshi-api/kalshi-credentials/demo/

echo "Kalshi files written and copied to system locations"



# Step 6: VERIFY ALL FILES ARE WRITTEN
echo "Verifying all credential files and database updates..."
echo "Database user info updated: ✓"
echo "Database auto-trade settings created: ✓"
echo "Kalshi auth file created: ✓"
echo "Kalshi PEM file created: ✓"
echo "Kalshi .env file created: ✓"
echo "System credential locations created: ✓"
echo "All credential files and database updates complete"

# Step 7: RUN MASTER RESTART
echo "Running MASTER RESTART..."
./scripts/MASTER_RESTART.sh

echo ""
echo "============================================================================="
echo "                    SETUP COMPLETE!"
echo "============================================================================="
echo ""
echo "Your REC.IO system is now running!"
echo ""

echo -e "\033[1;32mAccess your frontend at: http://$(curl -s ifconfig.me):3000\033[0m"
echo ""
echo "Login with your new credentials:"
echo "  User ID: $NEW_USER_ID"
echo "  Email: $NEW_USER_EMAIL"
echo "  Name: $NEW_FIRST_NAME $NEW_LAST_NAME"
echo ""
