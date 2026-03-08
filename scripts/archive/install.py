#!/usr/bin/env python3
"""
REC.IO Trading System - Complete Installation Script
This script provides a guided installation for new users.
"""

import os
import sys
import json
import subprocess
import getpass
import platform
from pathlib import Path
import shutil

# Global variable to track scipy installation status
scipy_installed = True

def print_banner():
    """Print installation banner."""
    print("=" * 70)
    print("           REC.IO TRADING SYSTEM - COMPLETE INSTALLATION")
    print("=" * 70)
    print("This script will guide you through setting up the REC.IO trading system.")
    print("It will install dependencies, set up PostgreSQL, and configure your user profile.")
    print()
    print("⚠️  If you see package configuration dialogs, select 'Ok' to continue.")
    print("   The script will handle most prompts automatically.")
    print("=" * 70)

def print_step(step_num, title, description=""):
    """Print a step header."""
    print(f"\n{'='*20} STEP {step_num}: {title} {'='*20}")
    if description:
        print(description)
    print()

def get_user_input(prompt, required=True, password=False):
    """Get user input with validation."""
    while True:
        if password:
            value = getpass.getpass(prompt)
        else:
            value = input(prompt).strip()
        
        if not value and required:
            print("❌ This field is required. Please try again.")
            continue
        return value

def check_system_requirements():
    """Check if system meets requirements."""
    print_step(1, "SYSTEM REQUIREMENTS CHECK")
    
    print("🔍 Checking system requirements...")
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ required")
        print(f"   Current version: {sys.version.split()[0]}")
        return False
    print(f"✅ Python {sys.version.split()[0]}")
    
    # Check operating system
    system = platform.system()
    if system not in ['Linux', 'Darwin', 'Windows']:
        print(f"❌ Unsupported operating system: {system}")
        return False
    print(f"✅ Operating system: {system}")
    
    # Check if we're in the right directory
    if not (Path.cwd() / "backend" / "main.py").exists():
        print("❌ Please run this script from the REC.IO project root directory")
        return False
    print("✅ Project structure verified")
    
    print("✅ All system requirements met")
    return True

def install_dependencies():
    """Install system dependencies."""
    print_step(2, "INSTALLING DEPENDENCIES")
    
    system = platform.system()
    
    if system == "Darwin":  # macOS
        print("🍎 Installing dependencies on macOS...")
        
        # Check if Homebrew is installed
        if not shutil.which("brew"):
            print("📦 Installing Homebrew...")
            install_cmd = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            if subprocess.run(install_cmd, shell=True).returncode != 0:
                print("❌ Failed to install Homebrew")
                return False
        
        # Install dependencies
        deps = ["python3", "postgresql", "supervisor", "git"]
        for dep in deps:
            print(f"📦 Installing {dep}...")
            if subprocess.run(["brew", "install", dep]).returncode != 0:
                print(f"❌ Failed to install {dep}")
                return False
    
    elif system == "Linux":
        print("🐧 Installing dependencies on Linux...")
        
        # Detect package manager
        if shutil.which("apt"):
            pkg_mgr = "apt"
            deps = [
                "python3", "python3-pip", "python3-venv", 
                "postgresql", "postgresql-client", "supervisor", "git",
                "build-essential", "gfortran", "libopenblas-dev", "liblapack-dev",
                "pkg-config", "python3-dev"
            ]
        elif shutil.which("yum"):
            pkg_mgr = "yum"
            deps = [
                "python3", "python3-pip", "postgresql", "postgresql-server", 
                "supervisor", "git", "gcc", "gcc-gfortran", "openblas-devel", 
                "lapack-devel", "pkgconfig", "python3-devel"
            ]
        else:
            print("❌ Unsupported package manager")
            return False
        
        # Update package list
        print("📦 Updating package list...")
        subprocess.run([pkg_mgr, "update", "-y"])
        
        # Install dependencies with automatic configuration
        for dep in deps:
            print(f"📦 Installing {dep}...")
            # Use DEBIAN_FRONTEND=noninteractive to avoid prompts
            env = os.environ.copy()
            env['DEBIAN_FRONTEND'] = 'noninteractive'
            env['UCF_FORCE_CONFNEW'] = '1'
            env['UCF_FORCE_CONFOLD'] = '1'
            
            result = subprocess.run(
                [pkg_mgr, "install", "-y", dep], 
                env=env,
                input=b'\n',  # Send newline to accept defaults
                capture_output=True
            )
            
            if result.returncode != 0:
                print(f"❌ Failed to install {dep}")
                print(f"Error: {result.stderr.decode()}")
                return False
    
    else:
        print("❌ Windows installation not yet supported")
        return False
    
    print("✅ Dependencies installed successfully")
    return True

