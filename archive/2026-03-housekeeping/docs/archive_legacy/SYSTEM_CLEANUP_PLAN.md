# 📋 REC.IO System Cleanup Plan

## 🎯 **CRITICAL ISSUES - IMMEDIATE FIXES**

### **1. Update requirements.txt with Missing Dependencies**

**Current State**: 5 critical dependencies are missing from requirements.txt but are actively used in the codebase:
- `flask-cors==4.0.0` (used in 4+ files)
- `psutil==6.1.0` (used in 3+ files) 
- `apscheduler==3.10.4` (used in 2+ files)
- `pandas==2.3.1` (used in 8+ files)
- `scipy==1.13.0` (used in 2+ files)

**Fix**: Add these dependencies to requirements.txt with proper version pinning.

**Checklist**:
- [x] Add `flask-cors==4.0.0` to requirements.txt
- [x] Add `psutil==6.1.0` to requirements.txt
- [x] Add `apscheduler==3.10.4` to requirements.txt
- [x] Add `pandas==2.3.1` to requirements.txt
- [x] Add `scipy==1.13.0` to requirements.txt
- [ ] Test installation on clean system
- [ ] Verify all imports work correctly

### **2. Fix Hardcoded User Detection in Authentication**

**Current State**: `scripts/setup_auth.py` hardcodes "user_0001" on lines 32 and 81, preventing dynamic user setup.

**Fix**: Implement dynamic user detection by:
- Reading current user from environment or user input
- Updating the script to work with any user ID
- Making it compatible with `setup_new_user.py` output

**Checklist**:
- [ ] Update `scripts/setup_auth.py` line 32 to detect user dynamically
- [ ] Update `scripts/setup_auth.py` line 81 to detect user dynamically
- [ ] Add user input prompt for user ID if not provided
- [ ] Test with multiple user scenarios
- [ ] Verify compatibility with `setup_new_user.py`

### **3. Standardize Kalshi Credential File Naming**

**Current State**: Inconsistent naming between creation and usage:
- Creation scripts create: `kalshi-auth.pem`
- Usage code expects: `kalshi.pem`
- 15+ files expect `kalshi.pem` but system creates `kalshi-auth.pem`

**Fix**: Either:
- Update all usage code to expect `kalshi-auth.pem`, OR
- Update creation scripts to create `kalshi.pem`, OR
- Implement proper symlink creation in setup scripts

**Checklist**:
- [ ] Choose consistent naming approach (recommend: `kalshi.pem`)
- [ ] Update `scripts/setup_new_user.py` to create `kalshi.pem`
- [ ] Update `scripts/create_kalshi_credentials.py` to create `kalshi.pem`
- [ ] Update all 15+ files that expect `kalshi.pem`:
  - [ ] `backend/trade_executor.py` (line 59)
  - [ ] `backend/api/kalshi-api/test_orderbook_websocket.py` (line 26)
  - [ ] `backend/api/kalshi-api/raw_orderbook_data.py` (line 26)
  - [ ] `backend/api/kalshi-api/test_public_trades_websocket.py` (line 43)
  - [ ] `backend/api/kalshi-api/test_market_ticker_websocket.py` (line 44)
  - [ ] `backend/api/kalshi-api/kalshi_account_sync_ws.py` (lines 82, 937)
  - [ ] `backend/api/kalshi-api/test_user_fills_websocket.py` (line 43)
  - [ ] `backend/api/kalshi-api/test_positions_rest_api.py` (line 55)
  - [ ] `backend/api/kalshi-api/kalshi_websocket_watchdog.py` (line 70)
  - [ ] `backend/api/kalshi-api/live_orderbook_snapshot.py` (line 29)
  - [ ] `backend/api/kalshi-api/kalshi_ws_api_watchdog.py` (line 61)
  - [ ] `backend/api/kalshi-api/kalshi_account_sync_OLD.py` (line 47)
  - [ ] `backend/api/kalshi-api/test_market_positions_websocket.py` (line 43)
- [ ] Test credential creation and usage
- [ ] Verify all Kalshi API calls work correctly

### **4. Add PEM Format Validation**

**Current State**: `scripts/setup_new_user.py` writes PEM files without validation, leading to malformed credentials.

**Fix**: Add PEM format validation in the `write_kalshi_credentials()` function to ensure proper RSA private key format.

**Checklist**:
- [ ] Add PEM format validation function
- [ ] Update `write_kalshi_credentials()` in `scripts/setup_new_user.py`
- [ ] Add validation for RSA private key format
- [ ] Add helpful error messages for malformed PEM
- [ ] Test with valid and invalid PEM content
- [ ] Verify PEM files are properly formatted

