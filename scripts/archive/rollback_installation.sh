#!/bin/bash
"""
Installation Rollback Script
Rolls back installation changes if setup fails.
"""

set -e

echo "🔄 Rolling back installation..."

# Stop all services
supervisorctl -c backend/supervisord.conf stop all 2>/dev/null || true

# Remove supervisor config
rm -f backend/supervisord.conf

# Remove user directories
rm -rf backend/data/users/user_0001

# Remove logs
rm -rf logs

# Drop database (optional - commented out for safety)
# sudo -u postgres psql -c "DROP DATABASE IF EXISTS rec_io_db;"
# sudo -u postgres psql -c "DROP USER IF EXISTS rec_io_user;"

echo "✅ Rollback completed"
