#!/usr/bin/env python3
"""
Startup cleanup script to remove orphaned PostgreSQL temporary schemas.
This should be run before starting the main services to clean up any orphaned schemas
from previous crashed processes.
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

def cleanup_orphaned_schemas():
    """Clean up orphaned temporary schemas that can be dropped."""
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
        
        logger.info(f"📊 Found {len(temp_schemas)} temporary schemas")
        
        # Try to drop each schema
        dropped_count = 0
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
                    continue
                
                # Try to drop the schema
                cursor.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
                logger.info(f"✅ Dropped {schema_name}")
                dropped_count += 1
                
            except Exception as e:
                logger.warning(f"⚠️ Could not drop {schema_name}: {e}")
                # Rollback the failed transaction
                conn.rollback()
        
        conn.commit()
        logger.info(f"🧹 Cleanup complete: {dropped_count}/{len(temp_schemas)} schemas dropped")
        
        # Report remaining schemas
        if dropped_count < len(temp_schemas):
            remaining = len(temp_schemas) - dropped_count
            logger.warning(f"⚠️ {remaining} schemas could not be dropped (owned by other processes)")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def main():
    """Main function for startup cleanup."""
    logger.info("🧹 Starting PostgreSQL schema cleanup...")
    success = cleanup_orphaned_schemas()
    
    if success:
        logger.info("✅ Startup cleanup completed successfully")
        return 0
    else:
        logger.error("❌ Startup cleanup failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
