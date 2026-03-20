#!/usr/bin/env python3

import sqlite3
import psycopg2
import os
from datetime import datetime

def migrate_sqlite_to_postgres():
    print("Starting SQLite to PostgreSQL migration...")
    
    # SQLite connection
    sqlite_path = "backend/data/trade_history/trades.db"
    if not os.path.exists(sqlite_path):
        print(f"SQLite database not found at {sqlite_path}")
        return False
    
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # PostgreSQL connection
    pg_conn = psycopg2.connect(
        host='localhost',
        database='rec_io_db',
        user='rec_io_user',
        password='rec_io_password'
    )
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get all tables from SQLite
        sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = sqlite_cursor.fetchall()
        
        print(f"Found {len(tables)} tables to migrate")
        
        for table in tables:
            table_name = table[0]
            print(f"Migrating table: {table_name}")
            
            # Get table schema
            sqlite_cursor.execute(f"PRAGMA table_info({table_name});")
            columns = sqlite_cursor.fetchall()
            
            # Create table in PostgreSQL
            column_defs = []
            for col in columns:
                col_name = col[1]
                col_type = col[2]
                # Convert SQLite types to PostgreSQL types
                if col_type.upper() in ['INTEGER', 'INT']:
                    pg_type = 'INTEGER'
                elif col_type.upper() in ['TEXT', 'VARCHAR']:
                    pg_type = 'TEXT'
                elif col_type.upper() in ['REAL', 'FLOAT']:
                    pg_type = 'REAL'
                elif col_type.upper() in ['BLOB']:
                    pg_type = 'BYTEA'
                else:
                    pg_type = 'TEXT'
                
                column_defs.append(f"{col_name} {pg_type}")
            
            create_table_sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(column_defs)});"
            pg_cursor.execute(create_table_sql)
            
            # Get data from SQLite
            sqlite_cursor.execute(f"SELECT * FROM {table_name};")
            rows = sqlite_cursor.fetchall()
            
            if rows:
                # Insert data into PostgreSQL
                placeholders = ', '.join(['%s'] * len(columns))
                insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders});"
                
                for row in rows:
                    pg_cursor.execute(insert_sql, row)
                
                print(f"  Migrated {len(rows)} rows")
            else:
                print(f"  Table {table_name} is empty")
        
        pg_conn.commit()
        print("Migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"Migration failed: {e}")
        pg_conn.rollback()
        return False
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == "__main__":
    migrate_sqlite_to_postgres()