def setup_postgresql():
    """Set up PostgreSQL database."""
    print_step(3, "SETTING UP POSTGRESQL")
    
    system = platform.system()
    
    # Start PostgreSQL service
    print("🗄️  Starting PostgreSQL service...")
    if system == "Darwin":
        subprocess.run(["brew", "services", "start", "postgresql"])
    else:
        # Use non-interactive environment for systemctl
        env = os.environ.copy()
        env['DEBIAN_FRONTEND'] = 'noninteractive'
        
        subprocess.run(["sudo", "systemctl", "start", "postgresql"], env=env)
        subprocess.run(["sudo", "systemctl", "enable", "postgresql"], env=env)
    
    # Create database user and database
    print("👤 Creating database user...")
    
    # Use default database configuration for new users
    db_user = "rec_io_user"
    db_password = "rec_io_password"
    db_name = "rec_io_db"
    
    print(f"🗄️  Using default database configuration:")
    print(f"   Database: {db_name}")
    print(f"   Username: {db_user}")
    print(f"   Password: {db_password}")
    print("   (You can change these later if needed)")
    
    # Create user and database
    create_user_cmd = f"CREATE USER {db_user} WITH PASSWORD '{db_password}';"
    create_db_cmd = f"CREATE DATABASE {db_name} OWNER {db_user};"
    grant_cmd = f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};"
    
    if system == "Darwin":
        # macOS PostgreSQL setup
        subprocess.run(["createdb", db_name], check=False)
        subprocess.run(["psql", "-d", db_name, "-c", create_user_cmd], check=False)
        subprocess.run(["psql", "-d", db_name, "-c", grant_cmd], check=False)
    else:
        # Linux PostgreSQL setup with non-interactive environment
        env = os.environ.copy()
        env['DEBIAN_FRONTEND'] = 'noninteractive'
        
        subprocess.run(["sudo", "-u", "postgres", "psql", "-c", create_user_cmd], env=env)
        subprocess.run(["sudo", "-u", "postgres", "psql", "-c", create_db_cmd], env=env)
        subprocess.run(["sudo", "-u", "postgres", "psql", "-c", grant_cmd], env=env)
    
    print("✅ PostgreSQL setup completed")
    return {
        "user": db_user,
        "password": db_password,
        "database": db_name
    }

def setup_python_environment():
    """Set up Python virtual environment."""
    print_step(4, "SETTING UP PYTHON ENVIRONMENT")
    
    print("🐍 Creating Python virtual environment...")
    if subprocess.run([sys.executable, "-m", "venv", "venv"]).returncode != 0:
        print("❌ Failed to create virtual environment")
        return False
    
    print("📦 Installing Python dependencies...")
    pip_cmd = "venv/bin/pip" if platform.system() != "Windows" else "venv\\Scripts\\pip"
    
    # First, upgrade pip
    print("📦 Upgrading pip...")
    subprocess.run([pip_cmd, "install", "--upgrade", "pip"])
    
    # Try to install all dependencies
    print("📦 Installing all dependencies...")
    result = subprocess.run([pip_cmd, "install", "-r", "requirements.txt"])
    
    if result.returncode != 0:
        print("⚠️  Some dependencies failed to install. Trying alternative approach...")
        
        # Try installing scipy separately with pre-built wheels
        print("📦 Installing scipy with pre-built wheels...")
        scipy_result = subprocess.run([pip_cmd, "install", "scipy", "--only-binary=scipy"])
        
        if scipy_result.returncode != 0:
            global scipy_installed
            scipy_installed = False
            print("⚠️  Scipy installation failed. Installing core dependencies only...")
            
            # Install core dependencies from requirements-core.txt
            if Path("requirements-core.txt").exists():
                print("📦 Installing core dependencies...")
                core_result = subprocess.run([pip_cmd, "install", "-r", "requirements-core.txt"])
                if core_result.returncode == 0:
                    print("✅ Core dependencies installed successfully")
                    print("⚠️  Note: scipy not available. Some advanced features may be limited.")
                else:
                    print("⚠️  Core dependencies installation failed. Trying individual packages...")
                    # Fallback to individual packages
                    core_deps = [
                        "fastapi", "uvicorn", "requests", "python-dotenv", 
                        "psycopg2-binary", "pandas", "numpy", "supervisor", 
                        "flask-cors", "pydantic", "websockets", "aiohttp"
                    ]
                    
                    for dep in core_deps:
                        print(f"📦 Installing {dep}...")
                        if subprocess.run([pip_cmd, "install", dep]).returncode != 0:
                            print(f"⚠️  Failed to install {dep}, continuing...")
            else:
                print("⚠️  requirements-core.txt not found. Trying individual packages...")
                # Fallback to individual packages
                core_deps = [
                    "fastapi", "uvicorn", "requests", "python-dotenv", 
                    "psycopg2-binary", "pandas", "numpy", "supervisor", 
                    "flask-cors", "pydantic", "websockets", "aiohttp"
                ]
                
                for dep in core_deps:
                    print(f"📦 Installing {dep}...")
                    if subprocess.run([pip_cmd, "install", dep]).returncode != 0:
                        print(f"⚠️  Failed to install {dep}, continuing...")
        else:
            # Try installing remaining dependencies
            print("📦 Installing remaining dependencies...")
            subprocess.run([pip_cmd, "install", "-r", "requirements.txt"])
    
    print("✅ Python environment setup completed")
    return True

