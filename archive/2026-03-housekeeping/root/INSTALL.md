# REC.IO Installation Guide

## 🚀 ONE COMMAND INSTALLATION

### **For New Users**

**Copy and paste this command on your Digital Ocean droplet:**

```bash
curl -sSL https://raw.githubusercontent.com/betaclone1/rec_io/main/install.sh | bash
```

**The installation will:**
1. **🔐 Ask for Kalshi credentials FIRST** (interactive)
2. **📦 Install system dependencies** (PostgreSQL, Python, etc.)
3. **🗄️ Setup PostgreSQL database** (create DB, user, tables)
4. **📥 Clone the repository** (get the code)
5. **🐍 Setup Python environment** (venv, dependencies)
6. **💾 Initialize database schema** (create tables and VERIFY)
7. **👤 Create user profile** (save credentials)
8. **✅ Show database summary** (table counts by schema)

### **After Installation**

**The script will show you:**
- Total database tables created
- Tables in each schema (analytics, historical_data, live_data)
- Database connectivity status
- Installation directory and server IP

**To start the system:**
```bash
cd /opt/rec_io
./scripts/MASTER_RESTART.sh
```

**Then access your system:**
- Web Interface: `http://YOUR_DROPLET_IP:3000`
- Health Check: `http://YOUR_DROPLET_IP:3000/health`

## 📋 System Requirements

- **OS**: Ubuntu 22.04 LTS
- **RAM**: 2GB minimum
- **Storage**: 10GB free space

## 🔐 Kalshi Credentials

**During installation, you'll be prompted to enter:**
- Kalshi Email
- Kalshi API Key
- Kalshi API Secret

**If you skip credentials:**
- System will run in demo mode
- You can add credentials later by editing: `backend/data/users/user_0001/credentials/kalshi-credentials/prod/credentials.json`

## 🆘 Need Help?

- **Check logs**: `tail -f /opt/rec_io/logs/*.out.log`
- **System status**: `supervisorctl status`
- **Restart system**: `cd /opt/rec_io && ./scripts/MASTER_RESTART.sh`
- **Installation log**: `/tmp/rec_io_installation.log`

---

**Ready to start?** Just run the one command above! 🚀
