/**
 * Trade Monitor NEW: monitor picker, market header, TradingView, read_api orderbook URL.
 * Left-column spot and %% changes: Postgres → redis_switchboard → `/ws/db_changes` (`live_symbol_spot`), handled in orderbook-redis-ui.js.
 */
(function () {
  let tradingViewInitialized = false;
  /** Set from GET /api/monitors/names `user_id` so localStorage keys are scoped to the logged-in tenant. */
  let tmNewMonitorListUserId = '';
  let tmNewMonitorsMetaById = new Map();

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
    const m = {
      BTC: 'COINBASE:BTCUSD',
      ETH: 'COINBASE:ETHUSD',
      SPX: 'SPX500',
      NDX: 'NDX',
      SOL: 'COINBASE:SOLUSD',
    };
    return m[sym] || 'COINBASE:' + sym + 'USD';
  }

  function updateTradingViewSymbol(symbol) {
    if (!window.tvWidget || !symbol) return;
    try {
      window.tvWidget.setSymbol(symbolMapTv(symbol));
    } catch (e) {
      console.error('[TradingView] setSymbol failed', e);
    }
  }

  window.updateTradingViewSymbol = updateTradingViewSymbol;

  window.initializeTradingViewWidget = function (symbol) {
    if (typeof TradingView === 'undefined' || !TradingView.widget) return;
    if (tradingViewInitialized) {
      updateTradingViewSymbol(symbol);
      return;
    }
    const tradingViewSymbol = symbolMapTv(symbol);
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
    tradingViewInitialized = true;
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

  /** Same 44px tile treatment as BTC: glyph + brand background for ETH / SOL / XRP. */
  function tmNewApplyMarketHeaderIcon(symbol) {
    const el = document.getElementById('mktIcon');
    if (!el || !el.classList.contains('mkt-icon')) return;
    const s = (symbol || 'BTC').toString().trim().toUpperCase() || 'BTC';
    el.classList.remove(
      'mkt-icon--btc',
      'mkt-icon--eth',
      'mkt-icon--sol',
      'mkt-icon--xrp',
      'mkt-icon--other'
    );
    const bySym = {
      BTC: { cls: 'mkt-icon--btc', ch: '\u20BF' },
      ETH: { cls: 'mkt-icon--eth', ch: '\u039E' },
      SOL: { cls: 'mkt-icon--sol', ch: 'S' },
      XRP: { cls: 'mkt-icon--xrp', ch: '\u2715' },
    };
    const spec = bySym[s];
    if (spec) {
      el.classList.add(spec.cls);
      el.textContent = spec.ch;
      return;
    }
    el.classList.add('mkt-icon--other');
    el.textContent = s.slice(0, 2);
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

  async function applyMonitorPayload(monitor) {
    if (!monitor) return;
    const sym = (monitor.symbol || '').toString().trim().toUpperCase() || 'BTC';
    let mkt = monitor.market;
    if (mkt !== '15m' && mkt !== 'hourly') mkt = '15m';

    document.body.dataset.currentSymbol = sym;
    document.body.dataset.currentMarket = mkt;
    tmNewApplyMarketHeaderIcon(sym);
    window.currentMarket = mkt;
    window.currentMonitorId = monitor.id;
    window.currentMonitorName = monitor.name != null ? String(monitor.name).trim() : null;
    const meta = tmNewMonitorsMetaById.get(String(monitor.id || '')) || null;
    tmNewApplyMonitorStateToBody(meta);

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

    if (window.initializeTradingViewWidget) {
      setTimeout(function () {
        window.initializeTradingViewWidget(sym);
      }, 50);
    }
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
    data.monitors.forEach(function (m) {
      tmNewMonitorsMetaById.set(String(m.id), {
        auto_trade_status:
          m && m.auto_trade_status != null ? String(m.auto_trade_status).trim().toLowerCase() : 'inactive',
        cooldown_timer: Number(m && m.cooldown_timer != null ? m.cooldown_timer : 0) || 0,
      });
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
    wireMonitorPicker();
    wireDiffModeToggle();
    window.diffMode = true;
    (async function () {
      if (!tradeMonitorRequireSessionOrBail()) {
        return;
      }
      try {
        await populateTmNewMonitorPicker();
      } catch (e) {
        console.error('[tm-new] populate monitors failed', e);
      }
    })();
  });
})();
