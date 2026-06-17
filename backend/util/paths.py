import os
import platform
import re
from pathlib import Path

_USER_NO_ENV_RE = re.compile(r"^\d{4}$")


def _tenant_user_no_for_paths() -> str:
    """Prefer REC_USER_NO (supervisor); single-user installs default to 0001."""
    u = os.environ.get("REC_USER_NO", "").strip()
    if _USER_NO_ENV_RE.match(u):
        return u
    return "0001"


def get_project_root():
    """Get the absolute path to the project root directory."""
    # This file is at backend/util/paths.py, so go up 2 levels to reach project root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_data_dir():
    """Get the unified data directory path."""
    return os.path.join(get_project_root(), "backend", "data")

def get_kalshi_data_dir():
    """Get the Kalshi data directory path."""
    return os.path.join(get_data_dir(), "live_data", "markets", "kalshi")

def get_coinbase_data_dir():
    """Get the Coinbase data directory path."""
    return os.path.join(get_data_dir(), "coinbase")

def get_accounts_data_dir():
    """Get the accounts data directory path."""
    u = _tenant_user_no_for_paths()
    return os.path.join(get_data_dir(), "users", f"user_{u}", "accounts")

def get_price_history_dir():
    """Get the price history directory path."""
    return os.path.join(get_data_dir(), "live_data", "price_history")

def get_btc_price_history_dir():
    """Get the BTC price history directory path."""
    return os.path.join(get_price_history_dir(), "btc")

def get_trade_history_dir():
    """Get the trade history directory path."""
    u = _tenant_user_no_for_paths()
    return os.path.join(get_data_dir(), "users", f"user_{u}", "trade_history")

def get_active_trades_dir():
    """Get the active trades directory path."""
    u = _tenant_user_no_for_paths()
    return os.path.join(get_data_dir(), "users", f"user_{u}", "active_trades")

def get_logs_dir():
    """Get the logs directory path."""
    return os.path.join(get_project_root(), "logs")

def get_kalshi_credentials_dir(user_no: str | None = None):
    """Get the Kalshi credentials directory path (…/kalshi-credentials; keys under prod/)."""
    if user_no is not None:
        u = str(user_no).strip()
        if not _USER_NO_ENV_RE.match(u):
            raise ValueError(f"Invalid user_no for Kalshi credentials path: {user_no!r}")
    else:
        u = _tenant_user_no_for_paths()
    return os.path.join(
        get_data_dir(), "users", f"user_{u}", "credentials", "kalshi-credentials"
    )


def get_quickbooks_credentials_dir(user_no: str | None = None):
    """Per-tenant QuickBooks Online OAuth and realm credentials (bookkeeper integration)."""
    if user_no is not None:
        u = str(user_no).strip()
        if not _USER_NO_ENV_RE.match(u):
            raise ValueError(f"Invalid user_no for QuickBooks credentials path: {user_no!r}")
    else:
        u = _tenant_user_no_for_paths()
    return os.path.join(
        get_data_dir(), "users", f"user_{u}", "credentials", "quickbooks"
    )


def get_mercury_credentials_dir():
    """Per-tenant Mercury Bank API credentials (bookkeeper integration)."""
    u = _tenant_user_no_for_paths()
    return os.path.join(
        get_data_dir(), "users", f"user_{u}", "credentials", "mercury"
    )

def get_supervisor_config_path():
    """Get the supervisor configuration file path."""
    return os.path.join(get_project_root(), "backend", "supervisord.conf")

def get_frontend_dir():
    """Get the frontend directory path."""
    return os.path.join(get_project_root(), "frontend")

def get_venv_python_path():
    """Get the virtual environment Python executable path."""
    return os.path.join(get_project_root(), "venv", "bin", "python")

def get_host():
    """Get the host configuration for the current environment."""
    # Check for environment variable first
    env_host = os.getenv("TRADING_SYSTEM_HOST")
    if env_host:
        return env_host
    
    # Try to detect the actual IP address for network access
    try:
        import socket
        # Get the local IP address that other devices can reach
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        # Fallback to localhost if detection fails
        return "localhost"

def get_service_url(port: int) -> str:
    """Get a service URL with the configured host."""
    host = get_host()
    return f"http://{host}:{port}"

