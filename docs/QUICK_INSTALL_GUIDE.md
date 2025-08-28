# REC.IO Quick Installation Guide

## One-Command Installation

The REC.IO system can be installed with a single command after cloning the repository.

### Prerequisites

- **Operating System**: macOS, Ubuntu/Debian, or CentOS/RHEL
- **Python**: 3.8 or higher
- **Disk Space**: At least 10GB available
- **Internet**: Active internet connection
- **Kalshi Account**: Trading credentials (API key and secret)

### Installation Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/rec-io-server.git
   cd rec-io-server
   ```

2. **Run the installation script**
   ```bash
   ./install.sh
   ```

3. **Follow the prompts**
   - Enter your personal information
   - Provide Kalshi trading credentials
   - Choose account type (demo or production)
   - Decide whether to clone system data

### What the Installation Does

The installation script will automatically:

- ✅ **Check system requirements** (Python, disk space, network)
- ✅ **Install dependencies** (PostgreSQL, Python packages, Supervisor)
- ✅ **Set up database** (Create schemas, tables, permissions)
- ✅ **Clone system data** (Optional: analytics, historical_data, live_data)
- ✅ **Create user profile** (Directories, credentials, preferences)
- ✅ **Configure services** (Supervisor, logging, ports)
- ✅ **🛡️ DISABLE AUTOMATIC MAINTENANCE** (Critical: Prevents system failures)
- ✅ **Start the system** (All services running)
- ✅ **Verify operation** (Database, API, web interface)

### 🛡️ Automatic Maintenance Protection

**CRITICAL**: The installation automatically disables Ubuntu's automatic maintenance services that can cause production failures:

- ❌ **APT Daily Upgrades** - Prevents automatic package updates
- ❌ **Unattended Upgrades** - Prevents automatic system updates  
- ❌ **Snap Updates** - Prevents automatic snap package updates
- ❌ **System Cleanup** - Prevents automatic file deletion

**Why This Matters**: These services can delete critical files (like virtual environment binaries) and cause complete system failures. The installation script protects your production trading system from these automatic operations.

### System Access

After installation, you can access:

- **Web Interface**: http://localhost:8000
- **Database**: localhost:5432 (rec_io_db)
- **Logs**: Check `installation.log` for details

### System Management

- **Start services**: `./scripts/MASTER_RESTART.sh`
- **Stop services**: `supervisorctl stop all`
- **View logs**: `supervisorctl tail`
- **Check status**: `supervisorctl status`

### Troubleshooting

If installation fails:

1. Check the `installation.log` file for details
2. Verify system requirements are met
3. Ensure Kalshi credentials are correct
4. Check port availability (5432, 8000-8010)

### Support

For installation issues or questions, check:
- Installation log: `installation.log`
- System logs: `/tmp/rec_io_*.log`
- Database logs: PostgreSQL service logs

---

**Note**: The installation includes optional system data cloning from the remote REC.IO system. This provides backtesting data and historical information needed for full system functionality. 