#!/usr/bin/env python3
"""
REC.IO New User Installation Tool
Sets up a fresh REC.IO system for brand new users.
"""

import os
import sys
import json
import subprocess
import psycopg2
from datetime import datetime
from pathlib import Path
import argparse
import getpass

def get_project_root():
    """Get the project root directory."""
    current_dir = Path.cwd()
    while current_dir != current_dir.parent:
        if (current_dir / "backend" / "main.py").exists():
            return str(current_dir)
        current_dir = current_dir.parent
    raise FileNotFoundError("Could not find project root")

class NewUserInstallation:
    def __init__(self):
        self.project_root = Path(get_project_root())
        self.installation_dir = self.project_root / "backup" / "new_user_installations"
        self.installation_dir.mkdir(parents=True, exist_ok=True)
        
        # Database configuration
        self.db_config = {
            'host': 'localhost',
            'port': 5432,
            'user': 'rec_io_user',
            'password': 'rec_io_password'
        }
    
    def check_system_requirements(self):
        """Check if system meets requirements."""
        print("🔍 Checking system requirements...")
        
        # Check Python version
        if sys.version_info < (3, 8):
            print("❌ Python 3.8+ required")
            return False
        print(f"✅ Python {sys.version.split()[0]}")
        
        # Check PostgreSQL
        try:
            result = subprocess.run(['psql', '--version'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✅ PostgreSQL: {result.stdout.strip()}")
            else:
                print("❌ PostgreSQL not found")
                return False
        except FileNotFoundError:
            print("❌ PostgreSQL not installed")
            return False
        
        # Check required directories
        required_dirs = ['backend', 'frontend', 'scripts']
        for dir_name in required_dirs:
            if (self.project_root / dir_name).exists():
                print(f"✅ {dir_name}/ directory")
            else:
                print(f"❌ {dir_name}/ directory missing")
                return False
        
        print("✅ All system requirements met")
        return True
    
    def get_user_input(self):
        """Get user input for installation."""
        print("\n📝 User Configuration")
        print("-" * 40)
        
        # Basic user info
        user_name = input("Enter your name: ").strip()
        user_email = input("Enter your email: ").strip()
        
        # Database configuration
        print("\n🗄️  Database Configuration")
        db_host = input("Database host [localhost]: ").strip() or "localhost"
        db_port = input("Database port [5432]: ").strip() or "5432"
        db_user = input("Database user [rec_io_user]: ").strip() or "rec_io_user"
        db_password = getpass.getpass("Database password [rec_io_password]: ") or "rec_io_password"
        
        # Trading platform credentials (optional)
        print("\n📈 Trading Platform Credentials (Optional)")
        use_kalshi = input("Set up Kalshi credentials? (y/n): ").lower().strip()
        
        kalshi_credentials = {}
        if use_kalshi == 'y':
            kalshi_credentials['api_key'] = getpass.getpass("Kalshi API Key: ")
            kalshi_credentials['api_secret'] = getpass.getpass("Kalshi API Secret: ")
            kalshi_credentials['email'] = input("Kalshi Email: ").strip()
            kalshi_credentials['password'] = getpass.getpass("Kalshi Password: ")
        
        # System preferences
        print("\n⚙️  System Preferences")
        auto_start = input("Auto-start system on boot? (y/n): ").lower().strip() == 'y'
        demo_mode = input("Start in demo mode? (y/n): ").lower().strip() != 'n'
        
        return {
            'user_name': user_name,
            'user_email': user_email,
            'database': {
                'host': db_host,
                'port': int(db_port),
                'user': db_user,
                'password': db_password,
                'database': 'rec_io_db'
            },
            'kalshi_credentials': kalshi_credentials,
            'preferences': {
                'auto_start': auto_start,
                'demo_mode': demo_mode
            }
        }
    
    def install_system_dependencies(self):
        """Install system dependencies."""
        print("\n📦 Installing system dependencies...")
        
        # Detect OS
        if sys.platform == "darwin":  # macOS
            print("🍎 Detected macOS")
            
            # Install Homebrew if not present
            if not subprocess.run(['which', 'brew'], capture_output=True).returncode == 0:
                print("Installing Homebrew...")
                subprocess.run(['/bin/bash', '-c', 
                              '$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)'])
            
            # Install PostgreSQL
            print("Installing PostgreSQL...")
            subprocess.run(['brew', 'install', 'postgresql'])
            subprocess.run(['brew', 'services', 'start', 'postgresql'])
            
            # Install Python dependencies
            print("Installing Python dependencies...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
            
        elif sys.platform.startswith("linux"):  # Linux
            print("🐧 Detected Linux")
            
            # Update package list
            subprocess.run(['sudo', 'apt-get', 'update'])
            
            # Install PostgreSQL
            print("Installing PostgreSQL...")
            subprocess.run(['sudo', 'apt-get', 'install', '-y', 'postgresql', 'postgresql-contrib'])
            
            # Install Python dependencies
            print("Installing Python dependencies...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
            
        else:
            print("⚠️  Unsupported OS. Please install dependencies manually.")
            return False
        
        print("✅ System dependencies installed")
        return True
    
    def setup_database(self, db_config):
        """Set up the PostgreSQL database."""
        print("\n🗄️  Setting up database...")
        
        try:
            # Connect to PostgreSQL as superuser
            conn = psycopg2.connect(
                host=db_config['host'],
                port=db_config['port'],
                user='postgres',
                password='',  # No password for local postgres user
                database='postgres'
            )
            conn.autocommit = True
            cursor = conn.cursor()
            
            # Create database user
            print("Creating database user...")
            cursor.execute(f"CREATE USER {db_config['user']} WITH PASSWORD '{db_config['password']}';")
            
            # Create database
            print("Creating database...")
            cursor.execute(f"CREATE DATABASE {db_config['database']} OWNER {db_config['user']};")
            
            # Grant privileges
            cursor.execute(f"GRANT ALL PRIVILEGES ON DATABASE {db_config['database']} TO {db_config['user']};")
            
            cursor.close()
            conn.close()
            
            # Run database schema
            print("Setting up database schema...")
            schema_file = self.project_root / "scripts" / "create_user_0001_tables.sql"
            if schema_file.exists():
                cmd = [
                    'psql',
                    '-h', db_config['host'],
                    '-p', str(db_config['port']),
                    '-U', db_config['user'],
                    '-d', db_config['database'],
                    '--no-password',
                    '-f', str(schema_file)
                ]
                
                env = os.environ.copy()
                env['PGPASSWORD'] = db_config['password']
                
                result = subprocess.run(cmd, env=env, capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"⚠️  Schema setup warning: {result.stderr}")
                else:
                    print("✅ Database schema created")
            
            print("✅ Database setup completed")
            return True
            
        except Exception as e:
            print(f"❌ Database setup failed: {e}")
            return False
    
    def setup_user_data(self, user_config):
        """Set up initial user data in the database."""
        print("\n👤 Setting up user data...")
        
        try:
            conn = psycopg2.connect(**user_config['database'])
            cursor = conn.cursor()
            
            # Insert user information
            cursor.execute("""
                INSERT INTO users (user_id, name, email, created_at, updated_at)
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    updated_at = NOW()
            """, ('ewais', user_config['user_name'], user_config['user_email']))
            
            # Insert user preferences
            cursor.execute("""
                INSERT INTO user_preferences (user_id, demo_mode, auto_start, created_at, updated_at)
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    demo_mode = EXCLUDED.demo_mode,
                    auto_start = EXCLUDED.auto_start,
                    updated_at = NOW()
            """, ('ewais', user_config['preferences']['demo_mode'], user_config['preferences']['auto_start']))
            
            # Insert initial account balance
            cursor.execute("""
                INSERT INTO account_balances (user_id, platform, balance, currency, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (user_id, platform) DO UPDATE SET
                    balance = EXCLUDED.balance,
                    updated_at = NOW()
            """, ('ewais', 'kalshi', 10000.00, 'USD'))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            print("✅ User data setup completed")
            return True
            
        except Exception as e:
            print(f"❌ User data setup failed: {e}")
            return False
    
    def setup_credentials(self, user_config):
        """Set up trading platform credentials."""
        if not user_config['kalshi_credentials']:
            print("⏭️  Skipping credentials setup (none provided)")
            return True
        
        print("\n🔐 Setting up trading credentials...")
        
        try:
            # Create credentials directory
            creds_dir = self.project_root / "backend" / "data" / "users" / "ewais" / "credentials"
            creds_dir.mkdir(parents=True, exist_ok=True)
            
            # Save Kalshi credentials
            kalshi_creds_file = creds_dir / "kalshi-credentials.json"
            with open(kalshi_creds_file, 'w') as f:
                json.dump(user_config['kalshi_credentials'], f, indent=2)
            
            # Set proper permissions
            os.chmod(kalshi_creds_file, 0o600)
            
            print("✅ Credentials saved securely")
            return True
            
        except Exception as e:
            print(f"❌ Credentials setup failed: {e}")
            return False
    
    def setup_supervisor(self):
        """Set up supervisor for service management."""
        print("\n🔧 Setting up supervisor...")
        
        try:
            # Check if supervisor is installed
            if subprocess.run(['which', 'supervisorctl'], capture_output=True).returncode != 0:
                print("Installing supervisor...")
                if sys.platform == "darwin":
                    subprocess.run(['brew', 'install', 'supervisor'])
                else:
                    subprocess.run(['sudo', 'apt-get', 'install', '-y', 'supervisor'])
            
            # Copy supervisor configuration
            supervisor_conf = self.project_root / "backend" / "supervisord.conf"
            if supervisor_conf.exists():
                # Create supervisor directory
                supervisor_dir = Path("/etc/supervisor/conf.d")
                if not supervisor_dir.exists():
                    supervisor_dir = Path.home() / ".supervisor"
                    supervisor_dir.mkdir(exist_ok=True)
                
                # Copy configuration
                target_conf = supervisor_dir / "rec_io.conf"
                import shutil
                shutil.copy2(supervisor_conf, target_conf)
                
                print("✅ Supervisor configuration installed")
                return True
            else:
                print("⚠️  Supervisor configuration not found")
                return False
                
        except Exception as e:
            print(f"❌ Supervisor setup failed: {e}")
            return False
    
    def create_desktop_shortcut(self):
        """Create desktop shortcut for easy access."""
        print("\n🖥️  Creating desktop shortcut...")
        
        try:
            if sys.platform == "darwin":  # macOS
                # Create .command file
                shortcut_content = f"""#!/bin/bash
cd "{self.project_root}"
./scripts/MASTER_RESTART.sh
"""
                shortcut_file = Path.home() / "Desktop" / "REC.IO.command"
                with open(shortcut_file, 'w') as f:
                    f.write(shortcut_content)
                os.chmod(shortcut_file, 0o755)
                
                print("✅ Desktop shortcut created")
                return True
            else:
                print("⏭️  Desktop shortcut creation skipped (not macOS)")
                return True
                
        except Exception as e:
            print(f"⚠️  Desktop shortcut creation failed: {e}")
            return False
    
    def run_installation(self, check_only=False, non_interactive=False):
        """Run the complete installation process."""
        print("🚀 REC.IO New User Installation")
        print("=" * 50)
        
        # Check system requirements
        if not self.check_system_requirements():
            print("❌ System requirements not met")
            return False
        
        if check_only:
            print("✅ System requirements check passed")
            return True
        
        # Get user input
        if non_interactive:
            # Use default configuration
            user_config = {
                'user_name': 'New User',
                'user_email': 'user@example.com',
                'database': {
                    'host': 'localhost',
                    'port': 5432,
                    'user': 'rec_io_user',
                    'password': 'rec_io_password',
                    'database': 'rec_io_db'
                },
                'kalshi_credentials': {},
                'preferences': {
                    'auto_start': False,
                    'demo_mode': True
                }
            }
        else:
            user_config = self.get_user_input()
        
        # Install system dependencies
        if not self.install_system_dependencies():
            print("❌ Failed to install system dependencies")
            return False
        
        # Set up database
        if not self.setup_database(user_config['database']):
            print("❌ Failed to set up database")
            return False
        
        # Set up user data
        if not self.setup_user_data(user_config):
            print("❌ Failed to set up user data")
            return False
        
        # Set up credentials
        if not self.setup_credentials(user_config):
            print("❌ Failed to set up credentials")
            return False
        
        # Set up supervisor
        if not self.setup_supervisor():
            print("⚠️  Supervisor setup failed (you may need to install manually)")
        
        # Create desktop shortcut
        self.create_desktop_shortcut()
        
        print("\n🎉 Installation completed successfully!")
        print("\nNext steps:")
        print("1. Start the system: ./scripts/MASTER_RESTART.sh")
        print("2. Access the web interface: http://localhost:3000")
        print("3. Configure your trading preferences")
        
        return True

def main():
    parser = argparse.ArgumentParser(description="REC.IO New User Installation Tool")
    parser.add_argument('--check-requirements', action='store_true',
                       help='Only check system requirements')
    parser.add_argument('--non-interactive', action='store_true',
                       help='Run installation with default settings')
    
    args = parser.parse_args()
    
    installer = NewUserInstallation()
    
    success = installer.run_installation(
        check_only=args.check_requirements,
        non_interactive=args.non_interactive
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
