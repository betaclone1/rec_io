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
  /** Latest WS orderbook per ticker — repaint after strike-table DOM rebuild. */
  const lastLiveOrderbookByTicker = Object.create(null);

  /**
   * Countdown uses only Kalshi ticker → expiration (America/New_York), not DB ttc_* columns.
   * UTC epoch ms; recomputed when marketExpireSourceKey (ticker string) changes.
   */
  let marketExpireAtMs = null;
  let marketExpireSourceKey = '';
  let ttcTimer = null;
  let hourlyHeaderLastFetchSymbol = '';
  let hourlyStrikeTableDbWsUnsub = null;
  let hourlyMonitorListDbWsUnsub = null;
  let portfolioDbWsUnsub = null;
  /** Last `live_symbol_spot` frame (Redis → main `/ws/db_changes`); used when symbol/monitor changes. */
  let lastLiveSymbolSpotMsg = null;
  /** Renew server watch while a strike row book stays expanded (hot cache is not throttled). */
  let lastExpandedOrderbookEventTicker = '';

  /** Cached portfolio positions keyed by ticker → {position_fp, avg_price_dollars}. */
  let positionsByTicker = Object.create(null);
  let positionsFetchInFlight = false;

  /** Cached resting orders keyed by ticker → [{price_dollars, remaining_fp, side}]. */
  let restingOrdersByTicker = Object.create(null);
  let ordersFetchInFlight = false;

  /** Strikes with 100¢ on either side are hidden except this many kept around the money line. */
  const MIN_HOURLY_VISIBLE_AROUND_MONEY_LINE = 3;

  /** rAF-coalesce ATM row moves on rapid `live_symbol_spot`. */
  let strikeTableAtmSyncRaf = null;

  /** Apply every WS frame immediately (no client-side rate limit). */
  function createTmUiPassthrough(applyLatest) {
    return {
      schedule: function (arg) {
        applyLatest(arg);
      },
      applyNow: function (arg) {
        applyLatest(arg);
      },
    };
  }

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
    if (hourlyStrikeRows.length) patchHourlyRowQuotesInPlace();
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

  /** True when the document origin and API base differ by hostname (e.g. 127.0.0.1 vs localhost). */
  function dbChangesWebSocketHostsDiffer(pageOriginStr, apiBaseStr) {
    try {
      var p = new URL(pageOriginStr.endsWith('/') ? pageOriginStr : pageOriginStr + '/');
      var a = new URL(String(apiBaseStr || '').replace(/\/?$/, '/') + 'x');
      return p.hostname.toLowerCase() !== a.hostname.toLowerCase();
    } catch (e) {
      return false;
    }
  }

  /**
   * Match ``tmMainApiBase`` host so WS hits the app that forwards Redis (not a static dev origin).
   * Cross-host static tabs (e.g. 127.0.0.1:8091 with API on localhost:3000) do not send cookies on the
   * WS upgrade; append ``token`` so ``tenant_asgi`` can authenticate (same as HTTP query token).
   */
  function tmLiveMarketWebSocketUrl() {
    var base = tmMainApiBase();
    var u;
    try {
      u = new URL(base + '/');
    } catch (e) {
      u = new URL((window.location.origin || '') + '/');
    }
    var wsProto = u.protocol === 'https:' ? 'wss:' : 'ws:';
    var sym = currentSymbol();
    var mkt = currentMarket();
    return (
      wsProto +
      '//' +
      u.host +
      '/ws/live_market?symbol=' +
      encodeURIComponent(sym) +
      '&market=' +
      encodeURIComponent(mkt)
    );
  }

  function tmHasAuthSession() {
    try {
      return !!(localStorage.getItem('rec_auth_token') || '').trim();
    } catch (e) {
      return false;
    }
  }

  function dbChangesWebSocketUrl() {
    var base = tmMainApiBase();
    var u;
    try {
      u = new URL(base + '/');
    } catch (e) {
      u = new URL((window.location.origin || '') + '/');
    }
    var wsProto = u.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = wsProto + '//' + u.host + '/ws/db_changes';
    try {
      var pageOrigin = (window.location.origin || '').replace(/\/$/, '');
      var apiBase = String(base || '').replace(/\/$/, '');
      if (pageOrigin && apiBase && dbChangesWebSocketHostsDiffer(pageOrigin, apiBase)) {
        var tok = '';
        try {
          tok = (localStorage.getItem('rec_auth_token') || '').trim();
        } catch (e2) {}
        if (tok) {
          url += (url.indexOf('?') === -1 ? '?' : '&') + 'token=' + encodeURIComponent(tok);
        }
      }
    } catch (e3) {}
    return url;
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

  function formatTmMomPercentile(momVal, accelVal) {
    const num = Number(momVal);
    if (!Number.isFinite(num)) return 'Mom: —';
    const sign = num > 0 ? '+' : '';
    let text = 'Mom: ' + (num === 0 ? '0' : sign + num.toFixed(1));
    const accel = Number(accelVal);
    if (Number.isFinite(accel)) {
      const aSign = accel > 0 ? '+' : '';
      text += ' (' + (accel === 0 ? '0' : aSign + accel.toFixed(1)) + ')';
    }
    return text;
  }

  function symbolMomentumAccelFromSpotMsg(sym) {
    const raw = (lastLiveSymbolSpotMsg && lastLiveSymbolSpotMsg.momentum_acceleration_by_symbol) || {};
    let val = raw[sym];
    if (val == null) {
      Object.keys(raw).forEach(function (k) {
        if (String(k).trim().toUpperCase() === sym && val == null) val = raw[k];
      });
    }
    if (val != null && Number.isFinite(Number(val))) return Number(val);
    const rows = (lastLiveSymbolSpotMsg && lastLiveSymbolSpotMsg.rows) || [];
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (!r || String(r.symbol || '').trim().toUpperCase() !== sym) continue;
      const rowVal = r.momentum_acceleration;
      if (rowVal != null && Number.isFinite(Number(rowVal))) return Number(rowVal);
    }
    return null;
  }

  function symbolMomentumFromSpotMsg(sym) {
    const raw = (lastLiveSymbolSpotMsg && lastLiveSymbolSpotMsg.momentum_by_symbol) || {};
    let val = raw[sym];
    if (val == null) {
      Object.keys(raw).forEach(function (k) {
        if (String(k).trim().toUpperCase() === sym && val == null) val = raw[k];
      });
    }
    if (val != null && Number.isFinite(Number(val))) return Number(val);
    return null;
  }

  function resolveOrderbookMomDisplay(oneM, sym) {
    if (oneM == null || !Number.isFinite(Number(oneM))) return symbolMomentumFromSpotMsg(sym);
    const n = Number(oneM);
    if (n !== 0) return n;
    const spotMom = symbolMomentumFromSpotMsg(sym);
    if (spotMom != null && spotMom !== 0) return spotMom;
    return n;
  }

  function symbolMomentum1mAvg() {
    const sym = currentSymbol();
    try {
      const bag = window.__liveMomentum1mAvgBySymbol;
      if (bag && bag[sym] != null && Number.isFinite(Number(bag[sym]))) {
        return resolveOrderbookMomDisplay(Number(bag[sym]), sym);
      }
    } catch (eBag) {}
    const raw = (lastLiveSymbolSpotMsg && lastLiveSymbolSpotMsg.momentum_1m_avg_by_symbol) || {};
    let val = raw[sym];
    if (val == null) {
      Object.keys(raw).forEach(function (k) {
        if (String(k).trim().toUpperCase() === sym && val == null) val = raw[k];
      });
    }
    if (val != null && Number.isFinite(Number(val))) return resolveOrderbookMomDisplay(Number(val), sym);
    const rows = (lastLiveSymbolSpotMsg && lastLiveSymbolSpotMsg.rows) || [];
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (!r || String(r.symbol || '').trim().toUpperCase() !== sym) continue;
      const rowVal = r.momentum_1m_avg;
      if (rowVal != null && Number.isFinite(Number(rowVal))) {
        return resolveOrderbookMomDisplay(Number(rowVal), sym);
      }
    }
    return symbolMomentumFromSpotMsg(sym);
  }

  function fmtMidMomHtml(val) {
    const num = Number(val);
    if (!Number.isFinite(num)) return '';
    const snapped = Math.abs(num) < 0.05 ? 0 : num;
    let arrow = '';
    let cls = 'mid-mom mid-mom--flat';
    if (snapped > 0) {
      arrow = '▲';
      cls = 'mid-mom mid-mom--up';
    } else if (snapped < 0) {
      arrow = '▼';
      cls = 'mid-mom mid-mom--down';
    }
    const text = snapped === 0 ? '0' : (snapped > 0 ? '+' : '') + snapped.toFixed(1);
    if (!arrow) {
      return '<span class="' + cls + '"><span class="mid-mom-val">' + text + '</span></span>';
    }
    return (
      '<span class="' +
      cls +
      '"><span class="mid-mom-arrow" aria-hidden="true">' +
      arrow +
      '</span><span class="mid-mom-val">' +
      text +
      '</span></span>'
    );
  }

  /**
   * Postgres live_data → NOTIFY → redis_switchboard → Redis → same-origin `/ws/db_changes`.
   * Payload built in ``backend/redis_switchboard.build_live_symbol_spot_payload``.
   */
  function applyLiveSymbolSpotMessage(msg) {
    if (!msg || msg.type !== 'live_symbol_spot') return;
    lastLiveSymbolSpotMsg = msg;
    try { window.lastLiveSymbolSpotMsg = msg; } catch (eWin) {}
    tmSpotUiThrottle.applyNow(msg);
  }

  function applyLiveSymbolSpotMessageNow(msg) {
    if (!msg || msg.type !== 'live_symbol_spot') return;
    lastLiveSymbolSpotMsg = msg;
    try { window.lastLiveSymbolSpotMsg = msg; } catch (eWin2) {}
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
    const rawMom1m = msg.momentum_1m_avg_by_symbol || {};
    const mom1mNorm = {};
    Object.keys(rawMom1m).forEach(function (k) {
      mom1mNorm[String(k).trim().toUpperCase()] = rawMom1m[k];
    });
    window.__liveMomentum1mAvgBySymbol = mom1mNorm;
    const rawMomAccel = msg.momentum_acceleration_by_symbol || {};
    const momAccelNorm = {};
    Object.keys(rawMomAccel).forEach(function (k) {
      momAccelNorm[String(k).trim().toUpperCase()] = rawMomAccel[k];
    });
    window.__liveMomentumAccelerationBySymbol = momAccelNorm;

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

    const rawMom1mAvg = msg.momentum_1m_avg_by_symbol || {};
    let momVal = rawMom1mAvg[sym];
    if (momVal == null) {
      Object.keys(rawMom1mAvg).forEach(function (k) {
        if (String(k).trim().toUpperCase() === sym && momVal == null) momVal = rawMom1mAvg[k];
      });
    }
    if (momVal == null) {
      const rawMom = msg.momentum_by_symbol || {};
      momVal = rawMom[sym];
      if (momVal == null) {
        Object.keys(rawMom).forEach(function (k) {
          if (String(k).trim().toUpperCase() === sym && momVal == null) momVal = rawMom[k];
        });
      }
    }
    let accelVal = rawMomAccel[sym];
    if (accelVal == null) {
      Object.keys(rawMomAccel).forEach(function (k) {
        if (String(k).trim().toUpperCase() === sym && accelVal == null) accelVal = rawMomAccel[k];
      });
    }
    if (accelVal == null) {
      accelVal = symbolMomentumAccelFromSpotMsg(sym);
    }
    const elMom = document.getElementById('symbol-momentum-value');
    if (elMom) elMom.textContent = formatTmMomPercentile(momVal, accelVal);

    try {
      window.dispatchEvent(new CustomEvent('rec:live-symbol-spot', { detail: msg }));
    } catch (e) {}
    refreshExpandedOrderbookMidMom();
  }

  const tmSpotUiThrottle = createTmUiPassthrough(applyLiveSymbolSpotMessageNow);

  window.tmNewRefreshLiveSpotPanel = function () {
    if (lastLiveSymbolSpotMsg) {
      tmSpotUiThrottle.applyNow(lastLiveSymbolSpotMsg);
    }
  };

  /** Global live_data (strike ladder, spot bootstrap, orderbook watch) — no tenant session. */
  function tmGlobalApiFetch(path, init) {
    init = init || {};
    if (init.credentials === undefined) init.credentials = 'include';
    const base = tmMainApiBase();
    const pathNorm = path.charAt(0) === '/' ? path : '/' + path;
    return fetch(base + pathNorm, init);
  }

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


  function orderbookPortfolioSubaccount() {
    var raw = typeof window !== 'undefined' && window.__HFT_ORDERBOOK_SUBACCOUNT__;
    if (raw != null && raw !== '') {
      var n = Number(raw);
      if (Number.isFinite(n)) return n;
    }
    return 1;
  }

  function parseRemainingFp(o) {
    var rem = o.remaining_count_fp;
    if (rem == null || rem === '') rem = o.remaining_count;
    var n = Number(rem);
    return Number.isFinite(n) ? n : 0;
  }

  function parseYesPriceDollars(o) {
    var yp = o.yes_price_dollars;
    if (yp != null && yp !== '') {
      var n = Number(yp);
      if (Number.isFinite(n)) return n;
    }
    var p = o.price;
    if (p != null && p !== '' && p !== '--') {
      var n2 = Number(p);
      if (Number.isFinite(n2)) return n2;
    }
    return NaN;
  }

  /**
   * Average YES fill price for orderbook badges (always YES-book cents on YES tab).
   * Kalshi position_cost / market_exposure for short YES (negative fp) is NO-side
   * notional — complement to get YES fill (e.g. cost 0.87, fp -1 → 13c YES).
   */
  function avgYesPriceFromPosition(p, fallbackYes) {
    var fp = Number(p.position_fp);
    if (!Number.isFinite(fp) || Math.abs(fp) < 1e-6) return NaN;

    function yesAvgFromExposureDollars(dollars) {
      if (!Number.isFinite(dollars) || Math.abs(dollars) <= 0) return NaN;
      var perContract = Math.abs(dollars / fp);
      if (perContract <= 0 || perContract >= 1) return NaN;
      if (fp < 0) {
        return 1 - perContract;
      }
      return perContract;
    }

    var cost = Number(p.position_cost_dollars);
    var avg = yesAvgFromExposureDollars(cost);
    if (Number.isFinite(avg)) return avg;

    var exp = Number(p.market_exposure_dollars);
    avg = yesAvgFromExposureDollars(exp);
    if (Number.isFinite(avg)) return avg;

    var fb = Number(fallbackYes);
    if (Number.isFinite(fb) && fb > 0 && fb < 1) return fb;
    return NaN;
  }

  function ingestRestingOrderRow(next, o, fallbackTicker) {
    var tk = String(o.ticker || fallbackTicker || '').trim();
    if (!tk) return;
    var rem = parseRemainingFp(o);
    if (rem <= 0) return;
    var yesD = parseYesPriceDollars(o);
    if (!Number.isFinite(yesD)) return;
    var side = String(o.orderbook_side || o.side || '').toLowerCase();
    if (side !== 'bid' && side !== 'ask') return;
    if (!next[tk]) next[tk] = [];
    var key = Math.round(yesD * 100) + ':' + side;
    for (var i = 0; i < next[tk].length; i++) {
      var ex = next[tk][i];
      var exKey = Math.round(ex.yes_price_dollars * 100) + ':' + ex.side;
      if (exKey === key) {
        ex.remaining_fp += rem;
        return;
      }
    }
    next[tk].push({
      yes_price_dollars: yesD,
      no_price_dollars: 1 - yesD,
      remaining_fp: rem,
      side: side,
    });
  }

  function applyHftPortfolioSnapshot(positions, orders, opts) {
    opts = opts || {};
    if (opts.subaccount != null) window.__HFT_ORDERBOOK_SUBACCOUNT__ = Number(opts.subaccount);
    var subFilter = orderbookPortfolioSubaccount();
    var activeTicker = String(opts.activeTicker || '').trim();
    var entryPrice = opts.entryPrice;

    var nextPos = Object.create(null);
    (positions || []).forEach(function (p) {
      if (Number(p.subaccount || 1) !== subFilter) return;
      var tk = String(p.ticker || p.market_ticker || '').trim();
      var fp = Number(p.position_fp);
      if (!tk || !Number.isFinite(fp) || Math.abs(fp) < 1e-6) return;
      var fb = tk === activeTicker ? entryPrice : null;
      var avg = avgYesPriceFromPosition(p, fb);
      if (!Number.isFinite(avg)) return;
      nextPos[tk] = { position_fp: fp, avg_price_dollars: avg };
    });
    positionsByTicker = nextPos;

    var nextOrd = Object.create(null);
    (orders || []).forEach(function (o) {
      ingestRestingOrderRow(nextOrd, o, activeTicker);
    });
    restingOrdersByTicker = nextOrd;
    restoreExpandedOrderbookAfterStrikeRender();
  }

  function expandOrderbookTicker(ticker) {
    var t = String(ticker || '').trim();
    if (!t) return;
    if (!hourlyStrikeRows.length || !hourlyStrikeRows.some(function (r) { return r.ticker === t; })) {
      window.__HFT_PENDING_EXPAND_TICKER__ = t;
      return;
    }
    window.__HFT_PENDING_EXPAND_TICKER__ = '';
    if (expandedHourlyTicker === t) {
      fetchPortfolioPositions();
      fetchRestingOrders();
      restoreExpandedOrderbookAfterStrikeRender();
      return;
    }
    expandedHourlyTicker = t;
    var st = hourlyExpandedState(t);
    st.autoCenter = true;
    st.userScrolled = false;
    st.lastScrollTop = 0;
    setTradeMonitorOrderbookWatch(t);
    renderHourlyRows();
  }

  function refreshOrderbookPortfolio() {
    fetchPortfolioPositions();
    fetchRestingOrders();
  }

  function fetchPortfolioPositions() {
    if (positionsFetchInFlight) return;
    positionsFetchInFlight = true;
    var subFilter = orderbookPortfolioSubaccount();
    tmMainApiFetch('/api/db/positions', { cache: 'no-store' })
      .then(function (res) { return res && res.ok ? res.json() : null; })
      .then(function (data) {
        positionsFetchInFlight = false;
        if (!data || !Array.isArray(data.positions)) return;
        var next = Object.create(null);
        data.positions.forEach(function (p) {
          if (Number(p.subaccount || 1) !== subFilter) return;
          var tk = String(p.ticker || p.market_ticker || '').trim();
          var fp = Number(p.position_fp);
          if (!tk || !Number.isFinite(fp) || Math.abs(fp) < 1e-6) return;
          var avg = avgYesPriceFromPosition(p, null);
          if (!Number.isFinite(avg)) return;
          next[tk] = { position_fp: fp, avg_price_dollars: avg };
        });
        positionsByTicker = next;
        restoreExpandedOrderbookAfterStrikeRender();
      })
      .catch(function () { positionsFetchInFlight = false; });
  }

  function fetchRestingOrders() {
    if (ordersFetchInFlight) return;
    ordersFetchInFlight = true;
    tmMainApiFetch('/api/db/orders', { cache: 'no-store' })
      .then(function (res) { return res && res.ok ? res.json() : null; })
      .then(function (data) {
        ordersFetchInFlight = false;
        if (!data || !Array.isArray(data.orders)) return;
        var next = Object.create(null);
        var subFilter = orderbookPortfolioSubaccount();
        data.orders.forEach(function (o) {
          if (String(o.status || '').toLowerCase() !== 'resting') return;
          var sa = Number(o.subaccount || 1);
          if (sa !== subFilter) return;
          ingestRestingOrderRow(next, o, '');
        });
        restingOrdersByTicker = next;
        restoreExpandedOrderbookAfterStrikeRender();
      })
      .catch(function () { ordersFetchInFlight = false; });
  }

  function restingOrdersForTicker(ticker) {
    return restingOrdersByTicker[String(ticker || '').trim()] || [];
  }

  function restingOrderBadgeHtml(remaining, side) {
    var sign = side === 'bid' ? '+' : '-';
    var qty = trimFracZeros(remaining.toFixed(2));
    return '<span class="ob-resting-badge"><span class="ob-resting-clock">\u25F7</span>' + sign + qty + '</span>';
  }

  function buildRestingByPrice(orders, bookMode) {
    var byPrice = Object.create(null);
    if (!orders || !orders.length) return byPrice;
    orders.forEach(function (o) {
      var priceDollars = bookMode === 'no' ? o.no_price_dollars : o.yes_price_dollars;
      var key = Math.round(priceDollars * 100);
      if (byPrice[key]) {
        byPrice[key].remaining_fp += o.remaining_fp;
      } else {
        byPrice[key] = { remaining_fp: o.remaining_fp, side: o.side };
      }
    });
    return byPrice;
  }

  function positionForTicker(ticker) {
    return positionsByTicker[String(ticker || '').trim()] || null;
  }

  function positionBadgeHtml(pos, bookMode) {
    if (!pos) return '';
    var fp = pos.position_fp;
    var avgYes = pos.avg_price_dollars;
    if (!Number.isFinite(avgYes) || avgYes <= 0 || avgYes >= 1) return '';
    var avgCents = Math.round((bookMode === 'no' ? 1 - avgYes : avgYes) * 100);
    var sign = fp > 0 ? '+' : '';
    var qty = trimFracZeros(Math.abs(fp).toFixed(2));
    return '<span class="ob-position-badge">' + sign + (fp > 0 ? '' : '\u2212') + qty + ' @ ' + avgCents + '\u00A2</span>';
  }

  function positionAvgBookPrice(pos, bookMode) {
    if (!pos) return null;
    var avgYes = pos.avg_price_dollars;
    if (!Number.isFinite(avgYes) || avgYes <= 0 || avgYes >= 1) return null;
    return bookMode === 'no' ? 1 - avgYes : avgYes;
  }

  function closestPositionRowMatch(rows, pos, bookMode) {
    var avgBook = positionAvgBookPrice(pos, bookMode);
    if (avgBook == null || !rows || !rows.length) return { idx: -1, dist: Infinity };
    var bestIdx = -1;
    var bestDist = Infinity;
    for (var i = 0; i < rows.length; i++) {
      var p = Number(rows[i].price || 0);
      if (!Number.isFinite(p)) continue;
      var d = Math.abs(p - avgBook);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
    }
    return { idx: bestIdx, dist: bestDist };
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

  function fairYesDollarsForTicker(ticker) {
    const mt = String(ticker || '').trim();
    if (!mt) return null;
    const row = hourlyRawStrikeRows.find((r) => String(r.ticker) === mt);
    if (!row) return null;
    return parseDollarField(row.fairPrice);
  }

  function fairBookDollarsForMode(fairYesDollars, bookMode) {
    if (fairYesDollars == null || !Number.isFinite(fairYesDollars)) return null;
    return bookMode === 'no' ? 1 - fairYesDollars : fairYesDollars;
  }

  function closestFairPriceMatch(asks, bids, fairBookDollars) {
    if (fairBookDollars == null || !Number.isFinite(fairBookDollars)) return null;
    let best = null;
    let bestDist = Infinity;
    (asks || []).forEach((r, i) => {
      const p = Number(r.price || 0);
      if (!Number.isFinite(p)) return;
      const d = Math.abs(p - fairBookDollars);
      if (d < bestDist) {
        bestDist = d;
        best = { section: 'asks', index: i, fairDollars: fairBookDollars };
      }
    });
    (bids || []).forEach((r, i) => {
      const p = Number(r.price || 0);
      if (!Number.isFinite(p)) return;
      const d = Math.abs(p - fairBookDollars);
      if (d < bestDist) {
        bestDist = d;
        best = { section: 'bids', index: i, fairDollars: fairBookDollars };
      }
    });
    return best;
  }

  function bestTouchPricesDollars(asks, bids) {
    let bestAsk = null;
    (asks || []).forEach((r) => {
      const p = Number(r.price);
      if (!Number.isFinite(p)) return;
      if (bestAsk == null || p < bestAsk) bestAsk = p;
    });
    let bestBid = null;
    (bids || []).forEach((r) => {
      const p = Number(r.price);
      if (!Number.isFinite(p)) return;
      if (bestBid == null || p > bestBid) bestBid = p;
    });
    return { bestAsk: bestAsk, bestBid: bestBid };
  }

  function bookMidpointDollars(asks, bids) {
    const touch = bestTouchPricesDollars(asks, bids);
    if (touch.bestAsk == null || touch.bestBid == null) return null;
    return (touch.bestAsk + touch.bestBid) / 2;
  }

  function enrichOrderbookLiveStats(msg, ticker) {
    if (!msg) return msg;
    const fairYes = fairYesDollarsForTicker(ticker);
    const bookLive = { yes: {}, no: {} };
    ['yes', 'no'].forEach((bookMode) => {
      const book = bookMode === 'yes' ? msg.trade_yes || {} : msg.trade_no || {};
      const asks = book.asks || [];
      const bids = book.bids || [];
      const midpoint = bookMidpointDollars(asks, bids);
      const fairBook = fairBookDollarsForMode(fairYes, bookMode);
      const fairPriceDiff =
        midpoint != null && fairBook != null ? fairBook - midpoint : null;
      bookLive[bookMode] = {
        midpoint: midpoint,
        fair_price_diff: fairPriceDiff,
        best_ask: bestTouchPricesDollars(asks, bids).bestAsk,
        best_bid: bestTouchPricesDollars(asks, bids).bestBid,
      };
    });
    msg.book_live = bookLive;
    return msg;
  }

  function buildFairMatch(asks, bids, ticker, bookMode) {
    const fairYes = fairYesDollarsForTicker(ticker);
    const fairBook = fairBookDollarsForMode(fairYes, bookMode);
    const fairMatch = closestFairPriceMatch(asks, bids, fairBook);
    if (!fairMatch) return fairMatch;
    const midpoint = bookMidpointDollars(asks, bids);
    fairMatch.midpoint = midpoint;
    fairMatch.fairPriceDiff =
      midpoint != null && fairBook != null ? fairBook - midpoint : null;
    return fairMatch;
  }

  function fmtFairPriceDiffHtml(diffDollars) {
    if (diffDollars == null || !Number.isFinite(diffDollars)) return '';
    const cents = Math.round(diffDollars * 100);
    const text = cents > 0 ? '+' + String(cents) : String(cents);
    let cls = 'book-fair-diff book-fair-diff--zero';
    if (cents > 0) cls = 'book-fair-diff book-fair-diff--pos';
    else if (cents < 0) cls = 'book-fair-diff book-fair-diff--neg';
    return '<span class="' + cls + '">' + text + '</span>';
  }

  function fmtBookPriceCell(levelPriceDollars, fairMatch, section, rowIndex) {
    const levelHtml = fmtPrice(levelPriceDollars);
    const isFair =
      fairMatch && fairMatch.section === section && fairMatch.index === rowIndex;
    if (!isFair) return levelHtml;
    const fairHtml = fmtWholeCentsFromDollars(fairMatch.fairDollars);
    const diffHtml = fmtFairPriceDiffHtml(fairMatch.fairPriceDiff);
    return (
      '<span class="book-fair-price">' +
      'Fair price: ' +
      fairHtml +
      diffHtml +
      '</span>' +
      levelHtml
    );
  }

  function rowsToHtml(rows, sideLabel, labelRowIndex, section, fairMatch, posIdx, pos, restingByPrice) {
    return (rows || [])
      .map((r, i) => {
        const p = Number(r.price || 0);
        const c = Number(r.size_fp || 0);
        const t = Number(r.total_dollars || 0);
        const side = i === labelRowIndex ? sideLabel : '';
        const sideCls = side ? 'book-side-label' : 'side-col';
        const isFair =
          fairMatch && fairMatch.section === section && fairMatch.index === i;
        const priceCls = isFair ? 'book-price-cell book-price-cell--fair' : 'book-price-cell';
        const priceInner = fmtBookPriceCell(p, fairMatch, section, i);
        const posBadge = i === posIdx ? positionBadgeHtml(pos, mode) : '';
        const priceKey = Math.round(p * 100);
        const resting = restingByPrice && restingByPrice[priceKey];
        const restBadge = resting ? restingOrderBadgeHtml(resting.remaining_fp, resting.side) : '';
        return `<tr><td class="${sideCls}">${side}</td><td class="${priceCls}">${priceInner}</td><td class="book-contracts-cell">${posBadge}<span class="book-contracts-val">${fmtContracts(c)}${restBadge}</span></td><td>${fmtTotalDollars(t)}</td></tr>`;
      })
      .join('');
  }

  function refreshExpandedOrderbookFairMarker() {
    const mt = String(expandedHourlyTicker || '').trim();
    if (!mt) return;
    const cached = lastLiveOrderbookByTicker[mt];
    if (!cached) return;
    const root = document.getElementById('hourlyStrikeList');
    if (!root) return;
    const mount = root.querySelector('[data-hourly-expanded="' + mt + '"]');
    if (!mount || !mount.querySelector('[data-hourly-scroll]')) return;
    enrichOrderbookLiveStats(cached, mt);
    patchOrderbookInto(mount, cached, mt);
  }

  function refreshExpandedOrderbookMidMom() {
    const mt = String(expandedHourlyTicker || '').trim();
    if (!mt) return;
    const cached = lastLiveOrderbookByTicker[mt];
    if (!cached) return;
    const root = document.getElementById('hourlyStrikeList');
    if (!root) return;
    const mount = root.querySelector('[data-hourly-expanded="' + mt + '"]');
    if (!mount) return;
    const midEl = mount.querySelector('[data-hourly-mid="' + mt + '"]');
    if (!midEl) return;
    midEl.innerHTML = buildMidCellInner(mode, cached.last_trade, cached.receive_latency_ms);
  }

  /** ms from server delta stamp (msg.ts_ms) to client receive/cache apply. */
  function stampReceiveLatencyMs(msg) {
    if (!msg) return null;
    if (Number.isFinite(msg.receive_latency_ms) && msg.receive_latency_ms >= 0) {
      return msg.receive_latency_ms;
    }
    const tsMs = Number(msg.ts_ms);
    if (!Number.isFinite(tsMs) || tsMs <= 0) {
      delete msg.receive_latency_ms;
      return null;
    }
    const latencyMs = Date.now() - tsMs;
    msg.receive_latency_ms = latencyMs;
    return latencyMs;
  }

  function fmtMidLatencyHtml(latencyMs) {
    if (!obLatencyTestEnabled()) return '';
    if (!Number.isFinite(latencyMs) || latencyMs < 0) return '';
    return (
      '<span class="mid-latency" title="ms since server recorded delta">' +
      Math.round(latencyMs) +
      'ms</span>'
    );
  }

  function buildMidCellInner(mode, lastTrade, receiveLatencyMs) {
    const lt = lastTrade || {};
    const cents = mode === 'yes' ? lt.yes_cents || '' : lt.no_cents || '';
    const price = cents || '—';
    const momHtml = fmtMidMomHtml(symbolMomentum1mAvg());
    const latHtml = fmtMidLatencyHtml(receiveLatencyMs);
    return (
      '<span class="mid-inner"><span class="mid-center-group"><span class="mid-last-wrap"><span class="mid-last">Last</span><span class="mid-price">' +
      price +
      '</span></span></span>' +
      momHtml +
      latHtml +
      '</span>'
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

  function applyHeaderTtcFromPack(pack) {
    if (!pack) return false;
    const eventRef = pack.eventTicker && String(pack.eventTicker).trim();
    const rowRef =
      pack.rows && pack.rows[0] && pack.rows[0].ticker && String(pack.rows[0].ticker).trim();
    const ref = eventRef || rowRef || '';
    const eventKey = ref ? kalshiEventRefKey(ref) : '';
    if (eventKey && eventKey !== marketExpireSourceKey) {
      clearMarketExpiration();
    }
    const endMs =
      pack.settlementEndMs != null && Number.isFinite(Number(pack.settlementEndMs))
        ? Number(pack.settlementEndMs)
        : null;
    if (endMs != null) {
      marketExpireSourceKey = eventKey || marketExpireSourceKey;
      marketExpireAtMs = endMs;
      applyHeaderTtcToClock();
      return true;
    }
    const packSec =
      pack.ttcSeconds != null && pack.ttcSeconds !== '' && Number.isFinite(Number(pack.ttcSeconds))
        ? Number(pack.ttcSeconds)
        : null;
    if (packSec != null) {
      marketExpireSourceKey = eventKey || marketExpireSourceKey;
      marketExpireAtMs = Date.now() + packSec * 1000;
      applyHeaderTtcToClock();
      return true;
    }
    if (ref && armExpirationFromTicker(ref)) {
      applyHeaderTtcToClock();
      return true;
    }
    return false;
  }

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
    if (wEl) {
      const nextWindow = monitorNumber + ' \u2022 ' + (mt || '');
      if (wEl.textContent !== nextWindow) wEl.textContent = nextWindow;
    }
    if (!applyHeaderTtcFromPack(pack)) {
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
    return pinExpandedStrikeInVisibleRows(out);
  }

  /** Keep the expanded strike visible even when 100¢ filter would hide it. */
  function pinExpandedStrikeInVisibleRows(rows) {
    const list = rows || [];
    const mt = String(expandedHourlyTicker || '').trim();
    if (!mt || !list.length) return list;
    if (list.some((r) => String(r.ticker) === mt)) return list;
    const src = hourlyRawStrikeRows.length ? hourlyRawStrikeRows : list;
    const extra = src.find((r) => String(r.ticker) === mt);
    if (!extra) return list;
    const out = list.slice();
    out.push(extra);
    out.sort((a, b) => Number(a.strike || 0) - Number(b.strike || 0));
    return out;
  }

  const obLatencyStats = {
    samples: [],
    last: null,
    p50_ms: null,
    p95_ms: null,
  };

  function obLatencyTestEnabled() {
    try {
      if (window.__REC_OB_LATENCY_TEST__) return true;
      return new URLSearchParams(window.location.search || '').get('ob_latency') === '1';
    } catch (e) {
      return false;
    }
  }

  function recordOrderbookCacheApplyLatency(msg) {
    if (!msg) return;
    const latencyMs = msg.receive_latency_ms;
    if (!Number.isFinite(latencyMs) || latencyMs < 0) return;
    window.__recObLastReceiveLatency = {
      market_ticker: String(msg.market_ticker || ''),
      book_seq: msg.book_seq != null ? msg.book_seq : null,
      ts_ms: msg.ts_ms != null ? Number(msg.ts_ms) : null,
      receive_latency_ms: latencyMs,
      received_ms: Date.now(),
    };
    if (!obLatencyTestEnabled()) return;
    const tsMs = Number(msg.ts_ms);
    if (!Number.isFinite(tsMs) || tsMs <= 0) return;
    const appliedMs = Date.now();
    obLatencyStats.last = {
      market_ticker: String(msg.market_ticker || ''),
      book_seq: msg.book_seq != null ? msg.book_seq : null,
      ts_ms: tsMs,
      applied_ms: appliedMs,
      latency_ms: latencyMs,
    };
    obLatencyStats.samples.push(latencyMs);
    if (obLatencyStats.samples.length > 500) obLatencyStats.samples.shift();
    const sorted = obLatencyStats.samples.slice().sort(function (a, b) {
      return a - b;
    });
    const n = sorted.length;
    obLatencyStats.p50_ms = sorted[Math.floor(n * 0.5)] || latencyMs;
    obLatencyStats.p95_ms = sorted[Math.floor(Math.min(n - 1, Math.floor(n * 0.95)))] || latencyMs;
    window.__recObLatencyStats = obLatencyStats;
    console.log(
      '[ob-latency]',
      obLatencyStats.last.market_ticker,
      'seq=' + String(obLatencyStats.last.book_seq),
      latencyMs + 'ms',
      'p50=' + obLatencyStats.p50_ms + 'ms',
      'p95=' + obLatencyStats.p95_ms + 'ms',
      'n=' + n
    );
  }

  function cacheLiveOrderbookPayload(msg) {
    const mt = String((msg && msg.market_ticker) || '').trim();
    if (!mt || !msg) return;
    stampReceiveLatencyMs(msg);
    recordOrderbookCacheApplyLatency(msg);
    enrichOrderbookLiveStats(msg, mt);
    lastLiveOrderbookByTicker[mt] = msg;
  }

  function restoreExpandedOrderbookAfterStrikeRender() {
    const mt = String(expandedHourlyTicker || '').trim();
    if (!mt) return;
    const root = document.getElementById('hourlyStrikeList');
    if (!root) return;
    const mount = root.querySelector('[data-hourly-expanded="' + mt + '"]');
    if (!mount) return;
    const cached = lastLiveOrderbookByTicker[mt];
    if (!cached) return;
    renderOrderbookInto(mount, cached, mt);
    lastExpandedOrderbookSignature = JSON.stringify({
      ticker: cached.market_ticker || '',
      mode: mode,
      yes: cached.trade_yes || {},
      no: cached.trade_no || {},
      last: cached.last_trade || {},
    });
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
      if (!expandedHourlyTicker) centerAtmStrikeOnNextRender = true;
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

  function ladderMessageSymbol(msg) {
    if (!msg || msg.symbol == null) return '';
    return String(msg.symbol).trim().toUpperCase();
  }

  function ladderMessageMarket(msg) {
    const m = msg && msg.market != null ? String(msg.market).trim().toLowerCase() : '';
    return m === 'hourly' ? 'hourly' : '15m';
  }

  function applyStrikePackToDom(pack, mkt) {
    const symNow = currentSymbol();
    if (mkt !== currentMarket()) return;
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
      if (symNow !== currentSymbol() || mkt !== currentMarket()) return;
      const nextStructSig = hourlyStructureSignature(fetchedRows);
      const nextSig = hourlyQuotesSignature(fetchedRows);
      hourlyStrikeRows = fetchedRows;
      migrateExpandedTickerOnLadderRefresh(pack);
      ensureHourlyExpandedTicker();
      if (nextStructSig !== lastHourlyStructureSignature) {
        lastHourlyStructureSignature = nextStructSig;
        lastHourlyRowsSignature = nextSig;
        if (!expandedHourlyTicker) centerAtmStrikeOnNextRender = true;
        renderHourlyRows();
      } else if (nextSig !== lastHourlyRowsSignature) {
        lastHourlyRowsSignature = nextSig;
        patchHourlyRowQuotesInPlace();
      }
      refreshExpandedOrderbookFairMarker();
    } else if (errEl) {
      errEl.classList.remove('u-hidden');
      errEl.textContent = 'No strike table data';
      try {
        window.__recTmStrikeTableHeaderPrice = null;
      } catch (eHdr2) {}
    }
    if (hourlyStrikeRows.length) syncStrikeTableAtmMarker();
  }

  function applyLiveStrikeLadderWs(msg) {
    if (!msg || msg.type !== 'live_strike_ladder') return;
    if (ladderMessageSymbol(msg) !== currentSymbol()) return;
    if (ladderMessageMarket(msg) !== currentMarket()) return;
    switchLayoutForMarket(currentMarket());
    const pack = {
      rows: [],
      currentPrice: null,
      marketTitle: null,
      ttcSeconds: null,
      settlementEndMs: null,
      eventTicker: null,
      headerSymbol: null,
      fetchFailed: true,
    };
    if (!msg.error) {
      const strikesArr = Array.isArray(msg.strikes) ? msg.strikes : [];
      const cpRaw = msg.current_price;
      pack.currentPrice =
        cpRaw != null && cpRaw !== '' && !isNaN(Number(cpRaw)) ? Number(cpRaw) : null;
      pack.marketTitle =
        msg.market_title != null && String(msg.market_title).trim() !== ''
          ? String(msg.market_title).trim()
          : null;
      pack.ttcSeconds =
        msg.ttc_seconds != null && msg.ttc_seconds !== '' && !isNaN(Number(msg.ttc_seconds))
          ? Number(msg.ttc_seconds)
          : msg.ttc != null && !isNaN(Number(msg.ttc))
            ? Number(msg.ttc)
            : null;
      pack.settlementEndMs =
        msg.settlement_end_ms != null && !isNaN(Number(msg.settlement_end_ms))
          ? Number(msg.settlement_end_ms)
          : null;
      pack.eventTicker =
        msg.event_ticker != null && String(msg.event_ticker).trim() !== ''
          ? String(msg.event_ticker).trim()
          : null;
      pack.headerSymbol = ladderMessageSymbol(msg);
      pack.rows = strikesArr
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
          fairPrice: parseDollarField(s.fair_price),
        }))
        .sort((a, b) => Number(a.strike || 0) - Number(b.strike || 0));
      pack.fetchFailed = false;
    }
    applyStrikePackToDom(pack, ladderMessageMarket(msg));
  }

  const tmStrikeLadderUiThrottle = createTmUiPassthrough(applyLiveStrikeLadderWs);

  function scheduleApplyLiveStrikeLadder(msg, options) {
    if (options && options.immediate) {
      tmStrikeLadderUiThrottle.applyNow(msg);
      return;
    }
    tmStrikeLadderUiThrottle.schedule(msg);
  }

  function fetchLiveStrikeLadderBootstrap(options) {
    const sym = currentSymbol();
    const mkt = currentMarket();
    const path =
      '/api/trade-monitor/strike-ladder?symbol=' +
      encodeURIComponent(sym) +
      '&market=' +
      encodeURIComponent(mkt);
    return tmGlobalApiFetch(path, { cache: 'no-store' })
      .then(function (res) {
        return res.json().then(function (data) {
          return { res: res, data: data };
        });
      })
      .then(function (pair) {
        const res = pair && pair.res;
        const data = pair && pair.data;
        if (!res || !res.ok || !data || data.error) return;
        const strikes = Array.isArray(data.strikes) ? data.strikes : [];
        if (!strikes.length) return;
        if (!data.type) data.type = 'live_strike_ladder';
        data.symbol = sym;
        data.market = mkt;
        scheduleApplyLiveStrikeLadder(data, options);
      })
      .catch(function () {});
  }

  function normalizeOrderbookPayload(d) {
    if (!d || d.error) return null;
    if (d.type === 'live_orderbook') return d;
    if (!d.market_ticker && !d.trade_yes && !d.trade_no) return null;
    return {
      type: 'live_orderbook',
      market_ticker: d.market_ticker || '',
      trade_yes: d.trade_yes || { asks: [], bids: [] },
      trade_no: d.trade_no || { asks: [], bids: [] },
      last_trade: d.last_trade || {},
      book_seq: d.book_seq,
      ts_ms: d.ts_ms,
      redis_written_ms: d.redis_written_ms,
    };
  }

  function scheduleExpandedOrderbookPaint(msg, options) {
    if (!msg || msg.type !== 'live_orderbook') return;
    if (options && options.immediate) {
      tmOrderbookUiThrottle.applyNow(msg);
    } else {
      tmOrderbookUiThrottle.schedule(msg);
    }
  }

  function fetchExpandedOrderbookHttp(ticker, options) {
    const mt = String(ticker || '').trim();
    if (!mt) return Promise.resolve();
    const immediate = !!(options && options.immediate);
    return tmGlobalApiFetch(orderbookUrlForTicker(mt), { cache: 'no-store' })
      .then(function (res) {
        return res && res.ok && res.json ? res.json() : null;
      })
      .then(function (data) {
        const msg = normalizeOrderbookPayload(data);
        if (msg) scheduleExpandedOrderbookPaint(msg, { immediate: immediate });
      })
      .catch(function () {});
  }

  function stopOrderbookExpandedSession() {}

  function refreshOrderbookWatchAndSnapshot(ticker, options) {
    const mt = String(ticker || '').trim();
    const q = mt ? '?market_ticker=' + encodeURIComponent(mt) : '';
    const immediate = !!(options && options.immediateFetch);
    return tmGlobalApiFetch('/api/trade-monitor/orderbook_watch' + q, {
      method: 'POST',
      cache: 'no-store',
    })
      .then(function (res) {
        return res && res.json ? res.json() : null;
      })
      .then(function (body) {
        if (body && body.orderbook) {
          const obMsg = normalizeOrderbookPayload(body.orderbook);
          if (obMsg) {
            scheduleExpandedOrderbookPaint(obMsg, { immediate: immediate });
          }
        }
        if (immediate) {
          return fetchExpandedOrderbookHttp(mt, { immediate: true });
        }
      })
      .catch(function () {
        if (immediate) return fetchExpandedOrderbookHttp(mt, { immediate: true });
      });
  }

  function startOrderbookExpandedSession(ticker) {
    const mt = String(ticker || '').trim();
    stopOrderbookExpandedSession();
    if (!mt) {
      void refreshOrderbookWatchAndSnapshot('', {});
      return;
    }
    fetchPortfolioPositions();
    fetchRestingOrders();
    connectPortfolioDbWs();
    void refreshOrderbookWatchAndSnapshot(mt, { immediateFetch: true });
  }

  function setTradeMonitorOrderbookWatch(marketTicker) {
    const mt = String(marketTicker || '').trim();
    if (mt) startOrderbookExpandedSession(mt);
    else {
      stopOrderbookExpandedSession();
      void refreshOrderbookWatchAndSnapshot('', {});
    }
  }

  /** If the user already has a book expanded, follow the new cycle contract on ladder rollover. */
  function migrateExpandedTickerOnLadderRefresh(pack) {
    const prevTicker = String(expandedHourlyTicker || '').trim();
    if (!prevTicker) return;
    const eventTicker =
      pack && pack.eventTicker != null ? String(pack.eventTicker).trim() : '';
    const rows = (pack && pack.rows) || [];
    const stillInLadder =
      rows.some(function (r) {
        return String(r.ticker) === prevTicker;
      }) ||
      hourlyRawStrikeRows.some(function (r) {
        return String(r.ticker) === prevTicker;
      });
    if (stillInLadder) {
      if (eventTicker && eventTicker !== lastExpandedOrderbookEventTicker) {
        lastExpandedOrderbookEventTicker = eventTicker;
        lastExpandedOrderbookSignature = '';
        void refreshOrderbookWatchAndSnapshot(prevTicker, { immediateFetch: true });
      }
      return;
    }
    const nextRow = rows.length ? rows[0] : null;
    if (!nextRow || !nextRow.ticker) {
      stopOrderbookExpandedSession();
      expandedHourlyTicker = '';
      return;
    }
    expandedHourlyTicker = String(nextRow.ticker);
    lastExpandedOrderbookEventTicker = eventTicker;
    lastExpandedOrderbookSignature = '';
    startOrderbookExpandedSession(expandedHourlyTicker);
    centerAtmStrikeOnNextRender = false;
    renderHourlyRows();
  }

  function applyLiveOrderbookWs(msg) {
    if (!msg || msg.type !== 'live_orderbook') return;
    tmOrderbookUiThrottle.applyNow(msg);
  }

  function applyLiveOrderbookWsNow(msg) {
    if (!msg || msg.type !== 'live_orderbook') return;
    stampReceiveLatencyMs(msg);
    const mtStale = String(msg.market_ticker || '').trim();
    if (msg.orderbook_stale || msg.stale) {
      if (mtStale) delete lastLiveOrderbookByTicker[mtStale];
      if (mtStale && mtStale === expandedHourlyTicker) {
        const mount = document.querySelector('[data-hourly-expanded="' + mtStale + '"]');
        if (mount) mount.innerHTML = '';
        lastExpandedOrderbookSignature = '';
      }
      return;
    }
    cacheLiveOrderbookPayload(msg);
    const mt = String(msg.market_ticker || '').trim();
    if (!mt || mt !== expandedHourlyTicker) return;
    const mount = document.querySelector('[data-hourly-expanded="' + mt + '"]');
    if (!mount) return;
    if (mt) armExpirationFromTicker(mt);
    const expandedSig = JSON.stringify({
      ticker: msg.market_ticker || '',
      mode: mode,
      book_seq: msg.book_seq != null ? msg.book_seq : null,
      yes: msg.trade_yes || {},
      no: msg.trade_no || {},
      last: msg.last_trade || {},
    });
    if (expandedSig !== lastExpandedOrderbookSignature) {
      lastExpandedOrderbookSignature = expandedSig;
      renderOrderbookInto(mount, msg, expandedHourlyTicker);
    }
  }

  const tmOrderbookUiThrottle = createTmUiPassthrough(applyLiveOrderbookWsNow);

  function syncStrikeTableAtmMarker() {
    if (strikeTableAtmSyncRaf != null) return;
    strikeTableAtmSyncRaf = requestAnimationFrame(function () {
      strikeTableAtmSyncRaf = null;
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
    });
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
          r.fairPrice,
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
    const mt = String(expandedHourlyTicker || '').trim();
    if (!mt) return;
    const inVisible = hourlyStrikeRows.some((r) => String(r.ticker) === mt);
    const inRaw = hourlyRawStrikeRows.some((r) => String(r.ticker) === mt);
    if (!inVisible && !inRaw) {
      stopOrderbookExpandedSession();
      expandedHourlyTicker = '';
    }
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
      .sort()
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
          setTradeMonitorOrderbookWatch(expandedHourlyTicker);
        } else {
          setTradeMonitorOrderbookWatch('');
        }
        renderHourlyRows();
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
    restoreExpandedOrderbookAfterStrikeRender();
    var pending = window.__HFT_PENDING_EXPAND_TICKER__;
    if (pending && document.body && document.body.classList.contains('hf-trade-monitor-page')) {
      var pt = String(pending).trim();
      window.__HFT_PENDING_EXPAND_TICKER__ = '';
      if (pt && expandedHourlyTicker !== pt && hourlyStrikeRows.some(function (r) { return r.ticker === pt; })) {
        expandOrderbookTicker(pt);
      }
    }
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
    const target = Math.round(midTop - scrollEl.clientHeight / 2 + midEl.offsetHeight / 2);
    const next = Math.max(0, target);
    if (Math.abs(scrollEl.scrollTop - next) > 1) scrollEl.scrollTop = next;
  }

  function bindOrderbookSideButtons(containerEl, d, ticker) {
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
        cacheLiveOrderbookPayload(d);
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

  /** Update ask/bid rows in place — spread row stays anchored in the viewport. */
  function patchOrderbookInto(containerEl, d, ticker) {
    if (!containerEl || !d) return false;
    stampReceiveLatencyMs(d);
    const t = String(ticker || d.market_ticker || '');
    const scrollEl = containerEl.querySelector('[data-hourly-scroll="' + t + '"]');
    if (!scrollEl) return false;
    const asksBody = scrollEl.querySelector('tbody.asks');
    const bidsBody = scrollEl.querySelector('tbody.bids');
    const midEl = containerEl.querySelector('[data-hourly-mid="' + t + '"]');
    if (!asksBody || !bidsBody || !midEl) return false;

    const st = hourlyExpandedState(ticker);
    const midAnchor = midEl.offsetTop - scrollEl.scrollTop;
    const book = mode === 'yes' ? d.trade_yes : d.trade_no;
    const asks = book.asks || [];
    const bids = book.bids || [];
    const askLabelIdx = asks.length > 0 ? asks.length - 1 : -1;
    const bidLabelIdx = bids.length > 0 ? 0 : -1;
    const fairMatch = buildFairMatch(asks, bids, ticker, mode);
    const pos = positionForTicker(ticker);
    const askMatch = closestPositionRowMatch(asks, pos, mode);
    const bidMatch = closestPositionRowMatch(bids, pos, mode);
    const askPosIdx = askMatch.dist <= bidMatch.dist ? askMatch.idx : -1;
    const bidPosIdx = bidMatch.dist < askMatch.dist ? bidMatch.idx : -1;
    const resting = buildRestingByPrice(restingOrdersForTicker(ticker), mode);

    asksBody.innerHTML = rowsToHtml(asks, 'Asks', askLabelIdx, 'asks', fairMatch, askPosIdx, pos, resting);
    bidsBody.innerHTML = rowsToHtml(bids, 'Bids', bidLabelIdx, 'bids', fairMatch, bidPosIdx, pos, resting);
    midEl.innerHTML = buildMidCellInner(mode, d.last_trade, d.receive_latency_ms);
    midEl.className = mode === 'yes' ? 'mid-row mid-yes' : 'mid-row mid-no';
    containerEl.querySelectorAll('[data-hourly-book-side]').forEach((btn) => {
      const s = String(btn.getAttribute('data-hourly-book-side') || '');
      btn.classList.toggle('is-active', s === mode);
    });
    if (!st.userScrolled) {
      centerMidRowInPanel(scrollEl, midEl);
    } else {
      const next = Math.round(Math.max(0, midEl.offsetTop - midAnchor));
      if (Math.abs(scrollEl.scrollTop - next) > 1) scrollEl.scrollTop = next;
    }
    st.lastScrollTop = scrollEl.scrollTop;
    return true;
  }

  function renderOrderbookInto(containerEl, d, ticker) {
    if (!containerEl) return;
    if (patchOrderbookInto(containerEl, d, ticker)) {
      cacheLiveOrderbookPayload(d);
      return;
    }
    stampReceiveLatencyMs(d);
    const st = hourlyExpandedState(ticker);
    const prevScroll = st && Number.isFinite(st.lastScrollTop) ? Number(st.lastScrollTop) : 0;
    const book = mode === 'yes' ? d.trade_yes : d.trade_no;
    const asks = book.asks || [];
    const bids = book.bids || [];
    const askLabelIdx = asks.length > 0 ? asks.length - 1 : -1;
    const bidLabelIdx = bids.length > 0 ? 0 : -1;
    const fairMatch = buildFairMatch(asks, bids, ticker, mode);
    const pos = positionForTicker(ticker);
    const askMatch = closestPositionRowMatch(asks, pos, mode);
    const bidMatch = closestPositionRowMatch(bids, pos, mode);
    const askPosIdx = askMatch.dist <= bidMatch.dist ? askMatch.idx : -1;
    const bidPosIdx = bidMatch.dist < askMatch.dist ? bidMatch.idx : -1;
    const resting = buildRestingByPrice(restingOrdersForTicker(ticker), mode);
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
      rowsToHtml(asks, 'Asks', askLabelIdx, 'asks', fairMatch, askPosIdx, pos, resting) +
      '</tbody>' +
      '<tbody><tr><td colspan="4" class="' +
      midClass +
      '" data-hourly-mid="' +
      String(ticker || '') +
      '">' +
      buildMidCellInner(mode, d.last_trade, d.receive_latency_ms) +
      '</td></tr></tbody>' +
      '<tbody class="bids">' +
      rowsToHtml(bids, 'Bids', bidLabelIdx, 'bids', fairMatch, bidPosIdx, pos, resting) +
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
    bindOrderbookSideButtons(containerEl, d, ticker);
    cacheLiveOrderbookPayload(d);
    refreshExpandedOrderbookMidMom();
  }

  function disconnectStrikeTableDbWs() {
    stopOrderbookExpandedSession();
    if (hourlyStrikeTableDbWsUnsub) {
      try {
        hourlyStrikeTableDbWsUnsub();
      } catch (e) {}
      hourlyStrikeTableDbWsUnsub = null;
    }
    if (hourlyMonitorListDbWsUnsub) {
      try {
        hourlyMonitorListDbWsUnsub();
      } catch (e) {}
      hourlyMonitorListDbWsUnsub = null;
    }
  }

  function connectTmMonitorListDbWs() {
    if (!tmHasAuthSession()) return;
    if (!window.recRealtimeWsCoordinator || typeof window.recRealtimeWsCoordinator.subscribe !== 'function') {
      return;
    }
    if (hourlyMonitorListDbWsUnsub) return;
    hourlyMonitorListDbWsUnsub = window.recRealtimeWsCoordinator.subscribe(dbChangesWebSocketUrl(), {
      onlyDbStreams: ['monitor_list'],
      onMessage: function (event) {
        try {
          const parse =
            typeof recRealtimeWsJson === 'function' ? recRealtimeWsJson(event) : JSON.parse(event.data);
          const msg = parse;
          if (msg && msg.type === 'db_change' && msg.database === 'monitor_list') {
            try {
              window.dispatchEvent(new CustomEvent('rec:tm-db-monitor-list'));
            } catch (e3) {}
          }
        } catch (e2) {}
      },
    });
  }

  function connectPortfolioDbWs() {
    if (!tmHasAuthSession()) return;
    if (!window.recRealtimeWsCoordinator || typeof window.recRealtimeWsCoordinator.subscribe !== 'function') {
      return;
    }
    if (portfolioDbWsUnsub) return;
    portfolioDbWsUnsub = window.recRealtimeWsCoordinator.subscribe(dbChangesWebSocketUrl(), {
      onlyDbStreams: ['portfolio_orders', 'portfolio_positions', 'portfolio_fills'],
      onMessage: function (event) {
        try {
          const parse =
            typeof recRealtimeWsJson === 'function' ? recRealtimeWsJson(event) : JSON.parse(event.data);
          const msg = parse;
          if (msg && msg.type === 'db_change') {
            if (msg.database === 'portfolio_orders') {
              fetchRestingOrders();
            } else if (msg.database === 'portfolio_positions') {
              fetchPortfolioPositions();
            }
          }
        } catch (e2) {}
      },
    });
  }

  function connectStrikeTableDbWs() {
    if (!window.recRealtimeWsCoordinator || typeof window.recRealtimeWsCoordinator.subscribe !== 'function') {
      return;
    }
    if (hourlyStrikeTableDbWsUnsub) return;
    disconnectStrikeTableDbWs();
    void fetchLiveStrikeLadderBootstrap({ immediate: true });
    hourlyStrikeTableDbWsUnsub = window.recRealtimeWsCoordinator.subscribe(tmLiveMarketWebSocketUrl(), {
      includeLiveSymbolSpot: true,
      includeLiveStrikeLadder: true,
      includeLiveOrderbook: true,
      onMessage: function (event) {
        try {
          const parse =
            typeof recRealtimeWsJson === 'function' ? recRealtimeWsJson(event) : JSON.parse(event.data);
          const msg = parse;
          if (msg && msg.type === 'live_symbol_spot') {
            applyLiveSymbolSpotMessage(msg);
            return;
          }
          if (msg && msg.type === 'live_strike_ladder') {
            tmStrikeLadderUiThrottle.applyNow(msg);
            return;
          }
          if (msg && msg.type === 'live_orderbook') {
            applyLiveOrderbookWs(msg);
          }
        } catch (e2) {}
      },
    });
    connectTmMonitorListDbWs();
  }

  function reconnectLiveMarketWs() {
    disconnectStrikeTableDbWs();
    connectStrikeTableDbWs();
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


  try {
    window.addEventListener('rec:live-symbol-spot', function () {
      applyHeaderTtcToClock();
      reapplyHourlyStrikeVisibilityFromSpot();
      if (hourlyStrikeRows.length) syncStrikeTableAtmMarker();
    });
  } catch (e) {}

  if (document.body && document.body.classList.contains('hf-trade-monitor-page')) {
    refreshOrderbookPortfolio();
    connectPortfolioDbWs();
  }

  if (document.body && document.body.classList.contains('trade-monitor-new-page')) {
    const symPick = document.getElementById('ticker-picker');
    if (symPick) {
      symPick.addEventListener('change', function () {
        window.tmNewRefreshLiveSpotPanel();
        reconnectLiveMarketWs();
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
      switchLayoutForMarket(currentMarket());
      void fetchLiveStrikeLadderBootstrap({ immediate: true });
      reconnectLiveMarketWs();
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
  if (document.body && document.body.classList.contains('trade-monitor-new-page')) {
    switchLayoutForMarket(currentMarket());
  }

  window.recOrderbookRedisUi = {
    renderOrderbookInto: renderOrderbookInto,
    patchOrderbookInto: patchOrderbookInto,
    normalizeOrderbookPayload: normalizeOrderbookPayload,
    applyHftPortfolioSnapshot: applyHftPortfolioSnapshot,
    expandOrderbookTicker: expandOrderbookTicker,
    refreshOrderbookPortfolio: refreshOrderbookPortfolio,
  };
})();
