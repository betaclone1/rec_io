# REC.IO v2 Security and Secrets Management

## Security Overview

The REC.IO v2 system implements a comprehensive security framework designed to protect sensitive trading data, user credentials, and system integrity while maintaining operational efficiency.

## Secrets Management Architecture

### Credential Storage Hierarchy

#### User-Based Credential Isolation
```
backend/data/users/user_0001/credentials/
└── kalshi-credentials/
    ├── prod/
    │   ├── .env                    # Production API credentials
    │   └── private_key.pem         # Production private key
    └── demo/
        ├── .env                    # Demo API credentials
        └── private_key.pem         # Demo private key
```

#### Security Principles
- **User Isolation**: Credentials stored per-user for security
- **Environment Separation**: Production and demo credentials separated
- **No Repository Storage**: Credentials never committed to version control
- **File Permissions**: Secure file permissions (600) for credential files

### Credential File Formats

#### Kalshi API Credentials (.env)
```bash
# Production environment
KALSHI_API_KEY_ID=your_production_api_key_id
KALSHI_PRIVATE_KEY_PATH=private_key.pem

# Demo environment
KALSHI_API_KEY_ID=your_demo_api_key_id
KALSHI_PRIVATE_KEY_PATH=private_key.pem
```

#### Private Key Format (.pem)
```bash
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...
-----END PRIVATE KEY-----
```

### Authentication System

#### User Authentication
```python
# User credentials storage
backend/data/users/user_0001/user_info.json
{
    "username": "ewais",
    "password_hash": "pbkdf2:sha256:600000$...",
    "name": "Eric Wais",
    "email": "eric@example.com",
    "created_at": "2025-01-27T10:00:00Z"
}
```

#### Session Token Management
```python
# Active session tokens
backend/data/users/user_0001/auth_tokens.json
{
    "tokens": {
        "token_hash_1": {
            "user_id": "user_0001",
            "created_at": "2025-01-27T10:00:00Z",
            "expires_at": "2025-01-28T10:00:00Z",
            "device_id": "device_abc123"
        }
    }
}
```

#### Device Token Management
```python
# Remembered device tokens
backend/data/users/user_0001/device_tokens.json
{
    "devices": {
        "device_abc123": {
            "user_id": "user_0001",
            "created_at": "2025-01-27T10:00:00Z",
            "expires_at": "2026-01-27T10:00:00Z",
            "last_used": "2025-01-27T15:30:00Z"
        }
    }
}
```

## Security Implementation

### Password Security

#### Password Hashing
```python
import hashlib
import secrets
from cryptography.fernet import Fernet

def hash_password(password: str) -> str:
    """Hash password using PBKDF2 with salt"""
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        600000  # 600k iterations
    )
    return f"pbkdf2:sha256:600000${salt}${hash_obj.hex()}"

def verify_password(password: str, hash_value: str) -> bool:
    """Verify password against stored hash"""
    try:
        parts = hash_value.split('$')
        iterations = int(parts[1].split(':')[2])
        salt = parts[2]
        stored_hash = parts[3]
        
        hash_obj = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        )
        return hash_obj.hex() == stored_hash
    except Exception:
        return False
```

#### Token Security
```python
def generate_secure_token() -> str:
    """Generate cryptographically secure token"""
    return secrets.token_urlsafe(32)

def hash_token(token: str) -> str:
    """Hash token for storage"""
    return hashlib.sha256(token.encode()).hexdigest()

def verify_token(token: str, stored_hash: str) -> bool:
    """Verify token against stored hash"""
    return hash_token(token) == stored_hash
```

### API Security

#### Kalshi API Authentication
```python
import hmac
import hashlib
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes

def generate_kalshi_signature(method: str, full_path: str, timestamp: str, key_path: str) -> str:
    """Generate Kalshi API signature"""
    with open(key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )

    message = f"{timestamp}{method.upper()}{full_path}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode("utf-8")
```

### File Security

#### Secure File Permissions
```bash
# Set secure permissions for credential files
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/*/.env
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/*/*.pem

# Set secure permissions for user data
chmod 700 backend/data/users/user_0001/
chmod 600 backend/data/users/user_0001/user_info.json
chmod 600 backend/data/users/user_0001/auth_tokens.json
chmod 600 backend/data/users/user_0001/device_tokens.json
```

#### File Access Control
```python
import os
import stat

def secure_file_permissions(file_path: str):
    """Set secure file permissions"""
    os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)  # 600

def check_file_security(file_path: str) -> bool:
    """Check if file has secure permissions"""
    try:
        mode = os.stat(file_path).st_mode
        return mode & stat.S_IRWXG == 0 and mode & stat.S_IRWXO == 0
    except OSError:
        return False
```

## Environment Security

### Environment Variables

#### Required Environment Variables
```bash
# Database security
export POSTGRES_PASSWORD="secure_database_password"

# System security
export AUTH_ENABLED="true"  # Enable authentication in production
export TRADING_SYSTEM_HOST="production_host"

# API security
export KALSHI_API_KEY_ID="your_api_key_id"
export KALSHI_PRIVATE_KEY_PATH="path/to/private_key.pem"
```

#### Security Best Practices
- **No Hardcoded Secrets**: All secrets via environment variables
- **Secure Transmission**: HTTPS for all external communications
- **Credential Rotation**: Regular credential rotation schedule
- **Access Logging**: Comprehensive access logging

### Network Security

