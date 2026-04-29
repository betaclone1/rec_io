(function () {
  let mode = 'yes';
  let shouldAutoCenter = true;
  let isBookVisible = false;
  let lastMarketMode = '';
  let lastStrikeTableFetchMs = 0;
  let hourlyStrikeRows = [];
  /** Last full strike list from strike-table API (before liquidity filter). */
  let hourlyRawStrikeRows = [];
  /** Hourly pack `current_price`: used only for ATM / liquidity filtering when DOM spot is missing. */
  let hourlyCurrentPrice = null;
  let expandedHourlyTicker = '';
  let lastHourlyRowsSignature = '';
  let lastHourlyStructureSignature = '';
  let lastExpandedOrderbookSignature = '';
  let hourlyLiquidityByTicker = new Map();
  const HOURLY_LIQUIDITY_TTL_MS = 8000;
  let hourlyExpandedStateByTicker = new Map();

  /**
   * Countdown uses only Kalshi ticker → expiration (America/New_York), not DB ttc_* columns.
   * UTC epoch ms; recomputed when marketExpireSourceKey (ticker string) changes.
   */
  let marketExpireAtMs = null;
  let marketExpireSourceKey = '';
  let hourlyHeaderLastFetchSymbol = '';
  let hourlyStrikeTableDbWs = null;
  /** Last `live_symbol_spot` frame (Redis → main `/ws/db_changes`); used when symbol/monitor changes. */
  let lastLiveSymbolSpotMsg = null;

  let tickBusy = false;
  let tickPending = false;

  function setMode(event, next) {
    if (event && typeof event.stopPropagation === 'function') {
      event.stopPropagation();
    }
    mode = next;
    const y = document.getElementById('tabYes');
    const n = document.getElementById('tabNo');
    y.classList.toggle('active', mode === 'yes');
    y.classList.toggle('tab-yes', true);
    n.classList.toggle('active', mode === 'no');
    n.classList.toggle('tab-no', true);
    shouldAutoCenter = true;
    tick();
  }
  window.setMode = setMode;

  function toggleOrderbook() {
    /* Order books are only inside expanded strike rows (15m and hourly use the same layout). */
  }
  window.toggleOrderbook = toggleOrderbook;

  function ensureInitialVisibility() {
    const panel = document.getElementById('bookPanel');
    if (!panel) return;
    isBookVisible = false;
    panel.classList.add('u-hidden');
  }

  function tmMainApiBase() {
    var o =
      typeof window !== 'undefined' &&
      window.__TM_NEW_API_ORIGIN__ &&
      String(window.__TM_NEW_API_ORIGIN__).trim();
    if (o) return String(o).replace(/\/$/, '');
    return (window.location.origin || '').replace(/\/$/, '');
  }

  /** Match ``tmMainApiBase`` host so WS hits the app that forwards Redis (not a static dev origin). */
  function dbChangesWebSocketUrl() {
    var base = tmMainApiBase();
    var u;
    try {
      u = new URL(base + '/');
    } catch (e) {
      u = new URL((window.location.origin || '') + '/');
    }
    var wsProto = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return wsProto + '//' + u.host + '/ws/db_changes';
  }

  function formatTmSpotUsd(val) {
    if (typeof val !== 'number' || isNaN(val)) return '—';
    return (
      '$' +
      val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    );
  }

  function decorateTmPctChangeCell(el, val) {
    if (!el) return;
    const num = parseFloat(val);
    if (isNaN(num)) {
      el.textContent = '—';
      el.style.backgroundColor = '';
      el.style.color = '';
      return;
    }
    const triangle = num >= 0 ? ' ▲' : ' ▼';
    el.textContent = Math.abs(num).toFixed(2) + '%' + triangle;
    el.style.color = '#fff';
    el.style.backgroundColor = num >= 0 ? '#28a745' : '#dc3545';
    el.style.padding = '2px 6px';
    el.style.borderRadius = '4px';
    el.style.display = 'inline-block';
  }

  /**
   * Postgres live_data → NOTIFY → redis_switchboard → Redis → same-origin `/ws/db_changes`.
   * Payload built in ``backend/redis_switchboard.build_live_symbol_spot_payload``.
   */
  function applyLiveSymbolSpotMessage(msg) {
    if (!msg || msg.type !== 'live_symbol_spot') return;
    lastLiveSymbolSpotMsg = msg;
    const rawSpot = msg.spot_by_symbol || {};
    const spotNorm = {};
    Object.keys(rawSpot).forEach(function (k) {
      spotNorm[String(k).trim().toUpperCase()] = rawSpot[k];
    });
    window.__liveSpotBySymbol = spotNorm;
    const rawCh = msg.changes_by_symbol || {};
    const chNorm = {};
    Object.keys(rawCh).forEach(function (k) {
      chNorm[String(k).trim().toUpperCase()] = rawCh[k];
    });
    window.__livePriceChangesBySymbol = chNorm;

    const sym = currentSymbol();

    const elPrice = document.getElementById('symbol-price-value');
    if (elPrice) {
      const sp = spotNorm[sym];
      if (sp != null && !isNaN(Number(sp))) {
        elPrice.textContent = formatTmSpotUsd(Number(sp));
      } else {
        elPrice.textContent = '$—';
      }
    }

    const ch = chNorm[sym] || {};
    decorateTmPctChangeCell(document.getElementById('change-1h'), ch.change1h);
    decorateTmPctChangeCell(document.getElementById('change-3h'), ch.change3h);
    decorateTmPctChangeCell(document.getElementById('change-1d'), ch.change1d);

    try {
      window.dispatchEvent(new CustomEvent('rec:live-symbol-spot', { detail: msg }));
    } catch (e) {}
  }

  window.tmNewRefreshLiveSpotPanel = function () {
    if (lastLiveSymbolSpotMsg) {
      applyLiveSymbolSpotMessage(lastLiveSymbolSpotMsg);
    }
  };

  function tmMainApiFetch(path, init) {
    init = init || {};
    if (init.credentials === undefined) init.credentials = 'include';
    var pageOrigin = window.location.origin;
    var base = tmMainApiBase();
    var pathNorm = path.charAt(0) === '/' ? path : '/' + path;
    var full = base + pathNorm;
    var target = new URL(full, pageOrigin);
    if (target.origin === pageOrigin) return fetch(full, init);
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

  function readApiOriginForTradeMonitor() {
    try {
      if (typeof window.__ORDERBOOK_API__ === 'string' && window.__ORDERBOOK_API__.trim()) {
        return new URL(window.__ORDERBOOK_API__.trim()).origin;
      }
    } catch (e) {}
    var readPort = window.__READ_API_PORT__;
    if (readPort === undefined || readPort === null || readPort === '') readPort = 3050;
    var proto = window.location.protocol || 'http:';
    var host = window.location.hostname || 'localhost';
    return proto + '//' + host + ':' + String(readPort);
  }

  async function fetchLiveSymbolSpotBootstrap() {
    if (!document.body || !document.body.classList.contains('trade-monitor-new-page')) {
      return;
    }
    try {
      var url = readApiOriginForTradeMonitor() + '/api/live_symbol_spot_bootstrap';
      const res = await fetch(url, { credentials: 'include', cache: 'no-store' });
      if (!res.ok) return;
      const msg = await res.json();
      if (msg && msg.type === 'live_symbol_spot') {
        applyLiveSymbolSpotMessage(msg);
      }
    } catch (e) {}
  }

  function trimFracZeros(s) {
    if (!s.includes('.')) return s;
    return s.replace(/\.?0+$/, '');
  }

  function fmtContracts(v) {
    const n = Number(v || 0);
    if (!Number.isFinite(n)) return '0';
    return trimFracZeros(n.toFixed(2));
  }

  function fmtTotalDollars(v) {
    const n = Number(v || 0);
    if (!Number.isFinite(n)) return '$0';
    const [intp, frac] = n.toFixed(2).split('.');
    const intFmt = Number(intp).toLocaleString('en-US');
    const fracTrim = frac.replace(/0+$/, '');
    if (!fracTrim) return '$' + intFmt;
    return '$' + intFmt + '.' + fracTrim;
  }

  function fmtPrice(v) {
    const n = Number(v || 0);
    const cents = n * 100;
    return `${cents.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')}¢`;
  }

  /** Yes/No tab labels: always whole cents (no fractional ¢ from dollar rounding). */
  function fmtWholeCentsFromDollars(dollars) {
    const n = Number(dollars);
    if (!Number.isFinite(n)) return '—';
    const c = Math.round(n * 100);
    return String(c) + '¢';
  }

  function parseDollarField(v) {
    if (v == null || v === '') return null;
    const n = Number(String(v).trim());
    return Number.isFinite(n) ? n : null;
  }

  function rowsToHtml(rows, sideLabel, labelRowIndex) {
    return (rows || [])
      .map((r, i) => {
        const p = Number(r.price || 0);
        const c = Number(r.size_fp || 0);
        const t = Number(r.total_dollars || 0);
        const side = i === labelRowIndex ? sideLabel : '';
        return `<tr><td class="side-col">${side}</td><td>${fmtPrice(p)}</td><td>${fmtContracts(c)}</td><td>${fmtTotalDollars(t)}</td></tr>`;
      })
      .join('');
  }

  function buildMidCellInner(mode, lastTrade) {
    const lt = lastTrade || {};
    const cents = mode === 'yes' ? lt.yes_cents || '' : lt.no_cents || '';
    const side = mode === 'yes' ? 'Trade Yes' : 'Trade No';
    const price = cents || '—';
    return (
      '<span class="mid-inner"><span class="mid-side">' +
      side +
      '</span><span class="mid-gap"></span><span class="mid-last-wrap"><span class="mid-last">Last</span><span class="mid-price">' +
      price +
      '</span></span></span>'
    );
  }

  function centerMidRow() {
    const panel = document.getElementById('bookScroll');
    const mid = document.getElementById('midPrice');
    if (!panel || !mid) return;
    const midTop = mid.offsetTop;
    const target = midTop - panel.clientHeight / 2 + mid.offsetHeight / 2;
    panel.scrollTop = Math.max(0, target);
  }

  function defaultTradeMonitorDbOrderbookUrl() {
    var readPort = window.__READ_API_PORT__;
    if (readPort === undefined || readPort === null || readPort === '') {
      readPort = 3050;
    }
    var proto = window.location.protocol || 'http:';
    var host = window.location.hostname || 'localhost';
    var params = new URLSearchParams(window.location.search || '');
    var sym = (params.get('symbol') || 'BTC').toString().trim().toUpperCase() || 'BTC';
    var mktRaw = (params.get('market') || '15m').toString().trim().toLowerCase();
    var mkt = mktRaw === 'hourly' ? 'hourly' : '15m';
    return (
      proto +
      '//' +
      host +
      ':' +
      String(readPort) +
      '/api/trade-monitor/orderbook?symbol=' +
      encodeURIComponent(sym) +
      '&market=' +
      encodeURIComponent(mkt)
    );
  }

  function orderbookSnapshotUrl() {
    if (typeof window.__ORDERBOOK_API__ === 'string' && window.__ORDERBOOK_API__.trim()) {
      return window.__ORDERBOOK_API__.trim();
    }
    var locPort = String(window.location.port || '');
    var proto = window.location.protocol || 'http:';
    var host = window.location.hostname || 'localhost';
    if (locPort === '8091') {
      if (document.body && document.body.classList.contains('trade-monitor-new-page')) {
        return defaultTradeMonitorDbOrderbookUrl();
      }
      return '/api/orderbook';
    }
    var readPort = window.__READ_API_PORT__;
    if (readPort === undefined || readPort === null || readPort === '') {
      readPort = 3050;
    }
    var readPs = String(readPort);
    if (locPort === readPs) {
      return '/api/orderbook';
    }
    return proto + '//' + host + ':' + readPs + '/api/orderbook';
  }

  function orderbookUrlForTicker(ticker) {
    if (!ticker) return orderbookSnapshotUrl();
    const u = new URL(orderbookSnapshotUrl(), window.location.origin);
    u.searchParams.set('market_ticker', String(ticker));
    return u.toString();
  }

  const KALSHI_MONTH = {
    JAN: 1,
    FEB: 2,
    MAR: 3,
    APR: 4,
    MAY: 5,
    JUN: 6,
    JUL: 7,
    AUG: 8,
    SEP: 9,
    OCT: 10,
    NOV: 11,
    DEC: 12,
  };
  const RE_KALSHI_15M_MID = /^(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d{4})$/i;
  const RE_KALSHI_HOURLY_MID = /^(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d{2})$/i;

  /** Civil date/time in America/New_York → UTC epoch ms (Intl; handles DST). */
  function easternLocalToUtcMs(y, mon, d, h, min) {
    let guess = Date.UTC(y, mon - 1, d, h, min, 0, 0);
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
    for (let i = 0; i < 48; i++) {
      const parts = formatter.formatToParts(new Date(guess));
      const o = {};
      for (let p = 0; p < parts.length; p++) {
        if (parts[p].type !== 'literal') o[parts[p].type] = +parts[p].value;
      }
      if (o.year === y && o.month === mon && o.day === d && o.hour === h && o.minute === min) {
        return guess;
      }
      const targetFake = Date.UTC(y, mon - 1, d, h, min);
      const gotFake = Date.UTC(o.year, o.month - 1, o.day, o.hour, o.minute);
      guess += targetFake - gotFake;
    }
    return guess;
  }

  /** Same rules as backend kalshi_contract_settlement_end_est: 15m = period end; hourly KX*D = settlement wall time in ET (no +1h). */
  function kalshiTickerSettlementEndMs(ticker) {
    if (ticker == null || typeof ticker !== 'string' || ticker.indexOf('-') < 0) return null;
    const parts = ticker.split('-');
    if (parts.length < 2) return null;
    const series = parts[0].toUpperCase();
    const mid = parts[1].toUpperCase();
    if (series.indexOf('15M') >= 0) {
      const m = mid.match(RE_KALSHI_15M_MID);
      if (!m) return null;
      const yy = parseInt(m[1], 10);
      const monAbbr = m[2].toUpperCase();
      const mon = KALSHI_MONTH[monAbbr];
      if (!mon) return null;
      const dd = parseInt(m[3], 10);
      const hhmm = m[4];
      const hh = parseInt(hhmm.slice(0, 2), 10);
      const mm = parseInt(hhmm.slice(2, 4), 10);
      const y = 2000 + yy;
      return easternLocalToUtcMs(y, mon, dd, hh, mm);
    }
    if (/^KX[A-Z0-9]+D$/.test(series)) {
      const m9 = mid.match(RE_KALSHI_HOURLY_MID);
      if (m9) {
        const yy = parseInt(m9[1], 10);
        const mon = KALSHI_MONTH[m9[2].toUpperCase()];
        if (!mon) return null;
        const dd = parseInt(m9[3], 10);
        const hh = parseInt(m9[4], 10);
        const y = 2000 + yy;
        return easternLocalToUtcMs(y, mon, dd, hh, 0);
      }
      const m11 = mid.match(RE_KALSHI_15M_MID);
      if (m11) {
        const yy = parseInt(m11[1], 10);
        const mon = KALSHI_MONTH[m11[2].toUpperCase()];
        if (!mon) return null;
        const dd = parseInt(m11[3], 10);
        const hhmm = m11[4];
        const hh = parseInt(hhmm.slice(0, 2), 10);
        const min = parseInt(hhmm.slice(2, 4), 10);
        const y = 2000 + yy;
        return easternLocalToUtcMs(y, mon, dd, hh, min);
      }
      return null;
    }
    return null;
  }

  function clearMarketExpiration() {
    marketExpireAtMs = null;
    marketExpireSourceKey = '';
  }

  /** First two hyphen segments (series + date/hour token); same contract across strike legs. */
  function kalshiEventRefKey(ticker) {
    const t = (ticker || '').trim();
    if (!t) return '';
    const parts = t.split('-');
    if (parts.length >= 2) return (parts[0] + '-' + parts[1]).toUpperCase();
    return t.toUpperCase();
  }

  function armExpirationFromTicker(refTicker) {
    const t = (refTicker || '').trim();
    if (!t) return false;
    const key = kalshiEventRefKey(t);
    if (key && key === marketExpireSourceKey && marketExpireAtMs != null) return true;
    const ms = kalshiTickerSettlementEndMs(t);
    if (ms == null) return false;
    marketExpireSourceKey = key;
    marketExpireAtMs = ms;
    return true;
  }

  function fmtAmpmNoLeadingZeroEt(utcMs) {
    return new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    }).format(new Date(utcMs));
  }

  function easternTzShortFromMs(utcMs) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      timeZoneName: 'short',
    }).formatToParts(new Date(utcMs));
    for (let i = 0; i < parts.length; i++) {
      if (parts[i].type === 'timeZoneName') return parts[i].value || 'ET';
    }
    return 'ET';
  }

  function monthDayLongEt(utcMs) {
    return new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      month: 'long',
      day: 'numeric',
    }).format(new Date(utcMs));
  }

  /** Same idea as backend _market_window_label_eastern: previous hour → closing (settlement) hour. */
  function hourlyMarketWindowLabelFromTicker(ticker) {
    const endMs = kalshiTickerSettlementEndMs(ticker);
    if (endMs == null) return '';
    const startMs = endMs - 60 * 60 * 1000;
    const md = monthDayLongEt(startMs);
    const a = fmtAmpmNoLeadingZeroEt(startMs);
    const b = fmtAmpmNoLeadingZeroEt(endMs);
    const tz = easternTzShortFromMs(startMs);
    return md + ', ' + a + '\u2013' + b + ' ' + tz;
  }

  function formatTtcClock(totalSeconds) {
    const s = Number(totalSeconds);
    if (!Number.isFinite(s) || s < 0) return '--:--';
    const whole = Math.floor(s);
    const mm = Math.floor(whole / 60);
    const ss = whole % 60;
    return String(mm).padStart(2, '0') + ':' + String(ss).padStart(2, '0');
  }

  function monitorTtcColor() {
    const ds = (document.body && document.body.dataset) || {};
    const cooldown = Number(ds.currentCooldownTimer || 0);
    if (Number.isFinite(cooldown) && cooldown > 0) return '#ef4444';
    const st = String(ds.currentAutoTradeStatus || 'inactive').trim().toLowerCase();
    return st === 'active' ? '#22c55e' : '#facc15';
  }

  function updateMarketHeaderTtc(ttcSeconds) {
    const el = document.getElementById('tmNewTtcClock');
    if (!el) return;
    if (ttcSeconds == null || !Number.isFinite(Number(ttcSeconds))) {
      el.textContent = '--:--';
    } else {
      el.textContent = formatTtcClock(ttcSeconds);
    }
    const c = monitorTtcColor();
    el.style.backgroundColor = 'transparent';
    el.style.borderColor = c;
    el.style.color = '#f3f4f6';
  }

  function applyHeaderTtcToClock() {
    if (marketExpireAtMs == null || !Number.isFinite(marketExpireAtMs)) {
      updateMarketHeaderTtc(null);
      return;
    }
    const sec = Math.max(0, Math.floor((marketExpireAtMs - Date.now()) / 1000));
    updateMarketHeaderTtc(sec);
  }

  function applyStrikePackHeader(pack, market) {
    if (!pack || pack.fetchFailed) return;
    const sym = (pack.headerSymbol || currentSymbol()).toString().trim().toUpperCase() || 'BTC';
    const mt = pack.marketTitle && String(pack.marketTitle).trim();
    const tEl = document.getElementById('mktTitle');
    const wEl = document.getElementById('mktWindow');
    const mktPhrase = market === 'hourly' ? 'hourly' : '15 min';
    if (tEl) tEl.textContent = mt ? sym + ' ' + mktPhrase + ' • ' + mt : sym + ' ' + mktPhrase;
    const ref =
      (pack.rows && pack.rows[0] && pack.rows[0].ticker && String(pack.rows[0].ticker).trim()) ||
      (pack.eventTicker && String(pack.eventTicker).trim()) ||
      '';
    if (wEl) wEl.textContent = ref ? hourlyMarketWindowLabelFromTicker(ref) : '';
    if (ref) {
      armExpirationFromTicker(ref);
    } else {
      clearMarketExpiration();
      updateMarketHeaderTtc(null);
    }
    if (typeof window.tmNewApplyMarketHeaderIcon === 'function') {
      window.tmNewApplyMarketHeaderIcon(sym);
    }
  }

  function currentSymbol() {
    const s =
      (document.body && document.body.dataset && document.body.dataset.currentSymbol) ||
      new URLSearchParams(window.location.search || '').get('symbol') ||
      'BTC';
    return String(s).trim().toUpperCase() || 'BTC';
  }

  function currentMarket() {
    const m =
      (document.body && document.body.dataset && document.body.dataset.currentMarket) ||
      new URLSearchParams(window.location.search || '').get('market') ||
      '15m';
    return String(m).trim().toLowerCase() === 'hourly' ? 'hourly' : '15m';
  }

  async function fetchStrikeTablePack(symbol, market) {
    const empty = {
      rows: [],
      currentPrice: null,
      marketTitle: null,
      ttcSeconds: null,
      settlementEndMs: null,
      eventTicker: null,
      headerSymbol: null,
      fetchFailed: true,
    };
    const mktParam = market === 'hourly' ? 'hourly' : '15m';
    const res = await tmMainApiFetch(
      '/api/postgresql/strike_table/' +
        encodeURIComponent(String(symbol).toLowerCase()) +
        '?market=' +
        encodeURIComponent(mktParam),
      { cache: 'no-store' }
    );
    const data = await res.json();
    if (!res.ok || !data || data.error) {
      return empty;
    }
    const strikesArr = Array.isArray(data.strikes) ? data.strikes : [];
    const cpRaw = data.current_price;
    const currentPrice =
      cpRaw != null && cpRaw !== '' && !isNaN(Number(cpRaw)) ? Number(cpRaw) : null;
    const marketTitle =
      data.market_title != null && String(data.market_title).trim() !== ''
        ? String(data.market_title).trim()
        : null;
    const ttcSeconds =
      data.ttc_seconds != null && data.ttc_seconds !== '' && !isNaN(Number(data.ttc_seconds))
        ? Number(data.ttc_seconds)
        : null;
    const settlementEndMs =
      data.settlement_end_ms != null &&
      data.settlement_end_ms !== '' &&
      !isNaN(Number(data.settlement_end_ms))
        ? Number(data.settlement_end_ms)
        : null;
    const headerSymbol =
      data.symbol != null && String(data.symbol).trim() !== ''
        ? String(data.symbol).trim().toUpperCase()
        : String(symbol).trim().toUpperCase() || 'BTC';
    const eventTicker =
      data.event_ticker != null && String(data.event_ticker).trim() !== ''
        ? String(data.event_ticker).trim()
        : null;
    const rows = strikesArr
      .filter((s) => s && s.ticker)
      .map((s) => ({
        ticker: String(s.ticker),
        strike: s.strike,
        yesAsk: s.yes_ask_dollars,
        noAsk: s.no_ask_dollars,
        buffer: s.buffer,
        bufferPct: s.buffer_pct,
        activeSide: s.active_side,
        probActive: s.probability,
      }))
      .sort((a, b) => Number(a.strike || 0) - Number(b.strike || 0));
    return {
      rows,
      currentPrice,
      marketTitle,
      ttcSeconds,
      settlementEndMs,
      eventTicker,
      headerSymbol,
      fetchFailed: false,
    };
  }

  function hasAsksAndBids(book) {
    if (!book || typeof book !== 'object') return false;
    const asks = Array.isArray(book.asks) ? book.asks : [];
    const bids = Array.isArray(book.bids) ? book.bids : [];
    return asks.length > 0 && bids.length > 0;
  }

  function cacheLiquidity(ticker, ok) {
    hourlyLiquidityByTicker.set(String(ticker), { ok: !!ok, ts: Date.now() });
  }

  function cachedLiquidityFresh(ticker) {
    const row = hourlyLiquidityByTicker.get(String(ticker));
    if (!row) return null;
    if (Date.now() - row.ts > HOURLY_LIQUIDITY_TTL_MS) return null;
    return row.ok;
  }

  async function fetchTickerLiquidityOk(ticker) {
    const cached = cachedLiquidityFresh(ticker);
    if (cached != null) return cached;
    try {
      const res = await fetch(orderbookUrlForTicker(ticker), { cache: 'no-store' });
      const d = await res.json();
      if (!res.ok || !d || d.error) {
        cacheLiquidity(ticker, false);
        return false;
      }
      const ok = hasAsksAndBids(d.trade_yes) && hasAsksAndBids(d.trade_no);
      cacheLiquidity(ticker, ok);
      return ok;
    } catch (e) {
      cacheLiquidity(ticker, false);
      return false;
    }
  }

  async function filterHourlyRowsByLiquidity(rows, spotPrice) {
    if (!Array.isArray(rows) || rows.length === 0) return [];
    const spot =
      spotPrice != null && Number.isFinite(Number(spotPrice)) ? Number(spotPrice) : null;
    const mustTicker = spot != null ? closestStrikeTicker(rows, spot) : '';

    const checks = rows.map((r) => fetchTickerLiquidityOk(r.ticker));
    const oks = await Promise.all(checks);
    const out = [];
    const outTickers = new Set();
    for (let i = 0; i < rows.length; i += 1) {
      if (oks[i]) {
        out.push(rows[i]);
        outTickers.add(String(rows[i].ticker));
      }
    }
    if (mustTicker && !outTickers.has(String(mustTicker))) {
      const pinned = rows.find((r) => String(r.ticker) === String(mustTicker));
      if (pinned) {
        out.push(pinned);
        outTickers.add(String(mustTicker));
      }
    }
    /* Always show ATM band: closest-to-spot strike plus one strike above and below on the ladder, even with no book liquidity. */
    if (mustTicker) {
      const atmIdx = rows.findIndex((r) => String(r.ticker) === String(mustTicker));
      if (atmIdx >= 0) {
        for (const j of [atmIdx - 1, atmIdx, atmIdx + 1]) {
          if (j < 0 || j >= rows.length) continue;
          const r = rows[j];
          const t = String(r.ticker);
          if (outTickers.has(t)) continue;
          out.push(r);
          outTickers.add(t);
        }
      }
    }
    out.sort((a, b) => Number(a.strike || 0) - Number(b.strike || 0));
    return out;
  }

  function fmtStrike(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return '$' + n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function closestStrikeTicker(rows, price) {
    if (price == null || !Number.isFinite(price) || !rows || !rows.length) return '';
    let bestTicker = '';
    let bestD = Infinity;
    let bestStrike = Infinity;
    for (const r of rows) {
      const s = Number(r.strike);
      if (!Number.isFinite(s)) continue;
      const d = Math.abs(s - price);
      if (d < bestD || (d === bestD && s < bestStrike)) {
        bestD = d;
        bestStrike = s;
        bestTicker = r.ticker;
      }
    }
    return bestTicker;
  }

  function parseSymbolPriceFromDom() {
    const el = document.getElementById('symbol-price-value');
    if (!el) return null;
    const raw = (el.textContent || '').trim();
    if (!raw || raw === '$—' || raw === '—') return null;
    const n = Number(String(raw).replace(/[^0-9.]/g, ''));
    return Number.isFinite(n) ? n : null;
  }

  /** Spot for ATM / liquidity filter and ATM strike caption: live DB feed, then DOM, else pack `current_price`. */
  function hourlySpotPrice() {
    try {
      const sym = currentSymbol();
      const bag = window.__liveSpotBySymbol;
      if (bag && sym) {
        const sp = bag[String(sym).trim().toUpperCase()];
        if (sp != null && Number.isFinite(Number(sp))) return Number(sp);
      }
    } catch (e) {}
    const dom = parseSymbolPriceFromDom();
    if (dom != null && Number.isFinite(dom)) return dom;
    if (hourlyCurrentPrice != null && Number.isFinite(hourlyCurrentPrice)) return hourlyCurrentPrice;
    return null;
  }

  function formatStrikeTableCurrentPriceLine(price) {
    if (price == null || !Number.isFinite(price)) return '';
    return (
      'Current price: $' +
      price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    );
  }

  /** Caption in bottom padding of strike cell only (absolute); in-flow strike stays centered. */
  function syncStrikeTableCurrentPriceLine() {
    const root = document.getElementById('hourlyStrikeList');
    if (!root || !hourlyStrikeRows.length) return;
    const spot = hourlySpotPrice();
    const caption = formatStrikeTableCurrentPriceLine(spot);
    const closest =
      spot != null && Number.isFinite(spot) ? closestStrikeTicker(hourlyStrikeRows, spot) : '';
    for (const r of hourlyStrikeRows) {
      const row = root.querySelector(
        'tr.hourly-strike-data-row[data-hourly-ticker="' + r.ticker + '"]'
      );
      if (!row) continue;
      const cpEl = row.querySelector('td.hourly-col-strike .quote-strike-cp');
      if (!cpEl) continue;
      const show = Boolean(caption && closest && String(r.ticker) === String(closest));
      if (show) {
        cpEl.textContent = caption;
        cpEl.setAttribute('aria-hidden', 'false');
      } else {
        cpEl.textContent = '';
        cpEl.setAttribute('aria-hidden', 'true');
      }
    }
  }

  function hourlyQuotesSignature(rows) {
    return (rows || [])
      .map((r) =>
        [
          r.ticker,
          r.strike,
          r.yesAsk,
          r.noAsk,
          r.buffer,
          r.bufferPct,
          r.activeSide,
          r.probActive,
        ].join('|')
      )
      .join('||');
  }

  /** Buffer column (dollars) for hourly strike rows. */
  function fmtHourlyBuffer(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return n.toFixed(2);
  }

  function fmtHourlyBufferPct(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return n.toFixed(2);
  }

  function fmtHourlyProb(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return n.toFixed(1);
  }

  function fmtAsk(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return fmtWholeCentsFromDollars(n);
  }

  /** Class names for strike-row Yes/No ask displays (green if yes ask higher, red if no ask higher). */
  function hourlyStrikeAskPillClassNames(yesAsk, noAsk) {
    const y = parseDollarField(yesAsk);
    const n = parseDollarField(noAsk);
    const baseY = 'hourly-ask-pill hourly-ask-pill-yes';
    const baseN = 'hourly-ask-pill hourly-ask-pill-no';
    if (y != null && n != null) {
      if (y > n) {
        return { yes: baseY + ' hourly-ask-pill--lead-yes', no: baseN + ' hourly-ask-pill--dim' };
      }
      if (n > y) {
        return { yes: baseY + ' hourly-ask-pill--dim', no: baseN + ' hourly-ask-pill--lead-no' };
      }
      return { yes: baseY + ' hourly-ask-pill--dim', no: baseN + ' hourly-ask-pill--dim' };
    }
    if (y != null) {
      return { yes: baseY + ' hourly-ask-pill--lead-yes', no: baseN + ' hourly-ask-pill--dim' };
    }
    if (n != null) {
      return { yes: baseY + ' hourly-ask-pill--dim', no: baseN + ' hourly-ask-pill--lead-no' };
    }
    return { yes: baseY + ' hourly-ask-pill--dim', no: baseN + ' hourly-ask-pill--dim' };
  }

  function ensureHourlyExpandedTicker() {
    if (!hourlyStrikeRows.length) {
      expandedHourlyTicker = '';
      return;
    }
    const exists = hourlyStrikeRows.some((r) => r.ticker === expandedHourlyTicker);
    if (!exists) expandedHourlyTicker = '';
  }

  function hourlyExpandedState(ticker) {
    const k = String(ticker || '');
    if (!hourlyExpandedStateByTicker.has(k)) {
      hourlyExpandedStateByTicker.set(k, {
        autoCenter: true,
        userScrolled: false,
        lastScrollTop: 0,
      });
    }
    return hourlyExpandedStateByTicker.get(k);
  }

  function hourlyStructureSignature(rows) {
    return (rows || [])
      .map((r) => [r.ticker, r.strike].join('|'))
      .join('||');
  }

  function renderHourlyRows() {
    const root = document.getElementById('hourlyStrikeList');
    if (!root) return;
    const bodyRows = hourlyStrikeRows
      .map((r) => {
        const isOpen = expandedHourlyTicker === r.ticker;
        const pill = hourlyStrikeAskPillClassNames(r.yesAsk, r.noAsk);
        const dataTr =
          '<tr class="hourly-strike-data-row' +
          (isOpen ? ' is-open' : '') +
          '" data-hourly-ticker="' +
          r.ticker +
          '" data-hourly-toggle="' +
          r.ticker +
          '">' +
          '<td class="hourly-col-strike">' +
          '<span class="quote-strike-value">' +
          fmtStrike(r.strike) +
          '</span>' +
          '<span class="quote-strike-cp" aria-hidden="true"></span>' +
          '</td>' +
          '<td class="hourly-col-buffer"><span data-hourly-stat="buf">' +
          fmtHourlyBuffer(r.buffer) +
          '</span></td>' +
          '<td class="hourly-col-bufpct"><span data-hourly-stat="bufpct">' +
          fmtHourlyBufferPct(r.bufferPct) +
          '</span></td>' +
          '<td class="hourly-col-prob"><span data-hourly-stat="prob">' +
          fmtHourlyProb(r.probActive) +
          '</span></td>' +
          '<td class="hourly-col-yes">' +
          '<span class="' +
          pill.yes +
          '">' +
          fmtAsk(r.yesAsk) +
          '</span></td>' +
          '<td class="hourly-col-no">' +
          '<span class="' +
          pill.no +
          '">' +
          fmtAsk(r.noAsk) +
          '</span></td>' +
          '</tr>';
        const bookTr = isOpen
          ? '<tr class="hourly-strike-book-row" data-hourly-book-row="' +
            r.ticker +
            '"><td colspan="6"><div class="hourly-strike-expanded" data-hourly-expanded="' +
            r.ticker +
            '"></div></td></tr>'
          : '';
        return dataTr + bookTr;
      })
      .join('');
    const tableHtml =
      '<table class="hourly-strike-table">' +
      '<colgroup>' +
      '<col class="hourly-col-strike-w" />' +
      '<col class="hourly-col-buffer-w" />' +
      '<col class="hourly-col-bufpct-w" />' +
      '<col class="hourly-col-prob-w" />' +
      '<col class="hourly-col-yes-w" />' +
      '<col class="hourly-col-no-w" />' +
      '</colgroup>' +
      '<thead><tr>' +
      '<th scope="col">STRIKE</th>' +
      '<th scope="col">BUFFER</th>' +
      '<th scope="col">%</th>' +
      '<th scope="col">Prob</th>' +
      '<th scope="col">YES</th>' +
      '<th scope="col">NO</th>' +
      '</tr></thead>' +
      '<tbody>' +
      (bodyRows || '<tr><td colspan="6" class="hourly-strike-empty">No strikes.</td></tr>') +
      '</tbody></table>';
    root.innerHTML = hourlyStrikeRows.length ? tableHtml : '<div class="load-err">No strikes.</div>';
    root.querySelectorAll('tr[data-hourly-toggle]').forEach((trEl) => {
      trEl.addEventListener('click', (ev) => {
        if (
          ev.target &&
          ev.target.closest &&
          (ev.target.closest('.hourly-col-yes') || ev.target.closest('.hourly-col-no'))
        ) {
          return;
        }
        const t = String(trEl.getAttribute('data-hourly-toggle') || '');
        expandedHourlyTicker = expandedHourlyTicker === t ? '' : t;
        if (expandedHourlyTicker) {
          const st = hourlyExpandedState(expandedHourlyTicker);
          st.autoCenter = true;
          st.userScrolled = false;
          st.lastScrollTop = 0;
        }
        renderHourlyRows();
      });
    });
    root.querySelectorAll('.hourly-col-yes, .hourly-col-no').forEach((td) => {
      td.addEventListener('click', (ev) => {
        ev.stopPropagation();
      });
    });
    syncStrikeTableCurrentPriceLine();
  }

  function patchHourlyRowQuotesInPlace() {
    const root = document.getElementById('hourlyStrikeList');
    if (!root) return;
    for (const r of hourlyStrikeRows) {
      const row = root.querySelector(
        'tr.hourly-strike-data-row[data-hourly-ticker="' + r.ticker + '"]'
      );
      if (!row) continue;
      const strikeTd = row.querySelector('td.hourly-col-strike');
      const valEl = strikeTd && strikeTd.querySelector('.quote-strike-value');
      const cpEl = strikeTd && strikeTd.querySelector('.quote-strike-cp');
      if (!strikeTd || !valEl || !cpEl) {
        renderHourlyRows();
        return;
      }
      valEl.textContent = fmtStrike(r.strike);
      const pill = hourlyStrikeAskPillClassNames(r.yesAsk, r.noAsk);
      const yesEl = row.querySelector('.hourly-ask-pill-yes');
      const noEl = row.querySelector('.hourly-ask-pill-no');
      if (yesEl) {
        yesEl.textContent = fmtAsk(r.yesAsk);
        yesEl.className = pill.yes;
      }
      if (noEl) {
        noEl.textContent = fmtAsk(r.noAsk);
        noEl.className = pill.no;
      }
      const bufEl = row.querySelector('[data-hourly-stat="buf"]');
      const bufPctEl = row.querySelector('[data-hourly-stat="bufpct"]');
      const probEl = row.querySelector('[data-hourly-stat="prob"]');
      if (!bufEl || !bufPctEl || !probEl) {
        renderHourlyRows();
        return;
      }
      bufEl.textContent = fmtHourlyBuffer(r.buffer);
      bufPctEl.textContent = fmtHourlyBufferPct(r.bufferPct);
      probEl.textContent = fmtHourlyProb(r.probActive);
    }
    syncStrikeTableCurrentPriceLine();
  }

  /** If spot moved and the true closest strike was liquidity-filtered out, add it from raw rows. */
  function ensureClosestStrikeRowVisible() {
    const raw = hourlyRawStrikeRows;
    if (!raw || !raw.length) return;
    const spot = hourlySpotPrice();
    const must = closestStrikeTicker(raw, spot);
    if (!must) return;
    if (hourlyStrikeRows.some((r) => String(r.ticker) === String(must))) return;
    const row = raw.find((r) => String(r.ticker) === String(must));
    if (!row) return;
    hourlyStrikeRows = hourlyStrikeRows.concat([row]).sort((a, b) => Number(a.strike || 0) - Number(b.strike || 0));
    lastHourlyStructureSignature = hourlyStructureSignature(hourlyStrikeRows);
    lastHourlyRowsSignature = hourlyQuotesSignature(hourlyStrikeRows);
    ensureHourlyExpandedTicker();
    renderHourlyRows();
  }

  function centerMidRowInPanel(scrollEl, midEl) {
    if (!scrollEl || !midEl) return;
    const midTop = midEl.offsetTop;
    const target = midTop - scrollEl.clientHeight / 2 + midEl.offsetHeight / 2;
    scrollEl.scrollTop = Math.max(0, target);
  }

  function renderOrderbookInto(containerEl, d, ticker) {
    if (!containerEl) return;
    const st = hourlyExpandedState(ticker);
    const prevScroll = st && Number.isFinite(st.lastScrollTop) ? Number(st.lastScrollTop) : 0;
    const book = mode === 'yes' ? d.trade_yes : d.trade_no;
    const asks = book.asks || [];
    const bids = book.bids || [];
    const askLabelIdx = asks.length > 0 ? asks.length - 1 : -1;
    const bidLabelIdx = bids.length > 0 ? 0 : -1;
    const midClass = mode === 'yes' ? 'mid-row mid-yes' : 'mid-row mid-no';
    const bookYesOn = mode === 'yes' ? ' is-active' : '';
    const bookNoOn = mode === 'no' ? ' is-active' : '';
    containerEl.innerHTML =
      '<div class="book-panel">' +
      '<table class="book-table panel-head">' +
      '<colgroup><col class="side"/><col class="price"/><col class="contracts"/><col class="total"/></colgroup>' +
      '<thead><tr>' +
      '<th scope="col" class="hourly-book-mode-th">' +
      '<div class="hourly-book-mode-toggle" role="group" aria-label="Order book side">' +
      '<button type="button" class="hourly-book-mode-btn hourly-book-mode-yes' +
      bookYesOn +
      '" data-hourly-book-side="yes">Yes</button>' +
      '<button type="button" class="hourly-book-mode-btn hourly-book-mode-no' +
      bookNoOn +
      '" data-hourly-book-side="no">No</button>' +
      '</div></th>' +
      '<th scope="col">Price</th><th scope="col">Contracts</th><th scope="col">Total</th>' +
      '</tr></thead>' +
      '</table>' +
      '<div class="panel-scroll" data-hourly-scroll="' +
      String(ticker || '') +
      '">' +
      '<table class="book-table">' +
      '<colgroup><col class="side"/><col class="price"/><col class="contracts"/><col class="total"/></colgroup>' +
      '<tbody class="asks">' +
      rowsToHtml(asks, 'Asks', askLabelIdx) +
      '</tbody>' +
      '<tbody><tr><td colspan="4" class="' +
      midClass +
      '" data-hourly-mid="' +
      String(ticker || '') +
      '">' +
      buildMidCellInner(mode, d.last_trade) +
      '</td></tr></tbody>' +
      '<tbody class="bids">' +
      rowsToHtml(bids, 'Bids', bidLabelIdx) +
      '</tbody>' +
      '</table></div></div>';

    const scrollEl = containerEl.querySelector('[data-hourly-scroll="' + String(ticker || '') + '"]');
    const midEl = containerEl.querySelector('[data-hourly-mid="' + String(ticker || '') + '"]');
    if (!scrollEl) return;
    if (st.autoCenter && !st.userScrolled) {
      centerMidRowInPanel(scrollEl, midEl);
      st.lastScrollTop = scrollEl.scrollTop;
      st.autoCenter = false;
    } else {
      scrollEl.scrollTop = Math.max(0, prevScroll);
    }
    if (!scrollEl.dataset.hourlyScrollBound) {
      scrollEl.addEventListener('scroll', () => {
        const cur = hourlyExpandedState(ticker);
        cur.userScrolled = true;
        cur.lastScrollTop = scrollEl.scrollTop;
      });
      scrollEl.dataset.hourlyScrollBound = '1';
    }
    containerEl.querySelectorAll('[data-hourly-book-side]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const s = String(btn.getAttribute('data-hourly-book-side') || '');
        if (s !== 'yes' && s !== 'no') return;
        mode = s;
        const stToggle = hourlyExpandedState(ticker);
        stToggle.autoCenter = true;
        stToggle.userScrolled = false;
        renderOrderbookInto(containerEl, d, ticker);
        lastExpandedOrderbookSignature = JSON.stringify({
          ticker: d.market_ticker || '',
          mode: mode,
          yes: d.trade_yes || {},
          no: d.trade_no || {},
          last: d.last_trade || {},
        });
      });
    });
  }

  function disconnectStrikeTableDbWs() {
    if (!hourlyStrikeTableDbWs) return;
    try {
      hourlyStrikeTableDbWs.close();
    } catch (e) {}
    hourlyStrikeTableDbWs = null;
  }

  function connectStrikeTableDbWs() {
    if (typeof WebSocket === 'undefined') return;
    if (hourlyStrikeTableDbWs && hourlyStrikeTableDbWs.readyState === WebSocket.OPEN) return;
    disconnectStrikeTableDbWs();
    const wsUrl = dbChangesWebSocketUrl();
    try {
      hourlyStrikeTableDbWs = new WebSocket(wsUrl);
    } catch (e) {
      hourlyStrikeTableDbWs = null;
      return;
    }
    hourlyStrikeTableDbWs.onopen = function () {
      void fetchLiveSymbolSpotBootstrap();
    };
    hourlyStrikeTableDbWs.onmessage = function (event) {
      try {
        const msg = JSON.parse(event.data);
        if (msg && msg.type === 'live_symbol_spot') {
          applyLiveSymbolSpotMessage(msg);
          return;
        }
        if (
          msg &&
          msg.type === 'db_change' &&
          (msg.database === 'strike_table_hourly' || msg.database === 'strike_table_15m')
        ) {
          lastStrikeTableFetchMs = 0;
        }
      } catch (e2) {}
    };
    hourlyStrikeTableDbWs.onclose = function () {
      hourlyStrikeTableDbWs = null;
      const cm = currentMarket();
      const tmNew = document.body && document.body.classList.contains('trade-monitor-new-page');
      if (tmNew || cm === 'hourly' || cm === '15m') {
        setTimeout(connectStrikeTableDbWs, 2500);
      }
    };
  }

  /** 15m and hourly: same DOM — embedded books only; legacy quote row + split panel stay hidden. */
  function switchLayoutForMarket(mkt) {
    const quoteRow = document.getElementById('quoteRow');
    const bookPanel = document.getElementById('bookPanel');
    const strikeListEl = document.getElementById('hourlyStrikeList');
    if (!quoteRow || !bookPanel || !strikeListEl) return;

    const prev = lastMarketMode;
    if (mkt === prev) {
      quoteRow.classList.add('u-hidden');
      bookPanel.classList.add('u-hidden');
      strikeListEl.classList.remove('u-hidden');
      return;
    }

    clearMarketExpiration();
    lastStrikeTableFetchMs = 0;
    hourlyHeaderLastFetchSymbol = '';
    lastMarketMode = mkt;

    quoteRow.classList.add('u-hidden');
    bookPanel.classList.add('u-hidden');
    strikeListEl.classList.remove('u-hidden');
    isBookVisible = false;
    connectStrikeTableDbWs();
  }

  async function tick() {
    if (tickBusy) {
      tickPending = true;
      return;
    }
    tickBusy = true;
    try {
      try {
        await runDataTick();
      } catch (e) {
        const errEl = document.getElementById('loadErr');
        if (errEl) {
          errEl.classList.remove('u-hidden');
          errEl.textContent = 'Error: ' + e;
        }
      }
    } finally {
      tickBusy = false;
      if (tickPending) {
        tickPending = false;
        tick();
      }
    }
  }

  async function runDataTick() {
    const mkt = currentMarket();
    switchLayoutForMarket(mkt);
    const symNow = currentSymbol();
    if (symNow !== hourlyHeaderLastFetchSymbol) {
      hourlyHeaderLastFetchSymbol = symNow;
      lastStrikeTableFetchMs = 0;
      clearMarketExpiration();
    }
    ensureClosestStrikeRowVisible();
    const nowMs = Date.now();
    if (nowMs - lastStrikeTableFetchMs > 1500) {
      lastStrikeTableFetchMs = nowMs;
      const pack = await fetchStrikeTablePack(currentSymbol(), mkt);
      applyStrikePackHeader(pack, mkt);
      const errEl = document.getElementById('loadErr');
      if (!pack.fetchFailed) {
        if (errEl) {
          errEl.classList.add('u-hidden');
          errEl.textContent = '';
        }
        const rawRows = pack.rows || [];
        hourlyRawStrikeRows = rawRows.slice();
        hourlyCurrentPrice =
          pack.currentPrice != null && Number.isFinite(pack.currentPrice) ? pack.currentPrice : null;
        const fetchedRows = await filterHourlyRowsByLiquidity(rawRows, hourlySpotPrice());
        const nextStructSig = hourlyStructureSignature(fetchedRows);
        const nextSig = hourlyQuotesSignature(fetchedRows);
        hourlyStrikeRows = fetchedRows;
        ensureHourlyExpandedTicker();
        if (nextStructSig !== lastHourlyStructureSignature) {
          lastHourlyStructureSignature = nextStructSig;
          lastHourlyRowsSignature = nextSig;
          renderHourlyRows();
        } else if (nextSig !== lastHourlyRowsSignature) {
          lastHourlyRowsSignature = nextSig;
          patchHourlyRowQuotesInPlace();
        }
      } else if (errEl) {
        errEl.classList.remove('u-hidden');
        errEl.textContent = 'No strike table data';
      }
    }
    if (hourlyStrikeRows.length) syncStrikeTableCurrentPriceLine();
    if (!expandedHourlyTicker) return;
    const mount = document.querySelector(
      '[data-hourly-expanded="' + expandedHourlyTicker + '"]'
    );
    if (!mount) return;
    const hrRes = await fetch(orderbookUrlForTicker(expandedHourlyTicker), { cache: 'no-store' });
    const hrData = await hrRes.json();
    if (hrData && !hrData.error) {
      const mth = (hrData.market_ticker || '').trim();
      if (mth) {
        armExpirationFromTicker(mth);
        const wExp = document.getElementById('mktWindow');
        if (wExp) wExp.textContent = hourlyMarketWindowLabelFromTicker(mth);
      }
      const expandedSig = JSON.stringify({
        ticker: hrData.market_ticker || '',
        mode: mode,
        yes: hrData.trade_yes || {},
        no: hrData.trade_no || {},
        last: hrData.last_trade || {},
      });
      if (expandedSig !== lastExpandedOrderbookSignature) {
        lastExpandedOrderbookSignature = expandedSig;
        renderOrderbookInto(mount, hrData, expandedHourlyTicker);
      }
    }
  }

  try {
    window.addEventListener('rec:live-symbol-spot', function () {
      if (hourlyStrikeRows.length) syncStrikeTableCurrentPriceLine();
    });
  } catch (e) {}

  if (document.body && document.body.classList.contains('trade-monitor-new-page')) {
    const symPick = document.getElementById('ticker-picker');
    if (symPick) {
      symPick.addEventListener('change', function () {
        window.tmNewRefreshLiveSpotPanel();
      });
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        connectStrikeTableDbWs();
      });
    } else {
      connectStrikeTableDbWs();
    }
  }

  ensureInitialVisibility();
  setInterval(function () {
    try {
      applyHeaderTtcToClock();
    } catch (e) {}
  }, 200);
  setInterval(tick, 500);
  tick();
})();
