# Master Database Registration Guide

## Overview

The REC.IO system includes an optional **master database registration** feature that allows you to track all collaborator systems in a central database. This provides a comprehensive view of all deployed systems without requiring hardcoded credentials.

## How It Works

### **Environment Variable Configuration**
Instead of hardcoding database credentials, the system uses environment variables:

```bash
# Master database configuration
export MASTER_DB_HOST=your_master_db_host
export MASTER_DB_NAME=your_master_db_name
export MASTER_DB_USER=your_master_db_user
export MASTER_DB_PASSWORD=your_master_db_password
export MASTER_DB_PORT=5432  # Optional, defaults to 5432
```

### **Automatic Registration**
When collaborators run the user registration system with the `--master-db` flag, their information is automatically sent to your master database:

- ✅ **User information** (name, email, phone)
- ✅ **System information** (server IP, hostname)
- ✅ **Registration details** (date, system version)
- ✅ **Status tracking** (active, inactive)

## Setting Up Master Database Registration

### **Step 1: Create Master Database**

On your master server, create a PostgreSQL database for tracking:

```bash
# Connect to PostgreSQL as superuser
sudo -u postgres psql

# Create database and user
CREATE DATABASE rec_io_master;
CREATE USER rec_io_master_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE rec_io_master TO rec_io_master_user;
\q
```

### **Step 2: Configure Environment Variables**

On your master server, set the environment variables:

```bash
# Add to your shell profile or system environment
export MASTER_DB_HOST=your_master_server_ip
export MASTER_DB_NAME=rec_io_master
export MASTER_DB_USER=rec_io_master_user
export MASTER_DB_PASSWORD=your_secure_password
export MASTER_DB_PORT=5432
```

### **Step 3: Test Master Database Connection**

Test the connection from your master server:

```bash
# Test connection
PGPASSWORD=your_secure_password psql -h your_master_server_ip -U rec_io_master_user -d rec_io_master -c "SELECT version();"
```

## Using Master Database Registration

### **For Collaborators**

Collaborators can register with the master database in two ways:

#### **Option 1: Environment Variables (Recommended)**
```bash
# Set environment variables on collaborator's system
export MASTER_DB_HOST=your_master_server_ip
export MASTER_DB_NAME=rec_io_master
export MASTER_DB_USER=rec_io_master_user
export MASTER_DB_PASSWORD=your_secure_password

# Run registration with master database
./scripts/user_registration_system.sh --master-db
```

#### **Option 2: One-Time Setup**
```bash
# Run registration with master database (will prompt for credentials if not set)
./scripts/user_registration_system.sh --master-db
```

### **For You (Master System)**

#### **View All Registered Users**
```bash
# Connect to master database
PGPASSWORD=your_secure_password psql -h your_master_server_ip -U rec_io_master_user -d rec_io_master

# View all users
SELECT user_id, name, email, registration_date, status FROM system.master_users ORDER BY registration_date DESC;

# View active users
SELECT user_id, name, email FROM system.master_users WHERE status = 'active';

# View recent registrations
SELECT user_id, name, email, registration_date FROM system.master_users WHERE registration_date > NOW() - INTERVAL '7 days';
```

#### **Update User Status**
```bash
# Mark user as inactive
UPDATE system.master_users SET status = 'inactive', last_updated = NOW() WHERE user_id = 'user_0002';

# Add notes to user
UPDATE system.master_users SET notes = 'Testing phase completed', last_updated = NOW() WHERE user_id = 'user_0002';
```

## Master Database Schema

### **system.master_users Table**
```sql
CREATE TABLE system.master_users (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    system_version VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    notes TEXT
);
```

### **Sample Queries**

#### **System Overview**
```sql
-- Total registered users
SELECT COUNT(*) as total_users FROM system.master_users;

-- Users by status
SELECT status, COUNT(*) as count FROM system.master_users GROUP BY status;

-- Recent registrations
SELECT user_id, name, email, registration_date 
FROM system.master_users 
WHERE registration_date > NOW() - INTERVAL '30 days'
ORDER BY registration_date DESC;
```

#### **System Health**
```sql
-- Active users (contact / audit)
SELECT user_id, name, email, last_updated
FROM system.master_users
WHERE status = 'active'
ORDER BY last_updated DESC;

-- Inactive users
SELECT user_id, name, email, last_updated
FROM system.master_users 
WHERE status = 'inactive'
ORDER BY last_updated DESC;
```

## Security Considerations

### **Network Security**
- ✅ **Use VPN or private network** for master database access
- ✅ **Configure firewall rules** to allow only necessary connections
- ✅ **Use SSL/TLS** for database connections in production

### **Database Security**
- ✅ **Strong passwords** for database users
- ✅ **Limited permissions** for master database user
- ✅ **Regular backups** of master database
- ✅ **Audit logging** for access tracking

### **Environment Variables**
- ✅ **Secure storage** of environment variables
- ✅ **No hardcoded credentials** in scripts
- ✅ **Environment-specific** configurations

## Integration with Existing Workflow

### **Updated Collaborator Setup Process**

1. **Collaborator creates droplet** from your snapshot
2. **System automatically sanitizes** and sets up Git repository
3. **Collaborator runs setup script** with master database registration
4. **User information sent** to your master database
5. **System ready** for use with full tracking

### **Master Database Benefits**

- ✅ **Complete visibility** of all collaborator systems
- ✅ **Contact information** for all users
- ✅ **System tracking** (IP addresses, hostnames)
- ✅ **Registration history** and status management
- ✅ **No manual tracking** required

## Troubleshooting

### **Connection Issues**
```bash
# Test network connectivity
ping your_master_server_ip

# Test database connectivity
PGPASSWORD=your_secure_password psql -h your_master_server_ip -U rec_io_master_user -d rec_io_master -c "SELECT 1;"
```

### **Permission Issues**
```bash
# Check database permissions
PGPASSWORD=your_secure_password psql -h your_master_server_ip -U rec_io_master_user -d rec_io_master -c "\du"
```

### **Registration Failures**
```bash
# Check registration logs
tail -f /opt/rec_io/logs/user_registration_*.log

# Verify environment variables
echo "MASTER_DB_HOST: $MASTER_DB_HOST"
echo "MASTER_DB_NAME: $MASTER_DB_NAME"
echo "MASTER_DB_USER: $MASTER_DB_USER"
```

## Best Practices

### **For Master Database Setup**
1. **Use dedicated database** for user tracking
2. **Regular backups** of master database
3. **Monitor database size** and performance
4. **Archive old records** periodically

### **For Collaborators**
1. **Secure environment variables** storage
2. **Test connection** before registration
3. **Keep registration information** updated
4. **Report issues** to master system admin

### **For System Administration**
1. **Monitor registration activity**
2. **Track system health** across all users
3. **Maintain contact information** accuracy
4. **Provide support** for registration issues

---

## Summary

The master database registration system provides:

- ✅ **Centralized user tracking** without hardcoded credentials
- ✅ **Environment variable configuration** for security
- ✅ **Automatic registration** during user setup
- ✅ **Comprehensive user information** storage
- ✅ **Status management** and system tracking
- ✅ **Integration** with existing deployment workflow

**This system allows you to maintain a complete registry of all collaborator systems while maintaining security and flexibility.**
