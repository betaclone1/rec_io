# REC.IO Project Structure

## Root Directory (Idiot-Proof)

### **Installation (ONE WAY ONLY)**
- `INSTALL.md` - **THE ONLY installation guide you need**
- `install.sh` - **THE ONLY installation script**

### **Core System**
- `README.md` - Main project documentation
- `requirements.txt` - Python dependencies
- `requirements-core.txt` - Core Python dependencies

### **Directories**
- `backend/` - Backend application code
- `frontend/` - Frontend web interface
- `scripts/` - System management scripts
- `docs/` - Detailed documentation (for reference)
- `config/` - Configuration files
- `logs/` - System logs
- `tests/` - Test files
- `venv/` - Python virtual environment

## 🚀 Installation Process (SIMPLE)

### **Step 1: Install**
```bash
curl -sSL https://raw.githubusercontent.com/betaclone1/rec_io/main/install.sh | bash
```

### **Step 2: Access**
- Web Interface: `http://YOUR_DROPLET_IP:3000`

## 📁 Documentation

### **Quick Start**
- `INSTALL.md` - **THE ONLY guide you need**

### **Reference**
- `README.md` - System overview
- `docs/` - Detailed documentation (if needed)

## 🔧 System Management

### **Core Scripts**
- `scripts/MASTER_RESTART.sh` - Start/stop all services
- `scripts/package_user_data.sh` - Backup and migration

---

**That's it! One command to install, one guide to follow.** 🎉
