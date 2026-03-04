#!/usr/bin/env python3
"""
Generate Master Database Schema Reference Document
Queries the database and creates a comprehensive schema documentation
"""

import psycopg2
import os
from datetime import datetime

def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        database=os.getenv('DB_NAME', 'rec_io_db'),
        user=os.getenv('DB_USER', 'rec_io_user'),
        password=os.getenv('DB_PASSWORD', 'rec_io_password'),
        port=int(os.getenv('DB_PORT', '5432'))
    )

def get_all_schemas(conn):
    """Get all schemas"""
    cur = conn.cursor()
    cur.execute("""
        SELECT schema_name 
        FROM information_schema.schemata 
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        ORDER BY schema_name;
    """)
    return [row[0] for row in cur.fetchall()]

def get_tables_in_schema(conn, schema):
    """Get all tables in a schema"""
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = %s
        ORDER BY table_name;
    """, (schema,))
    return [row[0] for row in cur.fetchall()]

def get_table_columns(conn, schema, table):
    """Get all column information for a table"""
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            column_name,
            data_type,
            character_maximum_length,
            numeric_precision,
            numeric_scale,
            is_nullable,
            column_default,
            ordinal_position
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position;
    """, (schema, table))
    return cur.fetchall()

def get_table_constraints(conn, schema, table):
    """Get constraints for a table"""
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            tc.constraint_name,
            tc.constraint_type,
            kcu.column_name,
            ccu.table_schema AS foreign_table_schema,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        LEFT JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.table_schema = %s AND tc.table_name = %s
        ORDER BY tc.constraint_type, tc.constraint_name;
    """, (schema, table))
    return cur.fetchall()

def get_table_indexes(conn, schema, table):
    """Get indexes for a table"""
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            indexname,
            indexdef
        FROM pg_indexes
        WHERE schemaname = %s AND tablename = %s
        ORDER BY indexname;
    """, (schema, table))
    return cur.fetchall()

def format_data_type(col_info):
    """Format data type with precision/scale"""
    data_type = col_info[1]
    max_length = col_info[2]
    precision = col_info[3]
    scale = col_info[4]
    
    if max_length:
        return f"{data_type}({max_length})"
    elif precision and scale:
        return f"{data_type}({precision},{scale})"
    elif precision:
        return f"{data_type}({precision})"
    else:
        return data_type

def generate_markdown(conn):
    """Generate the markdown document"""
    output = []
    output.append("# Master Database Schema Reference")
    output.append("")
    output.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append("")
    output.append("This document provides a complete reference of all database schemas, tables, and columns.")
    output.append("Update this document whenever schema changes are made during development.")
    output.append("")
    output.append("---")
    output.append("")
    
    schemas = get_all_schemas(conn)
    
    for schema in schemas:
        output.append(f"## Schema: `{schema}`")
        output.append("")
        
        tables = get_tables_in_schema(conn, schema)
        
        if not tables:
            output.append("*No tables in this schema*")
            output.append("")
            continue
        
        for table in tables:
            output.append(f"### Table: `{schema}.{table}`")
            output.append("")
            
            # Get columns
            columns = get_table_columns(conn, schema, table)
            if columns:
                output.append("#### Columns")
                output.append("")
                output.append("| Column Name | Data Type | Nullable | Default | Description |")
                output.append("|-------------|-----------|----------|---------|-------------|")
                
                for col in columns:
                    col_name = col[0]
                    data_type = format_data_type(col)
                    nullable = "YES" if col[5] == "YES" else "NO"
                    default = col[6] if col[6] else ""
                    if len(default) > 50:
                        default = default[:47] + "..."
                    
                    output.append(f"| `{col_name}` | `{data_type}` | {nullable} | {default or '-'} | |")
                
                output.append("")
            
            # Get constraints
            constraints = get_table_constraints(conn, schema, table)
            if constraints:
                output.append("#### Constraints")
                output.append("")
                for constraint in constraints:
                    const_type = constraint[1]
                    const_name = constraint[0]
                    col_name = constraint[2]
                    
                    if const_type == "PRIMARY KEY":
                        output.append(f"- **Primary Key:** `{const_name}` on `{col_name}`")
                    elif const_type == "FOREIGN KEY":
                        fk_table = constraint[4]
                        fk_col = constraint[5]
                        output.append(f"- **Foreign Key:** `{const_name}` - `{col_name}` → `{fk_table}.{fk_col}`")
                    elif const_type == "UNIQUE":
                        output.append(f"- **Unique:** `{const_name}` on `{col_name}`")
                    elif const_type == "CHECK":
                        output.append(f"- **Check:** `{const_name}`")
                output.append("")
            
            # Get indexes
            indexes = get_table_indexes(conn, schema, table)
            if indexes:
                output.append("#### Indexes")
                output.append("")
                for idx in indexes:
                    idx_name = idx[0]
                    idx_def = idx[1]
                    output.append(f"- `{idx_name}`")
                    output.append(f"  ```sql")
                    output.append(f"  {idx_def}")
                    output.append(f"  ```")
                output.append("")
            
            output.append("---")
            output.append("")
    
    return "\n".join(output)

def main():
    """Main function"""
    conn = get_db_connection()
    try:
        markdown = generate_markdown(conn)
        output_file = "docs/MASTER_DB_SCHEMA_REFERENCE.md"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w') as f:
            f.write(markdown)
        print(f"✅ Schema documentation generated: {output_file}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()

