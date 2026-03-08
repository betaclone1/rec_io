# Diagnostic: Login / SSL outage 2026-02-17

## What happened (past hour)

- **Desktop and mobile browsers:** "Your connection is not private" – `NET::ERR_CERT_DATE_INVALID`
- **WebView app:** Would not work (same cert error)
- **Incognito (after bypassing cert):** Login page reloaded repeatedly and would not accept text input

## Root causes

### 1. SSL certificate expired (fixed)

- **Nginx** was using `/etc/letsencrypt/live/rec-io.com-0001/` for SSL.
- That certificate **expired 2026-02-17 at 16:57 UTC** (about 1 hour before the report).
- A **valid** certificate exists at `/etc/letsencrypt/live/rec-io.com/` (valid until 2026-04-18).

**Fix applied:** Nginx config was updated to use the valid cert:

- `ssl_certificate` and `ssl_certificate_key` in `/etc/nginx/sites-available/rec-io-wildcard` now point to `rec-io.com` (not `rec-io.com-0001`).
- Nginx was reloaded. HTTPS should work again.

**Next time:** Before the **rec-io.com** cert expires (Apr 18, 2026), renew with:

```bash
sudo certbot renew
sudo systemctl reload nginx
```

Or set up a cron job for `certbot renew` (e.g. twice daily). Ensure nginx keeps using a cert path that certbot updates (e.g. keep using `rec-io.com` and renew that name).

### 2. Login page: `pointer-events: none` (fixed)

- `.form-group` had `pointer-events: none` again, which breaks focus/typing in WebViews and can contribute to odd behavior in browsers.
- **Fix applied:** Removed `pointer-events: none` from `.form-group` in `frontend/login.html`.

### 3. Login page: redirect loop risk (mitigated)

- If a user had a stale token in localStorage and `checkAuthStatus` redirected to `/app`, and the server then redirected back to `/login`, the page could loop.
- **Fix applied:** `authCheckDone` flag so we only redirect once per load; `checkAuthStatus` delay increased to 500 ms.

## URL typo in screenshot

The address bar showed `deviceld` (letter "l") instead of `deviceId`. If that typo exists in a bookmark or app, the auth redirect would be wrong. Correct query param is `deviceId`.

## Checklist for future cert outages

1. Check which cert nginx uses: `grep ssl_certificate /etc/nginx/sites-available/rec-io-wildcard`
2. Check expiry: `sudo openssl x509 -in /etc/letsencrypt/live/<name>/fullchain.pem -noout -dates`
3. If expired, either switch nginx to another valid cert (e.g. `rec-io.com` if `rec-io.com-0001` expired) or run `sudo certbot renew` then reload nginx.
4. Ensure `frontend/LOGIN_WEBVIEW_RULES.md` is followed so login stays usable in WebView.
