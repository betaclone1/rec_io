#!/usr/bin/env python3
"""
Check that database.py table definitions do not drift from MASTER_DB_SCHEMA_REFERENCE.md
for critical tables. Intended for CI: exit 0 if aligned, exit 1 if drift detected.

Critical tables: users.trades_0001, users.trades_simulated_0001, users.monitor_list_0001,
users.strategy_list_0001.

Usage:
  PYTHONPATH=$(pwd) python3 scripts/db/check_db_schema_drift.py

Uses the same parsing as scripts/db/audit_db_schema.py (doc and database.py). Does not
connect to the database.
"""

import os
import sys
import importlib.util

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # scripts/db -> project root
sys.path.insert(0, REPO_ROOT)

# Reuse parsing from audit script (load by path so scripts need not be a package)
_audit_path = os.path.join(SCRIPT_DIR, 'audit_db_schema.py')
_spec = importlib.util.spec_from_file_location('audit_db_schema', _audit_path)
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)
parse_doc_schema = _audit.parse_doc_schema
parse_database_py = _audit.parse_database_py
normalize_type_for_compare = _audit.normalize_type_for_compare

CRITICAL_TABLES = [
    'users.trades_0001',
    'users.trades_simulated_0001',
    'users.monitor_list_0001',
    'users.strategy_list_0001',
]


def main():
    doc_path = os.path.join(REPO_ROOT, 'docs', 'MASTER_DB_SCHEMA_REFERENCE.md')
    db_py_path = os.path.join(REPO_ROOT, 'backend', 'core', 'config', 'database.py')

    if not os.path.exists(doc_path):
        print(f"Reference doc not found: {doc_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(db_py_path):
        print(f"database.py not found: {db_py_path}", file=sys.stderr)
        sys.exit(1)

    doc_schema = parse_doc_schema(doc_path)
    py_schema = parse_database_py(db_py_path)

    failed = []
    for table in CRITICAL_TABLES:
        doc_cols = doc_schema.get(table, [])
        py_cols = py_schema.get(table, [])

        if not doc_cols:
            # Doc has no parsed columns (e.g. trades_simulated uses different format)
            continue
        if not py_cols:
            # database.py does not define this table (e.g. created elsewhere)
            continue

        doc_names = {c['name']: c for c in doc_cols}
        py_names = {c['name']: c for c in py_cols}
        only_doc = set(doc_names) - set(py_names)
        only_py = set(py_names) - set(doc_names)
        mismatches = []
        for name in set(doc_names) & set(py_names):
            doc_t = normalize_type_for_compare(doc_names[name]['type'])
            py_t = normalize_type_for_compare(py_names[name]['type'])
            if doc_t != py_t:
                mismatches.append((name, py_names[name]['type'], doc_names[name]['type']))

        # Fail only on: columns in database.py missing from reference, or type mismatches.
        # Reference may document more columns than database.py (e.g. ALTER-added); that is OK.
        if only_py or mismatches:
            failed.append((table, only_doc, only_py, mismatches))

    if not failed:
        print("OK: database.py matches reference doc for critical tables (with parsed columns).")
        sys.exit(0)

    print("DRIFT: database.py table definitions differ from MASTER_DB_SCHEMA_REFERENCE.md:", file=sys.stderr)
    for table, only_doc, only_py, mismatches in failed:
        print(f"\n  {table}:", file=sys.stderr)
        if only_doc:
            print(f"    In reference only: {sorted(only_doc)}", file=sys.stderr)
        if only_py:
            print(f"    In database.py only: {sorted(only_py)}", file=sys.stderr)
        for name, py_t, doc_t in mismatches:
            print(f"    Type [{name}]: database.py={py_t}  reference={doc_t}", file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
