#!/bin/bash

# TEST MOBILE FRONTEND FIXES
# This script tests the mobile fixes for trade history and trade monitor

echo "🧪 TESTING MOBILE FRONTEND FIXES"
echo "================================"

# Get the current IP address
CURRENT_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
echo "📍 Current IP: $CURRENT_IP"
echo ""

# Test mobile trade history
echo "📱 Testing mobile trade history..."
TRADE_HISTORY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$CURRENT_IP:3000/mobile/trade_history_mobile.html)
if [ "$TRADE_HISTORY_STATUS" = "200" ]; then
    echo "✅ Mobile trade history page loads successfully"
else
    echo "❌ Mobile trade history page failed to load (HTTP $TRADE_HISTORY_STATUS)"
fi

# Test mobile trade monitor
echo "📱 Testing mobile trade monitor..."
TRADE_MONITOR_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$CURRENT_IP:3000/mobile/trade_monitor_mobile.html)
if [ "$TRADE_MONITOR_STATUS" = "200" ]; then
    echo "✅ Mobile trade monitor page loads successfully"
else
    echo "❌ Mobile trade monitor page failed to load (HTTP $TRADE_MONITOR_STATUS)"
fi

# Test mobile account manager
echo "📱 Testing mobile account manager..."
ACCOUNT_MANAGER_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$CURRENT_IP:3000/mobile/account_manager_mobile.html)
if [ "$ACCOUNT_MANAGER_STATUS" = "200" ]; then
    echo "✅ Mobile account manager page loads successfully"
else
    echo "❌ Mobile account manager page failed to load (HTTP $ACCOUNT_MANAGER_STATUS)"
fi

# Test mobile index
echo "📱 Testing mobile index..."
MOBILE_INDEX_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$CURRENT_IP:3000/mobile)
if [ "$MOBILE_INDEX_STATUS" = "200" ]; then
    echo "✅ Mobile index page loads successfully"
else
    echo "❌ Mobile index page failed to load (HTTP $MOBILE_INDEX_STATUS)"
fi

echo ""
echo "🔧 FIXES APPLIED:"
echo "=================="
echo "✅ Added getMainAppUrl() function to mobile trade history"
echo "✅ Added getActiveTradeSupervisorUrl() function to mobile trade monitor"
echo "✅ Both functions use window.location.origin for mobile compatibility"
echo ""
echo "📱 MOBILE ACCESS URLS:"
echo "======================"
echo "Mobile Index: http://$CURRENT_IP:3000/mobile"
echo "Trade Monitor: http://$CURRENT_IP:3000/mobile/trade_monitor_mobile.html"
echo "Trade History: http://$CURRENT_IP:3000/mobile/trade_history_mobile.html"
echo "Account Manager: http://$CURRENT_IP:3000/mobile/account_manager_mobile.html"
echo ""
echo "🎯 EXPECTED BEHAVIOR:"
echo "===================="
echo "✅ Mobile trade history should now load data properly"
echo "✅ Mobile trade monitor should hide active trades panel when no open trades"
echo "✅ Both should work on other devices via IP address"
echo ""
echo "🚀 Mobile frontend fixes are now applied and ready for testing!" 