#!/usr/bin/env bash
# Capture production CPU/RAM baseline via SSH (read-only).
#
# Usage (from repo root):
#   ./scripts/prod/prod_cpu_ram_audit.sh > /tmp/prod_audit.txt
#   ./scripts/prod/prod_cpu_ram_audit.sh | tee docs/perf-audits/prod_audit_$(date -u +%Y%m%dT%H%M%SZ).txt
#
# Requires: scripts/prod/rec_prod_ssh.sh, SSH access to prod (REC_PROD_SSH_HOST).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "${ROOT}/scripts/prod/rec_prod_ssh.sh" 'bash -s' <<'REMOTE'
set -euo pipefail
REPO=/opt/rec_io_server
echo "AUDIT_TIMESTAMP_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "===SECTION:HOST==="
hostname -f 2>/dev/null || hostname
uname -a
uptime
echo "===SECTION:CPU==="
nproc
lscpu 2>/dev/null | egrep '^(Architecture|CPU\(s\)|Model name|Thread|Core|Socket)' || true
grep -m1 'model name' /proc/cpuinfo
echo "===SECTION:LOAD==="
cat /proc/loadavg
vmstat 1 3 2>/dev/null | tail -n +3 || true
echo "===SECTION:MEMORY==="
free -h
egrep '^(MemTotal|MemFree|MemAvailable|SwapTotal|Cached|Active|Inactive|AnonPages)' /proc/meminfo
echo "===SECTION:DISK==="
df -hT / /opt 2>/dev/null || df -hT /
echo "===SECTION:GIT_DEPLOYED==="
cd "$REPO" && git rev-parse HEAD 2>/dev/null && git log -1 --oneline 2>/dev/null
echo "===SECTION:SUPERVISOR==="
supervisorctl -c "$REPO/backend/supervisord.conf" status 2>/dev/null
echo "===SECTION:SUPERVISOR_CHILDREN==="
supervisorctl -c "$REPO/backend/supervisord.conf" status | while read -r line; do
  prog=$(echo "$line" | awk '{print $1}')
  pid=$(echo "$line" | sed -n 's/.*pid \([0-9]*\).*/\1/p')
  [[ -z "$pid" || "$pid" == "0" ]] && continue
  ps -p "$pid" -o rss=,%cpu=,%mem=,etime=,args= 2>/dev/null | while read -r rss cpu mem et args; do
    rss_mb=$(awk -v r="$rss" 'BEGIN{printf "%.1f", r/1024}')
    printf "%-38s pid=%-8s rss_mb=%7s cpu=%5.1f mem=%4.1f%% etime=%s\n" "$prog" "$pid" "$rss_mb" "$cpu" "$mem" "$et"
  done
done | sort -t= -k3 -nr
echo "===SECTION:BY_SCRIPT==="
supervisorctl -c "$REPO/backend/supervisord.conf" status | while read -r line; do
  prog=$(echo "$line" | awk '{print $1}')
  pid=$(echo "$line" | sed -n 's/.*pid \([0-9]*\).*/\1/p')
  [[ -z "$pid" || "$pid" == "0" ]] && continue
  ps -p "$pid" -o rss=,%cpu=,args= 2>/dev/null | while read -r rss cpu args; do
    script=$(echo "$args" | sed -n 's|.*/backend/\([^ ]*\).*|\1|p')
    rss_mb=$(awk -v r="$rss" 'BEGIN{printf "%.1f", r/1024}')
    printf "%s\t%s\t%s\t%s\t%s\n" "$script" "$prog" "$rss_mb" "$cpu" "$args"
  done
done | sort
echo "===SECTION:GROUP_TOTALS==="
ps -eo rss,%cpu,args | awk '/market_watchdog_ws/ {rss+=$1;cpu+=$2;n++} END {printf "market_watchdog_ws rss_mb=%.1f cpu_sum=%.1f count=%d\n", rss/1024, cpu, n+0}'
ps -eo rss,%cpu,args | awk '/strike_table_generator_ws/ {rss+=$1;cpu+=$2;n++} END {printf "strike_table_generator_ws rss_mb=%.1f cpu_sum=%.1f count=%d\n", rss/1024, cpu, n+0}'
ps -eo rss,%cpu,args | awk '/symbol_price_watchdog/ {rss+=$1;cpu+=$2;n++} END {printf "symbol_price_watchdog rss_mb=%.1f cpu_sum=%.1f count=%d\n", rss/1024, cpu, n+0}'
ps -eo rss,%cpu,args | awk '/\/opt\/rec_io_server/ && /python/ {rss+=$1;cpu+=$2;n++} END {printf "python_rec_io_total rss_mb=%.1f cpu_sum=%.1f count=%d\n", rss/1024, cpu, n+0}'
echo "===SECTION:REDIS==="
redis-cli INFO memory 2>/dev/null | egrep '^(used_memory_human|used_memory_rss_human|used_memory_peak_human|mem_fragmentation_ratio|total_system_memory_human)' || true
redis-cli DBSIZE 2>/dev/null || true
echo "===SECTION:POSTGRES==="
sudo -u postgres psql -d rec_io_db -tAc "SELECT version();" 2>/dev/null | head -1 || true
sudo -u postgres psql -d rec_io_db -tAc "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database();" 2>/dev/null || true
sudo -u postgres psql -d rec_io_db -tAc "SELECT state, count(*) FROM pg_stat_activity WHERE datname=current_database() GROUP BY 1 ORDER BY 2 DESC;" 2>/dev/null || true
sudo -u postgres psql -d rec_io_db -tAc "SELECT pg_size_pretty(pg_database_size(current_database()));" 2>/dev/null || true
ps -eo rss,cmd | awk '/postgres/ && /rec_io/ {s+=$1;n++} END {printf "postgres_rec_io_backends rss_mb=%.1f count=%d\n", (s+0)/1024, n+0}'
echo "===SECTION:TOP_CPU==="
ps -eo pid,rss,%cpu,etime,args --sort=-%cpu | head -16
echo "===SECTION:END==="
REMOTE
