#!/usr/bin/env python3
"""
System Data Unpacking Script

This script unpacks and imports system data from a packaged archive into the
rec_io_db PostgreSQL database on a new machine.

The script will:
1. Extract the compressed archive
2. Read metadata to understand the data structure
3. Import data into the appropriate schemas and tables
4. Verify the import was successful
"""

import os
import sys
import json
import tarfile
import shutil
import argparse
import subprocess
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

def extract_archive(archive_path, extract_dir):
    """Extract the tar.gz archive."""
    print(f"📦 Extracting archive: {archive_path}")
    
    if not os.path.exists(archive_path):
        raise FileNotFoundError(f"Archive not found: {archive_path}")
    
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(extract_dir)
    
    # Find the extracted directory (should be the only one)
    extracted_dirs = [d for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
    if not extracted_dirs:
        raise ValueError("No directory found in archive")
    
    extracted_path = os.path.join(extract_dir, extracted_dirs[0])
    print(f"  ✓ Extracted to: {extracted_path}")
    
    return extracted_path

def load_metadata(extracted_path):
    """Load metadata from the extracted archive."""
    metadata_file = os.path.join(extracted_path, 'metadata.json')
    
    if not os.path.exists(metadata_file):
        raise FileNotFoundError(f"Metadata file not found: {metadata_file}")
    
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)
    
    print(f"📋 Loaded metadata:")
    print(f"  Export timestamp: {metadata['export_timestamp']}")
    print(f"  Version: {metadata['system_data_version']}")
    print(f"  Schemas: {', '.join(metadata['schemas_exported'])}")
    print(f"  Public tables: {', '.join(metadata['public_tables_exported'])}")
    
    return metadata

def create_schemas_if_not_exist(conn, schemas):
    """Create schemas if they don't exist."""
    cursor = conn.cursor()
    
    print(f"\n🏗️ Creating schemas if they don't exist...")
    
    for schema in schemas:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        print(f"  ✓ Schema '{schema}' ready")
    
    conn.commit()

def import_schema_data(conn, schema_name, schema_dir):
    """Import all SQL files from a schema directory."""
    if not os.path.exists(schema_dir):
        print(f"  ⚠ Schema directory not found: {schema_dir}")
        return
    
    sql_files = [f for f in os.listdir(schema_dir) if f.endswith('.sql')]
    
    if not sql_files:
        print(f"  ⚠ No SQL files found in schema directory: {schema_dir}")
        return
    
    print(f"  📥 Importing {len(sql_files)} tables to schema '{schema_name}':")
    
    # Get database config for psql
    config = ConfigManager()
    db_config = config.get_database_config()
    
    for sql_file in sorted(sql_files):
        table_name = sql_file.replace('.sql', '')
        sql_path = os.path.join(schema_dir, sql_file)
        
        try:
            # Use psql to import the file
            cmd = ["psql", "-h", db_config['host'], "-U", db_config['user'], "-d", db_config['name'], "-f", sql_path]
            
            # Set environment variables for psql
            env = os.environ.copy()
            env['PGPASSWORD'] = db_config['password']
            
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"    ✓ Imported {table_name}")
            else:
                print(f"    ❌ Error importing {table_name} (exit code: {result.returncode})")
                if result.stderr:
                    print(f"      Error: {result.stderr.strip()}")
                
        except Exception as e:
            print(f"    ❌ Error importing {table_name}: {e}")
            # Continue with other tables

def import_public_tables(conn, public_dir):
    """Import system tables to public schema."""
    if not os.path.exists(public_dir):
        print(f"  ⚠ Public directory not found: {public_dir}")
        return
    
    sql_files = [f for f in os.listdir(public_dir) if f.endswith('.sql')]
    
    if not sql_files:
        print(f"  ⚠ No SQL files found in public directory: {public_dir}")
        return
    
    print(f"  📥 Importing {len(sql_files)} tables to public schema:")
    
    # Get database config for psql
    config = ConfigManager()
    db_config = config.get_database_config()
    
    for sql_file in sorted(sql_files):
        table_name = sql_file.replace('.sql', '')
        sql_path = os.path.join(public_dir, sql_file)
        
        try:
            # Use psql to import the file
            cmd = ["psql", "-h", db_config['host'], "-U", db_config['user'], "-d", db_config['name'], "-f", sql_path]
            
            # Set environment variables for psql
            env = os.environ.copy()
            env['PGPASSWORD'] = db_config['password']
            
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"    ✓ Imported {table_name}")
            else:
                print(f"    ❌ Error importing {table_name} (exit code: {result.returncode})")
                if result.stderr:
                    print(f"      Error: {result.stderr.strip()}")
                
        except Exception as e:
            print(f"    ❌ Error importing {table_name}: {e}")
            # Continue with other tables

