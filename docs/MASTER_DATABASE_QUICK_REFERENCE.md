# Master Database Quick Reference

## Database Setup Complete ✅

The master database table has been successfully configured in your `rec_io_db` database.

### **Table Location**
- **Database**: `rec_io_db`
- **Schema**: `users`
- **Table**: `master_users`

### **Table Structure**
```sql
CREATE TABLE users.master_users (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    server_ip VARCHAR(45),
    server_hostname VARCHAR(255),
    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    system_version VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    notes TEXT
);
```

### **Useful Views Created**
- `users.active_master_users` - Active users only
- `users.recent_master_registrations` - Recent registrations (30 days)
- `users.master_users_summary` - Summary statistics

### **Indexes Created**
- Primary key on `id`
- Unique constraint on `user_id`
- Index on `email`
- Index on `status`
- Index on `registration_date`
- Index on `server_ip`

## Management Commands

### **View Users**
```bash
# Show all users
./scripts/manage_master_users.sh list

# Show active users only
./scripts/manage_master_users.sh active

# Show recent registrations
./scripts/manage_master_users.sh recent

# Show summary statistics
./scripts/manage_master_users.sh summary
```

### **Add/Update Users**
```bash
# Add a new user
./scripts/manage_master_users.sh add-user user_0002 "John Doe" "john@example.com" "555-1234" "192.168.1.101" "johns-server"

# Update user status
./scripts/manage_master_users.sh update-status user_0002 inactive

# Add notes to user
./scripts/manage_master_users.sh add-notes user_0002 "Testing phase completed"
```

### **Search and Details**
```bash
# Search for users
./scripts/manage_master_users.sh search "john"

# Show user details
./scripts/manage_master_users.sh user-details user_0002

# Delete user
./scripts/manage_master_users.sh delete-user user_0002
```

## Direct Database Queries

### **Common Queries**
```sql
-- View all users
SELECT user_id, name, email, server_ip, registration_date, status 
FROM users.master_users ORDER BY registration_date DESC;

-- Active users
SELECT user_id, name, email, server_ip FROM users.master_users WHERE status = 'active';

-- Recent registrations
SELECT user_id, name, email, registration_date 
FROM users.master_users 
WHERE registration_date > NOW() - INTERVAL '7 days';

-- Summary statistics
SELECT COUNT(*) as total_users,
       COUNT(CASE WHEN status = 'active' THEN 1 END) as active_users,
       COUNT(CASE WHEN status = 'inactive' THEN 1 END) as inactive_users
FROM users.master_users;
```

## Environment Variables for Collaborators

When collaborators want to register with your master database, they need these environment variables:

```bash
export MASTER_DB_HOST=your_server_ip
export MASTER_DB_NAME=rec_io_db
export MASTER_DB_USER=rec_io_user
export MASTER_DB_PASSWORD=rec_io_password
export MASTER_DB_PORT=5432
```

## Registration Process

### **For Collaborators**
1. Set environment variables (you provide these)
2. Run user registration: `./scripts/user_registration_system.sh --master-db`
3. User information automatically sent to your master database

### **For You**
1. Monitor registrations: `./scripts/manage_master_users.sh recent`
2. View all users: `./scripts/manage_master_users.sh list`
3. Manage user status and notes as needed

## Security Notes

- ✅ **No hardcoded credentials** in any scripts
- ✅ **Environment variable configuration** for security
- ✅ **Database indexes** for performance
- ✅ **User management tools** for administration
- ✅ **Audit trail** with timestamps

## Next Steps

1. **Share environment variables** with collaborators
2. **Test registration process** with a collaborator
3. **Monitor user registrations** as they come in
4. **Use management tools** to track and manage users

---

**Your master database is now ready to track all collaborator systems!** 🎉
