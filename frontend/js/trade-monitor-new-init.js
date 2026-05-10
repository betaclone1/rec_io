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
  /** Latest active-trade rows by `trade_id` for PnL button clicks (cleared each render). */
  let tmNewLastActiveTradesById = new Map();

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
    var options = toggle.querySelectorAll('.paper-trading-toggle-option');
    if (options.length >= 2) {
      if (paperTrade) {
        options[0].style.color = '#a0aec0';
        options[0].style.fontWeight = '500';
        options[1].style.color = '#ffffff';
        options[1].style.fontWeight = '600';
      } else {
        options[0].style.color = '#ffffff';
        options[0].style.fontWeight = '600';
        options[1].style.color = '#a0aec0';
        options[1].style.fontWeight = '500';
      }
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

  function tmNewApplyPositionControlsFromMonitor(monitor) {
    if (!monitor) return;
    var positionInput = document.getElementById('position-size');
    if (positionInput && monitor.position_size !== undefined) {
      positionInput.value = monitor.position_size;
    }
    if (typeof window.applyMultiplierSelection === 'function') {
      window.applyMultiplierSelection(monitor.multiplier);
    } else {
      document.querySelectorAll('#positionSizeSelector .multiplier-btn').forEach(function (btn) {
        btn.classList.remove('active');
        if (parseFloat(btn.getAttribute('data-multiplier')) === monitor.multiplier) {
          btn.classList.add('active');
        }
      });
      window.currentMultiplier = monitor.multiplier;
    }
    var percentBtn = document.getElementById('toggle-percent');
    var contractsBtn = document.getElementById('toggle-contracts');
    if (monitor.position_type === 'percent') {
      if (percentBtn) {
        percentBtn.style.backgroundColor = '#007bff';
        percentBtn.style.borderColor = '#0056b3';
        percentBtn.classList.remove('tm-new-pos-mode-btn--inactive');
        percentBtn.classList.add('tm-new-pos-mode-btn--active');
      }
      if (contractsBtn) {
        contractsBtn.style.backgroundColor = 'transparent';
        contractsBtn.style.borderColor = '#ccc';
        contractsBtn.classList.remove('tm-new-pos-mode-btn--active');
        contractsBtn.classList.add('tm-new-pos-mode-btn--inactive');
      }
      if (positionInput) {
        positionInput.min = 1;
        positionInput.max = 100;
      }
    } else if (monitor.position_type === 'contracts') {
      if (contractsBtn) {
        contractsBtn.style.backgroundColor = '#007bff';
        contractsBtn.style.borderColor = '#0056b3';
        contractsBtn.classList.remove('tm-new-pos-mode-btn--inactive');
        contractsBtn.classList.add('tm-new-pos-mode-btn--active');
      }
      if (percentBtn) {
        percentBtn.style.backgroundColor = 'transparent';
        percentBtn.style.borderColor = '#ccc';
        percentBtn.classList.remove('tm-new-pos-mode-btn--active');
        percentBtn.classList.add('tm-new-pos-mode-btn--inactive');
      }
      if (positionInput) {
        positionInput.min = 1;
        positionInput.max = '';
      }
    }
    if (monitor.total_position != null && monitor.total_position !== '') {
      var tp = Number(monitor.total_position);
      if (!isNaN(tp)) {
        var obEl = document.getElementById('tmNewObContracts');
        if (obEl) delete obEl.dataset.tmNewDirty;
        if (typeof window.updatePositionDisplay === 'function') {
          window.updatePositionDisplay(tp);
        }
      }
    } else if (typeof window.tmNewSyncOrderBuilderContractsFromPicker === 'function') {
      window.tmNewSyncOrderBuilderContractsFromPicker();
    }
  }

  function tmNewWirePositionSizeControls() {
    if (!document.getElementById('positionSizeSelector')) return;
    if (typeof window.ignoreWsUpdates === 'undefined') {
      window.ignoreWsUpdates = false;
    }

    function applyMultiplierSelection(multiplierValue) {
      var parsed =
        multiplierValue !== undefined && multiplierValue !== null ? parseFloat(multiplierValue) : NaN;
      document.querySelectorAll('#positionSizeSelector .multiplier-btn').forEach(function (btn) {
        btn.classList.remove('active');
        if (!isNaN(parsed) && parseFloat(btn.getAttribute('data-multiplier')) === parsed) {
          btn.classList.add('active');
        }
      });
      if (!isNaN(parsed)) {
        window.currentMultiplier = parsed;
      }
    }
    window.applyMultiplierSelection = applyMultiplierSelection;

    function updatePositionDisplay(totalPosition) {
      if (totalPosition !== undefined && window.UatUnifiedModalPositionSize) {
        window.UatUnifiedModalPositionSize.refreshAllPositionDisplays(totalPosition);
        return;
      }
      var positionDisplay = document.getElementById('position-display');
      if (positionDisplay && totalPosition !== undefined) {
        var label = totalPosition === 1 ? 'contract' : 'contracts';
        positionDisplay.textContent = totalPosition + ' ' + label;
        if (typeof window.tmNewOnResolvedContracts === 'function') {
          try {
            window.tmNewOnResolvedContracts(totalPosition);
          } catch (eTot) {}
        }
      }
    }
    window.updatePositionDisplay = updatePositionDisplay;

    function sendPositionUpdateToMonitorManager() {
      var mid = window.currentMonitorId;
      if (mid == null || mid === '') return;
      var els = window.UatUnifiedModalPositionSize && window.UatUnifiedModalPositionSize.elsFromTmSidebar();
      if (window.UatUnifiedModalPositionSize && els) {
        window.UatUnifiedModalPositionSize.sendUpdate(mid, els);
      }
    }
    window.sendPositionUpdateToMonitorManager = sendPositionUpdateToMonitorManager;

    function tmNewPositionSizeIsPercentMode() {
      var pctBtn = document.getElementById('toggle-percent');
      return !!(pctBtn && pctBtn.style.backgroundColor === 'rgb(0, 123, 255)');
    }

    function tmNewStepPositionSize(delta) {
      var inp = document.getElementById('position-size');
      if (!inp || window.ignoreWsUpdates) return;
      var value = parseInt(inp.value, 10) || 1;
      value += delta;
      if (tmNewPositionSizeIsPercentMode()) {
        if (value < 1) value = 1;
        if (value > 100) value = 100;
      } else {
        if (value < 1) value = 1;
      }
      inp.value = value;
      inp.dispatchEvent(new Event('input', { bubbles: true }));
    }

    var positionInput = document.getElementById('position-size');
    if (positionInput) {
      positionInput.addEventListener('input', function () {
        if (window.ignoreWsUpdates) return;
        var value = parseInt(positionInput.value, 10) || 1;
        var isPercentMode = tmNewPositionSizeIsPercentMode();
        if (isPercentMode) {
          if (value < 1) value = 1;
          if (value > 100) value = 100;
          positionInput.value = value;
        } else {
          if (value < 1) value = 1;
          positionInput.value = value;
        }
        sendPositionUpdateToMonitorManager();
      });
    }

    var posUp = document.getElementById('tmNewPositionSizeUp');
    var posDown = document.getElementById('tmNewPositionSizeDown');
    if (posUp) {
      posUp.addEventListener('click', function () {
        tmNewStepPositionSize(1);
      });
    }
    if (posDown) {
      posDown.addEventListener('click', function () {
        tmNewStepPositionSize(-1);
      });
    }

    document.querySelectorAll('#positionSizeSelector .multiplier-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (window.ignoreWsUpdates) return;
        document.querySelectorAll('#positionSizeSelector .multiplier-btn').forEach(function (b) {
          b.classList.remove('active');
        });
        btn.classList.add('active');
        window.currentMultiplier = parseFloat(btn.getAttribute('data-multiplier'));
        sendPositionUpdateToMonitorManager();
      });
    });

    window.togglePositionType = function (type) {
      var percentBtn = document.getElementById('toggle-percent');
      var contractsBtn = document.getElementById('toggle-contracts');
      var inp = document.getElementById('position-size');
      if (!percentBtn || !contractsBtn || !inp) return;
      if (type === 'percent') {
        percentBtn.style.backgroundColor = '#007bff';
        percentBtn.style.borderColor = '#0056b3';
        contractsBtn.style.backgroundColor = 'transparent';
        contractsBtn.style.borderColor = '#ccc';
        percentBtn.classList.remove('tm-new-pos-mode-btn--inactive');
        percentBtn.classList.add('tm-new-pos-mode-btn--active');
        contractsBtn.classList.remove('tm-new-pos-mode-btn--active');
        contractsBtn.classList.add('tm-new-pos-mode-btn--inactive');
        inp.min = 1;
        inp.max = 100;
        inp.value = 10;
      } else {
        contractsBtn.style.backgroundColor = '#007bff';
        contractsBtn.style.borderColor = '#0056b3';
        percentBtn.style.backgroundColor = 'transparent';
        percentBtn.style.borderColor = '#ccc';
        contractsBtn.classList.remove('tm-new-pos-mode-btn--inactive');
        contractsBtn.classList.add('tm-new-pos-mode-btn--active');
        percentBtn.classList.remove('tm-new-pos-mode-btn--active');
        percentBtn.classList.add('tm-new-pos-mode-btn--inactive');
        inp.min = 1;
        inp.max = '';
      }
      sendPositionUpdateToMonitorManager();
    };
  }

  var tmNewObState = {
    userPickedStrike: false,
    /** After user taps Yes/No on the order panel (or a strike-table pill), do not re-derive side from quotes. */
    userLockedSide: false,
    ticker: '',
    side: 'yes',
    /** ``open`` = buy the selected side; ``close`` = UI shows position side, quotes use opposite leg to flatten. */
    orderKind: 'open',
    closeTradeId: null,
    /** Position entry price (0–1) when ``orderKind === 'close'``. */
    closeEntryBuyPrice: null,
  };

  function tmNewOrderBuilderClearCloseMode() {
    if (tmNewObState.orderKind !== 'close') return;
    tmNewObState.orderKind = 'open';
    tmNewObState.closeTradeId = null;
    tmNewObState.closeEntryBuyPrice = null;
  }

  /** Side whose ask/fees we use for cost (opposite of position when closing). */
  function tmNewOrderBuilderQuoteSideForExecution() {
    if (tmNewObState.orderKind === 'close') {
      return tmNewObState.side === 'no' ? 'yes' : 'no';
    }
    return tmNewObState.side;
  }

  function tmNewActiveTradeSideToYesNo(trade) {
    var s = (trade && trade.side != null ? String(trade.side) : '').trim().toUpperCase();
    if (s === 'N' || s === 'NO') return 'no';
    return 'yes';
  }

  var tmNewObSubmitPollTimer = null;
  var tmNewObSubmitPollAttempts = 0;
  var tmNewObSubmitAborted = false;
  /** When true, quote refresh must not overwrite review rows (pending / success / failure). */
  var tmNewObReviewPopulateLocked = false;
  /** Monitor id active when submit flow locked; same-monitor `rec:tm-monitor-changed` must not reset the review phase. */
  var tmNewObLockedMonitorId = '';

  function tmNewOrderBuilderSymbolOpen() {
    var sym = (document.body.dataset.currentSymbol || 'BTC').toString().trim().toUpperCase();
    try {
      var bag = window.__liveSpotBySymbol;
      if (bag && bag[sym] != null && Number.isFinite(Number(bag[sym]))) {
        return Number(bag[sym]);
      }
    } catch (eSo) {}
    var el = document.getElementById('symbol-price-value');
    if (el) {
      var t = (el.textContent || '').replace(/[$,\s]/g, '');
      var n = parseFloat(t);
      if (Number.isFinite(n)) return n;
    }
    return null;
  }

  function tmNewOrderBuilderAbortSubmitPoll() {
    tmNewObSubmitAborted = true;
    if (tmNewObSubmitPollTimer != null) {
      clearInterval(tmNewObSubmitPollTimer);
      tmNewObSubmitPollTimer = null;
    }
    tmNewObSubmitPollAttempts = 0;
  }

  function tmNewOrderBuilderResetSubmitWorkflow() {
    tmNewOrderBuilderAbortSubmitPoll();
    tmNewObSubmitAborted = false;
    tmNewObReviewPopulateLocked = false;
    tmNewObLockedMonitorId = '';
    var title = document.getElementById('tmNewObReviewTitle');
    if (title) title.textContent = 'Review order';
    var sub = document.getElementById('tmNewObSubmitBtn');
    if (sub) {
      sub.disabled = false;
      sub.removeAttribute('aria-disabled');
    }
  }

  function tmNewOrderBuilderSetReviewCostLabelEstimated() {
    var lab = document.getElementById('tmNewObReviewCostLabel');
    if (lab) lab.textContent = 'Estimated cost';
  }

  function tmNewOrderBuilderSetReviewRowsPendingDash() {
    var cEl = document.getElementById('tmNewObReviewContracts');
    var avgEl = document.getElementById('tmNewObReviewAvgPrice');
    var costEl = document.getElementById('tmNewObReviewEstCost');
    var payoutLabel = document.getElementById('tmNewObReviewPayoutLabel');
    var payoutEl = document.getElementById('tmNewObReviewPayout');
    tmNewOrderBuilderSetReviewCostLabelEstimated();
    if (cEl) cEl.textContent = '—';
    if (avgEl) avgEl.textContent = '—';
    if (costEl) costEl.textContent = '—';
    tmNewOrderBuilderApplyPayoutDisplay(payoutLabel, payoutEl, null);
  }

  function tmNewOrderBuilderApplyFilledReview(tr) {
    var cEl = document.getElementById('tmNewObReviewContracts');
    var avgEl = document.getElementById('tmNewObReviewAvgPrice');
    var costEl = document.getElementById('tmNewObReviewEstCost');
    var costLab = document.getElementById('tmNewObReviewCostLabel');
    var payoutLabel = document.getElementById('tmNewObReviewPayoutLabel');
    var payoutEl = document.getElementById('tmNewObReviewPayout');
    var pos = Number(tr.position);
    if (!Number.isFinite(pos)) pos = 0;
    var buyPx = Number(tr.buy_price);
    var fees = Number(tr.fees);
    if (!Number.isFinite(fees)) fees = 0;
    if (!Number.isFinite(buyPx)) buyPx = NaN;
    if (cEl) cEl.textContent = String(Math.round(pos * 100) / 100);
    var fmtA = typeof window.recTmFmtAsk === 'function' ? window.recTmFmtAsk : null;
    if (avgEl) avgEl.textContent = fmtA && Number.isFinite(buyPx) ? fmtA(buyPx) : '—';
    var costD = Number.isFinite(buyPx) && Number.isFinite(pos) ? pos * buyPx + fees : NaN;
    if (costLab) costLab.textContent = 'Cost';
    if (costEl) costEl.textContent = tmNewOrderBuilderFormatEstimatedCostUsd(costD);
    var sideU = (tr.side || '').toString().toUpperCase();
    var isNo = sideU === 'N' || sideU === 'NO';
    var estPayout = {
      maxPayout: pos,
      profitIfWin: Number.isFinite(costD) ? pos - costD : NaN,
      side: isNo ? 'no' : 'yes',
    };
    tmNewOrderBuilderApplyPayoutDisplay(payoutLabel, payoutEl, estPayout);
  }

  async function tmNewOrderBuilderBuildTriggerPayload() {
    var row =
      tmNewObState.ticker && typeof window.recTmGetHourlyStrikeRow === 'function'
        ? window.recTmGetHourlyStrikeRow(tmNewObState.ticker)
        : null;
    if (!row || !tmNewObState.ticker) {
      return { error: 'Select a strike contract from the table.' };
    }
    if (!window.currentMonitorName || window.currentMonitorId == null || window.currentMonitorId === '') {
      return { error: 'Select a monitor first.' };
    }
    var est = tmNewOrderBuilderReadEstimates();
    if (!est) {
      return { error: 'Quotes unavailable for this side. Wait for live prices.' };
    }
    var contracts = est.contracts;
    if (!Number.isFinite(contracts) || contracts < 1) {
      return { error: 'Enter at least one contract.' };
    }
    var strikeNum = Number(row.strike);
    if (!Number.isFinite(strikeNum)) {
      return { error: 'Invalid strike for this contract.' };
    }
    var strikeStr = '$' + strikeNum.toLocaleString(undefined, { maximumFractionDigits: 0 });
    var sym = (document.body.dataset.currentSymbol || 'BTC').toString().trim().toUpperCase();
    var strat = (document.body.dataset.currentMonitorStrategy || '').toString().trim();
    if (!strat || strat === '—') strat = 'Hourly HTC';
    var probRaw = row.probActive;
    var prob =
      probRaw != null && probRaw !== '' && Number.isFinite(Number(probRaw)) ? String(probRaw) : '0';
    var execSide = tmNewOrderBuilderQuoteSideForExecution();
    var diffRaw = execSide === 'no' ? row.noDiff : row.yesDiff;
    var diffVal =
      diffRaw != null && Number.isFinite(Number(diffRaw)) ? Number(diffRaw) : null;
    var symbolOpen = tmNewOrderBuilderSymbolOpen();
    var momentum = null;
    try {
      var mr = await tmNewApiFetch('/api/momentum?symbol=' + encodeURIComponent(sym), {
        cache: 'no-store',
      });
      if (mr.ok) {
        var mj = await mr.json();
        if (mj.momentum_score != null) momentum = mj.momentum_score;
      }
    } catch (eM) {}
    var contractTitle = (window.__recTmStrikeMarketTitle || '').trim();
    return {
      payload: {
        strike: strikeStr,
        side: execSide,
        ticker: String(tmNewObState.ticker),
        buy_price: est.ask,
        prob: prob,
        diff: diffVal,
        symbol_open: symbolOpen,
        momentum: momentum,
        contract: contractTitle,
        symbol: sym,
        position: contracts,
        trade_strategy: strat,
        monitor: String(window.currentMonitorName),
        entry_method: tmNewObState.orderKind === 'close' ? 'close' : 'manual',
        closing_trade_id:
          tmNewObState.orderKind === 'close' && tmNewObState.closeTradeId != null
            ? tmNewObState.closeTradeId
            : null,
        paper_trade: !!tmNewMonitorDetailCache.paper_trade,
        exchange: 'kalshi',
      },
    };
  }

  async function tmNewOrderBuilderFetchTradeAndMaybeComplete(tradeId, titleEl, submitBtn) {
    try {
      var r = await tmNewApiFetch('/trades/' + encodeURIComponent(String(tradeId)), {
        cache: 'no-store',
      });
      var tr = await r.json();
      if (!r.ok || !tr || tr.error) return;
      var st = (tr.status || '').toLowerCase();
      if (st === 'open' || st === 'partial') {
        if (tmNewObSubmitPollTimer != null) {
          clearInterval(tmNewObSubmitPollTimer);
          tmNewObSubmitPollTimer = null;
        }
        if (titleEl) {
          var rid = tr.id != null ? String(tr.id) : String(tradeId);
          titleEl.textContent = 'Successful Order #' + rid;
        }
        tmNewOrderBuilderApplyFilledReview(tr);
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.setAttribute('aria-disabled', 'true');
        }
        return;
      }
      if (
        st === 'failed' ||
        st === 'rejected' ||
        st === 'cancelled' ||
        st === 'canceled' ||
        st === 'closed'
      ) {
        if (tmNewObSubmitPollTimer != null) {
          clearInterval(tmNewObSubmitPollTimer);
          tmNewObSubmitPollTimer = null;
        }
        if (titleEl) titleEl.textContent = 'Order did not complete';
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.setAttribute('aria-disabled', 'true');
        }
      }
    } catch (ePoll) {}
  }

  async function tmNewOrderBuilderOnSubmitClose() {
    var submitBtn = document.getElementById('tmNewObSubmitBtn');
    var title = document.getElementById('tmNewObReviewTitle');
    if (!submitBtn || submitBtn.disabled) return;
    if (typeof window.closeTrade !== 'function') {
      alert('Close trade is unavailable (trade execution script not loaded).');
      return;
    }
    var tid = tmNewObState.closeTradeId;
    if (tid == null || tid === '') {
      alert('Missing trade to close.');
      return;
    }
    var est = tmNewOrderBuilderReadEstimates();
    if (!est || !Number.isFinite(est.ask)) {
      alert('Quotes unavailable for this close. Wait for live prices.');
      return;
    }
    var sellPrice = 1 - Number(est.ask);
    if (!Number.isFinite(sellPrice) || sellPrice <= 0 || sellPrice >= 1) {
      alert('Invalid close price from the current quote.');
      return;
    }
    submitBtn.disabled = true;
    submitBtn.setAttribute('aria-disabled', 'true');
    try {
      var mockEvent = {
        target: document.createElement('button'),
        preventDefault: function () {},
        stopPropagation: function () {},
      };
      var result = await window.closeTrade(tid, sellPrice, mockEvent);
      if (!result || !result.success) {
        alert((result && result.error) || 'Close failed');
        return;
      }
      tmNewOrderBuilderResetSubmitWorkflow();
      tmNewOrderBuilderClearCloseMode();
      if (title) title.textContent = 'Review order';
      tmNewOrderBuilderSetPhase(false);
      tmNewOrderBuilderUpdateUi();
      if (typeof window.tmNewRefreshActiveTradesPanel === 'function') {
        void window.tmNewRefreshActiveTradesPanel();
      }
    } catch (e) {
      alert(e && e.message ? e.message : 'Close failed');
    } finally {
      submitBtn.disabled = false;
      submitBtn.removeAttribute('aria-disabled');
    }
  }

  async function tmNewOrderBuilderOnSubmit() {
    var submitBtn = document.getElementById('tmNewObSubmitBtn');
    if (!submitBtn || submitBtn.disabled) return;
    if (tmNewObState.orderKind === 'close') {
      await tmNewOrderBuilderOnSubmitClose();
      return;
    }
    var title = document.getElementById('tmNewObReviewTitle');
    var built = await tmNewOrderBuilderBuildTriggerPayload();
    if (built.error) {
      alert(built.error);
      return;
    }
    submitBtn.disabled = true;
    try {
      var res = await tmNewApiFetch('/api/trigger_open_trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(built.payload),
      });
      var data = await res.json().catch(function () {
        return {};
      });
      if (!res.ok || !data || data.status !== 'success' || !data.trade_data || data.trade_data.id == null) {
        var msg = (data && (data.message || data.detail)) || 'HTTP ' + res.status;
        alert(msg || 'Order failed');
        submitBtn.disabled = false;
        submitBtn.removeAttribute('aria-disabled');
        return;
      }
      if (title) title.textContent = 'Order Pending...';
      tmNewObReviewPopulateLocked = true;
      tmNewObLockedMonitorId =
        window.currentMonitorId != null && window.currentMonitorId !== ''
          ? String(window.currentMonitorId)
          : '';
      tmNewOrderBuilderSetPhase(true);
      tmNewOrderBuilderSetReviewRowsPendingDash();
      submitBtn.disabled = true;
      submitBtn.setAttribute('aria-disabled', 'true');
      tmNewObSubmitAborted = false;
      tmNewObSubmitPollAttempts = 0;
      if (tmNewObSubmitPollTimer != null) {
        clearInterval(tmNewObSubmitPollTimer);
        tmNewObSubmitPollTimer = null;
      }
      var tid = Number(data.trade_data.id);
      void tmNewOrderBuilderFetchTradeAndMaybeComplete(tid, title, submitBtn);
      tmNewObSubmitPollTimer = setInterval(function () {
        if (tmNewObSubmitAborted) return;
        tmNewObSubmitPollAttempts++;
        if (tmNewObSubmitPollAttempts > 100) {
          clearInterval(tmNewObSubmitPollTimer);
          tmNewObSubmitPollTimer = null;
          if (title) title.textContent = 'Order still pending';
          return;
        }
        void tmNewOrderBuilderFetchTradeAndMaybeComplete(tid, title, submitBtn);
      }, 750);
    } catch (e) {
      alert(e && e.message ? e.message : 'Order failed');
      submitBtn.disabled = false;
      submitBtn.removeAttribute('aria-disabled');
    }
  }

  /**
   * Default Yes/No for order builder + strike table alignment.
   * Strike rows highlight the "lead" side via higher ask (see hourlyStrikeAskPillClassNames);
   * prefer that over raw active_side from DB so page load matches what the row shows.
   */
  function tmNewDeriveSideFromRow(row) {
    if (!row) return 'yes';
    var y = Number(row.yesAsk);
    var n = Number(row.noAsk);
    if (Number.isFinite(y) && Number.isFinite(n)) {
      if (y > n) return 'yes';
      if (n > y) return 'no';
    } else if (Number.isFinite(y)) {
      return 'yes';
    } else if (Number.isFinite(n)) {
      return 'no';
    }
    var active = (row.activeSide != null ? String(row.activeSide) : '').trim().toLowerCase();
    if (active === 'yes' || active === 'no') return active;
    return 'yes';
  }

  function tmNewRowHasBothAsks(row) {
    if (!row) return false;
    var y = Number(row.yesAsk);
    var n = Number(row.noAsk);
    return Number.isFinite(y) && Number.isFinite(n);
  }

  function tmNewOrderBuilderStrikeSuffix() {
    var mt = (window.__recTmStrikeMarketTitle || '').toLowerCase();
    if (mt.indexOf('below') !== -1) return ' or below';
    if (mt.indexOf('above') !== -1) return ' or above';
    return ' or above';
  }

  /** Asset the monitor is tracking (e.g. BTC, ETH), from the same source as the header market strip. */
  function tmNewOrderBuilderMonitorAssetSymbol() {
    var s = (document.body.dataset.currentSymbol || 'BTC').toString().trim().toUpperCase();
    return s || 'BTC';
  }

  function tmNewParseResolvedContractsFromUi() {
    var el = document.getElementById('position-display');
    if (el) {
      var m = /(\d+)\s+contracts?/i.exec(el.textContent || '');
      if (m) return Math.max(1, parseInt(m[1], 10) || 1);
    }
    var inp = document.getElementById('position-size');
    var pct = document.getElementById('toggle-percent');
    var isPct = pct && pct.style.backgroundColor === 'rgb(0, 123, 255)';
    if (inp && !isPct) {
      return Math.max(1, parseInt(inp.value, 10) || 1);
    }
    return 1;
  }

  function tmNewSyncOrderBuilderContractsFromPicker() {
    var inp = document.getElementById('tmNewObContracts');
    if (!inp || inp.dataset.tmNewDirty === '1') return;
    var v = tmNewParseResolvedContractsFromUi();
    inp.value = String(v);
    tmNewOrderBuilderUpdateEstimatedCost();
  }
  window.tmNewSyncOrderBuilderContractsFromPicker = tmNewSyncOrderBuilderContractsFromPicker;

  function tmNewOrderBuilderResetForMonitor() {
    tmNewOrderBuilderResetSubmitWorkflow();
    tmNewOrderBuilderSetPhase(false);
    tmNewObState.userPickedStrike = false;
    tmNewObState.userLockedSide = false;
    tmNewObState.ticker = '';
    tmNewObState.side = 'yes';
    tmNewObState.orderKind = 'open';
    tmNewObState.closeTradeId = null;
    tmNewObState.closeEntryBuyPrice = null;
    var inp = document.getElementById('tmNewObContracts');
    if (inp) delete inp.dataset.tmNewDirty;
    tmNewOrderBuilderUpdateUi();
  }

  function tmNewOrderBuilderApplyCloseTrade(trade) {
    if (!trade || trade.trade_id == null) return;
    if ((trade.status || '').toLowerCase() === 'pending') return;
    tmNewOrderBuilderResetSubmitWorkflow();
    tmNewOrderBuilderSetPhase(false);
    var ticker = trade.ticker != null ? String(trade.ticker).trim() : '';
    if (!ticker) return;
    tmNewObState.orderKind = 'close';
    tmNewObState.closeTradeId = trade.trade_id;
    var bp = Number(trade.buy_price);
    tmNewObState.closeEntryBuyPrice = Number.isFinite(bp) ? bp : null;
    tmNewObState.ticker = ticker;
    tmNewObState.side = tmNewActiveTradeSideToYesNo(trade);
    tmNewObState.userPickedStrike = true;
    tmNewObState.userLockedSide = true;
    var pos = Number(trade.position);
    if (!Number.isFinite(pos) || pos < 1) pos = 1;
    var inp = document.getElementById('tmNewObContracts');
    if (inp) {
      inp.value = String(Math.max(1, Math.floor(pos)));
      inp.dataset.tmNewDirty = '1';
    }
    try {
      window.dispatchEvent(
        new CustomEvent('rec:tm-order-builder-pick', {
          detail: {
            ticker: ticker,
            side: tmNewObState.side,
            fromActiveTradeClose: true,
          },
        })
      );
    } catch (ePick) {}
    tmNewOrderBuilderUpdateUi();
  }

  function tmNewOrderBuilderAskDollarsForSide(row, side) {
    if (!row) return NaN;
    var raw = side === 'no' ? row.noAsk : row.yesAsk;
    var n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : NaN;
  }

  /**
   * Mirrors ``backend/trade_manager.estimate_kalshi_taker_fee`` (paper IOC projection):
   * taker fee one leg = 0.07 * C * P * (1 - P), rounded up to the next cent.
   */
  function tmNewEstimateKalshiTakerFee(position, price) {
    var pos = Number(position);
    var p = Number(price);
    if (!Number.isFinite(pos) || pos <= 0) return 0;
    if (!Number.isFinite(p) || p <= 0 || p >= 1) return 0;
    var raw = 0.07 * pos * p * (1 - p);
    return Math.ceil(raw * 100) / 100;
  }

  function tmNewOrderBuilderFormatEstimatedCostUsd(dollars) {
    if (!Number.isFinite(dollars) || dollars < 0) return '—';
    return (
      '$' +
      dollars.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    );
  }

  /**
   * @returns {null|{contracts:number,ask:number,avgDisplay:string,notional:number,fee:number,totalCost:number,maxPayout:number,profitIfWin:number,side:string}}
   */
  function tmNewOrderBuilderReadEstimates() {
    var contractsEl = document.getElementById('tmNewObContracts');
    var contracts = contractsEl ? parseInt(contractsEl.value, 10) : NaN;
    if (!Number.isFinite(contracts) || contracts < 0) contracts = 0;
    var row =
      tmNewObState.ticker && typeof window.recTmGetHourlyStrikeRow === 'function'
        ? window.recTmGetHourlyStrikeRow(tmNewObState.ticker)
        : null;
    var quoteSide = tmNewOrderBuilderQuoteSideForExecution();
    var ask = tmNewOrderBuilderAskDollarsForSide(row, quoteSide);
    if (!Number.isFinite(ask)) return null;
    var fmtA = typeof window.recTmFmtAsk === 'function' ? window.recTmFmtAsk : null;
    var avgDisplay =
      row && fmtA ? fmtA(quoteSide === 'no' ? row.noAsk : row.yesAsk) : '—';
    var notional = contracts * ask;
    var fee = tmNewEstimateKalshiTakerFee(contracts, ask);
    var totalCost = notional + fee;
    var maxPayout = contracts;
    var profitIfWin = maxPayout - totalCost;
    var est = {
      contracts: contracts,
      ask: ask,
      avgDisplay: avgDisplay,
      notional: notional,
      fee: fee,
      totalCost: totalCost,
      maxPayout: maxPayout,
      profitIfWin: profitIfWin,
      side: tmNewObState.side,
      quoteSide: quoteSide,
      orderKind: tmNewObState.orderKind,
    };
    if (tmNewObState.orderKind === 'close') {
      var entry = Number(tmNewObState.closeEntryBuyPrice);
      if (Number.isFinite(entry) && Number.isFinite(contracts) && contracts > 0 && Number.isFinite(ask)) {
        var gross = contracts * (1 - entry - ask);
        est.estimatedClosePnl = gross - fee;
      } else {
        est.estimatedClosePnl = NaN;
      }
    }
    return est;
  }

  function tmNewOrderBuilderApplyPayoutDisplay(labelEl, valueEl, est) {
    if (labelEl) {
      if (est && est.orderKind === 'close') {
        labelEl.textContent = 'Estimated PnL';
      } else {
        labelEl.textContent =
          !est || !est.side ? 'Payout if Yes' : est.side === 'no' ? 'Payout if No' : 'Payout if Yes';
      }
    }
    if (!valueEl) return;
    if (!est) {
      valueEl.textContent = '—';
      return;
    }
    if (est.orderKind === 'close') {
      valueEl.replaceChildren();
      var pnl = est.estimatedClosePnl;
      if (!Number.isFinite(pnl)) {
        valueEl.textContent = '—';
        return;
      }
      var pnlSpan = document.createElement('span');
      pnlSpan.className =
        pnl >= 0 ? 'tm-new-ob-review-payout-profit-pos' : 'tm-new-ob-review-payout-profit-neg';
      var absStr = Math.abs(pnl).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
      pnlSpan.textContent = (pnl >= 0 ? '+$' : '−$') + absStr;
      valueEl.appendChild(pnlSpan);
      return;
    }
    valueEl.textContent = '';
    var mainSpan = document.createElement('span');
    mainSpan.className = 'tm-new-ob-review-payout-main';
    mainSpan.textContent = tmNewOrderBuilderFormatEstimatedCostUsd(Number(est.maxPayout));
    if (!Number.isFinite(est.profitIfWin)) {
      valueEl.appendChild(mainSpan);
      return;
    }
    var profitSpan = document.createElement('span');
    profitSpan.className =
      est.profitIfWin >= 0
        ? 'tm-new-ob-review-payout-profit-pos'
        : 'tm-new-ob-review-payout-profit-neg';
    var p = est.profitIfWin;
    var profitStr =
      p >= 0
        ? '(+$' +
          Math.abs(p).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          }) +
          ')'
        : '(-$' +
          Math.abs(p).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          }) +
          ')';
    profitSpan.textContent = profitStr;
    valueEl.appendChild(mainSpan);
    valueEl.appendChild(profitSpan);
  }

  function tmNewOrderBuilderSetPhase(review) {
    var edit = document.getElementById('tmNewObPhaseEdit');
    var rev = document.getElementById('tmNewObPhaseReview');
    if (!edit || !rev) return;
    if (review) {
      edit.classList.add('u-hidden');
      rev.classList.remove('u-hidden');
      rev.setAttribute('aria-hidden', 'false');
    } else {
      rev.classList.add('u-hidden');
      rev.setAttribute('aria-hidden', 'true');
      edit.classList.remove('u-hidden');
    }
  }

  function tmNewOrderBuilderPopulateReview() {
    tmNewOrderBuilderSetReviewCostLabelEstimated();
    var head = document.getElementById('tmNewObHeadline');
    var proposed = document.getElementById('tmNewObReviewProposed');
    if (proposed && head) proposed.textContent = head.textContent || '';
    var est = tmNewOrderBuilderReadEstimates();
    var cEl = document.getElementById('tmNewObReviewContracts');
    var avgEl = document.getElementById('tmNewObReviewAvgPrice');
    var costEl = document.getElementById('tmNewObReviewEstCost');
    var payoutLabel = document.getElementById('tmNewObReviewPayoutLabel');
    var payoutEl = document.getElementById('tmNewObReviewPayout');
    if (!est) {
      if (cEl) cEl.textContent = '—';
      if (avgEl) avgEl.textContent = '—';
      if (costEl) costEl.textContent = '—';
      tmNewOrderBuilderApplyPayoutDisplay(payoutLabel, payoutEl, null);
      return;
    }
    if (cEl) cEl.textContent = String(est.contracts);
    if (avgEl) avgEl.textContent = est.avgDisplay;
    if (costEl) costEl.textContent = tmNewOrderBuilderFormatEstimatedCostUsd(est.totalCost);
    tmNewOrderBuilderApplyPayoutDisplay(payoutLabel, payoutEl, est);
  }

  function tmNewOrderBuilderUpdateEstimatedCost() {
    var outEl = document.getElementById('tmNewObEstimatedCost');
    var editPayoutLabel = document.getElementById('tmNewObEditPayoutLabel');
    var editPayoutVal = document.getElementById('tmNewObEditPayout');
    var est = tmNewOrderBuilderReadEstimates();
    if (outEl) {
      if (!est) outEl.textContent = '—';
      else outEl.textContent = tmNewOrderBuilderFormatEstimatedCostUsd(est.totalCost);
    }
    tmNewOrderBuilderApplyPayoutDisplay(editPayoutLabel, editPayoutVal, est || null);
  }

  /**
   * Live orderbook / strike-row quote updates only: Yes/No ask labels and cost & payout lines.
   * Does not touch headline, lead/dim pills, or strike-table selection (those follow explicit UI events).
   */
  function tmNewOrderBuilderRefreshQuoteDependentUi() {
    if (!tmNewObState.ticker) return;
    var row =
      typeof window.recTmGetHourlyStrikeRow === 'function'
        ? window.recTmGetHourlyStrikeRow(tmNewObState.ticker)
        : null;
    var fmtA = typeof window.recTmFmtAsk === 'function' ? window.recTmFmtAsk : null;
    var yAsk = row && fmtA ? fmtA(row.yesAsk) : '—';
    var nAsk = row && fmtA ? fmtA(row.noAsk) : '—';
    var yBtn = document.getElementById('tmNewObBtnYes');
    var nBtn = document.getElementById('tmNewObBtnNo');
    if (yBtn) yBtn.textContent = 'Yes ' + yAsk;
    if (nBtn) nBtn.textContent = 'No ' + nAsk;
    tmNewOrderBuilderUpdateEstimatedCost();
    var revPh = document.getElementById('tmNewObPhaseReview');
    if (revPh && !revPh.classList.contains('u-hidden') && !tmNewObReviewPopulateLocked) {
      tmNewOrderBuilderPopulateReview();
    }
  }

  /**
   * @param {string} [postAccentRest] If set, builds: restPrefix + accent + postAccent (close-order line).
   */
  function tmNewOrderBuilderSetHeadlineEl(head, sideIsNo, accentText, restText, postAccentRest) {
    if (!head) return;
    head.classList.remove('tm-new-ob-headline--yes', 'tm-new-ob-headline--no');
    head.classList.add(sideIsNo ? 'tm-new-ob-headline--no' : 'tm-new-ob-headline--yes');
    while (head.firstChild) head.removeChild(head.firstChild);
    if (postAccentRest !== undefined) {
      var pre = document.createElement('span');
      pre.className = 'tm-new-ob-headline-rest';
      pre.textContent = restText;
      var accent = document.createElement('span');
      accent.className = 'tm-new-ob-headline-accent';
      accent.textContent = accentText;
      var post = document.createElement('span');
      post.className = 'tm-new-ob-headline-rest';
      post.textContent = postAccentRest;
      head.appendChild(pre);
      head.appendChild(accent);
      head.appendChild(post);
    } else {
      var accent2 = document.createElement('span');
      accent2.className = 'tm-new-ob-headline-accent';
      accent2.textContent = accentText;
      var rest = document.createElement('span');
      rest.className = 'tm-new-ob-headline-rest';
      rest.textContent = restText;
      head.appendChild(accent2);
      head.appendChild(rest);
    }
  }

  function tmNewOrderBuilderUpdateUi() {
    var row =
      tmNewObState.ticker && typeof window.recTmGetHourlyStrikeRow === 'function'
        ? window.recTmGetHourlyStrikeRow(tmNewObState.ticker)
        : null;
    var fmtS = typeof window.recTmFmtStrike === 'function' ? window.recTmFmtStrike : null;
    var fmtA = typeof window.recTmFmtAsk === 'function' ? window.recTmFmtAsk : null;
    var strikeTxt = row && fmtS ? fmtS(row.strike) : '—';
    var yAsk = row && fmtA ? fmtA(row.yesAsk) : '—';
    var nAsk = row && fmtA ? fmtA(row.noAsk) : '—';
    var sideLabel = tmNewObState.side === 'no' ? 'No' : 'Yes';
    var head = document.getElementById('tmNewObHeadline');
    if (head) {
      var sym = tmNewOrderBuilderMonitorAssetSymbol();
      var strikePart = strikeTxt + tmNewOrderBuilderStrikeSuffix();
      var sideIsNo = tmNewObState.side === 'no';
      if (tmNewObState.orderKind === 'close' && tmNewObState.closeTradeId != null) {
        tmNewOrderBuilderSetHeadlineEl(
          head,
          sideIsNo,
          sideLabel,
          'Close Order #' + String(tmNewObState.closeTradeId) + ' • ',
          ' ' + sym + ' ' + strikePart
        );
      } else {
        tmNewOrderBuilderSetHeadlineEl(
          head,
          sideIsNo,
          'Buy ' + sideLabel,
          ' • ' + sym + ' ' + strikePart
        );
      }
    }
    var yBtn = document.getElementById('tmNewObBtnYes');
    var nBtn = document.getElementById('tmNewObBtnNo');
    if (yBtn) {
      yBtn.textContent = 'Yes ' + yAsk;
      yBtn.className =
        'hourly-ask-pill hourly-ask-pill-yes ' +
        (tmNewObState.side === 'yes' ? 'hourly-ask-pill--lead-yes' : 'hourly-ask-pill--dim');
    }
    if (nBtn) {
      nBtn.textContent = 'No ' + nAsk;
      nBtn.className =
        'hourly-ask-pill hourly-ask-pill-no ' +
        (tmNewObState.side === 'no' ? 'hourly-ask-pill--lead-no' : 'hourly-ask-pill--dim');
    }
    if (typeof window.recTmApplyStrikeTableOrderSelection === 'function') {
      try {
        window.recTmApplyStrikeTableOrderSelection(tmNewObState.ticker, tmNewObState.side);
      } catch (ePill) {}
    }
    tmNewOrderBuilderUpdateEstimatedCost();
    var revPh = document.getElementById('tmNewObPhaseReview');
    if (revPh && !revPh.classList.contains('u-hidden') && !tmNewObReviewPopulateLocked) {
      tmNewOrderBuilderPopulateReview();
    }
  }

  function tmNewWireOrderBuilder() {
    if (!document.getElementById('tmNewOrderBuilder')) return;

    window.tmNewGetOrderBuilderStrikeSelection = function () {
      return { ticker: tmNewObState.ticker, side: tmNewObState.side };
    };

    window.recTmOrderBuilderRefreshQuotes = function () {
      tmNewOrderBuilderRefreshQuoteDependentUi();
    };

    window.tmNewOnResolvedContracts = function (n) {
      var inp = document.getElementById('tmNewObContracts');
      if (!inp || inp.dataset.tmNewDirty === '1') return;
      var v = typeof n === 'number' ? n : parseInt(n, 10);
      if (isNaN(v) || v < 1) v = 1;
      inp.value = String(Math.floor(v));
      tmNewOrderBuilderUpdateEstimatedCost();
    };

    window.addEventListener('rec:tm-monitor-changed', function (ev) {
      var d = ev && ev.detail;
      var mid = d && d.monitorId != null ? String(d.monitorId) : '';
      if (
        tmNewObReviewPopulateLocked &&
        tmNewObLockedMonitorId !== '' &&
        mid === tmNewObLockedMonitorId
      ) {
        tmNewSyncOrderBuilderContractsFromPicker();
        return;
      }
      tmNewOrderBuilderResetForMonitor();
      tmNewSyncOrderBuilderContractsFromPicker();
    });

    window.addEventListener('rec:tm-strike-atm-synced', function (ev) {
      var d = ev && ev.detail;
      if (!d || !d.atmTicker) return;
      if (tmNewObState.userPickedStrike) {
        if (String(tmNewObState.ticker) === String(d.atmTicker)) {
          tmNewOrderBuilderRefreshQuoteDependentUi();
        }
        return;
      }
      tmNewObState.ticker = String(d.atmTicker);
      if (!tmNewObState.userLockedSide) {
        var rowForInit = d.atmRow;
        if (
          !rowForInit &&
          tmNewObState.ticker &&
          typeof window.recTmGetHourlyStrikeRow === 'function'
        ) {
          rowForInit = window.recTmGetHourlyStrikeRow(tmNewObState.ticker);
        }
        var hasAtmRow =
          rowForInit &&
          (Number.isFinite(Number(rowForInit.yesAsk)) ||
            Number.isFinite(Number(rowForInit.noAsk)) ||
            (rowForInit.activeSide != null && String(rowForInit.activeSide).trim() !== ''));
        if (hasAtmRow) {
          tmNewObState.side = tmNewDeriveSideFromRow(rowForInit);
          if (tmNewRowHasBothAsks(rowForInit)) {
            tmNewObState.userLockedSide = true;
          }
        }
      }
      tmNewOrderBuilderUpdateUi();
      tmNewSyncOrderBuilderContractsFromPicker();
    });

    window.addEventListener('rec:tm-order-builder-pick', function (ev) {
      var d = ev && ev.detail;
      if (!d || !d.ticker) return;
      if (!d.fromActiveTradeClose && tmNewObState.orderKind === 'close') {
        tmNewOrderBuilderClearCloseMode();
      }
      tmNewObState.userPickedStrike = true;
      tmNewObState.ticker = String(d.ticker);
      if (d.side === 'yes' || d.side === 'no') {
        tmNewObState.side = d.side;
        tmNewObState.userLockedSide = true;
      } else {
        if (!tmNewObState.userLockedSide) {
          var rowPick =
            typeof window.recTmGetHourlyStrikeRow === 'function'
              ? window.recTmGetHourlyStrikeRow(d.ticker)
              : null;
          tmNewObState.side = tmNewDeriveSideFromRow(rowPick);
        }
      }
      tmNewOrderBuilderUpdateUi();
    });

    var yBtn = document.getElementById('tmNewObBtnYes');
    var nBtn = document.getElementById('tmNewObBtnNo');
    if (yBtn) {
      yBtn.addEventListener('click', function () {
        if (tmNewObState.orderKind === 'close' && tmNewObState.side !== 'yes') {
          tmNewOrderBuilderClearCloseMode();
        }
        tmNewObState.side = 'yes';
        tmNewObState.userLockedSide = true;
        tmNewOrderBuilderUpdateUi();
      });
    }
    if (nBtn) {
      nBtn.addEventListener('click', function () {
        if (tmNewObState.orderKind === 'close' && tmNewObState.side !== 'no') {
          tmNewOrderBuilderClearCloseMode();
        }
        tmNewObState.side = 'no';
        tmNewObState.userLockedSide = true;
        tmNewOrderBuilderUpdateUi();
      });
    }

    var obInp = document.getElementById('tmNewObContracts');
    if (obInp) {
      obInp.addEventListener('input', function () {
        obInp.dataset.tmNewDirty = '1';
        tmNewOrderBuilderUpdateEstimatedCost();
      });
    }

    var reviewBtn = document.getElementById('tmNewObReviewBtn');
    if (reviewBtn) {
      reviewBtn.addEventListener('click', function () {
        tmNewOrderBuilderResetSubmitWorkflow();
        tmNewOrderBuilderPopulateReview();
        tmNewOrderBuilderSetPhase(true);
      });
    }
    var backBtn = document.getElementById('tmNewObReviewBack');
    if (backBtn) {
      backBtn.addEventListener('click', function () {
        tmNewOrderBuilderResetSubmitWorkflow();
        tmNewOrderBuilderSetPhase(false);
      });
    }
    var submitBtn = document.getElementById('tmNewObSubmitBtn');
    if (submitBtn) {
      submitBtn.addEventListener('click', function () {
        void tmNewOrderBuilderOnSubmit();
      });
    }

    var atBody = document.getElementById('tmNewActiveTradesTableBody');
    if (atBody && !atBody.dataset.tmNewPnlDelegation) {
      atBody.dataset.tmNewPnlDelegation = '1';
      atBody.addEventListener('click', function (ev) {
        var t = ev.target;
        var btn = t && typeof t.closest === 'function' ? t.closest('.tm-new-ats-pnl-btn') : null;
        if (!btn) return;
        var id = btn.dataset.tradeId;
        if (!id) return;
        var row = tmNewLastActiveTradesById.get(String(id));
        if (row) tmNewOrderBuilderApplyCloseTrade(row);
      });
    }
  }

  tmNewWireOrderBuilder();

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
          var rawParsed =
            typeof recRealtimeWsJson === 'function' ? recRealtimeWsJson(event) : JSON.parse(event.data);
          var data = tmNewNormalizePreferencesWsMessage(rawParsed);
          if (!data || typeof data !== 'object') return;
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
          if (data.type === 'monitor_total_position_updated') {
            var messageMonitorId = data.monitor_id != null ? data.monitor_id.toString() : null;
            var currentIdNormalized = window.currentMonitorId
              ? window.currentMonitorId.toString().split('_').pop()
              : null;
            if (messageMonitorId && currentIdNormalized && messageMonitorId === currentIdNormalized) {
              var numericIdTp = parseInt(currentIdNormalized, 10);
              if (!isNaN(numericIdTp)) {
                void tmNewApiFetch('/api/monitor/' + numericIdTp, { cache: 'no-store' })
                  .then(function (resp) {
                    return resp.json();
                  })
                  .then(function (respData) {
                    if (respData && respData.status === 'ok' && respData.monitor) {
                      tmNewApplyPositionControlsFromMonitor(respData.monitor);
                    }
                  })
                  .catch(function (err) {
                    console.error('[tm-new] monitor refresh after total_position WS:', err);
                  });
              }
            }
            return;
          }
          if (data.type === 'active_trades_change') {
            if (!recTenantMatchesMessageTenant(data.tenant_user_no)) {
              return;
            }
            void tmNewRefreshActiveTradesPanel();
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

  /** Used by ``trade-execution-controller`` ``closeTrade`` for ``/trades`` + active_trades fetches. */
  window.__recTradesFetch = function (url, init) {
    try {
      var abs = new URL(String(url), window.location.href);
      return tmNewApiFetch(abs.pathname + abs.search, init || {});
    } catch (eUrl) {
      return fetch(url, init || {});
    }
  };

  function tmNewActiveTradesDisplayContractsTruncated(v) {
    if (v === null || v === undefined || v === '') return '';
    var n = Number(v);
    return Number.isFinite(n) ? String(Math.trunc(n)) : String(v);
  }

  function tmNewActiveTradesStrikeSortKey(strike) {
    if (strike == null) return NaN;
    var s = String(strike).replace(/[\$,]/g, '');
    return parseFloat(s);
  }

  function tmNewActiveTradesApplyRiskRowClasses(tr, prob) {
    tr.classList.remove('ultra-safe', 'safe', 'caution', 'high-risk', 'danger-stop');
    if (prob === null || prob === undefined) return;
    var p = Number(prob);
    if (!Number.isFinite(p)) return;
    if (p >= 95) tr.classList.add('ultra-safe');
    else if (p >= 80) tr.classList.add('safe');
    else if (p >= 50) tr.classList.add('caution');
    else if (p >= 25) tr.classList.add('high-risk');
    else tr.classList.add('danger-stop');
  }

  function tmNewActiveTradesFormatPnlDisplay(pnl) {
    var absStr = Math.abs(pnl).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return (pnl >= 0 ? '+' : '\u2212') + absStr;
  }

  function tmNewActiveTradesFormatPnlCell(td, trade) {
    td.classList.remove('tm-new-ats-pnl-cell');
    td.replaceChildren();
    if (trade.status === 'pending') {
      td.textContent = '\u2014';
      return;
    }
    var raw = trade.current_pnl;
    if (raw === null || raw === undefined) {
      td.textContent = '\u2014';
      return;
    }
    var pnl = parseFloat(raw);
    if (isNaN(pnl)) {
      td.textContent = '\u2014';
      return;
    }

    td.classList.add('tm-new-ats-pnl-cell');
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tm-new-ats-pnl-btn';
    if (pnl > 0) btn.classList.add('tm-new-ats-pnl-btn--pos');
    else if (pnl < 0) btn.classList.add('tm-new-ats-pnl-btn--neg');
    else btn.classList.add('tm-new-ats-pnl-btn--zero');

    btn.textContent = tmNewActiveTradesFormatPnlDisplay(pnl);
    if (trade.trade_id != null) btn.dataset.tradeId = String(trade.trade_id);
    btn.setAttribute('aria-label', 'Profit and loss ' + btn.textContent);

    td.appendChild(btn);
  }

  function tmNewRenderActiveTradesTableRows(tbody, trades) {
    tmNewLastActiveTradesById.clear();
    tbody.replaceChildren();
    if (!trades || trades.length === 0) {
      var er = document.createElement('tr');
      var ec = document.createElement('td');
      ec.colSpan = 6;
      ec.className = 'tm-new-active-trades-empty';
      ec.textContent = 'No active trades';
      er.appendChild(ec);
      tbody.appendChild(er);
      return;
    }
    var sorted = trades.slice().sort(function (a, b) {
      var ka = tmNewActiveTradesStrikeSortKey(a.strike);
      var kb = tmNewActiveTradesStrikeSortKey(b.strike);
      if (isNaN(ka) && isNaN(kb)) return 0;
      if (isNaN(ka)) return 1;
      if (isNaN(kb)) return -1;
      return ka - kb;
    });
    sorted.forEach(function (trade) {
      if (trade.trade_id != null) tmNewLastActiveTradesById.set(String(trade.trade_id), trade);
      var tr = document.createElement('tr');
      if (trade.trade_id != null) tr.dataset.tradeId = String(trade.trade_id);

      var strikeTd = document.createElement('td');
      strikeTd.textContent = trade.strike != null ? String(trade.strike) : '';
      tr.appendChild(strikeTd);

      var sideTd = document.createElement('td');
      sideTd.textContent = trade.side != null ? String(trade.side) : '';
      tr.appendChild(sideTd);

      var buyTd = document.createElement('td');
      var posTd = document.createElement('td');
      var probTd = document.createElement('td');

      if (trade.status === 'pending') {
        buyTd.textContent = 'Pending';
        posTd.textContent = 'Pending';
        probTd.textContent = 'Pending';
        tr.classList.add('pending-trade');
      } else {
        if (trade.buy_price !== null && trade.buy_price !== undefined) {
          var bp = parseFloat(trade.buy_price);
          buyTd.textContent = !isNaN(bp) ? bp.toFixed(2) : String(trade.buy_price);
        } else buyTd.textContent = '';
        if (trade.position !== null && trade.position !== undefined) {
          posTd.textContent = tmNewActiveTradesDisplayContractsTruncated(trade.position);
        } else posTd.textContent = '';
        if (trade.current_probability !== null && trade.current_probability !== undefined) {
          var pr = parseFloat(trade.current_probability);
          probTd.textContent = !isNaN(pr) ? pr.toFixed(1) : 'N/A';
        } else probTd.textContent = 'N/A';
        tmNewActiveTradesApplyRiskRowClasses(tr, trade.current_probability);
      }

      tr.appendChild(buyTd);
      tr.appendChild(posTd);
      tr.appendChild(probTd);

      var pnlTd = document.createElement('td');
      tmNewActiveTradesFormatPnlCell(pnlTd, trade);
      tr.appendChild(pnlTd);

      if (trade.status === 'closing') tr.classList.add('closing-trade');

      tbody.appendChild(tr);
    });
  }

  async function tmNewRefreshActiveTradesPanel() {
    var tbody = document.getElementById('tmNewActiveTradesTableBody');
    if (!tbody) return;
    var mon = window.currentMonitorName;
    if (!mon || !String(mon).trim()) {
      tbody.replaceChildren();
      var tr0 = document.createElement('tr');
      var td0 = document.createElement('td');
      td0.colSpan = 6;
      td0.className = 'tm-new-active-trades-empty';
      td0.textContent = 'Select a monitor';
      tr0.appendChild(td0);
      tbody.appendChild(tr0);
      return;
    }

    var res;
    try {
      res = await tmNewApiFetch('/api/active_trades/' + encodeURIComponent(String(mon).trim()), {
        cache: 'no-store',
      });
    } catch (e) {
      console.error('[tm-new] active_trades fetch failed', e);
      tbody.replaceChildren();
      var trE = document.createElement('tr');
      var tdE = document.createElement('td');
      tdE.colSpan = 6;
      tdE.className = 'tm-new-active-trades-empty';
      tdE.textContent = 'Could not load active trades';
      trE.appendChild(tdE);
      tbody.appendChild(trE);
      return;
    }

    var text = await res.text();
    var data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (e) {
      console.error('[tm-new] active_trades: response is not JSON', e);
      data = null;
    }

    if (!res.ok || !data || !Array.isArray(data.active_trades)) {
      tbody.replaceChildren();
      var trE2 = document.createElement('tr');
      var tdE2 = document.createElement('td');
      tdE2.colSpan = 6;
      tdE2.className = 'tm-new-active-trades-empty';
      tdE2.textContent =
        (data && (data.detail || data.message || data.error)) ||
        (!res.ok ? 'HTTP ' + res.status : 'Invalid response');
      trE2.appendChild(tdE2);
      tbody.appendChild(trE2);
      return;
    }

    tmNewRenderActiveTradesTableRows(tbody, data.active_trades);
  }

  window.tmNewRefreshActiveTradesPanel = tmNewRefreshActiveTradesPanel;

  window.addEventListener('rec:tm-monitor-changed', function () {
    void tmNewRefreshActiveTradesPanel();
  });

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
      return new URL('/tabs/trade_monitor_standalone_handoff.html', mainOrigin).href;
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
          'open /tabs/trade_monitor_standalone_handoff.html on the same host and port as after login';
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
   * After applying monitor state: full TradingView reload when the **monitor** changes (dropdown / picker),
   * including when the symbol string is unchanged (two monitors on the same underlying). For the same monitor
   * id (e.g. debounced refresh after DB/WS), only touch the widget if the symbol changed — avoids reloading
   * the iframe on every meta refresh.
   */
  function tmNewSyncTradingViewAfterMonitorApply(sym, prevSym, monitorChanged) {
    if (typeof TradingView === 'undefined' || !TradingView.widget) return;
    if (monitorChanged) {
      forceReloadTradingViewWidget(sym);
      return;
    }
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
    window.__ORDERBOOK_API__ = tmNewMainApiBase() + qs;
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
    const prevMonitorId =
      window.currentMonitorId != null && String(window.currentMonitorId).trim() !== ''
        ? String(window.currentMonitorId).trim()
        : '';
    const thisMonitorId = monitor.id != null ? String(monitor.id).trim() : '';
    const monitorChanged = prevMonitorId !== thisMonitorId;
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
    tmNewApplyPositionControlsFromMonitor(monitor);
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
      tmNewSyncTradingViewAfterMonitorApply(sym, prevSym, monitorChanged);
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
    tmNewWirePositionSizeControls();
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
