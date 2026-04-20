#!/usr/bin/env python3
"""
Database Schema Migration Utility Script
========================================

Updates all database tables to match MASTER_DB_SCHEMA_REFERENCE.md by adding
missing columns only. Does not change column types or defaults.

- Adds missing columns (preserving all existing data).
- Handles monitor-specific tables by discovering all instances.
- Type/default mismatches: this script does not run ALTER COLUMN. Use
  reversible migrations in scripts/migrations/ (scripts/db/run_migration.py) or
  apply ALTERs manually per docs/MASTER_DB_SCHEMA_REFERENCE.md. Run
  scripts/db/audit_db_schema.py to see type mismatches.

Usage:
    # Preview changes
    python3 scripts/db/update_db_schema_to_reference.py --dry-run

    # Apply migrations (no prompt)
    python3 scripts/db/update_db_schema_to_reference.py --yes

    # Apply migrations (interactive)
    python3 scripts/db/update_db_schema_to_reference.py

Connection: uses backend.core.config.database.get_postgresql_connection()
(DB_* / REC_DB_* env). See docs/MASTER_DB_SCHEMA_REFERENCE.md.
"""

import re
import sys
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Add project root to path (script lives in scripts/db/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Load .env so get_postgresql_connection() sees DB_* / REC_DB_*
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass
for rec_k, db_k in [
    ('REC_DB_HOST', 'DB_HOST'), ('REC_DB_PORT', 'DB_PORT'), ('REC_DB_NAME', 'DB_NAME'),
    ('REC_DB_USER', 'DB_USER'), ('REC_DB_PASS', 'DB_PASSWORD'),
]:
    if os.getenv(rec_k) and not os.getenv(db_k):
        os.environ[db_k] = os.getenv(rec_k)


def get_db_connection():
    """Get PostgreSQL connection via project config (DB_* / REC_DB_* env)."""
    try:
        from backend.core.config.database import get_postgresql_connection
        conn = get_postgresql_connection()
        if conn is None:
            raise RuntimeError("get_postgresql_connection() returned None")
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return None

def parse_schema_reference(file_path: str) -> Dict[str, Dict]:
    """
    Parse MASTER_DB_SCHEMA_REFERENCE.md and extract table schemas
    
    Returns: Dict mapping "schema.table" -> {columns: [...], constraints: [...], indexes: [...]}
    """
    schemas = {}
    current_table = None
    current_schema = None
    in_columns = False
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Split by table sections
    table_sections = re.split(r'### Table: `([^`]+)`', content)
    
    i = 1  # Start at 1 (skip content before first table)
    while i < len(table_sections):
        if i + 1 >= len(table_sections):
            break
        
        table_name = table_sections[i]
        table_content = table_sections[i + 1]
        
        # Extract schema from table name or use 'users' as default
        if '.' in table_name:
            schema, table = table_name.split('.', 1)
        else:
            # Try to find schema from context
            schema = 'users'  # Default
            table = table_name
        
        full_table_name = f"{schema}.{table}"
        
        # Initialize schema entry
        if full_table_name not in schemas:
            schemas[full_table_name] = {
                'columns': [],
                'constraints': [],
                'indexes': []
            }
        
        # Parse columns section
        columns_match = re.search(r'#### Columns\s*\n\s*\| Column Name.*?\n\s*\|-.*?\n((?:\|.*?\n)+)', table_content, re.DOTALL)
        if columns_match:
            columns_text = columns_match.group(1)
            for col_line in columns_text.strip().split('\n'):
                if not col_line.strip() or not col_line.startswith('|'):
                    continue
                
                parts = [p.strip() for p in col_line.split('|')]
                if len(parts) < 5:
                    continue
                
                col_name = parts[1].replace('`', '').strip()
                if not col_name:
                    continue
                
                data_type = parts[2].replace('`', '').strip()
                nullable_str = parts[3].strip().lower()
                default_str = parts[4].strip() if len(parts) > 4 else '-'
                
                nullable = nullable_str == 'yes'
                default = None if default_str == '-' or not default_str else default_str
                
                # Handle truncated defaults (ending with ...)
                if default and default.endswith('...'):
                    default = default[:-3] + "::regclass)"  # Common pattern for sequences
                
                # Normalize data type
                data_type = normalize_data_type(data_type)
                
                schemas[full_table_name]['columns'].append({
                    'name': col_name,
                    'type': data_type,
                    'nullable': nullable,
                    'default': default
                })
        
        i += 2  # Move to next table
    
    return schemas

def normalize_data_type(pg_type: str) -> str:
    """Normalize PostgreSQL data type from reference format to SQL format"""
    pg_type = pg_type.strip()
    
    # Extract precision/scale for numeric types first (before removing parentheses)
    if 'numeric' in pg_type.lower():
        match = re.search(r'\((\d+),(\d+)\)', pg_type)
        if match:
            precision, scale = match.groups()
            return f"NUMERIC({precision},{scale})"
        return 'NUMERIC'
    
    # Extract length for varchar/character varying
    if 'varying' in pg_type.lower() or 'character varying' in pg_type.lower():
        match = re.search(r'\((\d+)\)', pg_type)
        if match:
            length = match.group(1)
            return f"VARCHAR({length})"
        return 'VARCHAR'
    
    # Extract length for integer types (but we'll ignore the display width)
    if 'integer' in pg_type.lower() or 'int' in pg_type.lower():
        return 'INTEGER'
    
    if 'smallint' in pg_type.lower():
        return 'SMALLINT'
    
    if 'bigint' in pg_type.lower():
        return 'BIGINT'
    
    # Handle specific type mappings
    type_mappings = {
        'real': 'REAL',
        'double precision': 'DOUBLE PRECISION',
        'text': 'TEXT',
        'boolean': 'BOOLEAN',
        'bool': 'BOOLEAN',
        'timestamp without time zone': 'TIMESTAMP',
        'timestamp with time zone': 'TIMESTAMPTZ',
        'timestamptz': 'TIMESTAMPTZ',
        'date': 'DATE',
        'time without time zone': 'TIME',
        'time with time zone': 'TIMETZ',
        'time': 'TIME'
    }
    
    # Try direct mapping first
    pg_lower = pg_type.lower()
    for key, value in type_mappings.items():
        if key in pg_lower:
            return value
    
    # Default: return uppercase
    return pg_type.upper()

def get_existing_tables(conn) -> List[str]:
    """Get list of all existing tables in the database"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT schemaname, tablename 
        FROM pg_tables 
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schemaname, tablename
    """)
    tables = [f"{row[0]}.{row[1]}" for row in cursor.fetchall()]
    cursor.close()
    return tables

