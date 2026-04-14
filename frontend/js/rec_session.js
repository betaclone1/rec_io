/**
 * Same-origin /api/, /trades, and /ws/: attach session token and tenant hints.
 * WebSocket auth uses HttpOnly-style pattern via first-party cookie rec_auth_token
 * (set from JS, sent automatically on same-origin upgrades).
 * Load before other scripts that call fetch() or WebSocket to those paths.
 */
(function () {
  var COOKIE_NAME = 'rec_auth_token';
  var SEC_MAX_REMEMBER = 30 * 24 * 3600;
  var SEC_SESSION = 24 * 3600;

  function recSessionUserSlot() {
    var s = window.localStorage.getItem('rec_user_no');
    s = s ? String(s).trim() : '';
    return /^\d{4}$/.test(s) ? s : '';
  }

  function recSessionUserId() {
    var slot = recSessionUserSlot();
    return slot ? 'user_' + slot : '';
  }

  window.recSessionUserSlot = recSessionUserSlot;
  window.recSessionUserId = recSessionUserId;

  function recClearAuthCookie() {
    var secure = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie =
      COOKIE_NAME + '=; path=/; max-age=0; SameSite=Lax' + secure;
  }

  /**
   * Mirror localStorage session token into a first-party cookie so same-origin
   * WebSocket handshakes include Cookie (query ?token= is unreliable).
   * @param {boolean|undefined} rememberDevice If omitted, uses localStorage rec_remember_device.
   */
  function recSyncAuthCookie(rememberDevice) {
    var token = window.localStorage.getItem('rec_auth_token');
    if (!token || !String(token).trim()) {
      recClearAuthCookie();
      return;
    }
    var remember =
      rememberDevice === true ||
      (rememberDevice !== false &&
        window.localStorage.getItem('rec_remember_device') === '1');
    var maxAge = remember ? SEC_MAX_REMEMBER : SEC_SESSION;
    var secure = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie =
      COOKIE_NAME +
      '=' +
      encodeURIComponent(String(token).trim()) +
      '; path=/; max-age=' +
      maxAge +
      '; SameSite=Lax' +
      secure;
  }

  window.recClearAuthCookie = recClearAuthCookie;
  window.recSyncAuthCookie = recSyncAuthCookie;

  recSyncAuthCookie();

  var origFetch = window.fetch;

  function pathNeedsSessionPatch(pathname) {
    if (pathname.startsWith('/api/')) return true;
    if (pathname === '/trades' || pathname.startsWith('/trades/')) return true;
    return false;
  }

  function patchApiUrl(urlString) {
    var token = window.localStorage.getItem('rec_auth_token');
    var userNo = recSessionUserSlot();
    var u = new URL(urlString, window.location.origin);
    if (u.origin !== window.location.origin || !pathNeedsSessionPatch(u.pathname)) {
      return null;
    }
    if (userNo) {
      u.searchParams.set('user_id', 'user_' + userNo);
    }
    var headers = new Headers();
    if (token) {
      headers.set('Authorization', 'Bearer ' + token);
    }
    return { url: u.toString(), headers: headers };
  }

  function patchJsonBody(init) {
    var userNo = recSessionUserSlot();
    if (!userNo || !init || typeof init.body !== 'string') {
      return init;
    }
    var t = init.body.trim();
    if (!t || t.charAt(0) !== '{') {
      return init;
    }
    try {
      var o = JSON.parse(init.body);
      if (!o || typeof o !== 'object' || Array.isArray(o)) {
        return init;
      }
      if (!Object.prototype.hasOwnProperty.call(o, 'user_id')) {
        return init;
      }
      o.user_id = 'user_' + userNo;
      var next = Object.assign({}, init);
      next.body = JSON.stringify(o);
      return next;
    } catch (e) {
      return init;
    }
  }

  window.fetch = function (input, init) {
    try {
      if (typeof input === 'string') {
        var hit = patchApiUrl(input);
        if (!hit) {
          return origFetch.apply(this, arguments);
        }
        init = init ? Object.assign({}, init) : {};
        init = patchJsonBody(init);
        var headers = new Headers(init.headers || undefined);
        hit.headers.forEach(function (v, k) {
          headers.set(k, v);
        });
        init.headers = headers;
        return origFetch.call(this, hit.url, init);
      }
      if (typeof Request !== 'undefined' && input instanceof Request) {
        var hitR = patchApiUrl(input.url);
        if (!hitR) {
          return origFetch.apply(this, arguments);
        }
        init = init ? Object.assign({}, init) : {};
        var headersR = new Headers(input.headers);
        hitR.headers.forEach(function (v, k) {
          headersR.set(k, v);
        });
        var nextReq = new Request(hitR.url, {
          method: input.method,
          headers: headersR,
          body: input.body,
          mode: input.mode,
          credentials: input.credentials,
          cache: input.cache,
          redirect: input.redirect,
          referrer: input.referrer,
          referrerPolicy: input.referrerPolicy,
          integrity: input.integrity,
          keepalive: input.keepalive,
          signal: (init && init.signal) || input.signal,
        });
        return origFetch.call(this, nextReq, init);
      }
    } catch (e) {
      return origFetch.apply(this, arguments);
    }
    return origFetch.apply(this, arguments);
  };

  if (typeof WebSocket !== 'undefined') {
    var OrigWS = WebSocket;
    window.WebSocket = function (url, protocols) {
      var out = url;
      if (typeof url === 'string') {
        try {
          var abs = new URL(url, window.location.origin);
          if (abs.origin === window.location.origin && abs.pathname.indexOf('/ws/') === 0) {
            abs.searchParams.delete('token');
            out = abs.toString();
          }
        } catch (e2) {
          out = url;
        }
      }
      // Auth: Cookie rec_auth_token (recSyncAuthCookie). Do not use Sec-WebSocket-Protocol for
      // the session token; long custom subprotocol values break handshakes (1006).
      return protocols !== undefined ? new OrigWS(out, protocols) : new OrigWS(out);
    };
    window.WebSocket.prototype = OrigWS.prototype;
    window.WebSocket.CONNECTING = OrigWS.CONNECTING;
    window.WebSocket.OPEN = OrigWS.OPEN;
    window.WebSocket.CLOSING = OrigWS.CLOSING;
    window.WebSocket.CLOSED = OrigWS.CLOSED;
  }
})();