def check_table_exists_with_data(conn, schema_name, table_name):
    """Check if a table exists and has data."""
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = %s AND table_name = %s
        )
    """, (schema_name, table_name))
    
    table_exists = cursor.fetchone()[0]
    
    if not table_exists:
        return False, 0
    
    # Check if table has data
    cursor.execute(f"""
        SELECT COUNT(*) FROM "{schema_name}"."{table_name}"
    """)
    
    row_count = cursor.fetchone()[0]
    return True, row_count

def check_existing_data(conn, metadata, extracted_path):
    """Check which tables already exist with data."""
    existing_tables = {}
    
    print(f"\n🔍 Checking existing data in database...")
    
    # Check schema tables
    for schema in metadata['schemas_exported']:
        schema_dir = os.path.join(extracted_path, schema)
        if not os.path.exists(schema_dir):
            continue
            
        sql_files = [f for f in os.listdir(schema_dir) if f.endswith('.sql')]
        
        for sql_file in sql_files:
            table_name = sql_file.replace('.sql', '')
            exists, row_count = check_table_exists_with_data(conn, schema, table_name)
            
            if exists and row_count > 0:
                existing_tables[f"{schema}.{table_name}"] = row_count
                print(f"   📊 {schema}.{table_name}: {row_count:,} rows")
    
    # Check public tables
    public_dir = os.path.join(extracted_path, 'public')
    if os.path.exists(public_dir):
        sql_files = [f for f in os.listdir(public_dir) if f.endswith('.sql')]
        
        for sql_file in sql_files:
            table_name = sql_file.replace('.sql', '')
            exists, row_count = check_table_exists_with_data(conn, 'public', table_name)
            
            if exists and row_count > 0:
                existing_tables[f"public.{table_name}"] = row_count
                print(f"   📊 public.{table_name}: {row_count:,} rows")
    
    return existing_tables

def prompt_for_overwrite(existing_tables):
    """Prompt user for overwrite confirmation."""
    if not existing_tables:
        return True
    
    print(f"\n⚠️  Found {len(existing_tables)} tables with existing data:")
    for table, count in existing_tables.items():
        print(f"   - {table}: {count:,} rows")
    
    while True:
        response = input(f"\n❓ Do you want to overwrite existing data? (y/N): ").strip().lower()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no', '']:
            return False
        else:
            print("Please enter 'y' for yes or 'n' for no")

def verify_import(conn, metadata):
    """Verify that data was imported correctly."""
    cursor = conn.cursor()
    
    print(f"\n🔍 Verifying import...")
    
    total_tables = 0
    total_rows = 0
    
    # Check schemas
    for schema in metadata['schemas_exported']:
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_schema = %s
        """, (schema,))
        
        table_count = cursor.fetchone()[0]
        total_tables += table_count
        
        print(f"  📊 Schema '{schema}': {table_count} tables")
        
        # Count rows in each table
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s
        """, (schema,))
        
        tables = [row[0] for row in cursor.fetchall()]
        
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
                row_count = cursor.fetchone()[0]
                total_rows += row_count
                print(f"    - {table}: {row_count:,} rows")
            except Exception as e:
                print(f"    - {table}: Error counting rows - {e}")
    
    # Check public tables
    print(f"  📊 Public schema system tables:")
    for table in metadata['public_tables_exported']:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM public.{table}")
            row_count = cursor.fetchone()[0]
            total_rows += row_count
            print(f"    - {table}: {row_count:,} rows")
        except Exception as e:
            print(f"    - {table}: Error counting rows - {e}")
    
    print(f"\n📈 Import Summary:")
    print(f"  Total tables: {total_tables}")
    print(f"  Total rows: {total_rows:,}")
    
    return total_tables > 0 and total_rows > 0

def main():
    """Main unpacking function."""
    parser = argparse.ArgumentParser(description='Unpack system data from archive')
    parser.add_argument('archive_path', help='Path to the system data archive (.tar.gz)')
    parser.add_argument('--force', action='store_true', help='Force import even if data exists')
    
    args = parser.parse_args()
    
    print("🚀 System Data Unpacking Script")
    print("=" * 50)
    
    # Create temporary extraction directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    extract_dir = f"temp_extract_{timestamp}"
    os.makedirs(extract_dir, exist_ok=True)
    
    try:
        # Extract archive
        extracted_path = extract_archive(args.archive_path, extract_dir)
        
        # Load metadata
        metadata = load_metadata(extracted_path)
        
        # Connect to database
        print(f"\n🔌 Connecting to database...")
        conn = get_database_connection()
        print("  ✓ Database connection established")
        
        # Check for existing data
        existing_tables = check_existing_data(conn, metadata, extracted_path)
        
        # Determine if we should proceed
        should_proceed = True
        if existing_tables and not args.force:
            should_proceed = prompt_for_overwrite(existing_tables)
        
        if not should_proceed:
            print("❌ Import cancelled by user")
            conn.close()
            return
        
        # Create schemas if they don't exist
        create_schemas_if_not_exist(conn, metadata['schemas_exported'])
        
        # Import schema data
        print(f"\n📥 Importing schema data...")
        for schema in metadata['schemas_exported']:
            schema_dir = os.path.join(extracted_path, schema)
            print(f"\n📦 Schema: {schema}")
            import_schema_data(conn, schema, schema_dir)
        
        # Import public tables
        print(f"\n📥 Importing public schema tables...")
        public_dir = os.path.join(extracted_path, 'public')
        import_public_tables(conn, public_dir)
        
        # Verify import
        success = verify_import(conn, metadata)
        
        if success:
            print(f"\n✅ System data import completed successfully!")
            print(f"📋 Next steps:")
            print(f"   1. Verify the application starts correctly")
            print(f"   2. Check that all system functionality works")
            print(f"   3. Set up user accounts and credentials")
        else:
            print(f"\n⚠ Import completed but verification failed")
            print(f"   Please check the database manually")
        
    except Exception as e:
        print(f"\n❌ Error during unpacking: {e}")
        sys.exit(1)
    finally:
        # Clean up
        if 'conn' in locals():
            conn.close()
        
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
            print(f"\n🧹 Cleaned up temporary files")

if __name__ == "__main__":
    main()