def get_existing_columns(conn, schema: str, table: str) -> Dict[str, Dict]:
    """Get existing columns for a table"""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT 
            column_name,
            data_type,
            is_nullable,
            column_default,
            character_maximum_length,
            numeric_precision,
            numeric_scale
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (schema, table))
    
    columns = {}
    for row in cursor.fetchall():
        col_name = row['column_name']
        data_type = row['data_type']
        
        # Build full type string
        if data_type == 'numeric':
            if row['numeric_precision'] and row['numeric_scale']:
                full_type = f"NUMERIC({row['numeric_precision']},{row['numeric_scale']})"
            else:
                full_type = 'NUMERIC'
        elif data_type in ['character varying', 'varchar']:
            if row['character_maximum_length']:
                full_type = f"VARCHAR({row['character_maximum_length']})"
            else:
                full_type = 'VARCHAR'
        else:
            full_type = data_type.upper()
        
        columns[col_name] = {
            'type': full_type,
            'nullable': row['is_nullable'] == 'YES',
            'default': row['column_default']
        }
    
    cursor.close()
    return columns

def discover_monitor_tables(conn, base_table_pattern: str) -> List[str]:
    """
    Discover all monitor-specific table instances
    
    Examples:
    - "users.monitor_list_NNNN" -> finds all "users.monitor_list_XXXX"
    - "users.active_trades_NNNN_10002" -> finds all "users.active_trades_XXXX_YYYY"
    - "users.trades_NNNN" -> finds all "users.trades_XXXX"
    """
    # Extract schema and base name
    if '.' in base_table_pattern:
        schema, table_name = base_table_pattern.split('.', 1)
    else:
        schema = 'users'
        table_name = base_table_pattern
    
    # Pattern: replace trailing numbers with wildcard
    # monitor_list_0001 -> monitor_list_%
    # active_trades_0001_10002 -> active_trades_%_%
    # trades_0001 -> trades_%
    
    # Match pattern: table_name ending with _ followed by digits
    # Replace all trailing number groups with %
    pattern = re.sub(r'_\d+(_\d+)?$', '_%', table_name)
    # If no match, try replacing just the last number group
    if pattern == table_name:
        pattern = re.sub(r'_\d+$', '_%', table_name)
    
    cursor = conn.cursor()
    cursor.execute("""
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = %s 
        AND tablename LIKE %s
        ORDER BY tablename
    """, (schema, pattern))
    
    tables = [f"{schema}.{row[0]}" for row in cursor.fetchall()]
    cursor.close()
    return tables

