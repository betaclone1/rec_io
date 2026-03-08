#!/usr/bin/env python3
"""
Full audit: local DB schema vs MASTER_DB_SCHEMA_REFERENCE.md vs database.py.
Usage: PYTHONPATH=$(pwd) venv/bin/python scripts/db/audit_db_schema.py
No modifications; report only.
"""
import os
import re
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from backend.core.config.database import get_postgresql_connection, get_database_config


def get_conn():
    return get_postgresql_connection()

def normalize_db_type(data_type, character_maximum_length=None, numeric_precision=None, numeric_scale=None):
    """Normalize information_schema types to canonical form for comparison."""
    if data_type == 'integer' or data_type == 'int4':
        return 'INTEGER'
    if data_type == 'bigint' or data_type == 'int8':
        return 'BIGINT'
    if data_type == 'smallint' or data_type == 'int2':
        return 'SMALLINT'
    if data_type == 'real' or data_type == 'float4':
        return 'REAL'
    if data_type == 'double precision' or data_type == 'float8':
        return 'DOUBLE PRECISION'
    if data_type == 'character varying':
        n = character_maximum_length or ''
        return f"VARCHAR({n})" if n else 'VARCHAR'
    if data_type == 'numeric':
        if numeric_precision is not None and numeric_scale is not None:
            return f"NUMERIC({numeric_precision},{numeric_scale})"
        return 'NUMERIC'
    if data_type == 'text':
        return 'TEXT'
    if data_type == 'boolean' or data_type == 'bool':
        return 'BOOLEAN'
    if data_type == 'timestamp with time zone':
        return 'TIMESTAMPTZ'
    if data_type == 'timestamp without time zone':
        return 'TIMESTAMP'
    if data_type == 'date':
        return 'DATE'
    if data_type == 'time without time zone':
        return 'TIME'
    if data_type == 'time with time zone':
        return 'TIMETZ'
    return data_type.upper() if data_type else data_type

def get_db_schema(conn):
    """Return dict: full_table_name -> list of {name, type, nullable, default}."""
    cur = conn.cursor()
    cur.execute("""
        SELECT table_schema, table_name, column_name, data_type,
               character_maximum_length, numeric_precision, numeric_scale,
               is_nullable, column_default, ordinal_position
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        ORDER BY table_schema, table_name, ordinal_position
    """)
    schema = {}
    for row in cur.fetchall():
        schema_name, table_name, col_name, data_type, char_max, num_prec, num_scale, nullable, default, _ = row
        full = f"{schema_name}.{table_name}"
        if full not in schema:
            schema[full] = []
        pg_type = normalize_db_type(data_type, char_max, num_prec, num_scale)
        schema[full].append({
            'name': col_name,
            'type': pg_type,
            'nullable': nullable == 'YES',
            'default': default
        })
    cur.close()
    return schema

def _normalize_doc_type(pg_type):
    """Normalize doc type string to canonical SQL type."""
    pg_type = pg_type.strip()
    if 'numeric' in pg_type.lower():
        m = re.search(r'\((\d+),(\d+)\)', pg_type)
        return f"NUMERIC({m.group(1)},{m.group(2)})" if m else 'NUMERIC'
    if 'varying' in pg_type.lower():
        m = re.search(r'\((\d+)\)', pg_type)
        return f"VARCHAR({m.group(1)})" if m else 'VARCHAR'
    if 'integer' in pg_type.lower() or 'int' in pg_type.lower():
        return 'INTEGER'
    if 'smallint' in pg_type.lower():
        return 'SMALLINT'
    if 'bigint' in pg_type.lower():
        return 'BIGINT'
    for k, v in [('real', 'REAL'), ('double precision', 'DOUBLE PRECISION'), ('text', 'TEXT'),
                  ('boolean', 'BOOLEAN'), ('bool', 'BOOLEAN'), ('timestamp with time zone', 'TIMESTAMPTZ'),
                  ('timestamptz', 'TIMESTAMPTZ'), ('timestamp without time zone', 'TIMESTAMP'),
                  ('date', 'DATE'), ('time without time zone', 'TIME'), ('time with time zone', 'TIMETZ'), ('time', 'TIME')]:
        if k in pg_type.lower():
            return v
    return pg_type.upper()

def parse_doc_schema(doc_path):
    """Parse MASTER_DB_SCHEMA_REFERENCE.md; return dict full_table -> list of {name, type, nullable, default}."""
    with open(doc_path, 'r') as f:
        content = f.read()
    table_sections = re.split(r'### Table: `([^`]+)`', content)
    out = {}
    i = 1
    while i + 1 < len(table_sections):
        table_name = table_sections[i]
        table_content = table_sections[i + 1]
        if '.' in table_name:
            schema, table = table_name.split('.', 1)
        else:
            schema, table = 'users', table_name
        full = f"{schema}.{table}"
        out[full] = []
        columns_match = re.search(r'#### Columns\s*\n\s*\| Column Name.*?\n\s*\|-.*?\n((?:\|.*?\n)+)', table_content, re.DOTALL)
        if columns_match:
            for col_line in columns_match.group(1).strip().split('\n'):
                if not col_line.strip() or not col_line.startswith('|'):
                    continue
                parts = [p.strip() for p in col_line.split('|')]
                if len(parts) < 5:
                    continue
                col_name = parts[1].replace('`', '').strip()
                if not col_name:
                    continue
                data_type = _normalize_doc_type(parts[2].replace('`', '').strip())
                nullable = parts[3].strip().lower() == 'yes'
                default_str = parts[4].strip() if len(parts) > 4 else '-'
                default = None if default_str == '-' or not default_str else default_str
                out[full].append({'name': col_name, 'type': data_type, 'nullable': nullable, 'default': default})
        i += 2
    return out

