# SYSTEM-WIDE CODING RULES

## 🚨 CRITICAL: PORT MANAGEMENT - NEVER VIOLATE
**NEVER use hardcoded "localhost" in URLs**
**ALWAYS use the universal port configuration system**

### CORRECT PATTERN:
```python
from backend.util.paths import get_host
from backend.core.port_config import get_port

# ✅ CORRECT - Use universal port config
url = f"http://{get_host()}:{get_port('service_name')}/api/endpoint"
```

### ❌ WRONG PATTERNS:
```python
# ❌ NEVER DO THIS
url = f"http://localhost:{port}/api/endpoint"
url = "http://localhost:3000/api/endpoint"
url = f"http://127.0.0.1:{port}/api/endpoint"
```

## NETWORKING PATTERNS

### Service Communication:
- Services communicate via: `http://{get_host()}:{get_port('service_name')}/api/endpoint`
- Never hardcode IP addresses or hostnames
- Always use the universal port configuration system

### API Endpoints:
- Main app proxy endpoints: Use `get_host()` and `get_port()` for all service calls
- Frontend notifications: Use `get_host()` for all backend notifications
- Database change notifications: Use `get_host()` for all notifications

## ARCHITECTURAL RULES

### Port Configuration:
- All ports are defined in `backend/core/config/MASTER_PORT_MANIFEST.json`
- Use `backend.core.port_config.get_port(service_name)` to get ports
- Use `backend.util.paths.get_host()` to get the correct host

### Service Discovery:
- Services register their ports in the manifest
- Services use `get_host()` to bind to the correct interface
- All inter-service communication uses the universal system

## MANDATORY CHECKLIST BEFORE ANY CODE MODIFICATION

Before making ANY code changes, verify:

1. ✅ **No hardcoded localhost URLs**
2. ✅ **Using `get_host()` for all host references**
3. ✅ **Using `get_port()` for all port references**
4. ✅ **Following the universal port configuration system**
5. ✅ **All service communication uses the correct pattern**

## COMMON VIOLATIONS TO AVOID

### ❌ Common Mistakes:
- `http://localhost:3000` → Should be `http://{get_host()}:{get_port('main_app')}`
- `http://127.0.0.1:8001` → Should be `http://{get_host()}:{get_port('trade_executor')}`
- Hardcoded port numbers → Always use `get_port('service_name')`
- Direct IP addresses → Always use `get_host()`

### ✅ Correct Examples:
```python
# Service-to-service communication
trade_initiator_url = f"http://{get_host()}:{get_port('trade_initiator')}/api/initiate_trade"

# Frontend notifications
notification_url = f"http://{get_host()}:{get_port('main_app')}/api/notify_db_change"

# API calls
btc_response = requests.get(f"http://{get_host()}:{get_port('main_app')}/api/btc_price", timeout=5)
```

## ENFORCEMENT

This document MUST be read and followed before ANY code modification. The universal port configuration system is critical to the project's architecture and must never be violated.

## REMEMBER

- The project uses a universal port configuration system
- All services must use `get_host()` and `get_port()`
- Never hardcode localhost, IP addresses, or port numbers
- This is a critical architectural requirement that cannot be violated 