def is_monitor_specific_table(table_name: str) -> bool:
    """Check if table name matches monitor-specific pattern"""
    # Patterns: 
    # - monitor_list_0001
    # - active_trades_0001_10002
    # - trades_0001
    # - etc.
    return bool(re.search(r'_\d{4}(_\d{5})?$', table_name))

def generate_alter_statements(conn, reference_schemas: Dict) -> List[Tuple[str, str]]:
    """
    Generate ALTER TABLE statements for missing columns
    
    Returns: List of (table_name, alter_statement) tuples
    """
    statements = []
    existing_tables = get_existing_tables(conn)
    
    for ref_table, ref_schema in reference_schemas.items():
        schema_name, table_name = ref_table.split('.', 1)
        
        # Check if this is a monitor-specific table pattern
        if is_monitor_specific_table(table_name):
            # Discover all instances
            monitor_tables = discover_monitor_tables(conn, ref_table)
            if not monitor_tables:
                print(f"⚠️  No instances found for pattern: {ref_table}")
                continue
            
            print(f"📋 Found {len(monitor_tables)} instance(s) for pattern: {ref_table}")
            
            # Apply to all instances
            for monitor_table in monitor_tables:
                m_schema, m_table = monitor_table.split('.', 1)
                m_existing_columns = get_existing_columns(conn, m_schema, m_table)
                alter_stmts = generate_column_alters(m_existing_columns, ref_schema['columns'], m_schema, m_table)
                statements.extend([(monitor_table, stmt) for stmt in alter_stmts])
        else:
            # Regular table
            if ref_table not in existing_tables:
                print(f"⚠️  Table not found: {ref_table}")
                continue
            
            existing_columns = get_existing_columns(conn, schema_name, table_name)
            alter_stmts = generate_column_alters(existing_columns, ref_schema['columns'], schema_name, table_name)
            statements.extend([(ref_table, stmt) for stmt in alter_stmts])
    
    return statements