def parse_database_py(db_py_path):
    """Extract CREATE TABLE definitions from database.py. Returns dict full_table -> list of {name, type}."""
    with open(db_py_path, 'r') as f:
        content = f.read()
    # Find CREATE TABLE IF NOT EXISTS schema.name ( ... );
    pattern = r"CREATE TABLE IF NOT EXISTS\s+([a-z_]+)\.([a-z_0-9]+)\s*\((.*?)\)\s*;"
    matches = re.findall(pattern, content, re.DOTALL)
    result = {}
    for schema, table, body in matches:
        full = f"{schema}.{table}"
        # Skip template tables like strike_table_15m_{sym}
        if '{' in table:
            continue
        cols = []
        for line in body.split('\n'):
            line = line.strip().strip(',').strip()
            if not line or line.startswith('CONSTRAINT') or line.startswith('PRIMARY ') or line.startswith('UNIQUE ') or line.startswith('FOREIGN ') or line.startswith('CHECK'):
                continue
            # First token: column name; rest up to DEFAULT/NOT NULL/PRIMARY: type
            parts = line.split()
            if not parts:
                continue
            name = parts[0]
            if name.startswith('--') or name == '--':
                continue
            # Type: collect tokens until we hit DEFAULT, NOT NULL, PRIMARY, UNIQUE, etc.
            stop = {'DEFAULT', 'NOT', 'NULL', 'PRIMARY', 'UNIQUE', 'REFERENCES', 'CHECK'}
            i = 1
            type_parts = []
            while i < len(parts):
                if parts[i] in stop or (parts[i] == 'NULL' and i > 0 and parts[i-1] == 'NOT'):
                    break
                type_parts.append(parts[i])
                i += 1
            if type_parts:
                typ = ' '.join(type_parts).upper()
                # Normalize SERIAL -> INTEGER for comparison
                if typ == 'SERIAL':
                    typ = 'INTEGER'
                cols.append({'name': name, 'type': typ})
        result[full] = cols
    return result

def normalize_type_for_compare(t):
    """Normalize type string for comparison. Uses compatible buckets so REFERENCE (TEXT/REAL)
    and database.py (VARCHAR(n)/DECIMAL) align for drift check."""
    t = t.upper().strip()
    if 'TIMESTAMP WITH TIME ZONE' in t or t == 'TIMESTAMPTZ':
        return 'TIMESTAMPTZ'
    if 'TIMESTAMP WITHOUT TIME ZONE' in t or t == 'TIMESTAMP':
        return 'STRING'
    if 'TIME WITHOUT TIME ZONE' in t or t == 'TIME':
        return 'STRING'
    if t == 'DATE':
        return 'STRING'
    # Reference doc often uses TEXT for temporal columns; treat as compatible with DATE/TIME/TIMESTAMP
    # String-like: TEXT and VARCHAR(n) are compatible
    if t == 'TEXT' or t.startswith('VARCHAR') or t.startswith('CHARACTER VARYING') or t.startswith('CHAR('):
        return 'STRING'
    # Numeric: REAL, DOUBLE PRECISION, DECIMAL, NUMERIC are compatible
    if t == 'REAL' or 'DOUBLE PRECISION' in t or t.startswith('NUMERIC') or t.startswith('DECIMAL'):
        return 'NUMERIC'
    # Integer family: INTEGER and SMALLINT compatible for drift check
    if t == 'INTEGER' or t == 'INT' or t == 'SMALLINT' or t == 'BIGINT':
        return 'INT'
    if t == 'BOOLEAN' or t == 'BOOL':
        return 'BOOLEAN'
    return t

def compare_columns(db_cols, ref_cols, label_ref):
    """Compare two column lists. Returns (only_in_db, only_in_ref, type_mismatches)."""
    db_names = {c['name']: c for c in db_cols}
    ref_names = {c['name']: c for c in ref_cols}
    only_db = set(db_names) - set(ref_names)
    only_ref = set(ref_names) - set(db_names)
    mismatches = []
    for name in set(db_names) & set(ref_names):
        dt = normalize_type_for_compare(db_names[name]['type'])
        rt = normalize_type_for_compare(ref_names[name]['type'])
        if dt != rt:
            mismatches.append((name, db_names[name]['type'], ref_names[name]['type']))
    return (sorted(only_db), sorted(only_ref), mismatches)