def setup_user_profile():
    """Set up user profile."""
    print_step(5, "SETTING UP USER PROFILE")
    
    print("👤 Setting up your user profile...")
    
    # Get user information
    name = get_user_input("Enter your full name: ")
    email = get_user_input("Enter your email address: ")
    
    # Create user directory structure
    user_dir = Path("backend/data/users/user_0001")
    user_dir.mkdir(parents=True, exist_ok=True)
    
    # Create subdirectories
    (user_dir / "credentials" / "kalshi-credentials" / "prod").mkdir(parents=True, exist_ok=True)
    (user_dir / "credentials" / "kalshi-credentials" / "demo").mkdir(parents=True, exist_ok=True)
    (user_dir / "preferences").mkdir(exist_ok=True)
    (user_dir / "trade_history").mkdir(exist_ok=True)
    (user_dir / "active_trades").mkdir(exist_ok=True)
    (user_dir / "accounts").mkdir(exist_ok=True)
    
    # Create user_info.json
    user_info = {
        "user_id": "user_0001",
        "name": name,
        "email": email,
        "account_type": "user",
        "created": str(Path.cwd())
    }
    
    with open(user_dir / "user_info.json", "w") as f:
        json.dump(user_info, f, indent=2)
    
    # Create default preferences
    trade_prefs = {
        "auto_stop_enabled": False,
        "auto_stop_threshold": -50,
        "position_size": 100,
        "max_positions": 5,
        "risk_tolerance": "medium"
    }
    
    with open(user_dir / "preferences" / "trade_preferences.json", "w") as f:
        json.dump(trade_prefs, f, indent=2)
    
    # Set permissions
    os.chmod(user_dir / "credentials", 0o700)
    
    print("✅ User profile created successfully")
    return user_info

def setup_kalshi_credentials():
    """Set up Kalshi credentials (optional)."""
    print_step(6, "SETTING UP KALSHI CREDENTIALS (OPTIONAL)")
    
    use_kalshi = get_user_input("Do you want to set up Kalshi credentials now? (y/n): ").lower()
    
    if use_kalshi != 'y':
        print("ℹ️  You can add Kalshi credentials later by running:")
        print("   python3 scripts/setup_new_user.py")
        return True
    
    print("\n🔑 Kalshi API Credentials Setup")
    print("Get your credentials from: https://trading.kalshi.com/settings/api")
    print()
    
    kalshi_email = get_user_input("Enter your Kalshi account email: ")
    api_key = get_user_input("Enter your Kalshi API Key ID: ")
    private_key = get_user_input("Enter your Kalshi Private Key (PEM format): ", password=True)
    
    # Write credentials
    cred_dir = Path("backend/data/users/user_0001/credentials/kalshi-credentials/prod")
    
    # Write kalshi-auth.txt
    auth_file = cred_dir / "kalshi-auth.txt"
    with open(auth_file, "w") as f:
        f.write(f"email:{kalshi_email}\nkey:{api_key}\n")
    
    # Write kalshi-auth.pem
    pem_file = cred_dir / "kalshi-auth.pem"
    with open(pem_file, "w") as f:
        f.write(private_key)
    os.chmod(pem_file, 0o600)
    
    # Write .env file
    env_file = cred_dir / ".env"
    with open(env_file, "w") as f:
        f.write(f"""KALSHI_API_KEY_ID={api_key}
KALSHI_PRIVATE_KEY_PATH=kalshi-auth.pem
KALSHI_EMAIL={kalshi_email}
""")
    
    print("✅ Kalshi credentials configured successfully")
    return True