def generate_column_alters(existing_columns: Dict, ref_columns: List[Dict], schema: str, table: str) -> List[str]:
    """Generate ALTER TABLE statements for missing columns"""
    statements = []
    
    for ref_col in ref_columns:
        col_name = ref_col['name']
        ref_type = ref_col['type']
        ref_nullable = ref_col['nullable']
        ref_default = ref_col['default']
        
        if col_name not in existing_columns:
            # Column is missing - add it
            alter_parts = [f"ALTER TABLE {schema}.{table} ADD COLUMN {col_name} {ref_type}"]
            
            # Handle default value
            if ref_default:
                # Clean up default value
                default_val = ref_default.strip()
                # Remove type casts that might be in the reference (keep the value part)
                if '::' in default_val:
                    default_val = default_val.split('::')[0].strip()
                # Handle quoted strings
                if default_val.startswith("'") and default_val.endswith("'"):
                    default_val = default_val  # Keep as is
                # Common defaults that don't need quotes
                elif default_val.upper() in ['CURRENT_TIMESTAMP', 'FALSE', 'TRUE', 'NULL']:
                    default_val = default_val.upper()
                alter_parts.append(f"DEFAULT {default_val}")
            
            # Handle NOT NULL constraint
            if not ref_nullable:
                if ref_default:
                    # Can safely add NOT NULL with default
                    alter_parts.append("NOT NULL")
                else:
                    # NOT NULL without default - add as nullable to preserve data
                    print(f"  ⚠️  Column {schema}.{table}.{col_name} is NOT NULL but no default - adding as nullable to preserve data")
            
            stmt = " ".join(alter_parts)
            statements.append(stmt)
        else:
            # Column exists - check if type needs updating (optional, skip for now to be safe)
            existing_col = existing_columns[col_name]
            # Normalize types for comparison (remove case sensitivity)
            existing_type_norm = existing_col['type'].upper()
            ref_type_norm = ref_type.upper()
            if existing_type_norm != ref_type_norm:
                print(f"  ℹ️  Column {schema}.{table}.{col_name} type mismatch: existing={existing_col['type']}, reference={ref_type} (skipping type change)")
    
    return statements

def execute_migrations(conn, statements: List[Tuple[str, str]], dry_run: bool = False):
    """Execute migration statements"""
    if not statements:
        print("✅ No migrations needed - all tables are up to date")
        return
    
    print(f"\n{'='*80}")
    print(f"{'DRY RUN - ' if dry_run else ''}Found {len(statements)} migration(s) to apply")
    print(f"{'='*80}\n")
    
    # Group by table
    by_table = defaultdict(list)
    for table, stmt in statements:
        by_table[table].append(stmt)
    
    for table, stmts in sorted(by_table.items()):
        print(f"\n📋 Table: {table}")
        print(f"   {len(stmts)} column(s) to add:")
        for stmt in stmts:
            print(f"   • {stmt}")
    
    if dry_run:
        print("\n🔍 DRY RUN - No changes applied")
        return
    
    # Execute migrations
    cursor = conn.cursor()
    success_count = 0
    error_count = 0
    
    for table, stmt in statements:
        try:
            cursor.execute(stmt)
            success_count += 1
            print(f"✅ {table}: Added column")
        except Exception as e:
            error_count += 1
            print(f"❌ {table}: Error - {e}")
            print(f"   Statement: {stmt}")
    
    if success_count > 0:
        conn.commit()
        print(f"\n✅ Successfully applied {success_count} migration(s)")
    
    if error_count > 0:
        conn.rollback()
        print(f"\n❌ {error_count} migration(s) failed - rolled back")
        return False
    
    cursor.close()
    return True

def main():
    """Main execution"""
    schema_ref_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'docs',
        'MASTER_DB_SCHEMA_REFERENCE.md'
    )
    
    if not os.path.exists(schema_ref_path):
        print(f"❌ Schema reference file not found: {schema_ref_path}")
        sys.exit(1)
    
    print("📖 Parsing schema reference...")
    reference_schemas = parse_schema_reference(schema_ref_path)
    print(f"✅ Parsed {len(reference_schemas)} table definitions")
    
    print("\n🔌 Connecting to database...")
    conn = get_db_connection()
    if not conn:
        sys.exit(1)
    
    try:
        print("🔍 Analyzing database schema...")
        statements = generate_alter_statements(conn, reference_schemas)
        
        dry_run = '--dry-run' in sys.argv
        auto_yes = '--yes' in sys.argv or '-y' in sys.argv
        if not dry_run and statements and not auto_yes:
            print(f"\n⚠️  Ready to apply {len(statements)} migration(s)")
            response = input("Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("❌ Migration cancelled")
                return
        
        execute_migrations(conn, statements, dry_run=dry_run)
        
    finally:
        conn.close()
        print("\n🔌 Database connection closed")

if __name__ == '__main__':
    main()

