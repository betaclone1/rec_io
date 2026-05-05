/**
 * Trade Monitor NEW: monitor picker, market header, TradingView, read_api orderbook URL.
 * Left-column spot and %% changes: Postgres → redis_switchboard → `/ws/db_changes` (`live_symbol_spot`), handled in orderbook-redis-ui.js.
 */
(function () {
  /** Set from GET /api/monitors/names `user_id` so localStorage keys are scoped to the logged-in tenant. */
  let tmNewMonitorListUserId = '';
  let tmNewMonitorsMetaById = new Map();
  let tmNewMonitors = [];

  let tmNewTradingModeLiveLabel = 'LIVE';
  let tmNewTradingModePaperLabel = 'PAPER';
  let tmNewMonitorDetailCache = {
    paper_trade: false,
    test_filter: false,
    regime_monitor_enabled: false,
    regime_window: '30d',
    bankroll_allotment_total: null,
    auto_trade: false,
  };
  let tmNewPrefsWsUnsub = null;
  let tmNewMonitorListRefreshTimer = null;

  function tmNewPreferencesWsUrl() {
    var base = tmNewMainApiBase();
    var u;
    try {
      u = new URL(base + '/');
    } catch (e) {
      u = new URL((window.location.origin || '') + '/');
    }
    var wsProto = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return wsProto + '//' + u.host + '/ws/preferences';
  }

  function recTenantMatchesMessageTenant(msgTenant) {
    if (msgTenant == null || msgTenant === '') return true;
    if (typeof recSessionUserSlot !== 'function') return true;
    var slot = recSessionUserSlot();
    if (!slot) return true;
    var mt = String(msgTenant).trim();
    if (!/^\d+$/.test(mt)) return true;
    while (mt.length < 4) mt = '0' + mt;
    if (mt.length > 4) mt = mt.slice(-4);
    return mt === slot;
  }

  function recMonitorIdBelongsToSession(monRaw) {
    if (typeof recSessionUserSlot !== 'function') return true;
    var slot = recSessionUserSlot();
    if (!slot) return true;
    var s = String(monRaw || '').replace(/^MON_/i, 'mon_');
    var m = /^mon_(\d{4})_/.exec(s);
    if (!m) return true;
    return m[1] === slot;
  }

  function splitTradingModeLabel(label) {
    var s = String(label || '').trim();
    var idx = s.indexOf(' - ');
    if (idx !== -1) {
      return { mode: s.slice(0, idx).trim(), name: s.slice(idx + 3).trim() };
    }
    idx = s.indexOf('-');
    if (idx !== -1) {
      return {
        mode: s.slice(0, idx).trim(),
        name: s.slice(idx + 1).replace(/^\s*/, '').trim(),
      };
    }
    return { mode: s, name: '' };
  }

  function tmNewUpdateAccountDisplay() {
    var modeEl = document.getElementById('tmNewAccountMode');
    var sepEl = document.getElementById('tmNewAccountSep');
    var nameEl = document.getElementById('tmNewAccountName');
    if (!modeEl) return;
    var tm = (window.__recTradingMode || localStorage.getItem('rec_trading_mode') || 'live').toLowerCase();
    if (tm !== 'paper' && tm !== 'live') tm = 'live';
    var isLive = tm === 'live';
    var label = isLive ? tmNewTradingModeLiveLabel : tmNewTradingModePaperLabel;
    var parts = splitTradingModeLabel(label);
    modeEl.textContent = parts.mode;
    modeEl.className = 'trading-mode-mode ' + (isLive ? 'trading-mode-mode--live' : 'trading-mode-mode--paper');
    if (sepEl && nameEl) {
      if (parts.name) {
        sepEl.textContent = ' - ';
        nameEl.textContent = parts.name;
      } else {
        sepEl.textContent = '';
        nameEl.textContent = '';
      }
    }
  }

  async function tmNewFetchTradingModeFromServer() {
    try {
      var r = await tmNewApiFetch('/api/trading_mode', { cache: 'no-store' });
      if (!r.ok) return;
      var j = await r.json();
      if (j.trading_mode === 'live' || j.trading_mode === 'paper') {
        window.__recTradingMode = j.trading_mode;
        window.globalPaperMode = j.global_paper_mode === true;
        localStorage.setItem('rec_trading_mode', j.trading_mode);
        if (j.live_label) tmNewTradingModeLiveLabel = j.live_label;
        if (j.paper_label) tmNewTradingModePaperLabel = j.paper_label;
        tmNewUpdateAccountDisplay();
        tmNewSyncPaperToggleUi();
      }
    } catch (e) {}
  }

  function tmNewFormatBankrollCents(cents) {
    if (cents == null || cents === '') return '—';
    var n = Number(cents);
    if (!isFinite(n)) return '—';
    var dollars = n / 100;
    return (
      '$' +
      dollars.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    );
  }

  function tmNewUpdateBankrollFromMonitor(monitor) {
    var el = document.getElementById('tmNewMonitorBankroll');
    if (!el || !monitor) return;
    if (monitor.bankroll_allotment_total !== undefined && monitor.bankroll_allotment_total !== null) {
      el.textContent = tmNewFormatBankrollCents(monitor.bankroll_allotment_total);
    } else {
      el.textContent = '—';
    }
  }

  function tmNewRegimePaperToggleTooltip() {
    if (window.globalPaperMode === true) return 'Global Paper Trading Mode';
    if (tmNewMonitorDetailCache.regime_monitor_enabled)
      return 'Regime monitor controls LIVE/PAPER';
    if (tmNewMonitorDetailCache.test_filter) return 'Test filter monitor is paper-only';
    return '';
  }

  function tmNewSyncPaperToggleVisual(paperTrade) {
    var toggle = document.getElementById('tmNewPaperTradeToggle');
    if (!toggle) return;
    if (paperTrade) {
      toggle.classList.remove('live-mode');
      toggle.classList.add('paper-mode');
    } else {
      toggle.classList.remove('paper-mode');
      toggle.classList.add('live-mode');
    }
  }

  function tmNewSyncPaperToggleUi() {
    var toggle = document.getElementById('tmNewPaperTradeToggle');
    if (!toggle) return;
    var gp = window.globalPaperMode === true;
    var re = tmNewMonitorDetailCache.regime_monitor_enabled === true;
    var tf = tmNewMonitorDetailCache.test_filter === true;
    var locked = gp || re || tf;
    toggle.style.pointerEvents = locked ? 'none' : '';
    toggle.style.opacity = locked ? '0.55' : '';
    toggle.style.cursor = locked ? 'not-allowed' : '';
    var tip = tmNewRegimePaperToggleTooltip();
    toggle.title = tip || '';
    tmNewSyncPaperToggleVisual(!!tmNewMonitorDetailCache.paper_trade);
  }

  function tmNewNumericFromBackendMonitorId(raw) {
    var s = String(raw || '');
    var m = /^MON_(\d{4})_(\d+)$/i.exec(s);
    if (m) return m[2];
    m = /^mon_(\d{4})_(\d+)$/i.exec(s);
    if (m) return m[2];
    if (/^\d+$/.test(s)) return s;
    return '';
  }

  /** Tile id for unified auto-trade modal (matches dashboard `mon_<slot>_<id>`). */
  function tmNewUnifiedTileId() {
    var num = window.currentMonitorId;
    if (num == null || num === '') return '';
    var slot = typeof recSessionUserSlot === 'function' ? recSessionUserSlot() : '';
    var s = String(slot || '').trim();
    while (s.length < 4) s = '0' + s;
    if (s.length > 4) s = s.slice(-4);
    return 'mon_' + s + '_' + String(num);
  }

  function tmNewInstallUnifiedAutoTradeHooks() {
    window.__uatMonitorLookup = function (tileId) {
      var expected = tmNewUnifiedTileId();
      if (!expected) return null;
      if (String(tileId) !== String(expected)) {
        var apiNum = tmNewNumericFromBackendMonitorId(tileId);
        if (!apiNum || String(apiNum) !== String(window.currentMonitorId)) return null;
      }
      var mid = String(window.currentMonitorId || '');
      var meta = tmNewMonitorsMetaById.get(mid) || {};
      var mkt = (document.body.dataset.currentMarket || meta.market || '15m').toString();
      if (mkt !== 'hourly' && mkt !== '15m') mkt = '15m';
      var strat = (document.body.dataset.currentMonitorStrategy || meta.strategy || '').toString();
      return {
        id: expected,
        strategy: strat,
        market: mkt,
        test_filter: tmNewMonitorDetailCache.test_filter,
        paper_trade: tmNewMonitorDetailCache.paper_trade,
        regime_monitor_enabled: tmNewMonitorDetailCache.regime_monitor_enabled,
        regime_window: tmNewMonitorDetailCache.regime_window || '30d',
      };
    };
    window.__uatAfterSaveSuccess = function (tileId, payload /* , monitorObj */) {
      if (payload && payload.regime_monitor_enabled !== undefined) {
        tmNewMonitorDetailCache.regime_monitor_enabled = !!payload.regime_monitor_enabled;
      }
      if (payload && payload.regime_window != null && String(payload.regime_window).trim() !== '') {
        tmNewMonitorDetailCache.regime_window = String(payload.regime_window).trim();
      }
      if (payload && payload.test_filter !== undefined) {
        tmNewMonitorDetailCache.test_filter = !!payload.test_filter;
      }
      if (payload && payload.test_filter) {
        tmNewMonitorDetailCache.paper_trade = true;
      }
      tmNewSyncPaperToggleUi();
      tmNewScheduleMonitorRefreshFromDb();
    };
  }

  function tmNewApplyMonitorAccountFields(monitor) {
    if (!monitor) return;
    tmNewMonitorDetailCache.paper_trade = !!(
      monitor.paper_trade === true ||
      monitor.paper_trade === 'true' ||
      monitor.paper_trade === 1
    );
    tmNewMonitorDetailCache.test_filter = !!(
      monitor.test_filter === true ||
      monitor.test_filter === 'true' ||
      monitor.test_filter === 1
    );
    tmNewMonitorDetailCache.regime_monitor_enabled = !!(
      monitor.regime_monitor_enabled === true ||
      monitor.regime_monitor_enabled === 'true' ||
      monitor.regime_monitor_enabled === 1
    );
    if (monitor.regime_window != null && String(monitor.regime_window).trim() !== '') {
      tmNewMonitorDetailCache.regime_window = String(monitor.regime_window).trim();
    }
    tmNewMonitorDetailCache.bankroll_allotment_total = monitor.bankroll_allotment_total;
    tmNewMonitorDetailCache.auto_trade = !!(
      monitor.auto_trade === true ||
      monitor.auto_trade === 'true' ||
      monitor.auto_trade === 1 ||
      monitor.autoTrade === true
    );
    tmNewUpdateBankrollFromMonitor(monitor);
    tmNewSyncPaperToggleUi();
    tmNewSyncAutoTradeToggleUi();
  }

  function tmNewSyncAutoTradeToggleUi() {
    var el = document.getElementById('tmNewAutoTradeToggle');
    if (!el) return;
    var on = !!tmNewMonitorDetailCache.auto_trade;
    el.classList.toggle('active', on);
    el.classList.remove('disabled');
    el.setAttribute('aria-checked', on ? 'true' : 'false');
    if (document.body && document.body.dataset) {
      document.body.dataset.tmNewAutoTradeOn = on ? '1' : '0';
    }
    if (typeof window.tmNewSyncTtcClockChrome === 'function') {
      try {
        window.tmNewSyncTtcClockChrome();
      } catch (e) {}
    }
  }

  async function tmNewToggleAutoTrade() {
    var mid = window.currentMonitorId;
    if (mid == null || mid === '') return;
    var slot = typeof recSessionUserSlot === 'function' ? recSessionUserSlot() : '';
    if (!slot) return;
    var formattedMonitorId = 'MON_' + slot + '_' + String(mid);

    var toggle = document.getElementById('tmNewAutoTradeToggle');
    if (!toggle || toggle.classList.contains('disabled')) return;

    var prev = !!tmNewMonitorDetailCache.auto_trade;
    var next = !prev;
    tmNewMonitorDetailCache.auto_trade = next;
    tmNewSyncAutoTradeToggleUi();

    try {
      var response = await tmNewApiFetch('/api/monitor/toggle-auto-trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          monitor_id: formattedMonitorId,
          auto_trade: next,
        }),
      });
      var data = await response.json();
      if (data.status !== 'ok') {
        tmNewMonitorDetailCache.auto_trade = prev;
        tmNewSyncAutoTradeToggleUi();
      }
    } catch (e) {
      tmNewMonitorDetailCache.auto_trade = prev;
      tmNewSyncAutoTradeToggleUi();
    }
  }

  function tmNewWireAutoTradeToggle() {
    var toggle = document.getElementById('tmNewAutoTradeToggle');
    if (!toggle) return;
    toggle.addEventListener('click', function () {
      void tmNewToggleAutoTrade();
    });
    toggle.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        void tmNewToggleAutoTrade();
      }
    });
  }

  function tmNewWireAutoTradeSettingsGear() {
    var btn = document.getElementById('tmNewAutoTradeSettingsBtn');
    if (!btn || btn._tmSettingsTipWired) return;
    btn._tmSettingsTipWired = true;

    btn.addEventListener('click', function () {
      var tid = tmNewUnifiedTileId();
      if (!tid) {
        alert('Select a monitor first.');
        return;
      }
      if (typeof window.openUnifiedAutoTradeSettings !== 'function') {
        console.warn('[tm-new] openUnifiedAutoTradeSettings not loaded');
        return;
      }
      void window.openUnifiedAutoTradeSettings(tid);
    });
  }

  /** Regime flag for LIVE/PAPER lock: from existing GET /api/monitors (dashboard-shaped list), not main.py changes. */
  async function tmNewHydrateRegimeFromMonitorsList() {
    var num = window.currentMonitorId;
    if (num == null || num === '') return;
    var slot = typeof recSessionUserSlot === 'function' ? recSessionUserSlot() : '';
    if (!slot) return;
    var needle = 'mon_' + slot + '_' + String(num);
    try {
      var r = await tmNewApiFetch('/api/monitors', { cache: 'no-store' });
      if (!r.ok) return;
      var j = await r.json();
      if (!j || j.status !== 'ok' || !Array.isArray(j.monitors)) return;
      var row = j.monitors.find(function (m) {
        return m && String(m.id) === needle;
      });
      if (!row) return;
      tmNewMonitorDetailCache.regime_monitor_enabled = !!(
        row.regime_monitor_enabled === true ||
        row.regime_monitor_enabled === 'true' ||
        row.regime_monitor_enabled === 1
      );
      tmNewSyncPaperToggleUi();
    } catch (e) {}
  }

  async function tmNewTogglePaperTrade() {
    var mid = window.currentMonitorId;
    if (mid == null || mid === '') return;
    if (window.globalPaperMode === true) return;
    if (tmNewMonitorDetailCache.regime_monitor_enabled) return;
    if (tmNewMonitorDetailCache.test_filter) return;

    var slot = typeof recSessionUserSlot === 'function' ? recSessionUserSlot() : '';
    if (!slot) return;
    var numericId = String(mid);
    var formattedMonitorId = 'MON_' + slot + '_' + numericId;

    var currentPaper = !!tmNewMonitorDetailCache.paper_trade;
    var newPaper = !currentPaper;

    tmNewMonitorDetailCache.paper_trade = newPaper;
    tmNewSyncPaperToggleVisual(newPaper);

    try {
      var response = await tmNewApiFetch('/api/monitor/toggle-paper-trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          monitor_id: formattedMonitorId,
          paper_trade: newPaper,
        }),
      });
      var data = await response.json();
      if (data.status !== 'ok') {
        tmNewMonitorDetailCache.paper_trade = currentPaper;
        tmNewSyncPaperToggleVisual(currentPaper);
      }
    } catch (e) {
      tmNewMonitorDetailCache.paper_trade = currentPaper;
      tmNewSyncPaperToggleVisual(currentPaper);
    }
    tmNewSyncPaperToggleUi();
  }

  function tmNewWirePaperToggle() {
    var toggle = document.getElementById('tmNewPaperTradeToggle');
    if (!toggle) return;
    toggle.addEventListener('click', function () {
      void tmNewTogglePaperTrade();
    });
    toggle.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        void tmNewTogglePaperTrade();
      }
    });
  }

  function tmNewScheduleMonitorRefreshFromDb() {
    if (tmNewMonitorListRefreshTimer) clearTimeout(tmNewMonitorListRefreshTimer);
    tmNewMonitorListRefreshTimer = setTimeout(function () {
      tmNewMonitorListRefreshTimer = null;
      var id = window.currentMonitorId;
      if (id != null && id !== '') void loadMonitorById(id);
    }, 450);
  }

  /**
   * Redis ``publish_preferences_event`` sends ``{ type, data: { ... }, tenant_user_no }``;
   * main_app toggle broadcasts are flat. Merge inner ``data`` so handlers read one shape.
   */
  function tmNewNormalizePreferencesWsMessage(raw) {
    if (!raw || typeof raw !== 'object') return raw;
    var inner = raw.data;
    if (inner != null && typeof inner === 'object' && !Array.isArray(inner)) {
      var merged = Object.assign({}, raw);
      delete merged.data;
      Object.keys(inner).forEach(function (k) {
        if (merged[k] === undefined) merged[k] = inner[k];
      });
      return merged;
    }
    return raw;
  }

  /** Apply ``auto_trade_status`` / ``cooldown_timer`` from a prefs WS (or toggle) payload into meta + TTC when this monitor is selected. */
  function tmNewApplyAutoTradeFanoutFieldsMonitorNum(numStr, msg) {
    if (!numStr) return false;
    var prevM = tmNewMonitorsMetaById.get(String(numStr)) || {
      auto_trade_status: 'inactive',
      cooldown_timer: 0,
      strategy: '',
      market: '15m',
    };
    var patch = {};
    if (msg.auto_trade_status != null && String(msg.auto_trade_status).trim() !== '') {
      patch.auto_trade_status = String(msg.auto_trade_status).trim().toLowerCase();
    }
    if (msg.cooldown_timer != null && msg.cooldown_timer !== '' && !isNaN(Number(msg.cooldown_timer))) {
      patch.cooldown_timer = Math.max(0, Math.floor(Number(msg.cooldown_timer)));
    }
    if (Object.keys(patch).length === 0) return false;
    tmNewMonitorsMetaById.set(String(numStr), Object.assign({}, prevM, patch));
    if (String(window.currentMonitorId) !== String(numStr)) return true;
    tmNewApplyMonitorStateToBody(tmNewMonitorsMetaById.get(String(numStr)));
    if (typeof window.tmNewSyncTtcClockChrome === 'function') {
      try {
        window.tmNewSyncTtcClockChrome();
      } catch (e) {}
    }
    return true;
  }

  function tmNewConnectPreferencesWs() {
    if (tmNewPrefsWsUnsub) return;
    if (!window.recRealtimeWsCoordinator || typeof window.recRealtimeWsCoordinator.subscribe !== 'function') {
      return;
    }
    var url = tmNewPreferencesWsUrl();
    tmNewPrefsWsUnsub = window.recRealtimeWsCoordinator.subscribe(url, {
      onMessage: function (event) {
        try {
          var data = tmNewNormalizePreferencesWsMessage(JSON.parse(event.data));
          if (data.trading_mode === 'live' || data.trading_mode === 'paper') {
            window.__recTradingMode = data.trading_mode;
            window.globalPaperMode =
              data.global_paper_mode === true || data.trading_mode === 'paper';
            localStorage.setItem('rec_trading_mode', data.trading_mode);
            void tmNewFetchTradingModeFromServer();
            return;
          }
          if (data.type === 'paper_trade_toggled') {
            if (!recTenantMatchesMessageTenant(data.tenant_user_no) && !recMonitorIdBelongsToSession(data.monitor_id)) {
              return;
            }
            var num = tmNewNumericFromBackendMonitorId(data.monitor_id);
            if (num && String(window.currentMonitorId) === String(num)) {
              tmNewMonitorDetailCache.paper_trade = !!data.paper_trade;
              tmNewSyncPaperToggleUi();
            }
            return;
          }
          if (data.type === 'auto_trade_toggled') {
            if (!recTenantMatchesMessageTenant(data.tenant_user_no) && !recMonitorIdBelongsToSession(data.monitor_id)) {
              return;
            }
            var numAt = tmNewNumericFromBackendMonitorId(data.monitor_id);
            if (numAt && String(window.currentMonitorId) === String(numAt)) {
              tmNewMonitorDetailCache.auto_trade = !!data.auto_trade;
              tmNewApplyAutoTradeFanoutFieldsMonitorNum(String(numAt), data);
              tmNewSyncAutoTradeToggleUi();
            }
            return;
          }
          if (data.type === 'auto_trade_status_change') {
            if (!recMonitorIdBelongsToSession(data.monitor_id)) {
              return;
            }
            var numCh = tmNewNumericFromBackendMonitorId(data.monitor_id);
            if (!numCh) return;
            tmNewApplyAutoTradeFanoutFieldsMonitorNum(String(numCh), data);
            return;
          }
          if (data.type === 'monitor_list_updated') {
            if (!recTenantMatchesMessageTenant(data.tenant_user_no)) return;
            tmNewScheduleMonitorRefreshFromDb();
          }
        } catch (e2) {}
      },
    });
  }

  function tmNewMainApiBase() {
    var o =
      typeof window !== 'undefined' &&
      window.__TM_NEW_API_ORIGIN__ &&
      String(window.__TM_NEW_API_ORIGIN__).trim();
    if (o) return String(o).replace(/\/$/, '');
    return (window.location.origin || '').replace(/\/$/, '');
  }

  /**
   * Main-app `/api/*` (monitors, etc.). Same-origin: normal fetch (rec_session patches).
   * Cross-origin static dev tab: Bearer + `user_id` query for WebTenantMiddleware (see main CORS allowlist).
   */
  function tmNewApiFetch(path, init) {
    init = init || {};
    if (init.credentials === undefined) init.credentials = 'include';
    var pageOrigin = window.location.origin;
    var base = tmNewMainApiBase();
    var pathNorm = path.charAt(0) === '/' ? path : '/' + path;
    var full = base + pathNorm;
    var target = new URL(full, pageOrigin);
    if (target.origin === pageOrigin) {
      return fetch(full, init);
    }
    var token = '';
    try {
      token = (localStorage.getItem('rec_auth_token') || '').trim();
    } catch (e) {}
    var headers = new Headers(init.headers || undefined);
    if (token) headers.set('Authorization', 'Bearer ' + token);
    init.headers = headers;
    var slot = typeof recSessionUserSlot === 'function' ? recSessionUserSlot() : '';
    if (slot) target.searchParams.set('user_id', 'user_' + slot);
    return fetch(target.toString(), init);
  }

  function selectedMonitorStorageKey() {
    var u = tmNewMonitorListUserId && String(tmNewMonitorListUserId).trim();
    if (!u) u = 'anon';
    return 'tmNewSelectedMonitorId:' + u;
  }

  /** Same contract as other shell tabs: rec_session + rec_user_no (tenant slot). */
  function tradeMonitorHasShellSession() {
    try {
      var token = (localStorage.getItem('rec_auth_token') || '').trim();
      if (!token) return false;
      if (typeof recSessionUserSlot !== 'function') return false;
      return !!recSessionUserSlot();
    } catch (e) {
      return false;
    }
  }

  /** Stored by login / index shell so static tabs can link to the real handoff origin. */
  function tradeMonitorStoredMainAppOrigin() {
    try {
      var raw = (localStorage.getItem('rec_io_main_app_origin') || '').trim();
      if (!raw) return '';
      var u = new URL(raw);
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return '';
      return u.origin;
    } catch (e) {
      return '';
    }
  }

  function tradeMonitorStandaloneHandoffHref(mainOrigin) {
    if (!mainOrigin) return '';
    try {
      return new URL('/tabs/trade_monitor_NEW_standalone_handoff.html', mainOrigin).href;
    } catch (e) {
      return '';
    }
  }

  /**
   * If embedded in index.html, missing session sends the whole app to login.
   * Standalone tab (e.g. static dev): show #loadErr only, no top redirect.
   */
  function tradeMonitorRequireSessionOrBail() {
    if (tradeMonitorHasShellSession()) return true;
    var err = document.getElementById('loadErr');
    if (err) {
      var mainOrigin = tradeMonitorStoredMainAppOrigin();
      var handoffHref = tradeMonitorStandaloneHandoffHref(mainOrigin);
      err.replaceChildren();
      var s0 = document.createElement('strong');
      s0.textContent = 'No session on this origin.';
      err.appendChild(s0);
      err.appendChild(
        document.createTextNode(
          ' Browser storage is per site: localhost and 127.0.0.1 are different sites, and a static dev port (for example :8091) does not see the login from your main app.'
        )
      );
      err.appendChild(document.createElement('br'));
      err.appendChild(document.createElement('br'));
      var s1 = document.createElement('strong');
      s1.textContent = 'Same port as the app: ';
      err.appendChild(s1);
      var loginA = document.createElement('a');
      loginA.href = '/login';
      loginA.textContent = 'Sign in at /login';
      err.appendChild(loginA);
      err.appendChild(
        document.createTextNode(
          ' on this origin, or open Trade Monitor from the sidebar and use the ⧉ new tab link (same origin as the shell).'
        )
      );
      err.appendChild(document.createElement('br'));
      err.appendChild(document.createElement('br'));
      var s2 = document.createElement('strong');
      s2.textContent = 'Static UI on another port: ';
      err.appendChild(s2);
      err.appendChild(
        document.createTextNode(
          'while logged in on the main app, open the session handoff page and use Open in new tab: '
        )
      );
      if (handoffHref) {
        var ho = document.createElement('a');
        ho.href = handoffHref;
        ho.target = '_blank';
        ho.rel = 'noopener noreferrer';
        ho.textContent = handoffHref;
        err.appendChild(ho);
      } else {
        var code = document.createElement('code');
        code.textContent =
          'open /tabs/trade_monitor_NEW_standalone_handoff.html on the same host and port as after login';
        err.appendChild(code);
      }
      err.appendChild(document.createTextNode('.'));
      err.classList.remove('u-hidden');
    }
    if (window.self !== window.top) {
      window.top.location.href = '/login';
    }
    return false;
  }

  window.addEventListener('message', function (ev) {
    try {
      if (ev.origin !== window.location.origin) return;
      var d = ev.data;
      if (!d || d.type !== 'rec-tab-session-context') return;
      if (typeof recSyncAuthCookie === 'function') recSyncAuthCookie();
    } catch (e) {
      /* ignore */
    }
  });

  function symbolMapTv(sym) {
    const normalized = (sym || '').toString().trim().toUpperCase();
    const m = {
      BTC: 'COINBASE:BTCUSD',
      ETH: 'COINBASE:ETHUSD',
      SPX: 'SPX500',
      NDX: 'NDX',
      SOL: 'COINBASE:SOLUSD',
    };
    return m[normalized] || 'COINBASE:' + normalized + 'USD';
  }

  function updateTradingViewSymbol(symbol) {
    const normalized = (symbol || '').toString().trim().toUpperCase();
    if (!normalized) return;
    if (!window.tvWidget) return;
    try {
      window.tvWidget.setSymbol(symbolMapTv(normalized));
    } catch (e) {
      console.error('[TradingView] setSymbol failed', e);
    }
  }

  window.updateTradingViewSymbol = updateTradingViewSymbol;

  function forceReloadTradingViewWidget(symbol) {
    if (typeof TradingView === 'undefined' || !TradingView.widget) return;
    const normalized = (symbol || 'BTC').toString().trim().toUpperCase() || 'BTC';
    const mount = document.getElementById('tradingview_12345');
    if (!mount) return;
    try {
      if (window.tvWidget && typeof window.tvWidget.remove === 'function') {
        window.tvWidget.remove();
      }
    } catch (e) {}
    window.tvWidget = null;
    mount.innerHTML = '';
    const tradingViewSymbol = symbolMapTv(normalized);
    window.tvWidget = new TradingView.widget({
      width: '100%',
      height: '309',
      symbol: tradingViewSymbol,
      interval: '1',
      timezone: 'America/New_York',
      theme: 'dark',
      style: '1',
      locale: 'en',
      toolbar_bg: '#f1f3f6',
      'scalesProperties.textColor': '#FFFFFF',
      backgroundColor: '#1e2733',
      enable_publishing: false,
      hide_top_toolbar: true,
      hide_legend: true,
      save_image: false,
      disabled_features: ['volume_force_overlay', 'create_volume_indicator_by_default'],
      studies: [],
      container_id: 'tradingview_12345',
    });
  }

  /**
   * Keep a single TradingView iframe: create once, then setSymbol only when the asset changes.
   * Full reload on every monitor refresh (e.g. rec:tm-db-monitor-list) was reloading the widget for minutes.
   */
  function tmNewSyncTradingViewAfterMonitorApply(sym, prevSym) {
    if (typeof TradingView === 'undefined' || !TradingView.widget) return;
    if (!window.tvWidget) {
      forceReloadTradingViewWidget(sym);
      return;
    }
    if (prevSym !== sym) {
      updateTradingViewSymbol(sym);
    }
  }

  window.initializeTradingViewWidget = function (symbol) {
    const sym = (symbol || 'BTC').toString().trim().toUpperCase() || 'BTC';
    if (typeof TradingView === 'undefined' || !TradingView.widget) return;
    if (!window.tvWidget) {
      forceReloadTradingViewWidget(sym);
      return;
    }
    updateTradingViewSymbol(sym);
  };

  function marketShort(m) {
    if (m === '15m') return '15m';
    if (m === 'hourly') return 'Hourly';
    return '—';
  }

  function tmNewApplyMonitorStateToBody(meta) {
    const st = meta && meta.auto_trade_status != null ? String(meta.auto_trade_status).trim().toLowerCase() : '';
    const cdRaw = meta && meta.cooldown_timer != null ? Number(meta.cooldown_timer) : 0;
    const cd = Number.isFinite(cdRaw) && cdRaw > 0 ? Math.floor(cdRaw) : 0;
    document.body.dataset.currentAutoTradeStatus = st || 'inactive';
    document.body.dataset.currentCooldownTimer = String(cd);
  }

  function monitorOptionLabel(m) {
    const sid = m.id != null ? String(m.id) : '';
    const sym = (m.symbol || '—').toString().trim();
    const mk = marketShort(m.market);
    const strat = (m.strategy || '—').toString().trim() || '—';
    return [sid, sym, mk, strat].join(' \u2022 ');
  }

  function monitorIconSpec(symbol) {
    const s = (symbol || 'BTC').toString().trim().toUpperCase() || 'BTC';
    const dir = '/images/symbol_icons/';
    const bySym = {
      BTC: { cls: 'mkt-icon--btc', imgSrc: dir + 'bitcoin_icon.jpeg', alt: 'Bitcoin' },
      ETH: { cls: 'mkt-icon--eth', imgSrc: dir + 'etherium_icon.jpeg', alt: 'Ethereum' },
      SOL: { cls: 'mkt-icon--sol', imgSrc: dir + 'solana_icon.jpeg', alt: 'Solana' },
      XRP: { cls: 'mkt-icon--xrp', imgSrc: dir + 'xripple_icon.jpeg', alt: 'XRP' },
    };
    const spec = bySym[s];
    if (spec) return spec;
    return { cls: 'mkt-icon--other', ch: s.slice(0, 2), alt: s };
  }

  function applyMonitorIconToElement(el, symbol) {
    if (!el || !el.classList.contains('mkt-icon')) return;
    el.classList.remove('mkt-icon--btc', 'mkt-icon--eth', 'mkt-icon--sol', 'mkt-icon--xrp', 'mkt-icon--other');
    const spec = monitorIconSpec(symbol);
    el.classList.add(spec.cls);
    el.replaceChildren();
    if (spec.imgSrc) {
      const img = document.createElement('img');
      img.src = spec.imgSrc;
      img.alt = spec.alt != null ? String(spec.alt) : '';
      img.draggable = false;
      img.className = 'mkt-icon-img';
      img.loading = 'lazy';
      el.appendChild(img);
    } else {
      el.textContent = spec.ch || '';
    }
  }

  /** 44px tile: raster icons for BTC/ETH/SOL/XRP; glyph fallback for other symbols. */
  function tmNewApplyMarketHeaderIcon(symbol) {
    const el = document.getElementById('mktIcon');
    if (!el) return;
    const sym = (symbol || 'BTC').toString().trim().toUpperCase() || 'BTC';
    if (el.dataset.tmHeaderSymbol === sym) return;
    el.dataset.tmHeaderSymbol = sym;
    applyMonitorIconToElement(el, sym);
    const img = el.querySelector('img.mkt-icon-img');
    if (img) img.loading = 'eager';
  }

  window.tmNewApplyMarketHeaderIcon = tmNewApplyMarketHeaderIcon;

  function setOrderbookApiUrl(symbol, market) {
    const sym = (symbol || 'BTC').toString().trim().toUpperCase() || 'BTC';
    const mkt = (market === 'hourly' ? 'hourly' : '15m').toString().trim().toLowerCase();
    var qs =
      '/api/trade-monitor/orderbook?symbol=' +
      encodeURIComponent(sym) +
      '&market=' +
      encodeURIComponent(mkt);
    var readPort = window.__READ_API_PORT__;
    if (readPort === undefined || readPort === null || readPort === '') {
      readPort = 3050;
    }
    var proto = window.location.protocol || 'http:';
    var host = window.location.hostname || 'localhost';
    var locPort = String(window.location.port || '');
    if (locPort === String(readPort)) {
      window.__ORDERBOOK_API__ = window.location.origin + qs;
    } else {
      window.__ORDERBOOK_API__ = proto + '//' + host + ':' + String(readPort) + qs;
    }
  }

  function setHeaderDropdownOpen(isOpen) {
    const head = document.getElementById('mktHeadTrigger');
    const dd = document.getElementById('tmNewMonitorDropdown');
    if (!head || !dd) return;
    const open = !!isOpen;
    dd.classList.toggle('is-open', open);
    dd.setAttribute('aria-hidden', open ? 'false' : 'true');
    head.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function syncHeaderDropdownActive(monitorId) {
    const list = document.getElementById('tmNewMonitorDropdownList');
    if (!list) return;
    const want = String(monitorId || '');
    const nodes = list.querySelectorAll('[data-monitor-id]');
    let activeNode = null;
    nodes.forEach(function (el) {
      const active = String(el.getAttribute('data-monitor-id') || '') === want;
      el.classList.toggle('is-active', active);
      el.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active) activeNode = el;
    });
    if (activeNode && typeof activeNode.scrollIntoView === 'function') {
      activeNode.scrollIntoView({ block: 'nearest' });
    }
  }

  /** Fill `tmNewStrikeMarketTitle` from `/api/postgresql/strike_table` (deduped by symbol + market). */
  async function hydrateTmNewMonitorMarketTitles(monitors) {
    if (!monitors || !monitors.length) return;
    const pairKeys = [];
    const seen = Object.create(null);
    monitors.forEach(function (m) {
      const sym = (m.symbol || 'BTC').toString().trim().toUpperCase() || 'BTC';
      const mkt = m.market === 'hourly' ? 'hourly' : '15m';
      const key = sym + '\u0000' + mkt;
      if (seen[key]) return;
      seen[key] = true;
      pairKeys.push({ sym: sym, mkt: mkt, key: key });
    });
    const titleByKey = Object.create(null);
    await Promise.all(
      pairKeys.map(function (p) {
        return (async function () {
          let title = '';
          try {
            const res = await tmNewApiFetch(
              '/api/postgresql/strike_table/' +
                encodeURIComponent(p.sym.toLowerCase()) +
                '?market=' +
                encodeURIComponent(p.mkt === 'hourly' ? 'hourly' : '15m'),
              { cache: 'no-store' }
            );
            const data = await res.json();
            if (res.ok && data && !data.error && data.market_title != null) {
              const t = String(data.market_title).trim();
              if (t) title = t;
            }
          } catch (e) {
            title = '';
          }
          titleByKey[p.key] = title;
        })();
      })
    );
    monitors.forEach(function (m) {
      const sym = (m.symbol || 'BTC').toString().trim().toUpperCase() || 'BTC';
      const mkt = m.market === 'hourly' ? 'hourly' : '15m';
      const key = sym + '\u0000' + mkt;
      const t = titleByKey[key] || '';
      m.tmNewStrikeMarketTitle = t;
    });
  }

  function renderHeaderMonitorDropdown() {
    const list = document.getElementById('tmNewMonitorDropdownList');
    if (!list) return;
    list.innerHTML = '';
    tmNewMonitors.forEach(function (m) {
      const id = m && m.id != null ? String(m.id) : '';
      if (!id) return;
      const sym = (m.symbol || '—').toString().trim().toUpperCase() || '—';
      const mkLabel = marketShort(m.market);
      const strat = (m.strategy || '—').toString().trim() || '—';
      const title = sym + ' ' + mkLabel + ' \u2022 ' + strat;
      const mt =
        m.tmNewStrikeMarketTitle != null && String(m.tmNewStrikeMarketTitle).trim() !== ''
          ? String(m.tmNewStrikeMarketTitle).trim()
          : '';
      const fallbackName = (m.name != null ? String(m.name).trim() : '') || '';
      const subtitle = id + ' \u2022 ' + (mt || fallbackName || '—');
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'tm-new-monitor-option';
      row.setAttribute('role', 'option');
      row.setAttribute('data-monitor-id', id);
      row.setAttribute('aria-selected', 'false');

      const iconEl = document.createElement('div');
      iconEl.className = 'mkt-icon';
      iconEl.setAttribute('aria-hidden', 'true');
      applyMonitorIconToElement(iconEl, sym);

      const textEl = document.createElement('div');
      textEl.className = 'tm-new-monitor-option-text';
      const titleEl = document.createElement('p');
      titleEl.className = 'tm-new-monitor-option-title';
      titleEl.textContent = title;
      const subEl = document.createElement('p');
      subEl.className = 'tm-new-monitor-option-subtitle';
      subEl.textContent = subtitle;
      textEl.appendChild(titleEl);
      textEl.appendChild(subEl);

      row.appendChild(iconEl);
      row.appendChild(textEl);

      row.addEventListener('click', function () {
        localStorage.setItem(selectedMonitorStorageKey(), id);
        const picker = document.getElementById('monitor-picker');
        if (picker) picker.value = id;
        setHeaderDropdownOpen(false);
        void loadMonitorById(id);
      });

      list.appendChild(row);
    });
  }

  async function applyMonitorPayload(monitor) {
    if (!monitor) return;
    const prevSym = (document.body.dataset.currentSymbol || '').toString().trim().toUpperCase();
    const sym = (monitor.symbol || '').toString().trim().toUpperCase() || 'BTC';
    let mkt = monitor.market;
    if (mkt !== '15m' && mkt !== 'hourly') mkt = '15m';

    document.body.dataset.currentSymbol = sym;
    document.body.dataset.currentMarket = mkt;
    const meta = tmNewMonitorsMetaById.get(String(monitor.id || '')) || null;
    const stratRaw =
      monitor.strategy != null && String(monitor.strategy).trim() !== ''
        ? String(monitor.strategy).trim()
        : (meta && meta.strategy) || '';
    document.body.dataset.currentMonitorStrategy = stratRaw || '—';
    const monitorNumber = monitor.id != null ? String(monitor.id).trim() : '';
    document.body.dataset.currentMonitorNumber = monitorNumber || '—';
    const tTitle = document.getElementById('mktTitle');
    const tWin = document.getElementById('mktWindow');
    const mkLabel = marketShort(mkt);
    if (tTitle) tTitle.textContent = sym + ' ' + mkLabel + ' \u2022 ' + document.body.dataset.currentMonitorStrategy;
    if (tWin) tWin.textContent = document.body.dataset.currentMonitorNumber + ' \u2022';
    tmNewApplyMarketHeaderIcon(sym);
    window.currentMarket = mkt;
    window.currentMonitorId = monitor.id;
    window.currentMonitorName = monitor.name != null ? String(monitor.name).trim() : null;
    tmNewApplyMonitorStateToBody(meta);
    syncHeaderDropdownActive(monitor.id);
    tmNewApplyMonitorAccountFields(monitor);
    void tmNewHydrateRegimeFromMonitorsList();

    const hiddenSym = document.getElementById('ticker-picker');
    if (hiddenSym) {
      hiddenSym.innerHTML = '';
      const opt = document.createElement('option');
      opt.value = sym;
      opt.textContent = sym;
      hiddenSym.appendChild(opt);
      hiddenSym.value = sym;
    }

    setOrderbookApiUrl(sym, mkt);
    try {
      window.dispatchEvent(
        new CustomEvent('rec:tm-monitor-changed', {
          detail: { symbol: sym, market: mkt, monitorId: monitor.id },
        })
      );
    } catch (e) {}

    setTimeout(function () {
      tmNewSyncTradingViewAfterMonitorApply(sym, prevSym);
    }, 100);
    if (typeof window.tmNewRefreshLiveSpotPanel === 'function') {
      window.tmNewRefreshLiveSpotPanel();
    }
  }

  async function loadMonitorById(monitorId) {
    let res;
    try {
      res = await tmNewApiFetch('/api/monitor/' + encodeURIComponent(String(monitorId)), {
        credentials: 'include',
      });
    } catch (e) {
      console.error('[tm-new] monitor fetch failed', e);
      return;
    }
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (e) {
      console.error('[tm-new] monitor response not JSON', e);
      return;
    }
    if (!res.ok || !data || data.status !== 'ok' || !data.monitor) {
      const msg =
        (data && (data.detail || data.message)) || 'HTTP ' + res.status;
      console.error('[tm-new] monitor load failed', msg, data);
      return;
    }
    await applyMonitorPayload(data.monitor);
  }

  function tmNewMonitorMetaEntryFromRow(m) {
    return {
      auto_trade_status:
        m && m.auto_trade_status != null ? String(m.auto_trade_status).trim().toLowerCase() : 'inactive',
      cooldown_timer: Number(m && m.cooldown_timer != null ? m.cooldown_timer : 0) || 0,
      strategy: m && m.strategy != null ? String(m.strategy).trim() : '',
      market: m && m.market === 'hourly' ? 'hourly' : '15m',
    };
  }

  async function populateTmNewMonitorPicker() {
    const picker = document.getElementById('monitor-picker');
    if (!picker) return false;
    picker.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select monitor…';
    picker.appendChild(placeholder);

    let res;
    try {
      res = await tmNewApiFetch('/api/monitors/names', { credentials: 'include' });
    } catch (e) {
      console.error('[tm-new] monitors/names fetch failed', e);
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'Network error loading monitors';
      picker.appendChild(opt);
      return false;
    }

    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (e) {
      console.error('[tm-new] monitors/names: response is not JSON', e);
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'Invalid response from server';
      picker.appendChild(opt);
      return false;
    }

    if (!res.ok) {
      const msg =
        (data && (data.detail || data.message)) ||
        (res.status === 401
          ? 'Not authenticated - open this tab from the app after signing in'
          : 'HTTP ' + res.status);
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = msg;
      picker.appendChild(opt);
      return false;
    }

    if (!data || data.status !== 'ok' || !Array.isArray(data.monitors)) {
      const msg =
        (data && (data.message || data.detail)) || 'Unexpected response from monitors/names';
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = msg;
      picker.appendChild(opt);
      return false;
    }

    tmNewMonitorListUserId =
      data.user_id != null && String(data.user_id).trim() !== ''
        ? String(data.user_id).trim()
        : '';

    tmNewMonitorsMetaById = new Map();
    tmNewMonitors = data.monitors.slice();
    data.monitors.forEach(function (m) {
      tmNewMonitorsMetaById.set(String(m.id), tmNewMonitorMetaEntryFromRow(m));
      const option = document.createElement('option');
      option.value = String(m.id);
      if (m.market === '15m' || m.market === 'hourly') option.dataset.market = m.market;
      if (m.symbol) option.dataset.symbol = m.symbol;
      if (m.strategy != null) option.dataset.strategy = m.strategy;
      option.dataset.autoTradeStatus =
        m && m.auto_trade_status != null ? String(m.auto_trade_status).trim().toLowerCase() : 'inactive';
      option.dataset.cooldownTimer = String(Number(m && m.cooldown_timer != null ? m.cooldown_timer : 0) || 0);
      option.textContent = monitorOptionLabel(m);
      picker.appendChild(option);
    });
    try {
      await hydrateTmNewMonitorMarketTitles(tmNewMonitors);
    } catch (e) {
      console.error('[tm-new] hydrate monitor market titles failed', e);
    }
    renderHeaderMonitorDropdown();

    if (data.monitors.length === 0) {
      return true;
    }

    const stored = localStorage.getItem(selectedMonitorStorageKey());
    const exists = data.monitors.some(function (x) {
      return String(x.id) === String(stored);
    });
    const pickId = exists ? stored : String(data.monitors[0].id);
    picker.value = pickId;
    await loadMonitorById(pickId);
    return true;
  }

  function wireMonitorPicker() {
    const picker = document.getElementById('monitor-picker');
    if (!picker) return;
    picker.addEventListener('change', function () {
      const id = picker.value;
      if (!id) return;
      localStorage.setItem(selectedMonitorStorageKey(), id);
      void loadMonitorById(id);
    });
  }

  function wireHeaderMonitorDropdown() {
    const head = document.getElementById('mktHeadTrigger');
    const dropdown = document.getElementById('tmNewMonitorDropdown');
    if (!head || !dropdown) return;

    head.addEventListener('click', function () {
      const open = dropdown.classList.contains('is-open');
      setHeaderDropdownOpen(!open);
    });

    head.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        const open = dropdown.classList.contains('is-open');
        setHeaderDropdownOpen(!open);
      } else if (ev.key === 'Escape') {
        setHeaderDropdownOpen(false);
      }
    });

    document.addEventListener('click', function (ev) {
      if (!dropdown.classList.contains('is-open')) return;
      const target = ev.target;
      if (!(target instanceof Node)) return;
      if (head.contains(target) || dropdown.contains(target)) return;
      setHeaderDropdownOpen(false);
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') setHeaderDropdownOpen(false);
    });
  }

  function wireDiffModeToggle() {
    const diffModeToggle = document.getElementById('diffModeToggle');
    if (!diffModeToggle) return;
    function updateDiffModeDisplay(isDiffMode) {
      const diffText = document.getElementById('diffText');
      const priceText = document.getElementById('priceText');
      if (diffText && priceText) {
        if (isDiffMode) {
          diffText.style.opacity = '1';
          priceText.style.opacity = '0.2';
        } else {
          diffText.style.opacity = '0.2';
          priceText.style.opacity = '1';
        }
      }
    }
    updateDiffModeDisplay(!!window.diffMode);
    diffModeToggle.addEventListener('click', function () {
      const newValue = !window.diffMode;
      window.diffMode = newValue;
      updateDiffModeDisplay(newValue);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    tmNewInstallUnifiedAutoTradeHooks();
    wireMonitorPicker();
    wireHeaderMonitorDropdown();
    wireDiffModeToggle();
    window.diffMode = true;
    tmNewWirePaperToggle();
    tmNewWireAutoTradeToggle();
    tmNewWireAutoTradeSettingsGear();
    document.addEventListener('rec:tm-db-monitor-list', function () {
      tmNewScheduleMonitorRefreshFromDb();
    });
    try {
      var st = localStorage.getItem('rec_trading_mode');
      if (st === 'paper' || st === 'live') window.__recTradingMode = st;
      else window.__recTradingMode = window.__recTradingMode || 'live';
      if (typeof window.globalPaperMode !== 'boolean') window.globalPaperMode = false;
    } catch (e) {
      window.__recTradingMode = 'live';
    }
    tmNewUpdateAccountDisplay();
    (async function () {
      if (!tradeMonitorRequireSessionOrBail()) {
        return;
      }
      void tmNewFetchTradingModeFromServer();
      tmNewConnectPreferencesWs();
      try {
        await populateTmNewMonitorPicker();
      } catch (e) {
        console.error('[tm-new] populate monitors failed', e);
      }
    })();
  });
})();
