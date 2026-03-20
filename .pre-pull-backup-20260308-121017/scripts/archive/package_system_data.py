#!/usr/bin/env python3
"""
System Data Packaging Script

This script packages all non-user system data from the rec_io_db PostgreSQL database
into a single compressed file for portability to other machines.

System data includes:
- Analytics tables (probability lookup tables, fingerprint tables)
- Historical data (price history)
- Live data (price logs, strike tables)
- Work progress tables
- System tables

Excludes:
- Users schema (user-specific data)
- Public schema user tables (fills, positions, trades, active_trades)
"""

import os
import sys
import json
import gzip
import tarfile
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

# Add the backend directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from core.config.config_manager import ConfigManager

def get_database_connection():
    """Get database connection using the config manager."""
    config = ConfigManager()
    db_config = config.get_database_config()
    
    import psycopg2
    return psycopg2.connect(
        host=db_config['host'],
        port=db_config['port'],
        database=db_config['name'],
        user=db_config['user'],
        password=db_config['password']
    )

def get_system_schemas():
    """Return list of schemas that contain system data (non-user data)."""
    return [
        'analytics',
        'historical_data', 
        'live_data',
        'system',
        'work_progress'
    ]

def get_system_tables():
    """Return list of system tables in public schema."""
    return [
        'fills',
        'positions', 
        'trades',
        'active_trades'
    ]

def export_schema_data(conn, schema_name, output_dir):
    """Export all tables from a schema to SQL files."""
    cursor = conn.cursor()
    
    # Get database config for pg_dump
    config = ConfigManager()
    db_config = config.get_database_config()
    
    # Get all tables in the schema
    cursor.execute("""
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = %s 
        ORDER BY tablename
    """, (schema_name,))
    
    tables = [row[0] for row in cursor.fetchall()]
    
    if not tables:
        print(f"  No tables found in schema '{schema_name}'")
        return
    
    schema_dir = os.path.join(output_dir, schema_name)
    os.makedirs(schema_dir, exist_ok=True)
    
    print(f"  Exporting {len(tables)} tables from schema '{schema_name}':")
    
    for table in tables:
        table_file = os.path.join(schema_dir, f"{table}.sql")
        
        # Export table structure and data
        cmd = f"pg_dump -h {db_config['host']} -U {db_config['user']} -d {db_config['name']} --schema={schema_name} --table={schema_name}.{table} --data-only --no-owner --no-privileges --column-inserts > {table_file}"
        
        # Set environment variables for pg_dump
        env = os.environ.copy()
        env['PGPASSWORD'] = db_config['password']
        
        print(f"    - {table}")
        os.system(cmd)
        
        # Check if file was created and has content
        if os.path.exists(table_file) and os.path.getsize(table_file) > 0:
            print(f"      ✓ Exported {os.path.getsize(table_file)} bytes")
        else:
            print(f"      ⚠ Empty or failed export")
            if os.path.exists(table_file):
                os.remove(table_file)

def export_public_system_tables(conn, output_dir):
    """Export system tables from public schema."""
    cursor = conn.cursor()
    
    # Get database config for pg_dump
    config = ConfigManager()
    db_config = config.get_database_config()
    
    public_dir = os.path.join(output_dir, 'public')
    os.makedirs(public_dir, exist_ok=True)
    
    print(f"  Exporting system tables from public schema:")
    
    for table in get_system_tables():
        table_file = os.path.join(public_dir, f"{table}.sql")
        
        # Export table structure and data
        cmd = f"pg_dump -h {db_config['host']} -U {db_config['user']} -d {db_config['name']} --table=public.{table} --data-only --no-owner --no-privileges --column-inserts > {table_file}"
        
        # Set environment variables for pg_dump
        env = os.environ.copy()
        env['PGPASSWORD'] = db_config['password']
        
        print(f"    - {table}")
        os.system(cmd)
        
        # Check if file was created and has content
        if os.path.exists(table_file) and os.path.getsize(table_file) > 0:
            print(f"      ✓ Exported {os.path.getsize(table_file)} bytes")
        else:
            print(f"      ⚠ Empty or failed export")
            if os.path.exists(table_file):
                os.remove(table_file)

def create_metadata_file(output_dir):
    """Create metadata file with export information."""
    metadata = {
        'export_timestamp': datetime.now().isoformat(),
        'system_data_version': '1.0',
        'description': 'System-critical data export for rec_io trading platform',
        'schemas_exported': get_system_schemas(),
        'public_tables_exported': get_system_tables(),
        'excluded_data': {
            'schemas': ['users'],
            'description': 'User-specific data excluded for portability'
        },
        'import_instructions': [
            '1. Ensure PostgreSQL is running on target machine',
            '2. Create rec_io_db database if it does not exist',
            '3. Run the unpack_system_data.py script',
            '4. Verify data import by checking table counts'
        ]
    }
    
    metadata_file = os.path.join(output_dir, 'metadata.json')
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"  ✓ Created metadata file: {metadata_file}")

def main():
    """Main packaging function."""
    print("🚀 System Data Packaging Script")
    print("=" * 50)
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"system_data_export_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"📁 Output directory: {output_dir}")
    
    try:
        # Connect to database
        print("\n🔌 Connecting to database...")
        conn = get_database_connection()
        print("  ✓ Database connection established")
        
        # Export system schemas
        print(f"\n📊 Exporting system schemas...")
        for schema in get_system_schemas():
            print(f"\n📦 Schema: {schema}")
            export_schema_data(conn, schema, output_dir)
        
        # Export public schema system tables
        print(f"\n📊 Exporting public schema system tables...")
        export_public_system_tables(conn, output_dir)
        
        # Create metadata file
        print(f"\n📋 Creating metadata...")
        create_metadata_file(output_dir)
        
        # Create compressed archive
        print(f"\n🗜️ Creating compressed archive...")
        archive_name = f"{output_dir}.tar.gz"
        
        with tarfile.open(archive_name, "w:gz") as tar:
            tar.add(output_dir, arcname=os.path.basename(output_dir))
        
        # Calculate archive size
        archive_size = os.path.getsize(archive_name)
        archive_size_mb = archive_size / (1024 * 1024)
        
        print(f"  ✓ Created archive: {archive_name}")
        print(f"  📏 Archive size: {archive_size_mb:.2f} MB")
        
        # Clean up temporary directory
        print(f"\n🧹 Cleaning up...")
        shutil.rmtree(output_dir)
        print(f"  ✓ Removed temporary directory")
        
        print(f"\n✅ System data packaging completed successfully!")
        print(f"📦 Archive: {archive_name}")
        print(f"📏 Size: {archive_size_mb:.2f} MB")
        print(f"\n📋 Next steps:")
        print(f"   1. Copy {archive_name} to target machine")
        print(f"   2. Run unpack_system_data.py on target machine")
        
    except Exception as e:
        print(f"\n❌ Error during packaging: {e}")
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    main()