## 🔧 **HIGH PRIORITY - SYSTEM IMPROVEMENTS**

### **5. Add Python Version Check to Installation**

**Current State**: `scripts/INSTALL_SYSTEM.py` has no early Python version validation.

**Fix**: Add version check in `check_system_requirements()` function to validate Python 3.11+ before proceeding.

**Checklist**:
- [ ] Update `scripts/INSTALL_SYSTEM.py` `check_system_requirements()` function
- [ ] Add Python version validation (3.11+)
- [ ] Add helpful error message for incompatible versions
- [ ] Test with Python 3.10 (should fail gracefully)
- [ ] Test with Python 3.11+ (should proceed)
- [ ] Add version check to other installation scripts

### **6. Improve Error Handling in Service Startup**

**Current State**: Services fail silently with missing dependencies.

**Fix**: Add dependency validation before service startup in supervisor configuration.

**Checklist**:
- [ ] Add dependency validation script
- [ ] Update supervisor configuration to check dependencies
- [ ] Add graceful failure handling
- [ ] Add helpful error messages
- [ ] Test with missing dependencies
- [ ] Verify services start correctly with all dependencies

### **7. Fix Dynamic User Path Management**

**Current State**: 50+ files hardcode "user_0001" paths, making the system non-portable.

**Fix**: Implement proper user path management system that:
- Detects current user dynamically
- Updates all path references automatically
- Maintains backward compatibility

**Checklist**:
- [ ] Create user detection utility function
- [ ] Update all 50+ files with hardcoded paths:
  - [ ] `backend/main.py` (lines 52, 60, 61, 127, etc.)
  - [ ] `backend/util/paths.py` (lines 22, 40, 50, 64, etc.)
  - [ ] `backend/core/config/config.json` (lines 61, 75)
  - [ ] `backend/core/config/settings.py` (lines 118, 143)
  - [ ] `backend/active_trade_supervisor.py` (lines 1353, 1666, 1749)
  - [ ] `backend/auto_entry_supervisor.py` (lines 83, 155, 332, 345, 392, 958)
  - [ ] Plus 40+ other files with "user_0001" references
- [ ] Create user path management utility
- [ ] Add backward compatibility layer
- [ ] Test with multiple user scenarios
- [ ] Verify all paths work correctly

## 📊 **MEDIUM PRIORITY - ENHANCEMENTS**

### **8. Add Installation Prerequisites Documentation**

**Current State**: No clear system requirements listed.

**Fix**: Update `QUICK_INSTALL_GUIDE.md` with:
- Python 3.11+ requirement
- System dependencies (Homebrew, etc.)
- Pre-installation checklist

**Checklist**:
- [ ] Update `QUICK_INSTALL_GUIDE.md`
- [ ] Add system requirements section
- [ ] Add Python version requirement
- [ ] Add Homebrew installation instructions
- [ ] Add pre-installation checklist
- [ ] Add troubleshooting section
- [ ] Test installation guide on clean system

### **9. Implement Dependency Validation Script**

**Current State**: No way to validate all dependencies before installation.

**Fix**: Create a dependency validation script that:
- Checks all imports in the codebase
- Validates against requirements.txt
- Reports missing dependencies

**Checklist**:
- [ ] Create `scripts/validate_dependencies.py`
- [ ] Add import scanning functionality
- [ ] Add requirements.txt validation
- [ ] Add missing dependency reporting
- [ ] Add version compatibility checking
- [ ] Test with current system
- [ ] Test with missing dependencies

### **10. Add Installation Rollback Capability**

**Current State**: No way to rollback failed installations.

**Fix**: Implement installation state tracking and rollback functionality.

**Checklist**:
- [ ] Create installation state tracking
- [ ] Add rollback functionality
- [ ] Add backup creation before changes
- [ ] Add rollback script
- [ ] Test rollback functionality
- [ ] Add rollback documentation

## 🛠️ **IMPLEMENTATION PLAN**

### **Phase 1: Critical Fixes (Week 1)**

1. **Update requirements.txt**
   - Add missing dependencies with proper versions
   - Test installation on clean system

2. **Fix Authentication Script**
   - Implement dynamic user detection
   - Test with multiple user scenarios

3. **Standardize Credential Naming**
   - Choose consistent naming approach
   - Update all affected files
   - Test credential creation and usage

### **Phase 2: System Improvements (Week 2)**

4. **Add Python Version Validation**
   - Implement early version check
   - Add helpful error messages

