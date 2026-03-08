#!/bin/bash

# TEST NETWORK ACCESS FOR TRADING SYSTEM
# Run this script from another device to test connectivity

echo "🧪 TESTING NETWORK ACCESS TO TRADING SYSTEM"
echo "============================================"

# Get the target IP (replace with your Mac's IP)
TARGET_IP="192.168.86.42"

echo "🎯 Testing connection to: $TARGET_IP"
echo ""

# Test ping connectivity
echo "📡 Testing ping connectivity..."
if ping -c 3 $TARGET_IP > /dev/null 2>&1; then
    echo "✅ Ping successful - network connectivity OK"
else
    echo "❌ Ping failed - check network connection"
    exit 1
fi

echo ""

# Test HTTP connectivity to main app
echo "🌐 Testing HTTP connectivity to main app..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$TARGET_IP:3000)
if [ "$HTTP_STATUS" = "200" ]; then
    echo "✅ Main app accessible (HTTP $HTTP_STATUS)"
else
    echo "❌ Main app not accessible (HTTP $HTTP_STATUS)"
fi

# Test trade manager
echo "📊 Testing trade manager..."
TM_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$TARGET_IP:4000)
if [ "$TM_STATUS" = "200" ]; then
    echo "✅ Trade manager accessible (HTTP $TM_STATUS)"
else
    echo "❌ Trade manager not accessible (HTTP $TM_STATUS)"
fi

# Test trade executor
echo "⚡ Testing trade executor..."
TE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$TARGET_IP:8001)
if [ "$TE_STATUS" = "200" ]; then
    echo "✅ Trade executor accessible (HTTP $TE_STATUS)"
else
    echo "❌ Trade executor not accessible (HTTP $TE_STATUS)"
fi

echo ""
echo "🎉 NETWORK ACCESS TEST COMPLETE"
echo "==============================="
echo "📱 If all tests pass, you can access:"
echo "   Main App: http://$TARGET_IP:3000"
echo "   Trade Manager: http://$TARGET_IP:4000"
echo "   Trade Executor: http://$TARGET_IP:8001"
echo ""
echo "🔧 If tests fail:"
echo "   1. Ensure both devices are on the same network"
echo "   2. Check router firewall settings"
echo "   3. Verify the target IP is correct"
echo "   4. Try accessing from a different device" 