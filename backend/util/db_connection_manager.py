#!/usr/bin/env python3
"""
Database Connection Manager with proper cleanup to prevent orphaned temporary schemas.
"""

import psycopg2
import logging
from contextlib import contextmanager
from typing import Generator, Optional
import sys
import os

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config.database import get_database_config

logger = logging.getLogger(__name__)

@contextmanager
def get_db_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Context manager for database connections with proper cleanup.
    This prevents orphaned temporary schemas by ensuring connections are always closed.
    """
    conn = None
    try:
        conn = psycopg2.connect(**get_database_config())
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Database connection error: {e}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception as e:
                logger.warning(f"⚠️ Error closing database connection: {e}")

@contextmanager
def get_db_cursor() -> Generator[psycopg2.extensions.cursor, None, None]:
    """
    Context manager for database cursors with proper cleanup.
    This prevents orphaned temporary schemas by ensuring cursors and connections are always closed.
    """
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(**get_database_config())
        cursor = conn.cursor()
        yield cursor
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Database cursor error: {e}")
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception as e:
                logger.warning(f"⚠️ Error closing database cursor: {e}")
        if conn:
            try:
                conn.close()
            except Exception as e:
                logger.warning(f"⚠️ Error closing database connection: {e}")

def execute_with_cleanup(query: str, params: Optional[tuple] = None, fetch: bool = False):
    """
    Execute a database query with proper cleanup.
    Returns the result if fetch=True, otherwise returns None.
    """
    with get_db_cursor() as cursor:
        cursor.execute(query, params)
        if fetch:
            return cursor.fetchall()
        return None

def execute_transaction(queries: list, params_list: Optional[list] = None):
    """
    Execute multiple queries in a transaction with proper cleanup.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            for i, query in enumerate(queries):
                params = params_list[i] if params_list and i < len(params_list) else None
                cursor.execute(query, params)
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            cursor.close()

def test_connection():
    """Test database connection and return status."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            return True, "Database connection successful"
    except Exception as e:
        return False, f"Database connection error: {e}"

if __name__ == "__main__":
    # Test the connection manager
    success, message = test_connection()
    if success:
        print(f"✅ {message}")
    else:
        print(f"❌ {message}")
