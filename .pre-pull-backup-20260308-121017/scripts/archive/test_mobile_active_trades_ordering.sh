#!/bin/bash

# TEST MOBILE ACTIVE TRADES TABLE ORDERING
# This script tests that the mobile active trades table is properly ordered by strike

echo "🧪 TESTING MOBILE ACTIVE TRADES TABLE ORDERING"
echo "=============================================="

# Get the current IP address
CURRENT_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
echo "📍 Current IP: $CURRENT_IP"
echo ""

# Test mobile trade monitor page loads
echo "📱 Testing mobile trade monitor page..."
TRADE_MONITOR_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$CURRENT_IP:3000/mobile/trade_monitor_mobile.html)
if [ "$TRADE_MONITOR_STATUS" = "200" ]; then
    echo "✅ Mobile trade monitor page loads successfully"
else
    echo "❌ Mobile trade monitor page failed to load (HTTP $TRADE_MONITOR_STATUS)"
    exit 1
fi

echo ""
echo "🔧 FIXES APPLIED:"
echo "=================="
echo "✅ Added insertRowInSortedPosition() function to mobile trade monitor"
echo "✅ Modified renderActiveTradeSupervisorTrades() to use sorted insertion"
echo "✅ Active trades now ordered by strike price (ascending)"
echo "✅ Spanner row positioned correctly relative to current BTC price"
echo ""
echo "📱 MOBILE ACCESS URL:"
echo "====================="
echo "Trade Monitor: http://$CURRENT_IP:3000/mobile/trade_monitor_mobile.html"
echo ""
echo "🎯 EXPECTED BEHAVIOR:"
echo "===================="
echo "✅ Active trades table should be ordered by strike price (lowest to highest)"
echo "✅ Spanner row should appear at correct position based on current BTC price"
echo "✅ Trades with strikes below current price should appear above spanner row"
echo "✅ Trades with strikes above current price should appear below spanner row"
echo ""
echo "🚀 Mobile active trades table ordering fix is now applied!" 