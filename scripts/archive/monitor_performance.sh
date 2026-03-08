#!/bin/bash

echo "=== SYSTEM PERFORMANCE MONITOR ==="
echo "Timestamp: $(date)"
echo ""

echo "📊 CPU Usage:"
if command -v top &> /dev/null; then
    top -bn1 | grep "Cpu(s)" | awk '{print "CPU: " $2}' | cut -d'%' -f1
else
    echo "CPU: top command not available"
fi

echo ""
echo "💾 Memory Usage:"
if command -v free &> /dev/null; then
    free -h | grep Mem
else
    echo "Memory: free command not available"
fi

echo ""
echo "💿 Disk Usage:"
if command -v df &> /dev/null; then
    df -h | grep -E "(/$|/home|/Users)"
else
    echo "Disk: df command not available"
fi

echo ""
echo "📁 Log Directory Size:"
if [ -d "logs" ]; then
    du -sh logs/
    echo "Log files count: $(find logs/ -name "*.log" | wc -l)"
else
    echo "Logs directory not found"
fi

echo ""
echo "🔧 Active Services:"
supervisorctl -c backend/supervisord.conf status

echo ""
echo "🌐 Web Interface Status:"
if curl -s http://localhost:3000/ | grep -q "REC.IO"; then
    echo "✅ Web interface responding"
else
    echo "❌ Web interface not responding"
fi

echo ""
echo "📊 Process CPU Usage (Top 5):"
if command -v ps &> /dev/null; then
    ps aux | grep python | grep -v grep | sort -k3 -nr | head -5 | awk '{print $3 "% CPU - " $11}'
else
    echo "Process info not available"
fi

echo ""
echo "🔍 Critical Data Production:"
if [ -d "backend/data" ]; then
    json_count=$(find backend/data -name "*.json" 2>/dev/null | wc -l)
    echo "JSON files in data directory: $json_count"
    
    # Check for recent activity
    recent_files=$(find backend/data -name "*.json" -mtime -1 2>/dev/null | wc -l)
    echo "JSON files modified in last 24h: $recent_files"
else
    echo "Data directory not found"
fi

echo ""
echo "📈 System Load:"
if command -v uptime &> /dev/null; then
    uptime
else
    echo "Load info not available"
fi

echo ""
echo "=== MONITORING COMPLETE ===" 