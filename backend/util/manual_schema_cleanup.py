#!/usr/bin/env python3
"""
Manual cleanup script for orphaned PostgreSQL temporary schemas.
Run this script when you see orphaned pg_temp_* schemas in your database.

Usage:
    python backend/util/manual_schema_cleanup.py

This script will:
1. List all temporary schemas
2. Attempt to drop empty ones
3. Report which ones couldn't be dropped (owned by other processes)
"""

import psycopg2
import logging
import sys
import os

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config.database import get_database_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def list_temp_schemas():
    """List all temporary schemas in the database."""
    try:
        conn = psycopg2.connect(**get_database_config())
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT nspname 
            FROM pg_namespace 
            WHERE nspname LIKE 'pg_temp%' OR nspname LIKE 'pg_toast_temp%'
            ORDER BY nspname
        """)
        
        temp_schemas = cursor.fetchall()
        
        if not temp_schemas:
            logger.info("✅ No temporary schemas found")
            return []
        
        logger.info(f"📊 Found {len(temp_schemas)} temporary schemas:")
        for schema in temp_schemas:
            schema_name = schema[0]
            try:
                cursor.execute(f"""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = '{schema_name}'
                """)
                table_count = cursor.fetchone()[0]
                logger.info(f"  - {schema_name} ({table_count} tables)")
            except Exception as e:
                logger.info(f"  - {schema_name} (error checking: {e})")
        
        return [schema[0] for schema in temp_schemas]
        
    except Exception as e:
        logger.error(f"❌ Error listing schemas: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()

def cleanup_temp_schemas():
    """Clean up temporary schemas that can be dropped."""
    try:
        conn = psycopg2.connect(**get_database_config())
        cursor = conn.cursor()
        
        # Get all temporary schemas
        cursor.execute("""
            SELECT nspname 
            FROM pg_namespace 
            WHERE nspname LIKE 'pg_temp%' OR nspname LIKE 'pg_toast_temp%'
            ORDER BY nspname
        """)
        
        temp_schemas = cursor.fetchall()
        
        if not temp_schemas:
            logger.info("✅ No temporary schemas found")
            return True
        
        logger.info(f"📊 Found {len(temp_schemas)} temporary schemas to clean up")
        
        # Try to drop each schema
        dropped_count = 0
        failed_schemas = []
        
        for schema in temp_schemas:
            schema_name = schema[0]
            try:
                # Check if schema is empty first
                cursor.execute(f"""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = '{schema_name}'
                """)
                table_count = cursor.fetchone()[0]
                
                if table_count > 0:
                    logger.warning(f"⚠️ Schema {schema_name} has {table_count} tables, skipping")
                    failed_schemas.append(f"{schema_name} (has {table_count} tables)")
                    continue
                
                # Try to drop the schema
                cursor.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
                logger.info(f"✅ Dropped {schema_name}")
                dropped_count += 1
                
            except Exception as e:
                logger.warning(f"⚠️ Could not drop {schema_name}: {e}")
                failed_schemas.append(f"{schema_name} ({str(e)})")
                # Rollback the failed transaction
                conn.rollback()
        
        conn.commit()
        logger.info(f"🧹 Cleanup complete: {dropped_count}/{len(temp_schemas)} schemas dropped")
        
        # Report failed schemas
        if failed_schemas:
            logger.warning(f"⚠️ {len(failed_schemas)} schemas could not be dropped:")
            for schema in failed_schemas:
                logger.warning(f"  - {schema}")
            
            logger.info("\\n💡 To clean up remaining schemas:")
            logger.info("   1. Stop all services: supervisorctl stop all")
            logger.info("   2. Wait a few seconds for connections to close")
            logger.info("   3. Run this script again")
            logger.info("   4. Restart services: supervisorctl start all")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def main():
    """Main function for manual cleanup."""
    logger.info("🧹 Manual PostgreSQL schema cleanup")
    logger.info("=" * 50)
    
    # Check for --force flag
    force = '--force' in sys.argv
    
    # List schemas first
    schemas = list_temp_schemas()
    
    if not schemas:
        return 0
    
    # Ask user if they want to proceed (unless --force)
    if not force:
        print("\\nDo you want to attempt to clean up these schemas? (y/n): ", end="")
        response = input().strip().lower()
        
        if response not in ['y', 'yes']:
            logger.info("❌ Cleanup cancelled by user")
            return 0
    
    # Perform cleanup
    success = cleanup_temp_schemas()
    
    if success:
        logger.info("✅ Manual cleanup completed")
        return 0
    else:
        logger.error("❌ Manual cleanup failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