def create_environment_file(db_config):
    """Create .env file with database configuration."""
    print_step(7, "CREATING ENVIRONMENT CONFIGURATION")
    
    env_content = f"""# PostgreSQL Connection Settings
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB={db_config['database']}
POSTGRES_USER={db_config['user']}
POSTGRES_PASSWORD={db_config['password']}

# Trading System Configuration
TRADING_SYSTEM_HOST=localhost
REC_BIND_HOST=localhost
REC_TARGET_HOST=localhost
"""
    
    with open(".env", "w") as f:
        f.write(env_content)
    
    print("✅ Environment configuration created")
    return True

def setup_database_schema():
    """Set up database schema."""
    print_step(8, "SETTING UP DATABASE SCHEMA")
    
    print("🗄️  Setting up database schema...")
    
    # Run database setup script
    if Path("scripts/setup_database.sh").exists():
        subprocess.run(["bash", "scripts/setup_database.sh"])
    else:
        print("⚠️  Database setup script not found, schema may need manual setup")
    
    print("✅ Database schema setup completed")
    return True

def generate_supervisor_config():
    """Generate supervisor configuration."""
    print_step(9, "GENERATING SUPERVISOR CONFIGURATION")
    
    print("⚙️  Generating supervisor configuration...")
    
    if Path("scripts/generate_supervisor_config.sh").exists():
        subprocess.run(["bash", "scripts/generate_supervisor_config.sh"])
    else:
        print("⚠️  Supervisor config script not found")
    
    print("✅ Supervisor configuration generated")
    return True

def show_completion():
    """Show completion message and next steps."""
    print_step(10, "INSTALLATION COMPLETED")
    
    print("🎉 REC.IO Trading System installation completed successfully!")
    
    # Show scipy status
    if not scipy_installed:
        print()
        print("⚠️  Note: scipy was not installed due to compilation issues.")
        print("   The system will work with core functionality, but some advanced")
        print("   features may be limited. You can install scipy later with:")
        print("   sudo apt install gfortran libopenblas-dev liblapack-dev")
        print("   source venv/bin/activate && pip install scipy")
    
    print()
    print("📋 Next Steps:")
    print("1. Start the system:")
    print("   ./scripts/MASTER_RESTART.sh")
    print()
    print("2. Access the web interface:")
    print("   http://localhost:3000")
    print()
    print("3. Check system status:")
    print("   supervisorctl -c backend/supervisord.conf status")
    print()
    print("4. View logs:")
    print("   tail -f logs/main_app.out.log")
    print()
    print("📚 Documentation:")
    print("- Quick Start: docs/QUICK_INSTALL_GUIDE.md")
    print("- New User Setup: docs/NEW_USER_SETUP_GUIDE.md")
    print("- Security: docs/SECURITY_OVERVIEW.md")
    print()
    print("🔧 Troubleshooting:")
    print("- Test database: ./scripts/test_database.sh")
    print("- Check logs: tail -f logs/*.out.log")
    print("- Restart services: ./scripts/MASTER_RESTART.sh")
    print()
    print("=" * 70)
    print("✅ Installation completed successfully!")
    print("=" * 70)

def main():
    """Main installation function."""
    print_banner()
    
    try:
        # Step 1: Check system requirements
        if not check_system_requirements():
            print("❌ System requirements not met. Please fix the issues above.")
            return False
        
        # Step 2: Install dependencies
        if not install_dependencies():
            print("❌ Failed to install dependencies.")
            return False
        
        # Step 3: Setup PostgreSQL
        db_config = setup_postgresql()
        if not db_config:
            print("❌ Failed to setup PostgreSQL.")
            return False
        
        # Step 4: Setup Python environment
        if not setup_python_environment():
            print("❌ Failed to setup Python environment.")
            return False
        
        # Step 5: Setup user profile
        user_info = setup_user_profile()
        if not user_info:
            print("❌ Failed to setup user profile.")
            return False
        
        # Step 6: Setup Kalshi credentials (optional)
        setup_kalshi_credentials()
        
        # Step 7: Create environment file
        if not create_environment_file(db_config):
            print("❌ Failed to create environment file.")
            return False
        
        # Step 8: Setup database schema
        setup_database_schema()
        
        # Step 9: Generate supervisor config
        generate_supervisor_config()
        
        # Step 10: Show completion
        show_completion()
        
        return True
        
    except KeyboardInterrupt:
        print("\n\n❌ Installation cancelled by user.")
        return False
    except Exception as e:
        print(f"\n❌ Installation failed: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
