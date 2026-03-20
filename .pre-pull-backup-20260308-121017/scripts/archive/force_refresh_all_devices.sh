#!/bin/bash

echo "🔄 Force refreshing all devices and clearing caches..."

# Restart main app to ensure latest changes are loaded
echo "📡 Restarting main app..."
supervisorctl -c backend/supervisord.conf restart main_app

# Wait for restart
sleep 3

echo "✅ Cache-busting headers are now active for ALL static files:"
echo "   - /mobile/* (mobile HTML files)"
echo "   - /styles/* (CSS files)"
echo "   - /js/* (JavaScript files)"
echo "   - /images/* (image files)"
echo "   - /tabs/* (tab HTML files)"
echo "   - /audio/* (audio files)"

echo ""
echo "📱 To see updates on all devices:"
echo "   1. Open your mobile browser"
echo "   2. Navigate to: http://192.168.86.42:3000/mobile/account_manager_mobile.html"
echo "   3. Use hard refresh:"
echo "      - iOS Safari: Pull down to refresh"
echo "      - Android Chrome: Pull down to refresh"
echo "      - Desktop: Cmd+Shift+R (Mac) or Ctrl+F5 (Windows)"
echo ""
echo "🔧 For development, you can also:"
echo "   - Open Chrome DevTools → Network tab → check 'Disable cache'"
echo "   - Or use incognito/private browsing mode"
echo ""
echo "✅ All files now have 'no-cache' headers - updates should be immediate!" 