def ensure_data_dirs():
    """Ensure all data directories exist."""
    dirs = [
        get_data_dir(),
        get_kalshi_data_dir(),
        get_price_history_dir(),
        get_btc_price_history_dir(),
        get_logs_dir(),
        # User credentials directories (only these are still needed)
        os.path.join(
            get_data_dir(),
            "users",
            f"user_{_tenant_user_no_for_paths()}",
            "credentials",
            "kalshi-credentials",
            "prod",
        ),
        os.path.join(get_data_dir(), "users", "user_0001", "credentials", "kalshi-credentials", "demo"),
        os.path.join(
            get_data_dir(),
            "users",
            f"user_{_tenant_user_no_for_paths()}",
            "credentials",
            "quickbooks",
        ),
        os.path.join(
            get_data_dir(),
            "users",
            f"user_{_tenant_user_no_for_paths()}",
            "credentials",
            "mercury",
        ),
    ]
    for dir_path in dirs:
        os.makedirs(dir_path, exist_ok=True)

# NEW FUNCTIONS FOR DEPLOYMENT COMPATIBILITY

def get_supervisorctl_path():
    """
    Get supervisorctl path for current system.
    Prefer project venv (matches requirements.txt supervisor pin); then OS packages.
    """
    for venv_name in ("venv", ".venv"):
        venv_ctl = os.path.join(get_project_root(), venv_name, "bin", "supervisorctl")
        if os.path.isfile(venv_ctl) and os.access(venv_ctl, os.X_OK):
            return venv_ctl

    possible_paths = [
        "/usr/bin/supervisorctl",           # Ubuntu/Debian (prod)
        "/opt/homebrew/bin/supervisorctl",  # macOS Homebrew
        "/usr/local/bin/supervisorctl",
        "supervisorctl",
    ]

    for path in possible_paths:
        if path == "supervisorctl" or os.path.isfile(path):
            return path

    return "supervisorctl"


def get_supervisord_path():
    """Same resolution order as get_supervisorctl_path()."""
    for venv_name in ("venv", ".venv"):
        venv_sup = os.path.join(get_project_root(), venv_name, "bin", "supervisord")
        if os.path.isfile(venv_sup) and os.access(venv_sup, os.X_OK):
            return venv_sup

    possible_paths = [
        "/usr/bin/supervisord",
        "/opt/homebrew/bin/supervisord",
        "/usr/local/bin/supervisord",
        "supervisord",
    ]

    for path in possible_paths:
        if path == "supervisord" or os.path.isfile(path):
            return path

    return "supervisord"


def get_system_type():
    """
    Detect the current system type for path adaptations.
    """
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    elif system == "linux":
        return "ubuntu"
    else:
        return "unknown"


def get_dynamic_project_root():
    """
    Get the project root directory dynamically.
    Works on both macOS and Ubuntu environments.
    """
    # Method 1: Check if we're already in the project root
    current_dir = os.getcwd()
    if os.path.exists(os.path.join(current_dir, 'backend', 'main.py')):
        return current_dir
    
    # Method 2: Check if we're in a subdirectory of the project
    current_path = Path(current_dir)
    for parent in current_path.parents:
        if os.path.exists(os.path.join(parent, 'backend', 'main.py')):
            return str(parent)
    
    # Method 3: Check if we're running from within the backend directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    if os.path.exists(os.path.join(project_root, 'backend', 'main.py')):
        return project_root
    
    # Method 4: Fallback - try to find the project by looking for key files
    for root, dirs, files in os.walk(os.path.expanduser('~')):
        if 'backend' in dirs and 'main.py' in os.listdir(os.path.join(root, 'backend')):
            return root
    
    # Method 5: Fallback to original method
    return get_project_root()


def get_environment_paths():
    """
    Get environment-specific paths and configurations.
    """
    system_type = get_system_type()
    project_root = get_dynamic_project_root()
    
    paths = {
        'project_root': project_root,
        'backend_dir': os.path.join(project_root, 'backend'),
        'frontend_dir': os.path.join(project_root, 'frontend'),
        'logs_dir': os.path.join(project_root, 'logs'),
        'data_dir': os.path.join(project_root, 'backend', 'data'),
        'supervisor_config': get_supervisor_config_path(),
        'supervisorctl_path': get_supervisorctl_path(),
        'system_type': system_type
    }
    
    return paths 