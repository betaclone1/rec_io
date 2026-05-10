(function () {
  let mode = 'yes';
  let shouldAutoCenter = true;
  let isBookVisible = false;
  let lastMarketMode = '';
  let hourlyStrikeRows = [];
  /** Full strike ladder from strike-table API (same rows we render). */
  let hourlyRawStrikeRows = [];
  /** Pack `current_price` when DOM / live spot not yet available. */
  let hourlyCurrentPrice = null;
  let expandedHourlyTicker = '';
  let lastHourlyRowsSignature = '';
  let lastHourlyStructureSignature = '';
  let lastExpandedOrderbookSignature = '';
  let hourlyExpandedStateByTicker = new Map();
  let centerAtmStrikeOnNextRender = true;

  /**
   * Countdown uses only Kalshi ticker → expiration (America/New_York), not DB ttc_* columns.
   * UTC epoch ms; recomputed when marketExpireSourceKey (ticker string) changes.
   */
  let marketExpireAtMs = null;
  let marketExpireSourceKey = '';
  let ttcTimer = null;
  let hourlyHeaderLastFetchSymbol = '';
  let hourlyStrikeTableDbWsUnsub = null;
  /** Last `live_symbol_spot` frame (Redis → main `/ws/db_changes`); used when symbol/monitor changes. */
  let lastLiveSymbolSpotMsg = null;

  /** Strikes with 100¢ on either side are hidden except this many kept around the money line. */
  const MIN_HOURLY_VISIBLE_AROUND_MONEY_LINE = 3;

  let refreshBusy = false;
  let refreshPending = false;
  let refreshTimer = null;

  /** Coalesce high-frequency `/ws/db_changes` so we do not refetch the ladder on every orderbook tick. */
  const STRIKE_TABLE_WS_MIN_INTERVAL_MS = 900;
  let strikeTableWsRefreshTimer = null;
  let lastStrikeTableWsRefreshRun = 0;

  /** Debounce ATM row DOM work on rapid `live_symbol_spot` frames. */
  const STRIKE_TABLE_ATM_SYNC_MIN_MS = 120;
  let strikeTableAtmSyncTimer = null;
  let strikeTableAtmSyncLast = 0;

  const EXPANDED_ORDERBOOK_WS_DEBOUNCE_MS = 200;
  let expandedOrderbookWsTimer = null;

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
    requestDataRefresh();
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

  async function fetchLiveSymbolSpotBootstrap() {
    if (!document.body || !document.body.classList.contains('trade-monitor-new-page')) {
      return;
    }
    try {
      const res = await tmMainApiFetch('/api/live_symbol_spot_bootstrap', { cache: 'no-store' });
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
    var base = tmMainApiBase();
    var params = new URLSearchParams(window.location.search || '');
    var sym = (params.get('symbol') || 'BTC').toString().trim().toUpperCase() || 'BTC';
    var mktRaw = (params.get('market') || '15m').toString().trim().toLowerCase();
    var mkt = mktRaw === 'hourly' ? 'hourly' : '15m';
    return (
      base +
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
    if (ttcTimer) {
      clearTimeout(ttcTimer);
      ttcTimer = null;
    }
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
    el.style.backgroundColor = 'transparent';
    el.style.color = '#f3f4f6';
    const autoOn =
      document.body &&
      document.body.dataset &&
      document.body.dataset.tmNewAutoTradeOn === '1';
    if (!autoOn) {
      el.style.borderColor = 'transparent';
      el.style.boxShadow = 'none';
      return;
    }
    const c = monitorTtcColor();
    const glow =
      c === '#22c55e'
        ? '0 0 8px rgba(34, 197, 94, 0.45)'
        : c === '#ef4444'
          ? '0 0 8px rgba(239, 68, 68, 0.45)'
          : '0 0 8px rgba(250, 204, 21, 0.45)';
    el.style.borderColor = c;
    el.style.boxShadow = glow;
  }

  function applyHeaderTtcToClock() {
    if (marketExpireAtMs == null || !Number.isFinite(marketExpireAtMs)) {
      updateMarketHeaderTtc(null);
      if (ttcTimer) {
        clearTimeout(ttcTimer);
        ttcTimer = null;
      }
      return;
    }
    const sec = Math.max(0, Math.floor((marketExpireAtMs - Date.now()) / 1000));
    updateMarketHeaderTtc(sec);
    if (ttcTimer) clearTimeout(ttcTimer);
    if (sec > 0) {
      ttcTimer = setTimeout(() => {
        ttcTimer = null;
        applyHeaderTtcToClock();
      }, 1000);
    } else {
      ttcTimer = null;
    }
  }

  /** Called from trade-monitor-new-init when auto-trade toggle syncs so border updates immediately. */
  window.tmNewSyncTtcClockChrome = applyHeaderTtcToClock;

  function applyStrikePackHeader(pack, market) {
    if (!pack || pack.fetchFailed) return;
    const sym = (pack.headerSymbol || currentSymbol()).toString().trim().toUpperCase() || 'BTC';
    const mt = pack.marketTitle && String(pack.marketTitle).trim();
    const tEl = document.getElementById('mktTitle');
    const wEl = document.getElementById('mktWindow');
    const strat =
      (document.body && document.body.dataset && document.body.dataset.currentMonitorStrategy) || '—';
    const monitorNumber =
      (document.body && document.body.dataset && document.body.dataset.currentMonitorNumber) || '—';
    const mktKey = currentMarket();
    const mkLabel = mktKey === 'hourly' ? 'Hourly' : '15m';
    if (tEl) {
      const nextTitle = sym + ' ' + mkLabel + ' \u2022 ' + strat;
      if (tEl.textContent !== nextTitle) tEl.textContent = nextTitle;
    }
    const ref =
      (pack.rows && pack.rows[0] && pack.rows[0].ticker && String(pack.rows[0].ticker).trim()) ||
      (pack.eventTicker && String(pack.eventTicker).trim()) ||
      '';
    if (wEl) {
      const nextWindow = monitorNumber + ' \u2022 ' + (mt || '');
      if (wEl.textContent !== nextWindow) wEl.textContent = nextWindow;
    }
    if (ref) {
      armExpirationFromTicker(ref);
      applyHeaderTtcToClock();
    } else {
      clearMarketExpiration();
      updateMarketHeaderTtc(null);
    }
    if (typeof window.tmNewApplyMarketHeaderIcon === 'function') {
      window.tmNewApplyMarketHeaderIcon(sym);
    }
    try {
      window.__recTmStrikeMarketTitle = mt ? String(mt).trim() : '';
    } catch (eMt) {}
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
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      return empty;
    }
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
        yesDiff: s.yes_diff != null && s.yes_diff !== '' ? Number(s.yes_diff) : null,
        noDiff: s.no_diff != null && s.no_diff !== '' ? Number(s.no_diff) : null,
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

  /** Whole cents from dollars; matches fmtWholeCentsFromDollars / pill display. */
  function hourlyAskWholeCents(dollarsField) {
    const d = parseDollarField(dollarsField);
    if (d == null) return null;
    return Math.round(d * 100);
  }

  /** True if this side quotes at 100¢ (hide candidate). Missing ask is not treated as 100. */
  function hourlyAskIs100Cents(dollarsField) {
    const c = hourlyAskWholeCents(dollarsField);
    return c != null && c >= 100;
  }

  function hourlyRowHasEitherAsk100(row) {
    return hourlyAskIs100Cents(row.yesAsk) || hourlyAskIs100Cents(row.noAsk);
  }

  function moneyLineCenterIndex(rows, spot) {
    const n = rows.length;
    if (!n) return 0;
    if (spot == null || !Number.isFinite(spot)) return Math.floor(n / 2);
    let bestI = 0;
    let bestD = Infinity;
    let bestStrike = Infinity;
    for (let i = 0; i < n; i++) {
      const s = Number(rows[i].strike);
      if (!Number.isFinite(s)) continue;
      const d = Math.abs(s - spot);
      if (d < bestD || (d === bestD && s < bestStrike)) {
        bestD = d;
        bestStrike = s;
        bestI = i;
      }
    }
    return bestI;
  }

  /**
   * At least this many ladder indices stay visible even when both asks would otherwise filter out
   * (100¢). Indices are expanded symmetrically around the strike closest to `spot`.
   */
  function moneyLineProtectedIndices(rows, spot) {
    const n = rows.length;
    const out = new Set();
    if (n === 0) return out;
    if (n <= MIN_HOURLY_VISIBLE_AROUND_MONEY_LINE) {
      for (let i = 0; i < n; i++) out.add(i);
      return out;
    }
    const c = moneyLineCenterIndex(rows, spot);
    out.add(c);
    let lo = c;
    let hi = c;
    while (out.size < MIN_HOURLY_VISIBLE_AROUND_MONEY_LINE) {
      const canLo = lo > 0;
      const canHi = hi < n - 1;
      if (!canLo && !canHi) break;
      const preferLo = canLo && (!canHi || c - lo <= hi - c);
      if (preferLo) {
        lo--;
        out.add(lo);
      } else if (canHi) {
        hi++;
        out.add(hi);
      } else {
        lo--;
        out.add(lo);
      }
    }
    return out;
  }

  /**
   * Hide strikes where YES or NO ask is 100¢, except always keep at least 3 rows around the
   * money line (closest strike to `spot`). `rows` must be strike-sorted like the API.
   */
  function applyHourlyStrikeAskVisibility(rows, spot) {
    const list = rows || [];
    if (!list.length) return [];
    const protectedIdx = moneyLineProtectedIndices(list, spot);
    const out = [];
    for (let i = 0; i < list.length; i++) {
      if (protectedIdx.has(i) || !hourlyRowHasEitherAsk100(list[i])) out.push(list[i]);
    }
    return out;
  }

  /** Re-filter ladder when live spot moves (protected-3 center tracks money line). */
  function reapplyHourlyStrikeVisibilityFromSpot() {
    if (!document.body || !document.body.classList.contains('trade-monitor-new-page')) return;
    if (!hourlyRawStrikeRows.length) return;
    const spot = hourlySpotPrice();
    const visible = applyHourlyStrikeAskVisibility(hourlyRawStrikeRows, spot);
    const nextStruct = hourlyStructureSignature(visible);
    const nextQuotes = hourlyQuotesSignature(visible);
    if (nextStruct === lastHourlyStructureSignature && nextQuotes === lastHourlyRowsSignature) return;
    hourlyStrikeRows = visible;
    ensureHourlyExpandedTicker();
    if (nextStruct !== lastHourlyStructureSignature) {
      lastHourlyStructureSignature = nextStruct;
      lastHourlyRowsSignature = nextQuotes;
      centerAtmStrikeOnNextRender = true;
      renderHourlyRows();
    } else {
      lastHourlyRowsSignature = nextQuotes;
      patchHourlyRowQuotesInPlace();
    }
    try {
      if (typeof window.recTmOrderBuilderRefreshQuotes === 'function') {
        window.recTmOrderBuilderRefreshQuotes();
      }
    } catch (eOb) {}
  }

  function parseSymbolPriceFromDom() {
    const el = document.getElementById('symbol-price-value');
    if (!el) return null;
    const raw = (el.textContent || '').trim();
    if (!raw || raw === '$—' || raw === '—') return null;
    const n = Number(String(raw).replace(/[^0-9.]/g, ''));
    return Number.isFinite(n) ? n : null;
  }

  /** Spot for ATM highlight / centering: live feed, DOM, else pack `current_price`. */
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

  function scheduleStrikeTableRefreshFromWs() {
    const now = Date.now();
    const elapsed = now - lastStrikeTableWsRefreshRun;
    if (strikeTableWsRefreshTimer != null) return;
    const delay = elapsed >= STRIKE_TABLE_WS_MIN_INTERVAL_MS ? 0 : STRIKE_TABLE_WS_MIN_INTERVAL_MS - elapsed;
    strikeTableWsRefreshTimer = setTimeout(() => {
      strikeTableWsRefreshTimer = null;
      lastStrikeTableWsRefreshRun = Date.now();
      requestDataRefresh();
    }, delay);
  }

  async function refreshExpandedHourlyOrderbookIfOpen() {
    if (!expandedHourlyTicker) return;
    const mount = document.querySelector(
      '[data-hourly-expanded="' + expandedHourlyTicker + '"]'
    );
    if (!mount) return;
    const expandedTicker = expandedHourlyTicker;
    let hrRes;
    try {
      hrRes = await fetch(orderbookUrlForTicker(expandedTicker), { cache: 'no-store' });
    } catch (e) {
      return;
    }
    let hrData;
    try {
      hrData = await hrRes.json();
    } catch (e2) {
      return;
    }
    if (expandedTicker !== expandedHourlyTicker) return;
    if (hrData && !hrData.error) {
      const mth = (hrData.market_ticker || '').trim();
      if (mth) {
        armExpirationFromTicker(mth);
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

  function scheduleExpandedOrderbookRefreshFromWs() {
    if (!expandedHourlyTicker) return;
    if (expandedOrderbookWsTimer != null) clearTimeout(expandedOrderbookWsTimer);
    expandedOrderbookWsTimer = setTimeout(() => {
      expandedOrderbookWsTimer = null;
      void refreshExpandedHourlyOrderbookIfOpen();
    }, EXPANDED_ORDERBOOK_WS_DEBOUNCE_MS);
  }

  function syncStrikeTableAtmMarker() {
    const now = Date.now();
    if (now - strikeTableAtmSyncLast < STRIKE_TABLE_ATM_SYNC_MIN_MS) {
      if (strikeTableAtmSyncTimer == null) {
        strikeTableAtmSyncTimer = setTimeout(() => {
          strikeTableAtmSyncTimer = null;
          syncStrikeTableAtmMarker();
        }, STRIKE_TABLE_ATM_SYNC_MIN_MS - (now - strikeTableAtmSyncLast));
      }
      return;
    }
    strikeTableAtmSyncLast = Date.now();

    const root = document.getElementById('hourlyStrikeList');
    if (!root || !hourlyStrikeRows.length) return;
    const scrollRoot = root.querySelector('[data-hourly-strike-scroll]') || root;
    const spot = hourlySpotPrice();
    const closest =
      spot != null && Number.isFinite(spot) ? closestStrikeTicker(hourlyStrikeRows, spot) : '';
    let closestRow = null;
    for (const r of hourlyStrikeRows) {
      const row = root.querySelector(
        'tr.hourly-strike-data-row[data-hourly-ticker="' + r.ticker + '"]'
      );
      if (!row) continue;
      const strikeTd = row.querySelector('td.hourly-col-strike');
      if (!strikeTd) continue;
      if (closest && String(r.ticker) === String(closest)) {
        strikeTd.classList.add('hourly-strike-atm');
        closestRow = row;
      } else {
        strikeTd.classList.remove('hourly-strike-atm');
      }
    }
    if (centerAtmStrikeOnNextRender && closest) {
      const targetTicker = String(closest);
      const tryCenter = (attempt) => {
        const h = Number(scrollRoot.clientHeight || 0);
        const row = root.querySelector(
          'tr.hourly-strike-data-row[data-hourly-ticker="' + targetTicker + '"]'
        );
        if (h > 20 && row) {
          const rootRect = scrollRoot.getBoundingClientRect();
          const rowRect = row.getBoundingClientRect();
          const rowTopInScroll = rowRect.top - rootRect.top + scrollRoot.scrollTop;
          const target = rowTopInScroll - h / 2 + rowRect.height / 2;
          scrollRoot.scrollTop = Math.max(0, target);
          // If content still doesn't overflow (transient bootstrap render), keep centering armed.
          if (scrollRoot.scrollHeight > scrollRoot.clientHeight + 4 && hourlyStrikeRows.length > 1) {
            centerAtmStrikeOnNextRender = false;
          }
          return;
        }
        if (attempt >= 14) return;
        requestAnimationFrame(() => tryCenter(attempt + 1));
      };
      requestAnimationFrame(() => tryCenter(0));
    }
    try {
      if (document.body && document.body.classList.contains('trade-monitor-new-page')) {
        const atmRow =
          closest && hourlyStrikeRows.length
            ? hourlyStrikeRows.find((r) => String(r.ticker) === String(closest))
            : null;
        window.dispatchEvent(
          new CustomEvent('rec:tm-strike-atm-synced', {
            detail: {
              atmTicker: closest ? String(closest) : '',
              atmRow: atmRow || null,
              spot: hourlySpotPrice(),
              strikeTableCurrentPrice:
                hourlyCurrentPrice != null && Number.isFinite(hourlyCurrentPrice)
                  ? hourlyCurrentPrice
                  : null,
            },
          })
        );
      }
    } catch (eSync) {}
    if (typeof window.recTmOrderBuilderRefreshQuotes === 'function') {
      try {
        window.recTmOrderBuilderRefreshQuotes();
      } catch (eOb) {}
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
          r.yesDiff,
          r.noDiff,
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

  /** yes_diff / no_diff from strike table API, whole number; positive with leading +. */
  function fmtHourlyStrikeDiff(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    const r = Math.round(n);
    if (r > 0) return '+' + String(r);
    return String(r);
  }

  /** Full class list for diff span (sign coloring via CSS modifiers). */
  function hourlyStrikeDiffClassName(v) {
    const base = 'hourly-strike-yesno-diff';
    if (v == null || v === '') return base + ' hourly-strike-yesno-diff--na';
    const n = Number(v);
    if (!Number.isFinite(n)) return base + ' hourly-strike-yesno-diff--na';
    const r = Math.round(n);
    if (r > 0) return base + ' hourly-strike-yesno-diff--pos';
    if (r < 0) return base + ' hourly-strike-yesno-diff--neg';
    return base + ' hourly-strike-yesno-diff--zero';
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

  /** Match order panel strike + side; re-run after row render/patch (className resets pills). */
  function recTmApplyStrikeTableOrderSelection(ticker, side) {
    if (!document.body || !document.body.classList.contains('trade-monitor-new-page')) return;
    const root = document.getElementById('hourlyStrikeList');
    if (!root) return;
    root.querySelectorAll('.hourly-ask-pill--order-selected').forEach((el) => {
      el.classList.remove('hourly-ask-pill--order-selected');
    });
    const t = ticker != null && String(ticker).trim() !== '' ? String(ticker).trim() : '';
    if (!t) return;
    const s = side === 'no' ? 'no' : 'yes';
    let trMatch = null;
    root.querySelectorAll('tr.hourly-strike-data-row').forEach((row) => {
      if (String(row.getAttribute('data-hourly-ticker') || '') === t) {
        trMatch = row;
      }
    });
    if (!trMatch) return;
    const pill =
      s === 'no'
        ? trMatch.querySelector('.hourly-ask-pill-no')
        : trMatch.querySelector('.hourly-ask-pill-yes');
    if (pill) pill.classList.add('hourly-ask-pill--order-selected');
  }
  window.recTmApplyStrikeTableOrderSelection = recTmApplyStrikeTableOrderSelection;

  function recTmSyncStrikeTablePillsFromOrderBuilder() {
    if (typeof window.tmNewGetOrderBuilderStrikeSelection !== 'function') return;
    try {
      const sel = window.tmNewGetOrderBuilderStrikeSelection();
      recTmApplyStrikeTableOrderSelection(sel && sel.ticker, sel && sel.side);
    } catch (eSync) {}
  }

  function renderHourlyRows() {
    const root = document.getElementById('hourlyStrikeList');
    if (!root) return;
    const prevScrollEl = root.querySelector('[data-hourly-strike-scroll]');
    const prevScrollTop = prevScrollEl ? prevScrollEl.scrollTop : 0;
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
          '<span class="quote-strike-atm-ind" aria-hidden="true"></span>' +
          '<span class="quote-strike-value">' +
          fmtStrike(r.strike) +
          '</span>' +
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
          '<span class="hourly-strike-pill-wrap">' +
          '<span class="' +
          pill.yes +
          '">' +
          fmtAsk(r.yesAsk) +
          '</span>' +
          '<span class="' +
          hourlyStrikeDiffClassName(r.yesDiff) +
          '" data-hourly-strike-diff="yes">' +
          fmtHourlyStrikeDiff(r.yesDiff) +
          '</span></span></td>' +
          '<td class="hourly-col-no">' +
          '<span class="hourly-strike-pill-wrap">' +
          '<span class="' +
          pill.no +
          '">' +
          fmtAsk(r.noAsk) +
          '</span>' +
          '<span class="' +
          hourlyStrikeDiffClassName(r.noDiff) +
          '" data-hourly-strike-diff="no">' +
          fmtHourlyStrikeDiff(r.noDiff) +
          '</span></span></td>' +
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
    const colgroup =
      '<colgroup>' +
      '<col class="hourly-col-strike-w" />' +
      '<col class="hourly-col-buffer-w" />' +
      '<col class="hourly-col-bufpct-w" />' +
      '<col class="hourly-col-prob-w" />' +
      '<col class="hourly-col-yes-w" />' +
      '<col class="hourly-col-no-w" />' +
      '</colgroup>';
    const tableHtml =
      '<div class="hourly-strike-head">' +
      '<table class="hourly-strike-table">' +
      colgroup +
      '<thead><tr>' +
      '<th scope="col">STRIKE</th>' +
      '<th scope="col">BUFFER</th>' +
      '<th scope="col">%</th>' +
      '<th scope="col">Prob</th>' +
      '<th scope="col">YES</th>' +
      '<th scope="col">NO</th>' +
      '</tr></thead></table></div>' +
      '<div class="hourly-strike-scroll" data-hourly-strike-scroll>' +
      '<table class="hourly-strike-table">' +
      colgroup +
      '<tbody>' +
      (bodyRows || '<tr><td colspan="6" class="hourly-strike-empty">No strikes.</td></tr>') +
      '</tbody></table></div>';
    root.innerHTML = hourlyStrikeRows.length ? tableHtml : '<div class="load-err">No strikes.</div>';
    const newScrollEl = root.querySelector('[data-hourly-strike-scroll]');
    if (newScrollEl && !centerAtmStrikeOnNextRender) {
      newScrollEl.scrollTop = Math.max(0, prevScrollTop);
    }
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
        requestDataRefresh();
        try {
          if (document.body && document.body.classList.contains('trade-monitor-new-page')) {
            window.dispatchEvent(
              new CustomEvent('rec:tm-order-builder-pick', {
                detail: { ticker: t, side: null },
              })
            );
          }
        } catch (ePick) {}
      });
    });
    syncStrikeTableAtmMarker();
    recTmSyncStrikeTablePillsFromOrderBuilder();
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
      if (!strikeTd || !valEl) {
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
      const yesDiffEl = row.querySelector('[data-hourly-strike-diff="yes"]');
      const noDiffEl = row.querySelector('[data-hourly-strike-diff="no"]');
      if (yesDiffEl) {
        yesDiffEl.textContent = fmtHourlyStrikeDiff(r.yesDiff);
        yesDiffEl.className = hourlyStrikeDiffClassName(r.yesDiff);
      }
      if (noDiffEl) {
        noDiffEl.textContent = fmtHourlyStrikeDiff(r.noDiff);
        noDiffEl.className = hourlyStrikeDiffClassName(r.noDiff);
      }
    }
    syncStrikeTableAtmMarker();
    recTmSyncStrikeTablePillsFromOrderBuilder();
    if (typeof window.recTmOrderBuilderRefreshQuotes === 'function') {
      try {
        window.recTmOrderBuilderRefreshQuotes();
      } catch (eOb2) {}
    }
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
    if (!hourlyStrikeTableDbWsUnsub) return;
    try {
      hourlyStrikeTableDbWsUnsub();
    } catch (e) {}
    hourlyStrikeTableDbWsUnsub = null;
  }

  function connectStrikeTableDbWs() {
    if (!window.recRealtimeWsCoordinator || typeof window.recRealtimeWsCoordinator.subscribe !== 'function') {
      return;
    }
    if (hourlyStrikeTableDbWsUnsub) return;
    disconnectStrikeTableDbWs();
    const wsUrl = dbChangesWebSocketUrl();
    hourlyStrikeTableDbWsUnsub = window.recRealtimeWsCoordinator.subscribe(wsUrl, {
      includeLiveSymbolSpot: true,
      onlyDbStreams: [
        'strike_table_hourly',
        'strike_table_15m',
        'market_kalshi_hourly',
        'market_kalshi_15m',
        'orderbook_kalshi',
        'monitor_list',
      ],
      onOpen: function () {
        void fetchLiveSymbolSpotBootstrap();
      },
      onMessage: function (event) {
        try {
          const parse =
            typeof recRealtimeWsJson === 'function' ? recRealtimeWsJson(event) : JSON.parse(event.data);
          const msg = parse;
          if (msg && msg.type === 'live_symbol_spot') {
            applyLiveSymbolSpotMessage(msg);
            return;
          }
          if (msg && msg.type === 'db_change') {
            if (msg.database === 'orderbook_kalshi') {
              scheduleExpandedOrderbookRefreshFromWs();
              return;
            }
            if (
              msg.database === 'strike_table_hourly' ||
              msg.database === 'strike_table_15m' ||
              msg.database === 'market_kalshi_hourly' ||
              msg.database === 'market_kalshi_15m'
            ) {
              scheduleStrikeTableRefreshFromWs();
            }
            if (msg.database === 'monitor_list') {
              try {
                window.dispatchEvent(new CustomEvent('rec:tm-db-monitor-list'));
              } catch (e3) {}
            }
          }
        } catch (e2) {}
      },
    });
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
    hourlyHeaderLastFetchSymbol = '';
    lastMarketMode = mkt;

    quoteRow.classList.add('u-hidden');
    bookPanel.classList.add('u-hidden');
    strikeListEl.classList.remove('u-hidden');
    isBookVisible = false;
    connectStrikeTableDbWs();
  }

  function requestDataRefresh() {
    if (refreshTimer) return;
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      void refreshDataNow();
    }, 40);
  }

  async function refreshDataNow() {
    if (refreshBusy) {
      refreshPending = true;
      return;
    }
    refreshBusy = true;
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
      refreshBusy = false;
      if (refreshPending) {
        refreshPending = false;
        requestDataRefresh();
      }
    }
  }

  async function runDataTick() {
    const mkt = currentMarket();
    switchLayoutForMarket(mkt);
    const symNow = currentSymbol();
    if (symNow !== hourlyHeaderLastFetchSymbol) {
      hourlyHeaderLastFetchSymbol = symNow;
      clearMarketExpiration();
    }
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
      try {
        window.__recTmStrikeTableHeaderPrice =
          hourlyCurrentPrice != null && Number.isFinite(hourlyCurrentPrice) ? hourlyCurrentPrice : null;
      } catch (eHdr) {}
      const spotForVisibility = hourlySpotPrice();
      const fetchedRows = applyHourlyStrikeAskVisibility(rawRows, spotForVisibility);
      if (symNow !== currentSymbol() || mkt !== currentMarket()) {
        return;
      }
      const nextStructSig = hourlyStructureSignature(fetchedRows);
      const nextSig = hourlyQuotesSignature(fetchedRows);
      hourlyStrikeRows = fetchedRows;
      ensureHourlyExpandedTicker();
      if (nextStructSig !== lastHourlyStructureSignature) {
        lastHourlyStructureSignature = nextStructSig;
        lastHourlyRowsSignature = nextSig;
        // Re-arm centering when the strike ladder structure changes (e.g. initial 1-row -> full rows hydrate).
        centerAtmStrikeOnNextRender = true;
        renderHourlyRows();
      } else if (nextSig !== lastHourlyRowsSignature) {
        lastHourlyRowsSignature = nextSig;
        patchHourlyRowQuotesInPlace();
      }
    } else if (errEl) {
      errEl.classList.remove('u-hidden');
      errEl.textContent = 'No strike table data';
      try {
        window.__recTmStrikeTableHeaderPrice = null;
      } catch (eHdr2) {}
    }
    if (hourlyStrikeRows.length) syncStrikeTableAtmMarker();
    await refreshExpandedHourlyOrderbookIfOpen();
  }

  try {
    window.addEventListener('rec:live-symbol-spot', function () {
      applyHeaderTtcToClock();
      reapplyHourlyStrikeVisibilityFromSpot();
      if (hourlyStrikeRows.length) syncStrikeTableAtmMarker();
    });
  } catch (e) {}

  if (document.body && document.body.classList.contains('trade-monitor-new-page')) {
    const symPick = document.getElementById('ticker-picker');
    if (symPick) {
      symPick.addEventListener('change', function () {
        window.tmNewRefreshLiveSpotPanel();
        requestDataRefresh();
      });
    }
    (function installTmNewObStrikeListDelegation() {
      const root = document.getElementById('hourlyStrikeList');
      if (!root || root.dataset.tmNewObStrikePickBound) return;
      root.dataset.tmNewObStrikePickBound = '1';
      root.addEventListener('click', function (ev) {
        const yesPill = ev.target.closest && ev.target.closest('.hourly-ask-pill-yes');
        const noPill = ev.target.closest && ev.target.closest('.hourly-ask-pill-no');
        if (!yesPill && !noPill) return;
        const tr = ev.target.closest && ev.target.closest('tr.hourly-strike-data-row');
        if (!tr) return;
        const ticker = tr.getAttribute('data-hourly-ticker');
        if (!ticker) return;
        try {
          window.dispatchEvent(
            new CustomEvent('rec:tm-order-builder-pick', {
              detail: { ticker: String(ticker), side: yesPill ? 'yes' : 'no' },
            })
          );
        } catch (ePill) {}
      });
    })();
    window.addEventListener('rec:tm-monitor-changed', function () {
      hourlyHeaderLastFetchSymbol = '';
      lastHourlyRowsSignature = '';
      lastHourlyStructureSignature = '';
      lastExpandedOrderbookSignature = '';
      centerAtmStrikeOnNextRender = true;
      requestDataRefresh();
    });
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        connectStrikeTableDbWs();
      });
    } else {
      connectStrikeTableDbWs();
    }
  }

  window.recTmGetHourlyStrikeRow = function (ticker) {
    const t = String(ticker || '');
    return hourlyStrikeRows.find((r) => String(r.ticker) === t) || null;
  };
  window.recTmFmtStrike = fmtStrike;
  window.recTmFmtAsk = fmtAsk;

  ensureInitialVisibility();
  centerAtmStrikeOnNextRender = true;
  requestDataRefresh();
})();