#### Firewall Configuration
```bash
# Allow only necessary ports
sudo ufw allow 3000/tcp  # Main application
sudo ufw allow 4000/tcp  # Trade manager
sudo ufw allow 8001/tcp  # Trade executor
sudo ufw allow 5432/tcp  # PostgreSQL (local only)
sudo ufw deny 22/tcp      # SSH (if not needed)
```

#### SSL/TLS Configuration
```python
# HTTPS configuration for production
ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain('cert.pem', 'key.pem')

# Secure WebSocket configuration
websocket_url = "wss://your-domain.com/ws"
```

## Access Control

### User Authentication Flow

#### Login Process
```python
@app.post("/api/auth/login")
async def login(request: Request):
    """User authentication endpoint"""
    data = await request.json()
    username = data.get("username")
    password = data.get("password")
    
    # Load user data
    user_data = load_user_data(username)
    if not user_data:
        return {"error": "Invalid credentials"}
    
    # Verify password
    if not verify_password(password, user_data["password_hash"]):
        return {"error": "Invalid credentials"}
    
    # Generate session token
    token = generate_secure_token()
    token_hash = hash_token(token)
    
    # Store token
    store_session_token(token_hash, user_data["user_id"])
    
    return {
        "token": token,
        "user": {
            "username": user_data["username"],
            "name": user_data["name"]
        }
    }
```

#### Token Verification
```python
def verify_auth_token(token: str) -> Optional[Dict]:
    """Verify authentication token"""
    if not token:
        return None
    
    token_hash = hash_token(token)
    token_data = get_session_token(token_hash)
    
    if not token_data:
        return None
    
    # Check expiration
    if is_token_expired(token_data):
        remove_session_token(token_hash)
        return None
    
    return token_data
```

### API Access Control

#### Protected Endpoints
```python
def require_auth(func):
    """Decorator for authentication-required endpoints"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        user_data = verify_auth_token(token)
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return await func(*args, **kwargs)
    return wrapper

@app.get("/api/trades")
@require_auth
async def get_trades():
    """Protected endpoint example"""
    return {"trades": get_user_trades()}
```

## Security Monitoring

### Access Logging
```python
import logging
from datetime import datetime

# Configure security logging
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.INFO)

def log_security_event(event_type: str, details: Dict):
    """Log security events"""
    security_logger.info(f"SECURITY_EVENT: {event_type} - {details}")

def log_login_attempt(username: str, success: bool, ip_address: str):
    """Log login attempts"""
    log_security_event("LOGIN_ATTEMPT", {
        "username": username,
        "success": success,
        "ip_address": ip_address,
        "timestamp": datetime.now().isoformat()
    })
```

### Security Alerts
```python
def check_security_thresholds():
    """Check for security violations"""
    alerts = []
    
    # Check for failed login attempts
    failed_logins = count_failed_logins(time_window="1h")
    if failed_logins > 5:
        alerts.append(f"High number of failed login attempts: {failed_logins}")
    
    # Check for suspicious API usage
    api_errors = count_api_errors(time_window="1h")
    if api_errors > 10:
        alerts.append(f"High number of API errors: {api_errors}")
    
    # Check file permissions
    if not check_credential_file_security():
        alerts.append("Insecure credential file permissions")
    
    return alerts
```

## Backup and Recovery

### Secure Backup Strategy
```bash
# Encrypted backup of sensitive data
gpg --encrypt --recipient your-email@example.com backup_$(date +%Y%m%d).tar.gz

# Secure backup storage
aws s3 cp backup_$(date +%Y%m%d).tar.gz.gpg s3://secure-backup-bucket/
```

### Disaster Recovery
```python
def restore_credentials_from_backup(backup_path: str):
    """Restore credentials from secure backup"""
    # Decrypt backup
    subprocess.run(["gpg", "--decrypt", backup_path])
    
    # Restore credential files
    subprocess.run(["tar", "-xzf", backup_path.replace(".gpg", "")])
    
    # Verify file permissions
    secure_file_permissions("backend/data/users/user_0001/credentials/")
```

## Security Compliance

### Data Protection
- **Encryption at Rest**: Sensitive data encrypted in storage
- **Encryption in Transit**: All external communications encrypted
- **Access Controls**: Role-based access control
- **Audit Logging**: Comprehensive audit trail

### Regulatory Compliance
- **GDPR Compliance**: User data protection
- **Financial Regulations**: Trading data security
- **API Security**: Secure external API communications
- **Data Retention**: Proper data retention policies

## Security Best Practices

### Development Security
- **No Secrets in Code**: All secrets externalized
- **Input Validation**: Comprehensive input validation
- **Error Handling**: Secure error handling
- **Code Review**: Security-focused code review

### Operational Security
- **Regular Updates**: Security patch management
- **Monitoring**: Continuous security monitoring
- **Incident Response**: Security incident procedures
- **Training**: Security awareness training

## Future Security Enhancements

### Planned Improvements
- **Multi-Factor Authentication**: SMS/email verification
- **Advanced Encryption**: Hardware security modules
- **Intrusion Detection**: Automated threat detection
- **Security Automation**: Automated security responses

### v3 Security Architecture
- **Zero Trust**: Zero trust security model
- **Microservices Security**: Service-to-service authentication
- **API Gateway**: Centralized API security
- **Container Security**: Secure container deployment

## Conclusion

The REC.IO v2 security framework provides comprehensive protection for sensitive trading data and user credentials while maintaining operational efficiency. The system implements industry-standard security practices and is designed for future security enhancements as part of the v3 development plan.
