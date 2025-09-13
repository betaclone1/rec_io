#!/usr/bin/env python3
"""
Force cleanup script for orphaned PostgreSQL temporary schemas.
This script should be run with superuser privileges to clean up schemas
that are owned by crashed processes.
"""

import psycopg2
import logging
import sys
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def force_cleanup_schemas():
    """Force cleanup of orphaned temporary schemas using superuser privileges."""
    try:
        # Connect as postgres superuser
        conn = psycopg2.connect(
            host='137.184.224.94',
            user='postgres',
            password='rec_io_password',
            dbname='rec_io_db'
        )
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
        
        logger.info(f"📊 Found {len(temp_schemas)} temporary schemas to force cleanup")
        
        # Force drop each schema
        dropped_count = 0
        for schema in temp_schemas:
            schema_name = schema[0]
            try:
                # Force drop the schema
                cursor.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
                logger.info(f"✅ Force dropped {schema_name}")
                dropped_count += 1
                
            except Exception as e:
                logger.warning(f"⚠️ Could not force drop {schema_name}: {e}")
                # Rollback the failed transaction
                conn.rollback()
        
        conn.commit()
        logger.info(f"🧹 Force cleanup complete: {dropped_count}/{len(temp_schemas)} schemas dropped")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error during force cleanup: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def main():
    """Main function for force cleanup."""
    logger.info("🧹 Starting force cleanup of PostgreSQL schemas...")
    success = force_cleanup_schemas()
    
    if success:
        logger.info("✅ Force cleanup completed successfully")
        return 0
    else:
        logger.error("❌ Force cleanup failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
