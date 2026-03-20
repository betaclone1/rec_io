---
description: "SSH into production and confirm DB connectivity (list schemas)."
---

# Access prod DB

Use SSH to connect to the **production server** and run a minimal `psql` check. The command should:

1. Confirm it can connect to the PostgreSQL database (`SELECT 1`).
2. Print the visible schemas via `information_schema.schemata`.

**Target:** `ssh root@137.184.224.94`

## Execute on prod

Run the following on the remote host via SSH (single SSH invocation):

```bash
ssh root@137.184.224.94 'set -euo pipefail;
export PGPASSWORD="${REC_DB_PASS:-${DB_PASSWORD:-rec_io_password}}";
export PGSSLMODE="${REC_DB_SSLMODE:-${DB_SSLMODE:-disable}}";
psql \
  -h "${REC_DB_HOST:-${DB_HOST:-localhost}}" \
  -p "${REC_DB_PORT:-${DB_PORT:-5432}}" \
  -U "${REC_DB_USER:-${DB_USER:-rec_io_user}}" \
  -d "${REC_DB_NAME:-${DB_NAME:-rec_io_db}}" \
  -v ON_ERROR_STOP=1 \
  -c "SELECT 1 AS connection_ok;" \
  -c "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name;"'
```

Return output from both queries (connection confirmation and schema list) to the user.
