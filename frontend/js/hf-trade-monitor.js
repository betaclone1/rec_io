/**
 * HF Trade Monitor -- frontend controller.
 *
 * Polls /api/hft/status for engine state + gate values.
 * Subscribes to /ws/db_changes for live portfolio updates (positions, orders).
 * Wires toggle, config save, and live data display.
 */
(function () {
  'use strict';

  var POLL_INTERVAL_MS = 1000;
  /** Buffer % gate for UI (percent points: 0.025 = 0.025%). Must match HFT_MIN_BUFFER_PCT default. */
  var BUFFER_GATE_MIN_PCT = 0.025;
  var apiOrigin = window.location.origin;
  var pollTimer = null;
  var lastState = null;
  var logEntries = [];
  var MAX_LOG = 200;
  /** While true, applyStatus must not overwrite toggle DOM (avoids 1s poll / WS race). */
  var engineTogglePending = false;
  var autoTradeTogglePending = false;
  var neutralModeTogglePending = false;
  /** Live 1m mom + accel from trade-monitor WS (orderbook-redis-ui). */
  var liveMom1m = null;
  var liveMomAccel = null;

  // ---- DOM refs ----
  function $(id) { return document.getElementById(id); }

  function hfCurrentSymbol() {
    return (document.body.getAttribute('data-current-symbol') || 'BTC').trim().toUpperCase();
  }

  function syncLiveMomentumFromSpotDetail(detail) {
    if (!detail) return;
    var sym = hfCurrentSymbol();
    var momBag = detail.momentum_1m_avg_by_symbol || {};
    var accelBag = detail.momentum_acceleration_by_symbol || {};
    var mom = momBag[sym];
    var accel = accelBag[sym];
    if (mom == null && detail.rows) {
      for (var i = 0; i < detail.rows.length; i++) {
        var row = detail.rows[i];
        if (!row || String(row.symbol || '').trim().toUpperCase() !== sym) continue;
        if (mom == null && row.momentum_1m_avg != null) mom = row.momentum_1m_avg;
        if (accel == null && row.momentum_acceleration != null) accel = row.momentum_acceleration;
      }
    }
    if (mom != null && !isNaN(Number(mom))) liveMom1m = Number(mom);
    if (accel != null && !isNaN(Number(accel))) liveMomAccel = Number(accel);
  }

  function formatMomGateDisplay(mom, accel) {
    if (mom == null || isNaN(Number(mom))) return null;
    var momNum = Number(mom);
    var text = (momNum > 0 ? '+' : '') + momNum.toFixed(1);
    if (accel != null && !isNaN(Number(accel))) {
      var a = Number(accel);
      var aSign = a > 0 ? '+' : '';
      text += ' (' + (a === 0 ? '0' : aSign + a.toFixed(1)) + ')';
    }
    return text;
  }

  function syncOrderbookSubaccount(subaccount) {
    var n = parseInt(subaccount, 10);
    if (!Number.isFinite(n)) n = 2;
    window.__HFT_ORDERBOOK_SUBACCOUNT__ = n;
  }

  function syncOrderbookFromHftStatus(d) {
    var ctrl = d.control || {};
    var eng = d.engine || {};
    var sub = ctrl.subaccount != null ? ctrl.subaccount : 2;
    syncOrderbookSubaccount(sub);
    var ob = window.recOrderbookRedisUi;
    if (!ob) return;
    if (typeof ob.applyHftPortfolioSnapshot === 'function') {
      ob.applyHftPortfolioSnapshot(d.positions || [], d.resting_orders || [], {
        subaccount: sub,
        activeTicker: eng.active_ticker,
        entryPrice: eng.entry_price,
      });
    }
    if (eng.active_ticker && typeof ob.expandOrderbookTicker === 'function') {
      ob.expandOrderbookTicker(eng.active_ticker);
    }
  }

  // ---- Fetch helper ----
  function apiFetch(path, opts) {
    var url = apiOrigin + path;
    var headers = Object.assign({ 'Content-Type': 'application/json' }, (opts && opts.headers) || {});
    try {
      var tok = localStorage.getItem('rec_auth_token');
      if (tok) headers['Authorization'] = 'Bearer ' + tok;
    } catch (e) {}
    return fetch(url, Object.assign({}, opts, { headers: headers }));
  }

  // ---- Activity log ----
  function addLog(msg) {
    var now = new Date();
    var ts = now.toLocaleTimeString('en-US', { hour12: false }) + '.' + String(now.getMilliseconds()).padStart(3, '0');
    logEntries.unshift({ ts: ts, msg: msg });
    if (logEntries.length > MAX_LOG) logEntries.length = MAX_LOG;
    renderLog();
  }

  function renderLog() {
    var el = $('hfLog');
    if (!el) return;
    var html = '';
    for (var i = 0; i < logEntries.length; i++) {
      html += '<div class="hf-log-entry"><span class="ts">' + logEntries[i].ts + '</span><span class="ev">' + logEntries[i].msg + '</span></div>';
    }
    el.innerHTML = html;
  }

  // ---- Gate rendering ----
  function setGate(elId, valElId, displayValue, passes) {
    var gate = $(elId);
    var valEl = $(valElId);
    if (!gate || !valEl) return;
    valEl.textContent = displayValue != null ? String(displayValue) : '--';
    gate.classList.remove('pass', 'fail');
    if (displayValue != null) {
      gate.classList.add(passes ? 'pass' : 'fail');
    }
  }

  // ---- Status poll ----
  function pollStatus() {
    apiFetch('/api/hft/status')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.status !== 'ok') return;
        applyStatus(d);
      })
      .catch(function () {});
  }

  function setEngineToggleRunning(running, pending) {
    var engToggle = $('hfEngineToggle');
    if (!engToggle) return;
    engToggle.classList.toggle('active', !!running);
    engToggle.classList.toggle('pending', !!pending);
    engToggle.setAttribute('aria-checked', running ? 'true' : 'false');
  }

  function applyStatus(d) {
    var ctrl = d.control || {};
    var eng = d.engine || {};
    var proc = d.process || {};

    syncLiveMomentumFromGlobals();

    if (!engineTogglePending) {
      setEngineToggleRunning(!!proc.running, false);
    }

    var toggle = $('hfAutoTradeToggle');
    if (toggle && !autoTradeTogglePending) {
      var on = !!ctrl.enabled;
      toggle.classList.toggle('active', on);
      toggle.setAttribute('aria-checked', on ? 'true' : 'false');
    }

    var neutralToggle = $('hfNeutralModeToggle');
    if (neutralToggle && !neutralModeTogglePending) {
      var neutralOn = !!ctrl.neutral_mode;
      neutralToggle.classList.toggle('active', neutralOn);
      neutralToggle.setAttribute('aria-checked', neutralOn ? 'true' : 'false');
    }

    var titleEl = $('hfTitle');
    if (titleEl) {
      var sym = document.body.getAttribute('data-current-symbol') || 'BTC';
      var mkt = document.body.getAttribute('data-current-market') || '15m';
      titleEl.textContent = ctrl.neutral_mode
        ? sym + ' ' + mkt + ' — Neutral Mode (trial)'
        : sym + ' ' + mkt + ' — Market Making';
    }

    // Config inputs (only update if not focused)
    var countInput = $('hfConfigCount');
    if (countInput && document.activeElement !== countInput) {
      countInput.value = parseFloat(ctrl.count || '1').toString();
    }
    var subInput = $('hfConfigSubaccount');
    if (subInput && document.activeElement !== subInput) {
      subInput.value = String(ctrl.subaccount || 2);
    }
    syncOrderbookSubaccount(ctrl.subaccount != null ? ctrl.subaccount : 2);

    // Engine state
    var state = proc.running ? (eng.state || 'IDLE') : 'OFF';
    var dot = $('hfStateDot');
    var label = $('hfStateLabel');
    if (dot) dot.setAttribute('data-state', state);
    if (label) label.textContent = state;

    // Log state transitions
    if (lastState !== null && lastState !== state) {
      addLog(lastState + ' -> ' + state);
    }
    lastState = state;

    // Gates
    var ttc = eng.gate_ttc;
    var bufPct = eng.gate_buffer_pct;
    var mom = liveMom1m != null ? liveMom1m : eng.gate_mom_1m;
    var momAccel = liveMomAccel;

    var ttcRounded = ttc != null ? Math.round(ttc) : null;
    setGate('hfGateTtc', 'hfGateTtcVal', ttcRounded, ttcRounded != null && ttcRounded > 120);

    var bufNum = bufPct != null ? Number(bufPct) : null;
    var bufPasses = bufNum != null && !isNaN(bufNum) && bufNum > BUFFER_GATE_MIN_PCT;
    setGate(
      'hfGateBuffer', 'hfGateBufferVal',
      bufNum != null && !isNaN(bufNum) ? bufNum.toFixed(2) + '%' : null,
      bufPasses
    );

    var momDisplay = formatMomGateDisplay(mom, momAccel);
    if (ctrl.neutral_mode) {
      setGate('hfGateMom', 'hfGateMomVal', 'n/a', true);
    } else {
      setGate('hfGateMom', 'hfGateMomVal', momDisplay, mom != null && mom >= -20 && mom <= 20);
    }

    var gatesPass = !!eng.gates_pass;
    var blockReason = eng.gate_block_reason || '';
    var rolloverRem = eng.rollover_settle_remaining_sec;
    setGate('hfGateReady', 'hfGateReadyVal', gatesPass ? 'YES' : 'NO', gatesPass);
    var blockEl = $('hfGateBlockReason');
    if (blockEl) {
      if (!gatesPass && blockReason) {
        var msg = 'Blocked: ' + blockReason.replace(/_/g, ' ');
        if (rolloverRem > 0) {
          msg += ' (' + rolloverRem + 's)';
        }
        blockEl.textContent = msg;
        blockEl.style.display = '';
      } else {
        blockEl.textContent = '';
        blockEl.style.display = 'none';
      }
    }

    // Spread
    var bid = eng.gate_best_bid;
    var ask = eng.gate_best_ask;
    var spread = null;
    if (bid && ask) {
      spread = (parseFloat(ask) - parseFloat(bid)).toFixed(2);
    }
    var spreadEl = $('hfGateSpreadVal');
    if (spreadEl) spreadEl.textContent = spread != null ? spread : '--';
    var spreadGate = $('hfGateSpread');
    if (spreadGate) {
      spreadGate.classList.remove('pass', 'fail');
      if (spread != null) {
        spreadGate.classList.add(parseFloat(spread) > 0 ? 'pass' : 'fail');
      }
    }

    // Best bid/ask
    var bidEl = $('hfBestBid');
    var askEl = $('hfBestAsk');
    if (bidEl) bidEl.textContent = bid || '--';
    if (askEl) askEl.textContent = ask || '--';

    // Active ticker
    var tickerEl = $('hfActiveTicker');
    if (tickerEl) tickerEl.textContent = eng.active_ticker || '--';

    // TTC chip
    var ttcChip = $('hfTtcChip');
    if (ttcChip) {
      if (ttc != null) {
        var mins = Math.floor(ttc / 60);
        var secs = Math.round(ttc % 60);
        ttcChip.textContent = 'TTC ' + mins + ':' + String(secs).padStart(2, '0');
      } else {
        ttcChip.textContent = 'TTC --:--';
      }
    }

    renderRestingOrders(d.resting_orders || [], d.resting_orders_panel);

    // Positions from status response
    if (d.positions) {
      renderPositions(d.positions);
    }

    syncOrderbookFromHftStatus(d);
  }

  // ---- Positions rendering (from WS) ----
  function renderPositions(positions) {
    var tbody = $('hfPositionsTableBody');
    var empty = $('hfPositionsEmpty');
    if (!tbody) return;

    var ctrl = {};
    try {
      var countInput = $('hfConfigSubaccount');
      ctrl.subaccount = countInput ? parseInt(countInput.value) : 2;
    } catch (e) {
      ctrl.subaccount = 2;
    }

    var filtered = positions.filter(function (p) {
      return p.subaccount === ctrl.subaccount;
    });

    if (filtered.length === 0) {
      tbody.innerHTML = '';
      if (empty) empty.style.display = '';
      return;
    }
    if (empty) empty.style.display = 'none';

    var html = '';
    for (var i = 0; i < filtered.length; i++) {
      var p = filtered[i];
      var pnl = parseFloat(p.realized_pnl_dollars || 0);
      var pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
      var pnlStr = pnl >= 0 ? '+$' + pnl.toFixed(2) : '-$' + Math.abs(pnl).toFixed(2);
      html += '<tr>'
        + '<td style="font-size:10px">' + (p.ticker || '--') + '</td>'
        + '<td>' + (p.position_fp || '0') + '</td>'
        + '<td class="' + pnlClass + '">' + pnlStr + '</td>'
        + '<td>' + (p.volume_fp || '0') + '</td>'
        + '</tr>';
    }
    tbody.innerHTML = html;
  }

  // ---- Resting orders rendering ----
  function renderRestingOrders(orders, panel) {
    var tbody = $('hfRestingOrdersTableBody');
    var empty = $('hfRestingOrdersEmpty');
    if (!tbody) return;

    panel = panel || {};
    var closeOrders = (orders || []).filter(function (o) {
      return String(o.dir || '').toLowerCase() === 'close';
    });
    var displayOrders = orders || [];
    var seekingClose = panel.seeking_close && closeOrders.length === 0;

    if (displayOrders.length === 0 && seekingClose) {
      tbody.innerHTML = '';
      if (empty) {
        var side = (panel.seeking_close_side || '').toUpperCase();
        var sideLabel = side ? side + ' ' : '';
        var cooldown = panel.in_cooldown ? ' (backoff)' : '';
        empty.textContent = 'Seeking ' + sideLabel + 'close — post-only retry' + cooldown;
        empty.classList.add('hf-resting-seeking');
        empty.style.display = '';
      }
      return;
    }

    if (displayOrders.length === 0) {
      tbody.innerHTML = '';
      if (empty) {
        empty.textContent = panel.has_open_position
          ? 'Open position — no resting close order'
          : 'No resting orders';
        empty.classList.toggle('hf-resting-seeking', !!panel.has_open_position);
        empty.style.display = '';
      }
      return;
    }

    var html = '';
    for (var i = 0; i < displayOrders.length; i++) {
      var o = displayOrders[i];
      var sideClass = o.side === 'bid' ? 'pnl-positive' : 'pnl-negative';
      var remaining = o.remaining_count != null ? String(o.remaining_count) : '--';
      var dir = o.dir || o.type || '--';
      html += '<tr>'
        + '<td class="' + sideClass + '">' + (o.side || '--').toUpperCase() + '</td>'
        + '<td>' + (o.price || '--') + '</td>'
        + '<td>' + remaining + '</td>'
        + '<td>' + dir + '</td>'
        + '</tr>';
    }
    tbody.innerHTML = html;

    if (empty) {
      if (seekingClose) {
        var seekSide = (panel.seeking_close_side || '').toUpperCase();
        var seekLabel = seekSide ? seekSide + ' ' : '';
        var seekCooldown = panel.in_cooldown ? ' (backoff)' : '';
        empty.textContent = 'Also seeking ' + seekLabel + 'close' + seekCooldown;
        empty.classList.add('hf-resting-seeking');
        empty.style.display = '';
      } else {
        empty.classList.remove('hf-resting-seeking');
        empty.style.display = 'none';
      }
    }
  }

  // ---- Engine process toggle ----
  function wireEngineToggle() {
    var toggle = $('hfEngineToggle');
    if (!toggle) return;

    function clearEnginePending(revertTo) {
      engineTogglePending = false;
      setEngineToggleRunning(revertTo, false);
    }

    function doToggle() {
      if (engineTogglePending) return;
      var currentlyOn = toggle.classList.contains('active');
      var next = !currentlyOn;
      engineTogglePending = true;
      setEngineToggleRunning(next, true);
      addLog('Engine -> ' + (next ? 'START' : 'STOP'));

      apiFetch('/api/hft/process', {
        method: 'POST',
        body: JSON.stringify({ running: next }),
      })
        .then(function (r) {
          return r.json().then(function (d) {
            return { httpOk: r.ok, httpStatus: r.status, data: d };
          });
        })
        .then(function (res) {
          var d = res.data || {};
          if (!res.httpOk || d.status !== 'ok') {
            clearEnginePending(currentlyOn);
            var errMsg = d.message || d.reason || d.detail;
            if (!errMsg && res.httpStatus === 404) {
              errMsg = 'route not found — restart main_app to load /api/hft/process';
            }
            addLog('Engine FAILED: ' + (errMsg || 'HTTP ' + res.httpStatus));
            return;
          }
          engineTogglePending = false;
          setEngineToggleRunning(!!(d.process && d.process.running), false);
          if (d.reason === 'already_running') {
            addLog('Engine already running (pid ' + (d.process && d.process.pid) + ')');
          } else if (d.reason === 'not_running') {
            addLog('Engine was not running');
          } else if (d.started) {
            addLog('Engine started (pid ' + (d.process && d.process.pid) + ')');
          } else if (d.stopped) {
            addLog('Engine stopped');
          }
          pollStatus();
        })
        .catch(function (err) {
          clearEnginePending(currentlyOn);
          addLog('Engine error: ' + err.message);
        });
    }

    toggle.addEventListener('click', doToggle);
    toggle.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        doToggle();
      }
    });
  }

  // ---- Toggle ----
  function setAutoTradeToggle(on, pending) {
    var toggle = $('hfAutoTradeToggle');
    if (!toggle) return;
    toggle.classList.toggle('active', !!on);
    toggle.classList.toggle('pending', !!pending);
    toggle.setAttribute('aria-checked', on ? 'true' : 'false');
  }

  function setNeutralModeToggle(on, pending) {
    var toggle = $('hfNeutralModeToggle');
    if (!toggle) return;
    toggle.classList.toggle('active', !!on);
    toggle.classList.toggle('pending', !!pending);
    toggle.setAttribute('aria-checked', on ? 'true' : 'false');
  }

  function wireNeutralModeToggle() {
    var toggle = $('hfNeutralModeToggle');
    if (!toggle) return;

    function doToggle() {
      if (neutralModeTogglePending) return;
      var currentlyOn = toggle.classList.contains('active');
      var next = !currentlyOn;
      neutralModeTogglePending = true;
      setNeutralModeToggle(next, true);
      addLog('Neutral Mode -> ' + (next ? 'ON' : 'OFF'));

      apiFetch('/api/hft/config', {
        method: 'POST',
        body: JSON.stringify({ neutral_mode: next }),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          neutralModeTogglePending = false;
          if (d.status !== 'ok') {
            setNeutralModeToggle(currentlyOn, false);
            addLog('Neutral Mode FAILED: ' + (d.message || 'unknown'));
            return;
          }
          var on = !!(d.control && d.control.neutral_mode);
          setNeutralModeToggle(on, false);
          pollStatus();
        })
        .catch(function (err) {
          neutralModeTogglePending = false;
          setNeutralModeToggle(currentlyOn, false);
          addLog('Neutral Mode error: ' + err.message);
        });
    }

    toggle.addEventListener('click', doToggle);
    toggle.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        doToggle();
      }
    });
  }

  function wireToggle() {
    var toggle = $('hfAutoTradeToggle');
    if (!toggle) return;

    function doToggle() {
      if (autoTradeTogglePending) return;
      var currentlyOn = toggle.classList.contains('active');
      var next = !currentlyOn;
      autoTradeTogglePending = true;
      setAutoTradeToggle(next, true);
      addLog('Toggle -> ' + (next ? 'ENABLED' : 'DISABLED'));

      apiFetch('/api/hft/toggle', {
        method: 'POST',
        body: JSON.stringify({ enabled: next }),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          autoTradeTogglePending = false;
          if (d.status !== 'ok') {
            setAutoTradeToggle(currentlyOn, false);
            addLog('Toggle FAILED: ' + (d.message || 'unknown'));
            return;
          }
          setAutoTradeToggle(!!d.enabled, false);
          pollStatus();
        })
        .catch(function (err) {
          autoTradeTogglePending = false;
          setAutoTradeToggle(currentlyOn, false);
          addLog('Toggle error: ' + err.message);
        });
    }

    toggle.addEventListener('click', doToggle);
    toggle.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        doToggle();
      }
    });
  }

  // ---- Config save ----
  function wireConfigSave() {
    var btn = $('hfConfigSaveBtn');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var count = parseFloat(($('hfConfigCount') || {}).value || '1');
      var subaccount = parseInt(($('hfConfigSubaccount') || {}).value || '2');
      addLog('Saving config: count=' + count + ' subaccount=' + subaccount);

      syncOrderbookSubaccount(subaccount);

      apiFetch('/api/hft/config', {
        method: 'POST',
        body: JSON.stringify({ count: count, subaccount: subaccount }),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.status === 'ok') {
            addLog('Config saved');
            pollStatus();
          } else {
            addLog('Config save failed: ' + (d.message || 'unknown'));
          }
        })
        .catch(function (err) {
          addLog('Config save error: ' + err.message);
        });
    });
  }

  // ---- WebSocket for live portfolio updates ----
  function wireWebSocket() {
    if (typeof window.recRealtimeWsCoordinator === 'undefined') return;

    var proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = proto + '//' + window.location.host + '/ws/db_changes';

    window.recRealtimeWsCoordinator.subscribe(wsUrl, {
      onlyDbStreams: ['portfolio_positions', 'portfolio_orders', 'portfolio_fills'],
      onMessage: function (event) {
        var d = window.recRealtimeWsJson ? window.recRealtimeWsJson(event) : null;
        if (!d) return;
        if (d.type === 'db_change') {
          var db = d.database || '';
          if (db === 'portfolio_positions' || db === 'portfolio_orders' || db === 'portfolio_fills') {
            pollStatus();
          }
        }
      },
    });
  }

  // ---- Positions WS (direct from live_state pub/sub via db_changes) ----
  function fetchPositions() {
    apiFetch('/api/hft/status')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.status !== 'ok') return;
        // The positions come from the engine state polling;
        // for now we rely on the /api/hft/status poll for position data too.
      })
      .catch(function () {});
  }

  function syncLiveMomentumFromGlobals() {
    var sym = hfCurrentSymbol();
    try {
      var momBag = window.__liveMomentum1mAvgBySymbol;
      var accelBag = window.__liveMomentumAccelerationBySymbol;
      if (momBag && momBag[sym] != null && !isNaN(Number(momBag[sym]))) {
        liveMom1m = Number(momBag[sym]);
      }
      if (accelBag && accelBag[sym] != null && !isNaN(Number(accelBag[sym]))) {
        liveMomAccel = Number(accelBag[sym]);
      }
    } catch (e) {}
  }

  function wireLiveSymbolSpot() {
    window.addEventListener('rec:live-symbol-spot', function (ev) {
      syncLiveMomentumFromSpotDetail(ev && ev.detail);
      var momEl = $('hfGateMomVal');
      if (momEl && !neutralModeTogglePending) {
        var display = formatMomGateDisplay(liveMom1m, liveMomAccel);
        if (display != null) momEl.textContent = display;
      }
    });
    if (window.lastLiveSymbolSpotMsg) {
      syncLiveMomentumFromSpotDetail(window.lastLiveSymbolSpotMsg);
    } else {
      syncLiveMomentumFromGlobals();
    }
  }

  // ---- Init ----
  function init() {
    addLog('HF Trade Monitor initialized');
    wireEngineToggle();
    wireToggle();
    wireNeutralModeToggle();
    wireConfigSave();
    wireWebSocket();
    wireLiveSymbolSpot();
    pollStatus();
    pollTimer = setInterval(pollStatus, POLL_INTERVAL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