5. **Improve Error Handling**
   - Add dependency validation
   - Implement graceful failure handling

6. **Fix User Path Management**
   - Create user detection system
   - Update path management utilities

### **Phase 3: Documentation & Testing (Week 3)**

7. **Update Documentation**
   - Add system requirements
   - Create installation troubleshooting guide

8. **Create Validation Scripts**
   - Dependency validation
   - System health checks

9. **Test Installation Process**
   - Fresh installation on clean systems
   - Cross-platform compatibility testing

## 🔍 **SPECIFIC FILES TO MODIFY**

### **Critical Files:**
- `requirements.txt` - Add missing dependencies
- `scripts/setup_auth.py` - Fix hardcoded user detection
- `scripts/setup_new_user.py` - Add PEM validation
- `scripts/INSTALL_SYSTEM.py` - Add version check

### **Files with Hardcoded Paths (50+ files):**
- `backend/main.py` (lines 52, 60, 61, 127, etc.)
- `backend/util/paths.py` (lines 22, 40, 50, 64, etc.)
- `backend/core/config/config.json` (lines 61, 75)
- `backend/core/config/settings.py` (lines 118, 143)
- Plus 40+ other files with "user_0001" references

### **Kalshi Credential Files (15+ files):**
- `backend/trade_executor.py` (line 59)
- `backend/api/kalshi-api/*` (multiple files)
- All expect "kalshi.pem" but system creates "kalshi-auth.pem"

## 📈 **SUCCESS METRICS**

- **Zero missing dependencies** in fresh installation
- **Dynamic user detection** working for any user ID
- **Consistent credential naming** across all services
- **Proper PEM validation** preventing malformed credentials
- **Python version validation** preventing installation failures
- **Improved error messages** for troubleshooting

## 🚨 **RISK MITIGATION**

1. **Backup current system** before making changes
2. **Test each fix** on clean installation
3. **Maintain backward compatibility** for existing users
4. **Create rollback procedures** for each change
5. **Document all changes** for future reference

## 📋 **TESTING CHECKLIST**

### **Pre-Implementation Testing:**
- [ ] Backup current system
- [ ] Create test environment
- [ ] Document current working state
- [ ] Create rollback plan

### **Post-Implementation Testing:**
- [ ] Test fresh installation on clean system
- [ ] Test with Python 3.10 (should fail gracefully)
- [ ] Test with Python 3.11+ (should work)
- [ ] Test with multiple user scenarios
- [ ] Test credential creation and usage
- [ ] Test all Kalshi API functionality
- [ ] Test all system services startup
- [ ] Test error handling and messages

### **Cross-Platform Testing:**
- [ ] Test on macOS (current)
- [ ] Test on Linux (if applicable)
- [ ] Test on Windows (if applicable)
- [ ] Test with different Python versions

## 📝 **DOCUMENTATION UPDATES**

### **Files to Update:**
- [ ] `QUICK_INSTALL_GUIDE.md` - Add system requirements
- [ ] `README.md` - Update installation instructions
- [ ] `DEPLOYMENT_GUIDE.md` - Add troubleshooting section
- [ ] Create `TROUBLESHOOTING.md` - Common issues and solutions
- [ ] Update `AUTHENTICATION_GUIDE.md` - Dynamic user setup

## 🎯 **PRIORITY RANKING**

### **Critical (Must Fix Before Next Release):**
1. Update requirements.txt with missing dependencies
2. Fix hardcoded user detection in authentication
3. Standardize Kalshi credential file naming
4. Add PEM format validation

### **High Priority (Should Fix Soon):**
5. Add Python version check to installation
6. Improve error handling in service startup
7. Fix dynamic user path management

### **Medium Priority (Nice to Have):**
8. Add installation prerequisites documentation
9. Implement dependency validation script
10. Add installation rollback capability

## 📊 **PROGRESS TRACKING**

### **Phase 1 Progress:**
- [x] Critical Fix 1: Missing Dependencies
- [ ] Critical Fix 2: User Detection
- [ ] Critical Fix 3: Credential Naming
- [ ] Critical Fix 4: PEM Validation

### **Phase 2 Progress:**
- [ ] System Improvement 1: Python Version Check
- [ ] System Improvement 2: Error Handling
- [ ] System Improvement 3: User Path Management

### **Phase 3 Progress:**
- [ ] Documentation Update 1: Installation Guide
- [ ] Documentation Update 2: Troubleshooting
- [ ] Testing Complete: All Scenarios

---

**Last Updated**: 2025-08-03  
**Status**: Planning Phase  
**Next Action**: Begin Phase 1 Critical Fixes 