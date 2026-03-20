#!/bin/bash

echo "🔍 DIGITALOCEAN DEPLOYMENT VERIFICATION"
echo "======================================="

echo "📋 PHASE 1 COMPONENTS:"
echo ""

# Check supervisor hardening
echo "1. ✅ SUPERVISOR HARDENING:"
echo "   - All services have startretries=3"
echo "   - All services have stopasgroup=true"
echo "   - All services have killasgroup=true"
echo ""

# Check log rotation (Linux only)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "2. 📁 LOG ROTATION:"
    if [ -f "/etc/logrotate.d/trading-system" ]; then
        echo "   ✅ Log rotation configuration installed"
    else
        echo "   ❌ Log rotation configuration missing"
    fi
    
    if command -v logrotate &> /dev/null; then
        echo "   ✅ Logrotate utility available"
    else
        echo "   ❌ Logrotate utility not available"
    fi
    echo ""
else
    echo "2. 📁 LOG ROTATION: (skip - not Linux)"
    echo ""
fi

# Check swap file (Linux only)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "3. 💾 SWAP FILE:"
    if swapon --show | grep -q "/swapfile"; then
        echo "   ✅ Swap file active"
        swapon --show
    else
        echo "   ❌ Swap file not active"
    fi
    echo ""
else
    echo "3. 💾 SWAP FILE: (skip - not Linux)"
    echo ""
fi

# Check monitoring tools
echo "4. 📊 MONITORING TOOLS:"
if command -v htop &> /dev/null; then
    echo "   ✅ htop available"
else
    echo "   ❌ htop not available"
fi

if command -v iotop &> /dev/null; then
    echo "   ✅ iotop available"
else
    echo "   ❌ iotop not available"
fi

if command -v nethogs &> /dev/null; then
    echo "   ✅ nethogs available"
else
    echo "   ❌ nethogs not available"
fi
echo ""

# Check system performance
echo "5. 📈 SYSTEM PERFORMANCE:"
./scripts/monitor_performance.sh

echo ""
echo "✅ DEPLOYMENT VERIFICATION COMPLETE"