def main():
    repo_root = os.path.join(os.path.dirname(__file__), '..', '..')
    doc_path = os.path.join(repo_root, 'docs', 'MASTER_DB_SCHEMA_REFERENCE.md')
    db_py_path = os.path.join(repo_root, 'backend', 'core', 'config', 'database.py')

    print("=== 1. LOCAL DB SCHEMA (all tables) ===")
    try:
        conn = get_conn()
        db_schema = get_db_schema(conn)
        conn.close()
    except Exception as e:
        print("Failed to connect to local DB:", e)
        db_schema = {}

    db_tables = sorted(db_schema.keys())
    print(f"Tables in local DB: {len(db_tables)}")
    for t in db_tables:
        print(f"  {t} ({len(db_schema[t])} columns)")

    print("\n=== 2. MASTER DOC SCHEMA ===")
    if not os.path.exists(doc_path):
        print("Doc not found:", doc_path)
        doc_schema = {}
    else:
        doc_schema = parse_doc_schema(doc_path)
    doc_tables = sorted(doc_schema.keys())
    print(f"Tables in MASTER_DB_SCHEMA_REFERENCE.md: {len(doc_tables)}")
    for t in doc_tables:
        print(f"  {t} ({len(doc_schema[t])} columns)")

    print("\n=== 3. database.py CREATE TABLE definitions ===")
    py_schema = parse_database_py(db_py_path)
    py_tables = sorted(py_schema.keys())
    print(f"Tables created in database.py: {len(py_tables)}")
    for t in py_tables:
        print(f"  {t} ({len(py_schema[t])} columns)")

    print("\n" + "="*80)
    print("=== 4. DOC vs LOCAL DB ===")
    print("="*80)
    only_in_db = set(db_tables) - set(doc_tables)
    only_in_doc = set(doc_tables) - set(db_tables)
    if only_in_db:
        print("\nTables in DB but NOT in Doc:", len(only_in_db))
        for t in sorted(only_in_db):
            print(f"  {t}")
    if only_in_doc:
        print("\nTables in Doc but NOT in DB:", len(only_in_doc))
        for t in sorted(only_in_doc):
            print(f"  {t}")

    doc_vs_db_ok = []
    doc_vs_db_issues = []
    for table in sorted(set(db_tables) & set(doc_tables)):
        db_cols = db_schema[table]
        doc_cols = doc_schema[table]
        only_db, only_doc, mismatches = compare_columns(db_cols, doc_cols, "Doc")
        if only_db or only_doc or mismatches:
            doc_vs_db_issues.append((table, only_db, only_doc, mismatches))
        else:
            doc_vs_db_ok.append(table)

    if doc_vs_db_ok:
        print(f"\nTables where Doc and DB match exactly: {len(doc_vs_db_ok)}")
        for t in doc_vs_db_ok:
            print(f"  {t}")
    if doc_vs_db_issues:
        print(f"\nTables with Doc vs DB discrepancies: {len(doc_vs_db_issues)}")
        for table, only_db, only_doc, mismatches in doc_vs_db_issues:
            print(f"\n  --- {table} ---")
            if only_doc:
                print(f"    Columns in DOC only: {only_doc}")
            if only_db:
                print(f"    Columns in DB only: {only_db}")
            if mismatches:
                for name, db_t, doc_t in mismatches:
                    print(f"    Type mismatch [{name}]: DB={db_t}  DOC={doc_t}")

    print("\n" + "="*80)
    print("=== 5. database.py vs LOCAL DB ===")
    print("="*80)
    only_py = set(py_tables) - set(db_tables)
    if only_py:
        print("\nTables in database.py but not in DB:", sorted(only_py))
    py_vs_db_ok = []
    py_vs_db_issues = []
    for table in sorted(set(py_tables) & set(db_tables)):
        db_cols = db_schema[table]
        py_cols = py_schema[table]
        only_db, only_py_cols, mismatches = compare_columns(db_cols, py_cols, "database.py")
        if only_py_cols or only_db or mismatches:
            py_vs_db_issues.append((table, only_db, only_py_cols, mismatches))
        else:
            py_vs_db_ok.append(table)

    if py_vs_db_ok:
        print(f"\nTables where database.py and DB match exactly: {len(py_vs_db_ok)}")
        for t in py_vs_db_ok:
            print(f"  {t}")
    if py_vs_db_issues:
        print(f"\nTables where database.py differs from DB: {len(py_vs_db_issues)}")
        for table, only_db, only_py_cols, mismatches in py_vs_db_issues:
            print(f"\n  --- {table} ---")
            if only_py_cols:
                print(f"    Columns in database.py only: {only_py_cols}")
            if only_db:
                print(f"    Columns in DB only: {only_db}")
            if mismatches:
                for name, db_t, py_t in mismatches:
                    print(f"    Type mismatch [{name}]: DB={db_t}  database.py={py_t}")

    print("\n=== Audit complete (no changes made) ===")

if __name__ == '__main__':
    main()
