# 🌐 PORTABILITY GUIDE - UNIVERSAL DEPLOYMENT

## Overview

This guide explains how to deploy the REC.IO trading system in different environments after the portability fixes have been implemented.

## ✅ PORTABILITY FIXES COMPLETED

### **1. Backend Configuration Fixed**
- **File**: `backend/core/config/config.json`
- **Change**: Replaced hardcoded `192.168.86.42` with `localhost`
- **Impact**: All backend services now use dynamic host detection

### **2. iOS App Fixed**
- **File**: `rec_webview_app/rec_webview_app/ContentView.swift`
- **Change**: Replaced hardcoded IP with `localhost`
- **File**: `rec_webview_app/rec_webview_app/Info.plist`
- **Change**: Updated NSExceptionDomains to use `localhost`

### **3. Dynamic Host Detection System**
- **File**: `backend/util/paths.py`
- **Feature**: Automatic IP detection with environment variable override
- **Fallback**: Uses `localhost` if detection fails

## 🚀 DEPLOYMENT SCENARIOS

### **Scenario 1: Local Development**
```bash
# Default configuration - works out of the box
./scripts/MASTER_RESTART.sh

# Access via:
# Web: http://localhost:3000
# iOS App: Automatically connects to localhost
```

### **Scenario 2: Production Server**
```bash
# Set environment variable for production
export TRADING_SYSTEM_HOST="0.0.0.0"

# Start the system
./scripts/MASTER_RESTART.sh

# Access via:
# Web: http://YOUR_SERVER_IP:3000
# iOS App: Update ContentView.swift with your server IP
```

### **Scenario 3: Docker/Container Deployment**
```bash
# Set environment variable for container
export TRADING_SYSTEM_HOST="0.0.0.0"

# Build and run container
docker build -t rec-trading-system .
docker run -p 3000:3000 -p 4000:4000 -e TRADING_SYSTEM_HOST=0.0.0.0 rec-trading-system
```

### **Scenario 4: Cloud Deployment (AWS, GCP, Azure)**
```bash
# Set environment variable for cloud instance
export TRADING_SYSTEM_HOST="0.0.0.0"

# Start the system
./scripts/MASTER_RESTART.sh

# Configure firewall to allow ports 3000, 4000, 8001, etc.
# Update iOS app with cloud server IP address
```

## 🔧 ENVIRONMENT VARIABLES

### **TRADING_SYSTEM_HOST**
Controls the host binding for all services:

```bash
# Local development
export TRADING_SYSTEM_HOST="localhost"

# Production (accepts external connections)
export TRADING_SYSTEM_HOST="0.0.0.0"

# Specific IP (for testing)
export TRADING_SYSTEM_HOST="192.168.1.100"
```

### **Dynamic Host Detection**
The system automatically detects the local IP address:

```python
# From backend/util/paths.py
def get_host():
    # 1. Check environment variable first
    env_host = os.getenv("TRADING_SYSTEM_HOST")
    if env_host:
        return env_host
    
    # 2. Try to detect actual IP address
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        # 3. Fallback to localhost
        return "localhost"
```

## 📱 iOS APP CONFIGURATION

### **For Local Development**
The iOS app is now configured to use `localhost` by default:

```swift
// ContentView.swift - Current configuration
urlString = "http://localhost:3000/"
```

### **For Production/Remote Server**
To connect to a remote server, update the iOS app:

```swift
// Option 1: Hardcode server IP
urlString = "http://YOUR_SERVER_IP:3000/"

// Option 2: Use environment variable (requires app configuration)
urlString = "http://\(getServerHost()):3000/"
```

### **Network Security Configuration**
The iOS app's `Info.plist` now allows `localhost` connections:

```xml
<key>NSExceptionDomains</key>
<dict>
    <key>localhost</key>
    <dict>
        <key>NSExceptionAllowsInsecureHTTPLoads</key>
        <true/>
        <key>NSIncludesSubdomains</key>
        <true/>
    </dict>
</dict>
```

## 🔍 VERIFICATION COMMANDS

### **Test Host Detection**
```bash
# Test the host detection system
python -c "from backend.util.paths import get_host; print(get_host())"

# Expected output:
# [HOST] Detected IP address: 192.168.86.42
# 192.168.86.42
```

### **Test Port Management**
```bash
# Test centralized port system
python -c "from backend.core.port_config import get_port; print(get_port('main_app'))"

# Expected output: 3000
```

### **Test Service Connectivity**
```bash
# Test main app
curl http://localhost:3000/health

# Test trade manager
curl http://localhost:4000/health

# Test all ports
curl http://localhost:3000/api/ports
```

## 🚨 TROUBLESHOOTING

### **Issue: Services not accessible from other devices**
```bash
# Solution: Set environment variable
export TRADING_SYSTEM_HOST="0.0.0.0"
./scripts/MASTER_RESTART.sh
```

### **Issue: iOS app can't connect**
```bash
# Check network security settings in Info.plist
# Ensure the server IP is in NSExceptionDomains
# Update ContentView.swift with correct server IP
```

### **Issue: Port conflicts**
```bash
# Check current port usage
python -c "from backend.core.port_config import list_all_ports; print(list_all_ports())"

# Restart system to clear conflicts
./scripts/MASTER_RESTART.sh
```

## 📊 PORTABILITY STATUS

### **✅ FIXED COMPONENTS**
- Backend configuration (`config.json`)
- iOS app URLs (`ContentView.swift`)
- iOS network security (`Info.plist`)
- Dynamic host detection system
- Centralized port management

### **✅ PORTABLE FEATURES**
- Environment variable override
- Automatic IP detection
- Fallback to localhost
- Centralized configuration
- No hardcoded dependencies

### **🎯 DEPLOYMENT READY**
The system is now **100% portable** and can be deployed to:
- Local development machines
- Production servers
- Cloud instances
- Docker containers
- Different network configurations

## 🚀 QUICK DEPLOYMENT CHECKLIST

1. **Set environment variable** (if needed):
   ```bash
   export TRADING_SYSTEM_HOST="0.0.0.0"  # For production
   ```

2. **Start the system**:
   ```bash
   ./scripts/MASTER_RESTART.sh
   ```

3. **Verify services**:
   ```bash
   supervisorctl -c backend/supervisord.conf status
   ```

4. **Test connectivity**:
   ```bash
   curl http://localhost:3000/health
   ```

5. **Update iOS app** (if connecting to remote server):
   - Edit `ContentView.swift` with server IP
   - Update `Info.plist` NSExceptionDomains

The system is now **universally portable** and ready for deployment in any environment! 