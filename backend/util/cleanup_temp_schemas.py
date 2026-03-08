#!/usr/bin/env python3
"""
Cleanup script for orphaned PostgreSQL temporary schemas.
These schemas are created when processes crash or are killed without proper connection cleanup.
"""

import psycopg2
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.core.config.database import get_postgresql_connection, get_database_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def cleanup_temp_schemas():
    """Clean up orphaned temporary schemas."""
    try:
        conn = get_postgresql_connection()
        if not conn:
            logger.error("❌ Failed to connect to PostgreSQL")
            return False
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
            return
        
        logger.info(f"📊 Found {len(temp_schemas)} temporary schemas to clean up")
        
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
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()
    
    return True

def check_temp_schemas():
    """Check current temporary schemas without cleaning them."""
    try:
        conn = get_postgresql_connection()
        if not conn:
            logger.error("❌ Failed to connect to PostgreSQL")
            return
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
            return
        
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
        
    except Exception as e:
        logger.error(f"❌ Error checking schemas: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        check_temp_schemas()
    else:
        cleanup_temp_schemas()
