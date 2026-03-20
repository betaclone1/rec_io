# 🚀 GOOGLE DRIVE CLOUD STORAGE SETUP GUIDE

## Overview
This guide walks you through setting up Google Drive integration for the REC.IO trading system, starting with `trades.db` as a test case.

## 📋 Prerequisites

### 1. Google Cloud Project Setup
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the Google Drive API:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Drive API"
   - Click "Enable"

### 2. Create Service Account
1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "Service Account"
3. Fill in details:
   - Name: `rec-io-trading-system`
   - Description: `Service account for REC.IO trading system cloud storage`
4. Click "Create and Continue"
5. Skip role assignment (we'll handle permissions manually)
6. Click "Done"

### 3. Generate Credentials
1. Click on your service account
2. Go to "Keys" tab
3. Click "Add Key" > "Create new key"
4. Choose "JSON" format
5. Download the JSON file
6. Save it as `google-drive-credentials.json` in your project

### 4. Google Drive Folder Setup
1. Go to [Google Drive](https://drive.google.com/)
2. Create a new folder called "REC.IO Trading Data"
3. Right-click the folder > "Share"
4. Add your service account email (from the JSON file) with "Editor" permissions
5. Copy the folder ID from the URL (the long string after `/folders/`)

## 🔧 Installation

### 1. Install Google Drive Dependencies
```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

### 2. Set Environment Variables
```bash
# Set the path to your credentials file
export GOOGLE_DRIVE_CREDENTIALS="/path/to/your/google-drive-credentials.json"

# Set your Google Drive folder ID
export GOOGLE_DRIVE_FOLDER_ID="your_folder_id_here"

# Enable cloud storage
export TRADING_SYSTEM_STORAGE="cloud"
```

### 3. Test the Integration
```bash
# Run the test script
python test_cloud_storage.py
```

## 🧪 Testing the Integration

### Phase 1: Local Testing
```bash
# Test with local storage first
export TRADING_SYSTEM_STORAGE="local"
python test_cloud_storage.py
```

### Phase 2: Cloud Testing
```bash
# Test with cloud storage
export TRADING_SYSTEM_STORAGE="cloud"
python test_cloud_storage.py
```

## 📊 Expected Results

### Successful Local Test:
```
🧪 TESTING CLOUD STORAGE INTEGRATION
==================================================
📊 Current storage type: local
🔍 Testing trades.db path resolution...
✅ Trades.db path: /path/to/backend/data/trade_history/trades.db
📁 Path exists: True
💾 Testing database operations...
✅ Test trade inserted: 1 records found
📝 Cloud storage not enabled - skipping cloud sync tests
✅ All tests completed successfully!
```

### Successful Cloud Test:
```
🧪 TESTING CLOUD STORAGE INTEGRATION
==================================================
📊 Current storage type: cloud
🔍 Testing trades.db path resolution...
✅ Trades.db path: /path/to/temp_cloud_sync/trades.db
📁 Path exists: True
💾 Testing database operations...
✅ Test trade inserted: 1 records found
☁️ Testing cloud sync...
📤 Upload to cloud: ✅ Success
📥 Download from cloud: ✅ Success
✅ All tests completed successfully!
```

## 🔄 Integration with Existing System

### Current System Access Pattern:
```python
# Before: Direct file access
trades_db_path = os.path.join(get_trade_history_dir(), "trades.db")

# After: Cloud-aware access
from backend.util.cloud_storage import get_trades_db_path
trades_db_path = get_trades_db_path()
```

### Files to Update:
1. `backend/trade_manager.py`
2. `backend/main.py`
3. `backend/active_trade_supervisor.py`
4. `backend/db_poller.py`
5. `backend/system_monitor.py`

## 🚨 Troubleshooting

### Common Issues:

#### 1. "Google Drive API not available"
```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

#### 2. "Credentials file not found"
- Check the path in `GOOGLE_DRIVE_CREDENTIALS`
- Ensure the JSON file exists and is readable

#### 3. "Permission denied"
- Make sure the service account has access to the Google Drive folder
- Check that the folder ID is correct

#### 4. "File not found in Google Drive"
- The first run will create an empty database
- Subsequent runs will sync with the cloud version

## 📈 Next Steps

### After Successful Testing:
1. **Update all trades.db references** in the codebase
2. **Test with real trading data**
3. **Add automatic sync scheduling**
4. **Extend to other databases** (active_trades.db, fills.db, etc.)

### Production Considerations:
1. **Backup strategy** - Keep local backups
2. **Conflict resolution** - Handle concurrent access
3. **Performance optimization** - Cache frequently accessed data
4. **Error handling** - Graceful fallback to local storage

## 🔐 Security Notes

1. **Keep credentials secure** - Don't commit to version control
2. **Use environment variables** - Never hardcode credentials
3. **Regular rotation** - Update service account keys periodically
4. **Minimal permissions** - Only grant necessary access

## 📞 Support

If you encounter issues:
1. Check the troubleshooting section above
2. Verify all environment variables are set correctly
3. Test with the provided test script
4. Check Google Cloud Console for API usage and errors 