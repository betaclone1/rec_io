    function formatMonitorMarketLabel(market) {
      if (market == null) return '';
      const raw = String(market).trim();
      if (!raw) return '';
      const m = raw.toLowerCase();
      if (m === 'hourly') return 'Hourly';
      if (m === '15m') return '15m';
      return raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase();
    }

    // Normalize monitor id from tile to DB id the API expects
    function normalizeMonitorIdForApi(monitorId){
      if (monitorId == null || monitorId === '') return monitorId;
      const s = String(monitorId).trim();
      const m = /^mon_(\d+)_(\d+)$/i.exec(s);
      if (m) return m[2];
      return monitorId;
    }

    function uatAssetUrl(path) {
      const p = path.charAt(0) === '/' ? path : '/' + path;
      const base = (typeof window.__TM_NEW_API_ORIGIN__ === 'string' && window.__TM_NEW_API_ORIGIN__.trim())
        ? String(window.__TM_NEW_API_ORIGIN__).replace(/\/$/, '')
        : '';
      return base ? base + p : p;
    }

    var __uatModalMountPromise = null;

    function uatWireFlipSellOnModal(modal) {
      if (!modal || modal.dataset.uatFlipSellWired === '1') return;
      modal.dataset.uatFlipSellWired = '1';
      modal.addEventListener('change', function (e) {
        var t = e.target;
        if (!t || !t.matches || !t.matches('input.uat-flip-sell-input[type=checkbox]')) return;
        var row = t.closest('.uat-auto-stop-accuracy-row');
        if (!row) return;
        var mult = row.querySelector('.uat-flip-multipliers');
        if (mult) mult.classList.toggle('uat-flip-multipliers--disabled', !t.checked);
      });
      modal.addEventListener('click', function (e) {
        var btn = e.target.closest('.uat-flip-multiplier-btn');
        if (!btn || !modal.contains(btn)) return;
        var mult = btn.closest('.uat-flip-multipliers');
        if (!mult || mult.classList.contains('uat-flip-multipliers--disabled')) return;
        mult.querySelectorAll('.uat-flip-multiplier-btn').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
      });
    }

    function uatSymbolWideSyncDisabledState() {
      [
        ['symbolWideLossPreventionToggle', 'symbolWideCooldownDurationInput'],
        ['msSymbolWideLossPreventionToggle', 'msSymbolWideCooldownDurationInput'],
      ].forEach(function (pair) {
        var sw = document.getElementById(pair[0]);
        var dur = document.getElementById(pair[1]);
        if (!sw || !dur) return;
        dur.disabled = !sw.checked;
        dur.style.opacity = sw.checked ? '1' : '0.5';
      });
    }

    function uatApplySymbolWideFromApi(data) {
      if (!data || typeof data !== 'object') return;
      var on =
        data.symbol_wide_loss_prevention === true ||
        data.symbol_wide_loss_prevention === 'true' ||
        data.symbol_wide_loss_prevention === 1;
      var rawDur = data.symbol_wide_cooldown_duration;
      var hrs =
        rawDur != null && rawDur !== ''
          ? String(Math.max(1, parseInt(rawDur, 10) || 4))
          : '4';
      var sw = document.getElementById('symbolWideLossPreventionToggle');
      var dur = document.getElementById('symbolWideCooldownDurationInput');
      var msw = document.getElementById('msSymbolWideLossPreventionToggle');
      var mdur = document.getElementById('msSymbolWideCooldownDurationInput');
      if (sw) sw.checked = on;
      if (dur) dur.value = hrs;
      if (msw) msw.checked = on;
      if (mdur) mdur.value = hrs;
      uatSymbolWideSyncDisabledState();
    }

    function uatReadSymbolWideForPayload(isMomentumScalp) {
      var swEl = isMomentumScalp
        ? document.getElementById('msSymbolWideLossPreventionToggle')
        : document.getElementById('symbolWideLossPreventionToggle');
      var durEl = isMomentumScalp
        ? document.getElementById('msSymbolWideCooldownDurationInput')
        : document.getElementById('symbolWideCooldownDurationInput');
      var out = {};
      if (swEl) out.symbol_wide_loss_prevention = swEl.checked;
      if (durEl) {
        var n = parseInt(String(durEl.value).trim(), 10);
        out.symbol_wide_cooldown_duration = Number.isFinite(n) && n > 0 ? n : 4;
      }
      return out;
    }

    function uatWireSymbolWideOnModal(modal) {
      if (!modal || modal.dataset.uatSymWideWired === '1') return;
      modal.dataset.uatSymWideWired = '1';
      modal.addEventListener('change', function (e) {
        var t = e.target;
        if (!t || !t.id) return;
        if (
          t.id !== 'symbolWideLossPreventionToggle' &&
          t.id !== 'msSymbolWideLossPreventionToggle'
        ) {
          return;
        }
        uatSymbolWideSyncDisabledState();
      });
    }

    function uatWireProbabilityWindowHandles() {
      const minProbHandle = document.getElementById('minProbabilityHandle');
      const maxProbHandle = document.getElementById('maxProbabilityHandle');
      if (!minProbHandle || !maxProbHandle || minProbHandle._uatProbWired) return;
      minProbHandle._uatProbWired = true;
      maxProbHandle._uatProbWired = true;
      minProbHandle.addEventListener('mousedown', handleDashboardProbMouseDown);
      maxProbHandle.addEventListener('mousedown', handleDashboardProbMouseDown);
    }

    function uatWireCooldownWindowHandles() {
      const minCooldownWindowHandle = document.getElementById('minCooldownWindowHandle');
      const maxCooldownWindowHandle = document.getElementById('maxCooldownWindowHandle');
      if (!minCooldownWindowHandle || !maxCooldownWindowHandle || minCooldownWindowHandle._uatCooldownWired) return;
      minCooldownWindowHandle._uatCooldownWired = true;
      maxCooldownWindowHandle._uatCooldownWired = true;
      minCooldownWindowHandle.addEventListener('mousedown', handleDashboardCooldownWindowMouseDown);
      maxCooldownWindowHandle.addEventListener('mousedown', handleDashboardCooldownWindowMouseDown);
    }

    function uatBindUnifiedModalPositionControls() {
      var um = document.getElementById('unifiedAutoTradeModal');
      if (!um || um._uatPositionBound) return;
      um._uatPositionBound = true;
      if (window.UatUnifiedModalPositionSize) {
        window.UatUnifiedModalPositionSize.bindModal(um, {
          persist: 'deferred',
          mirrorSidebar: false,
          getMonitorId: function () {
            return normalizeMonitorIdForApi(um.getAttribute('data-tile-id'));
          }
        });
      }
      uatWireFlipSellOnModal(um);
      uatWireSymbolWideOnModal(um);
      uatWireProbabilityWindowHandles();
      uatWireCooldownWindowHandles();
    }

    function ensureUnifiedAutoTradeModalMounted() {
      if (document.getElementById('unifiedAutoTradeModal')) {
        uatBindUnifiedModalPositionControls();
        return Promise.resolve();
      }
      if (__uatModalMountPromise) return __uatModalMountPromise;
      __uatModalMountPromise = fetch(uatAssetUrl('/tabs/partials/unified_auto_trade_modal.html'), { credentials: 'include' })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          var wrap = document.createElement('div');
          wrap.innerHTML = html;
          while (wrap.firstChild) {
            document.body.appendChild(wrap.firstChild);
          }
          uatBindUnifiedModalPositionControls();
        })
        .catch(function (e) {
          __uatModalMountPromise = null;
          throw e;
        });
      return __uatModalMountPromise;
    }

    function uatResolveMonitorRow(tileId) {
      if (typeof window.__uatMonitorLookup === 'function') {
        try {
          var hook = window.__uatMonitorLookup(tileId);
          if (hook) return hook;
        } catch (e1) {}
      }
      if (typeof monitors !== 'undefined' && Array.isArray(monitors)) {
        return monitors.find(function (m) { return m.id === tileId; }) || null;
      }
      return null;
    }

    function dashboardUatLoadMonitorPositionIntoModal(apiId) {
      if (!apiId || !window.UatUnifiedModalPositionSize) return;
      fetch('/api/monitor/' + apiId + '')
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j || j.status !== 'ok' || !j.monitor) return;
          var modal = document.getElementById('unifiedAutoTradeModal');
          var els = window.UatUnifiedModalPositionSize.getElsFromModal(modal);
          if (j.monitor.total_position != null) {
            modal._uatLastTotalPosition = j.monitor.total_position;
          }
          window.UatUnifiedModalPositionSize.setModalBankrollAllotmentCents(modal, j.monitor.bankroll_allotment_total);
          window.UatUnifiedModalPositionSize.applyMonitorToEls(els, j.monitor);
          if (j.monitor.total_position != null) {
            window.UatUnifiedModalPositionSize.refreshAllPositionDisplays(j.monitor.total_position);
          }
          window.UatUnifiedModalPositionSize.syncModalPositionPreview(modal);
          window.UatUnifiedModalPositionSize.captureOpenSnapshot(modal);
        })
        .catch(function () {});
    }

    function formatDashboardUnifiedAutoTradeModalTitle(tileId, monitor) {
      const raw = normalizeMonitorIdForApi(tileId);
      let num = raw != null && String(raw).trim() !== '' ? String(raw).trim() : '';
      if (!num && tileId != null) {
        const s = String(tileId);
        const m = s.match(/mon_\d+_(.+)$/i);
        num = m ? m[1] : s;
      }
      if (!num) num = '?';
      const strat = monitor && monitor.strategy ? String(monitor.strategy).trim() : '';
      const mkt = monitor ? formatMonitorMarketLabel(monitor.market) : '';
      const tail = [strat, mkt].filter(Boolean).join(', ');
      return tail ? ('Monitor ' + num + ' - ' + tail) : ('Monitor ' + num);
    }

    function dashboardUatUpdateRegimeWindowPickerVisibility() {
      const row = document.getElementById('regimeWindowPickerRow');
      const cb = document.getElementById('regimeMonitorEnabled');
      const sel = document.getElementById('regimeWindowSelect');
      if (!row || !cb) return;
      const on = !!cb.checked;
      row.style.display = on ? 'flex' : 'none';
      if (sel) {
        sel.disabled = !on;
        sel.style.opacity = '';
        sel.style.cursor = '';
      }
    }

    function dashboardUatUpdateSpikeAlertSliderGroupVisibility() {
      const cb = document.getElementById('spikeAlertEnabled');
      const spikeOn = !!(cb && cb.checked);
      const g = document.getElementById('spikeAlertSliderGroup');
      if (g) g.style.display = spikeOn ? 'contents' : 'none';
      let showProb = false;
      const probWrap = document.getElementById('probAdjSpikeGroup');
      if (probWrap) {
        const stratOk = probWrap.getAttribute('data-strategy-shows-prob-adj') === '1';
        showProb = spikeOn && stratOk;
        probWrap.style.display = showProb ? 'contents' : 'none';
        probWrap.setAttribute('aria-hidden', showProb ? 'false' : 'true');
      }
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          if (spikeOn) {
            var sm = document.getElementById('spikeAlertMomentumSlider');
            if (sm) updateSpikeAlertMomentumDisplay(sm.value);
            var sc = document.getElementById('spikeAlertCooldownSlider');
            if (sc) updateSpikeAlertCooldownDisplay(sc.value);
            var st = document.getElementById('spikeAlertTimeSlider');
            if (st) updateSpikeAlertTimeDisplay(st.value);
          }
          if (showProb) {
            var ps = document.getElementById('probAdjSlider');
            if (ps) updateProbAdjDisplay(ps.value);
          }
        });
      });
    }

    function _dashboardFormatAutoStopAccuracyLine(bucket) {
      if (!bucket || bucket.total === 0) {
        return '-';
      }
      var p = bucket.accuracy_pct;
      var c = bucket.confirmed != null ? bucket.confirmed : 0;
      var t = bucket.total;
      return (p != null ? p + '%' : '—') + ' · ' + c + '/' + t + ' losses confirmed';
    }

    function _dashboardSetAutoStopAccuracyRow(row, bucket) {
      var val = row && row.querySelector ? row.querySelector('.uat-acc-value') : null;
      if (val) val.textContent = _dashboardFormatAutoStopAccuracyLine(bucket);
    }

    function _dashboardSetAutoStopAccuracyHosts(modalRoot, selector, block) {
      var hosts = modalRoot ? modalRoot.querySelectorAll(selector) : [];
      hosts.forEach(function (host) {
        _dashboardSetAutoStopAccuracyRow(
          host.querySelector('[data-uat-acc="7d"]'),
          block && block['7d'] ? block['7d'] : null
        );
        _dashboardSetAutoStopAccuracyRow(
          host.querySelector('[data-uat-acc="30d"]'),
          block && block['30d'] ? block['30d'] : null
        );
      });
    }

    function dashboardUatNormalizeFlipMultForButtons(multRaw) {
      if (multRaw == null || multRaw === '') return '1';
      var s = String(multRaw).trim().toLowerCase().replace(/x$/i, '');
      if (s === '1' || s === '2' || s === '3') return s;
      var m = s.match(/[123]/);
      return m ? m[0] : '1';
    }

    function dashboardUatReadFlipMult(checkboxId) {
      var cb = document.getElementById(checkboxId);
      if (!cb) return '1';
      var row = cb.closest('.uat-auto-stop-accuracy-row');
      var active = row && row.querySelector('.uat-flip-multiplier-btn.active');
      var mm = active && active.getAttribute('data-uat-mult');
      return mm ? String(mm) : '1';
    }

    function dashboardUatApplyFlipRow(checkboxId, enabled, multRaw) {
      var cb = document.getElementById(checkboxId);
      if (!cb) return;
      cb.checked = !!enabled;
      var row = cb.closest('.uat-auto-stop-accuracy-row');
      var multEl = row && row.querySelector('.uat-flip-multipliers');
      if (multEl) {
        multEl.classList.toggle('uat-flip-multipliers--disabled', !cb.checked);
        var target = dashboardUatNormalizeFlipMultForButtons(multRaw);
        multEl.querySelectorAll('.uat-flip-multiplier-btn').forEach(function (b) {
          b.classList.toggle('active', b.getAttribute('data-uat-mult') === target);
        });
      }
    }

    async function fetchAndRenderDashboardAutoStopAccuracy(apiMonitorId) {
      var modal = document.getElementById('unifiedAutoTradeModal');
      if (!modal || !apiMonitorId) return;
      modal.querySelectorAll('.uat-auto-stop-accuracy [data-uat-acc] .uat-acc-value').forEach(function (el) {
        el.textContent = '…';
      });
      try {
        var r = await fetch('/api/monitor_auto_stop_accuracy?monitor_id=' + encodeURIComponent(apiMonitorId));
        var j = await r.json();
        if (!j || j.status !== 'ok') throw new Error((j && j.message) || 'request failed');
        _dashboardSetAutoStopAccuracyHosts(modal, '.uat-acc-probability-stop', j.probability_stop);
        _dashboardSetAutoStopAccuracyHosts(modal, '.uat-acc-stop-loss-floor', j.stop_loss_floor);
      } catch (e) {
        console.warn('monitor_auto_stop_accuracy', e);
        modal.querySelectorAll('.uat-auto-stop-accuracy [data-uat-acc] .uat-acc-value').forEach(function (el) {
          el.textContent = 'unavailable';
        });
      }
    }

    // Simple value syncing for the modal (text labels)
    function bindValue(id, outId, fmt){
      const el = document.getElementById(id); const out = document.getElementById(outId);
      if (!el || !out) return;
      const update = () => out.textContent = fmt ? fmt(el.value) : el.value;
      el.addEventListener('input', update); update();
    }

    // Helper function to format seconds as MM:SS
    function formatSecondsToMMSS(seconds) {
      const m = Math.floor(seconds / 60);
      const s = seconds % 60;
      return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    // Time Window Slider Variables and Functions
    let dashboardTimeWindowSliderWidth = 0;
    let dashboardMinTimeSeconds = 0;
    let dashboardMaxTimeSeconds = 3600;
    let dashboardIsDragging = false;
    let dashboardCurrentHandle = null;
    
    // Probability Window Slider Variables (Hourly HTC)
    let dashboardProbSliderWidth = 0;
    let dashboardMinProbability = 95.00;
    let dashboardMaxProbability = 100.00;
    let dashboardProbIsDragging = false;
    let dashboardProbCurrentHandle = null;
    
    // Momentum Scalp Ask Window Slider Variables
    let dashboardMSAskSliderWidth = 0;
    let dashboardMSMinAsk = 0.0000;
    let dashboardMSMaxAsk = 0.9800;
    let dashboardMSAskIsDragging = false;
    let dashboardMSAskCurrentHandle = null;
    
    // Momentum Breakout/Contain Ask Window Variables (reuse probability slider)
    let dashboardContainMinAsk = 0.0000;
    let dashboardContainMaxAsk = 0.9800;
    
    // Cooldown Window Slider Variables (Momentum Contain)
    let dashboardCooldownWindowSliderWidth = 0;
    let dashboardMinCooldownTimerSeconds = 300; // 5 minutes default
    let dashboardMaxCooldownTimerSeconds = 3300; // 55 minutes default
    let dashboardCooldownWindowIsDragging = false;
    let dashboardCooldownWindowCurrentHandle = null;

    // Initialize Time Window slider
    function initDashboardTimeWindowSlider() {
      const container = document.getElementById('timeWindowSliderContainer');
      if (!container) return;
      dashboardTimeWindowSliderWidth = container.offsetWidth;
      updateDashboardTimeWindowSlider();
    }

    // Update Time Window slider positions and range
    function updateDashboardTimeWindowSlider() {
      if (!dashboardTimeWindowSliderWidth) return;
      
      const minHandle = document.getElementById('minTimeHandle');
      const maxHandle = document.getElementById('maxTimeHandle');
      const range = document.getElementById('timeWindowRange');
      const minDisplay = document.getElementById('timeWindowMinDisplay');
      const maxDisplay = document.getElementById('timeWindowMaxDisplay');
      
      if (!minHandle || !maxHandle || !range || !minDisplay || !maxDisplay) return;
      
      const maxScale = window.dashboardTimeWindowMaxSeconds || 3600;
      const minPercent = (dashboardMinTimeSeconds / maxScale) * 100;
      const maxPercent = (dashboardMaxTimeSeconds / maxScale) * 100;
      
      minHandle.style.left = `${minPercent}%`;
      maxHandle.style.left = `${maxPercent}%`;
      
      range.style.left = `${minPercent}%`;
      range.style.width = `${maxPercent - minPercent}%`;
      
      minDisplay.textContent = formatSecondsToMMSS(dashboardMinTimeSeconds);
      maxDisplay.textContent = formatSecondsToMMSS(dashboardMaxTimeSeconds);
      
      minDisplay.style.left = `${minPercent}%`;
      maxDisplay.style.left = `${maxPercent}%`;
    }

    // Handle mouse events for Time Window slider
    function handleDashboardTimeWindowMouseDown(e) {
      dashboardIsDragging = true;
      dashboardCurrentHandle = e.target;
      document.addEventListener('mousemove', handleDashboardTimeWindowMouseMove);
      document.addEventListener('mouseup', handleDashboardTimeWindowMouseUp);
      e.preventDefault();
    }

    function handleDashboardTimeWindowMouseMove(e) {
      if (!dashboardIsDragging || !dashboardCurrentHandle) return;
      
      const container = document.getElementById('timeWindowSliderContainer');
      if (!container) return;
      
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const percent = Math.max(0, Math.min(100, (x / rect.width) * 100));
      
      const maxScale = window.dashboardTimeWindowMaxSeconds || 3600;
      const numIntervals = maxScale / 15;
      const intervalIndex = Math.round((percent / 100) * numIntervals);
      const snappedSeconds = Math.max(0, Math.min(maxScale, intervalIndex * 15));
      
      const minHandle = document.getElementById('minTimeHandle');
      const maxHandle = document.getElementById('maxTimeHandle');
      
      if (dashboardCurrentHandle === minHandle) {
        if (snappedSeconds >= dashboardMaxTimeSeconds) return;
        dashboardMinTimeSeconds = snappedSeconds;
      } else if (dashboardCurrentHandle === maxHandle) {
        if (snappedSeconds <= dashboardMinTimeSeconds) return;
        dashboardMaxTimeSeconds = snappedSeconds;
      }
      
      updateDashboardTimeWindowSlider();
    }

    function handleDashboardTimeWindowMouseUp() {
      dashboardIsDragging = false;
      dashboardCurrentHandle = null;
      document.removeEventListener('mousemove', handleDashboardTimeWindowMouseMove);
      document.removeEventListener('mouseup', handleDashboardTimeWindowMouseUp);
    }
    
    // PROBABILITY WINDOW SLIDER (Hourly HTC)
    function initDashboardProbabilityWindowSlider() {
      const container = document.getElementById('probabilityWindowSliderContainer');
      if (!container) return;
      dashboardProbSliderWidth = container.offsetWidth;
      updateDashboardProbabilityWindowSlider();
    }
    
    function updateDashboardProbabilityWindowSlider() {
      if (!dashboardProbSliderWidth) return;
      
      // Get current strategy from modal
      const modal = document.getElementById('unifiedAutoTradeModal');
      if (!modal || modal.style.display === 'none') return;
      const tileId = modal.getAttribute('data-tile-id');
      const monitor = uatResolveMonitorRow(tileId);
      const currentStrategy = monitor ? monitor.strategy : '';
      const isMomentumBreakout = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM BREAKOUT');
      const isMomentumContain = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM CONTAIN');
      
      const minHandle = document.getElementById('minProbabilityHandle');
      const maxHandle = document.getElementById('maxProbabilityHandle');
      const range = document.getElementById('probabilityWindowRange');
      const minDisplay = document.getElementById('probabilityWindowMinDisplay');
      const maxDisplay = document.getElementById('probabilityWindowMaxDisplay');
      
      if (!minHandle || !maxHandle || !range || !minDisplay || !maxDisplay) return;
      
      if (isMomentumBreakout || isMomentumContain) {
        // Use ask price values (0.0000 to 1.0000)
        const MIN_ASK_SEPARATION = 0.01;
        if (dashboardContainMaxAsk - dashboardContainMinAsk < MIN_ASK_SEPARATION) {
          if (dashboardContainMaxAsk < 1.0) {
            dashboardContainMaxAsk = parseFloat((dashboardContainMinAsk + MIN_ASK_SEPARATION).toFixed(4));
          } else {
            dashboardContainMinAsk = parseFloat((dashboardContainMaxAsk - MIN_ASK_SEPARATION).toFixed(4));
          }
        }
        
        const minPercent = (dashboardContainMinAsk / 1.0) * 100;
        const maxPercent = (dashboardContainMaxAsk / 1.0) * 100;
        
        minHandle.style.left = `${minPercent}%`;
        maxHandle.style.left = `${maxPercent}%`;
        range.style.left = `${minPercent}%`;
        range.style.width = `${maxPercent - minPercent}%`;
        minDisplay.textContent = '$' + dashboardContainMinAsk.toFixed(4);
        maxDisplay.textContent = '$' + dashboardContainMaxAsk.toFixed(4);
        minDisplay.style.left = `${minPercent}%`;
        maxDisplay.style.left = `${maxPercent}%`;
      } else {
        // Use probability values (0 to 100)
        const MIN_SEPARATION = 0.5;
        if (dashboardMaxProbability - dashboardMinProbability < MIN_SEPARATION) {
          if (dashboardMaxProbability < 100) {
            dashboardMaxProbability = parseFloat((dashboardMinProbability + MIN_SEPARATION).toFixed(1));
          } else {
            dashboardMinProbability = parseFloat((dashboardMaxProbability - MIN_SEPARATION).toFixed(1));
          }
        }
        
        const minPercent = (dashboardMinProbability / 100) * 100;
        const maxPercent = (dashboardMaxProbability / 100) * 100;
        
        minHandle.style.left = `${minPercent}%`;
        maxHandle.style.left = `${maxPercent}%`;
        range.style.left = `${minPercent}%`;
        range.style.width = `${maxPercent - minPercent}%`;
        minDisplay.textContent = dashboardMinProbability.toFixed(1) + '%';
        maxDisplay.textContent = dashboardMaxProbability.toFixed(1) + '%';
        minDisplay.style.left = `${minPercent}%`;
        maxDisplay.style.left = `${maxPercent}%`;
      }
    }
    
    function handleDashboardProbMouseDown(e) {
      dashboardProbIsDragging = true;
      dashboardProbCurrentHandle = e.target;
      document.addEventListener('mousemove', handleDashboardProbMouseMove);
      document.addEventListener('mouseup', handleDashboardProbMouseUp);
      e.preventDefault();
    }
    
    function handleDashboardProbMouseMove(e) {
      if (!dashboardProbIsDragging || !dashboardProbCurrentHandle) return;
      
      const container = document.getElementById('probabilityWindowSliderContainer');
      if (!container) return;
      
      // Get current strategy from modal
      const modal = document.getElementById('unifiedAutoTradeModal');
      if (!modal) return;
      const tileId = modal.getAttribute('data-tile-id');
      const monitor = uatResolveMonitorRow(tileId);
      const currentStrategy = monitor ? monitor.strategy : '';
      const isMomentumBreakout = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM BREAKOUT');
      const isMomentumContain = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM CONTAIN');
      
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const percent = Math.max(0, Math.min(100, (x / rect.width) * 100));
      
      const minHandle = document.getElementById('minProbabilityHandle');
      const maxHandle = document.getElementById('maxProbabilityHandle');
      
      if (isMomentumBreakout || isMomentumContain) {
        // Use ask price values (0.0000 to 1.0000)
        const askPrice = parseFloat((percent / 100).toFixed(4));
        const MIN_ASK_SEPARATION = 0.01;
        
        if (dashboardProbCurrentHandle === minHandle) {
          if (askPrice >= dashboardContainMaxAsk - MIN_ASK_SEPARATION) {
            dashboardContainMinAsk = parseFloat((dashboardContainMaxAsk - MIN_ASK_SEPARATION).toFixed(4));
          } else {
            dashboardContainMinAsk = askPrice;
          }
        } else if (dashboardProbCurrentHandle === maxHandle) {
          if (askPrice <= dashboardContainMinAsk + MIN_ASK_SEPARATION) {
            dashboardContainMaxAsk = parseFloat((dashboardContainMinAsk + MIN_ASK_SEPARATION).toFixed(4));
          } else {
            dashboardContainMaxAsk = askPrice;
          }
        }
      } else {
        // Use probability values (0 to 100)
        const probability = parseFloat((Math.round(percent * 10) / 10).toFixed(1));
        const MIN_SEPARATION = 0.5;
        
        if (dashboardProbCurrentHandle === minHandle) {
          if (probability >= dashboardMaxProbability - MIN_SEPARATION) {
            dashboardMinProbability = parseFloat((dashboardMaxProbability - MIN_SEPARATION).toFixed(1));
          } else {
            dashboardMinProbability = probability;
          }
        } else if (dashboardProbCurrentHandle === maxHandle) {
          if (probability <= dashboardMinProbability + MIN_SEPARATION) {
            dashboardMaxProbability = parseFloat((dashboardMinProbability + MIN_SEPARATION).toFixed(1));
          } else {
            dashboardMaxProbability = probability;
          }
        }
      }
      
      updateDashboardProbabilityWindowSlider();
    }
    
    function handleDashboardProbMouseUp() {
      dashboardProbIsDragging = false;
      dashboardProbCurrentHandle = null;
      document.removeEventListener('mousemove', handleDashboardProbMouseMove);
      document.removeEventListener('mouseup', handleDashboardProbMouseUp);
    }
    
    // COOLDOWN WINDOW SLIDER (Momentum Contain)
    function initDashboardCooldownWindowSlider() {
      const container = document.getElementById('cooldownWindowSliderContainer');
      if (!container) return;
      dashboardCooldownWindowSliderWidth = container.offsetWidth;
      updateDashboardCooldownWindowSlider();
    }
    
    function updateDashboardCooldownWindowSlider() {
      if (!dashboardCooldownWindowSliderWidth) return;
      
      const minHandle = document.getElementById('minCooldownWindowHandle');
      const maxHandle = document.getElementById('maxCooldownWindowHandle');
      const range = document.getElementById('cooldownWindowRange');
      const minDisplay = document.getElementById('cooldownWindowMinDisplay');
      const maxDisplay = document.getElementById('cooldownWindowMaxDisplay');
      
      if (!minHandle || !maxHandle || !range || !minDisplay || !maxDisplay) return;
      
      // Max range is 0-3600 seconds (0-60 minutes)
      const minPercent = (dashboardMinCooldownTimerSeconds / 3600) * 100;
      const maxPercent = (dashboardMaxCooldownTimerSeconds / 3600) * 100;
      
      minHandle.style.left = `${minPercent}%`;
      maxHandle.style.left = `${maxPercent}%`;
      
      range.style.left = `${minPercent}%`;
      range.style.width = `${maxPercent - minPercent}%`;
      
      // Update time display boxes - min BELOW, max ABOVE (matching Price Window)
      minDisplay.textContent = formatSecondsToMMSS(dashboardMinCooldownTimerSeconds);
      minDisplay.style.left = `${minPercent}%`;
      
      maxDisplay.textContent = formatSecondsToMMSS(dashboardMaxCooldownTimerSeconds);
      maxDisplay.style.left = `${maxPercent}%`;
    }
    
    function handleDashboardCooldownWindowMouseDown(e) {
      dashboardCooldownWindowIsDragging = true;
      dashboardCooldownWindowCurrentHandle = e.target;
      document.addEventListener('mousemove', handleDashboardCooldownWindowMouseMove);
      document.addEventListener('mouseup', handleDashboardCooldownWindowMouseUp);
      e.preventDefault();
    }
    
    function handleDashboardCooldownWindowMouseMove(e) {
      if (!dashboardCooldownWindowIsDragging || !dashboardCooldownWindowCurrentHandle) return;
      
      const container = document.getElementById('cooldownWindowSliderContainer');
      if (!container) return;
      
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const percent = Math.max(0, Math.min(100, (x / rect.width) * 100));
      
      // Map percentage to seconds (0-3600, snapped to 15-second intervals)
      const intervalIndex = Math.round((percent / 100) * 240);
      const snappedSeconds = Math.max(0, Math.min(3600, intervalIndex * 15));
      
      const minHandle = document.getElementById('minCooldownWindowHandle');
      const maxHandle = document.getElementById('maxCooldownWindowHandle');
      
      if (dashboardCooldownWindowCurrentHandle === minHandle) {
        if (snappedSeconds >= dashboardMaxCooldownTimerSeconds) return;
        dashboardMinCooldownTimerSeconds = snappedSeconds;
      } else if (dashboardCooldownWindowCurrentHandle === maxHandle) {
        if (snappedSeconds <= dashboardMinCooldownTimerSeconds) return;
        dashboardMaxCooldownTimerSeconds = snappedSeconds;
      }
      
      updateDashboardCooldownWindowSlider();
    }
    
    function handleDashboardCooldownWindowMouseUp() {
      dashboardCooldownWindowIsDragging = false;
      dashboardCooldownWindowCurrentHandle = null;
      document.removeEventListener('mousemove', handleDashboardCooldownWindowMouseMove);
      document.removeEventListener('mouseup', handleDashboardCooldownWindowMouseUp);
    }
    
    // MOMENTUM SCALP Ask Window Slider
    function initDashboardMSAskWindowSlider() {
      const container = document.getElementById('msAskWindowSliderContainer');
      if (!container) return;
      dashboardMSAskSliderWidth = container.offsetWidth;
      updateDashboardMSAskWindowSlider();
      
      const msMinAskHandle = document.getElementById('msMinAskHandle');
      const msMaxAskHandle = document.getElementById('msMaxAskHandle');
      if (msMinAskHandle && !msMinAskHandle._wired) {
        msMinAskHandle._wired = true;
        msMinAskHandle.addEventListener('mousedown', handleDashboardMSAskMouseDown);
        msMinAskHandle.addEventListener('touchstart', handleDashboardMSAskMouseDown);
      }
      if (msMaxAskHandle && !msMaxAskHandle._wired) {
        msMaxAskHandle._wired = true;
        msMaxAskHandle.addEventListener('mousedown', handleDashboardMSAskMouseDown);
        msMaxAskHandle.addEventListener('touchstart', handleDashboardMSAskMouseDown);
      }
    }
    
    function updateDashboardMSAskWindowSlider() {
      if (!dashboardMSAskSliderWidth) return;
      
      // Enforce minimum separation (0.01 = 1 cent)
      const MIN_SEPARATION = 0.01;
      if (dashboardMSMaxAsk - dashboardMSMinAsk < MIN_SEPARATION) {
        // If too close, adjust max to maintain minimum separation
        if (dashboardMSMaxAsk < 1.0) {
          dashboardMSMaxAsk = parseFloat((dashboardMSMinAsk + MIN_SEPARATION).toFixed(4));
        } else {
          // If max is at 1.0, adjust min down
          dashboardMSMinAsk = parseFloat((dashboardMSMaxAsk - MIN_SEPARATION).toFixed(4));
        }
      }
      
      const msMinAskHandle = document.getElementById('msMinAskHandle');
      const msMaxAskHandle = document.getElementById('msMaxAskHandle');
      const msRange = document.getElementById('msAskWindowRange');
      const msMinDisplay = document.getElementById('msAskWindowMinDisplay');
      const msMaxDisplay = document.getElementById('msAskWindowMaxDisplay');
      
      if (!msMinAskHandle || !msMaxAskHandle || !msRange || !msMinDisplay || !msMaxDisplay) return;
      
      // Convert ask prices (0.0000-1.0000) to percentages (0-100)
      const minPercent = (dashboardMSMinAsk / 1.0) * 100;
      const maxPercent = (dashboardMSMaxAsk / 1.0) * 100;
      
      msMinAskHandle.style.left = `${minPercent}%`;
      msMaxAskHandle.style.left = `${maxPercent}%`;
      
      msRange.style.left = `${minPercent}%`;
      msRange.style.width = `${maxPercent - minPercent}%`;
      
      msMinDisplay.textContent = dashboardMSMinAsk.toFixed(4);
      msMaxDisplay.textContent = dashboardMSMaxAsk.toFixed(4);
      
      msMinDisplay.style.left = `${minPercent}%`;
      msMaxDisplay.style.left = `${maxPercent}%`;
    }
    
    function handleDashboardMSAskMouseDown(e) {
      dashboardMSAskIsDragging = true;
      dashboardMSAskCurrentHandle = e.target;
      document.addEventListener('mousemove', handleDashboardMSAskMouseMove);
      document.addEventListener('mouseup', handleDashboardMSAskMouseUp);
      document.addEventListener('touchmove', handleDashboardMSAskMouseMove);
      document.addEventListener('touchend', handleDashboardMSAskMouseUp);
      e.preventDefault();
    }
    
    function handleDashboardMSAskMouseMove(e) {
      if (!dashboardMSAskIsDragging || !dashboardMSAskCurrentHandle) return;
      
      const container = document.getElementById('msAskWindowSliderContainer');
      if (!container) return;
      
      const rect = container.getBoundingClientRect();
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const x = clientX - rect.left;
      const percent = Math.max(0, Math.min(100, (x / rect.width) * 100));
      // Convert percent (0-100) to ask price (0.0000-1.0000) with 4 decimal places
      const askPrice = parseFloat((percent / 100).toFixed(4));
      
      const MIN_SEPARATION = 0.01; // Minimum separation between min and max (0.01 = 1 cent)
      const msMinAskHandle = document.getElementById('msMinAskHandle');
      const msMaxAskHandle = document.getElementById('msMaxAskHandle');
      
      if (dashboardMSAskCurrentHandle === msMinAskHandle) {
        // Ensure min doesn't get too close to max
        if (askPrice >= dashboardMSMaxAsk - MIN_SEPARATION) {
          dashboardMSMinAsk = parseFloat((dashboardMSMaxAsk - MIN_SEPARATION).toFixed(4));
        } else {
          dashboardMSMinAsk = askPrice;
        }
      } else if (dashboardMSAskCurrentHandle === msMaxAskHandle) {
        // Ensure max doesn't get too close to min
        if (askPrice <= dashboardMSMinAsk + MIN_SEPARATION) {
          dashboardMSMaxAsk = parseFloat((dashboardMSMinAsk + MIN_SEPARATION).toFixed(4));
        } else {
          dashboardMSMaxAsk = askPrice;
        }
      }
      
      updateDashboardMSAskWindowSlider();
    }
    
    function handleDashboardMSAskMouseUp() {
      dashboardMSAskIsDragging = false;
      dashboardMSAskCurrentHandle = null;
      document.removeEventListener('mousemove', handleDashboardMSAskMouseMove);
      document.removeEventListener('mouseup', handleDashboardMSAskMouseUp);
      document.removeEventListener('touchmove', handleDashboardMSAskMouseMove);
      document.removeEventListener('touchend', handleDashboardMSAskMouseUp);
    }

    // Minimum Time to Close Controls
    function setupDashboardMinTTCControls() {
      const minTTCDisplay = document.getElementById('autoStopMinTTCDisplay');
      const minTTCInput = document.getElementById('autoStopMinTTCInput');
      const minTTCUp = document.getElementById('autoStopMinTTCUp');
      const minTTCDown = document.getElementById('autoStopMinTTCDown');
      
      if (minTTCDisplay && minTTCInput && minTTCUp && minTTCDown) {
        if (!minTTCUp._dashWired) {
          minTTCUp._dashWired = true;
          minTTCUp.addEventListener('click', function() {
            const currentVal = parseInt(minTTCInput.value, 10) || 0;
            const newVal = currentVal + 15;
            minTTCInput.value = newVal;
            minTTCDisplay.textContent = formatSecondsToMMSS(newVal);
          });
        }
        
        if (!minTTCDown._dashWired) {
          minTTCDown._dashWired = true;
          minTTCDown.addEventListener('click', function() {
            const currentVal = parseInt(minTTCInput.value, 10) || 0;
            const newVal = Math.max(0, currentVal - 30);
            minTTCInput.value = newVal;
            minTTCDisplay.textContent = formatSecondsToMMSS(newVal);
          });
        }
      }
    }

    // Prefetch settings once monitors load (dashboard only — Trade Monitor NEW has no loadMonitors)
    let dashboardSettingsCache = {};
    (function addPrefetch(){
      if (typeof loadMonitors !== 'function') return;
      const originalLoad = loadMonitors;
      loadMonitors = async function(){
        await originalLoad();
        var list = [];
        try {
          if (typeof window.__uatDashboardMonitors === 'function') {
            list = window.__uatDashboardMonitors() || [];
          } else if (typeof monitors !== 'undefined' && Array.isArray(monitors)) {
            list = monitors;
          }
        } catch (e0) { list = []; }
        if (!Array.isArray(list)) return;
        list.forEach(async m => {
          if (!m || !m.id || m.id === 'NEW_MONITOR') return;
          const id = normalizeMonitorIdForApi(m.id);
          try{
            const r = await fetch('/api/get_auto_entry_settings?monitor_id=' + id);
            const j = await r.json();
            if (j && j.status !== 'error') dashboardSettingsCache[m.id] = j;
          }catch(e){ /* ignore */ }
        });
      };
    })();

    function uatRangeBubbleLeftPx(slider, percent) {
      const thumbW = 16;
      const w = slider.offsetWidth;
      const along = percent * Math.max(0, w - thumbW) + thumbW / 2;
      const container = slider.closest('.value-bubble-container');
      if (!container) {
        return slider.offsetLeft + along;
      }
      const sr = slider.getBoundingClientRect();
      const cr = container.getBoundingClientRect();
      return sr.left - cr.left + along;
    }

    // UI value-bubble update functions (same behavior as trade_monitor)
    function updateAutoEntrySliderDisplay(value){
      const display = document.getElementById('autoEntrySliderValueDisplay');
      const slider = document.getElementById('autoEntryProbabilitySlider');
      if (!display || !slider) return;
      display.textContent = value + '%';
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateAutoEntryDifferentialDisplay(value){
      const display = document.getElementById('autoEntryDifferentialValueDisplay');
      const slider = document.getElementById('autoEntryDifferentialSlider');
      if (!display || !slider) return;
      const v = parseFloat(value);
      display.textContent = v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2);
      const min = parseFloat(slider.min), max = parseFloat(slider.max);
      const percent = (v - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateAutoEntryMaxDifferentialDisplay(value){
      const display = document.getElementById('autoEntryMaxDifferentialValueDisplay');
      const slider = document.getElementById('autoEntryMaxDifferentialSlider');
      if (!display || !slider) return;
      const v = parseFloat(value);
      display.textContent = v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2);
      const min = parseFloat(slider.min), max = parseFloat(slider.max);
      const percent = (v - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateAutoEntryMinVolumeDisplay(value){
      const display = document.getElementById('autoEntryMinVolumeValueDisplay');
      const slider = document.getElementById('autoEntryMinVolumeSlider');
      if (!display || !slider) return;
      const raw = parseInt(value, 10);
      const num = Number.isFinite(raw) ? raw : 0;
      display.textContent = Math.max(25, num);
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (num - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateAutoEntryWinStreakThresholdDisplay(value){
      const display = document.getElementById('autoEntryWinStreakThresholdValueDisplay');
      const slider = document.getElementById('autoEntryWinStreakThresholdSlider');
      if (!display || !slider) return;
      const v = parseInt(value, 10);
      display.textContent = v;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (v - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateSpikeAlertMomentumDisplay(value){
      const display = document.getElementById('spikeAlertMomentumValueDisplay');
      const slider = document.getElementById('spikeAlertMomentumSlider');
      if (!display || !slider) return;
      display.textContent = `±${value}`;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateSpikeAlertCooldownDisplay(value){
      const display = document.getElementById('spikeAlertCooldownValueDisplay');
      const slider = document.getElementById('spikeAlertCooldownSlider');
      if (!display || !slider) return;
      display.textContent = `±${value}`;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateSpikeAlertTimeDisplay(value){
      const display = document.getElementById('spikeAlertTimeValueDisplay');
      const slider = document.getElementById('spikeAlertTimeSlider');
      if (!display || !slider) return;
      display.textContent = `${value} min`;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }

    function updateDashboardRisingDevilMinAskRangeDisplay(value){
      const display = document.getElementById('risingDevilMinAskRangeValueDisplay');
      const slider = document.getElementById('risingDevilMinAskRangeSlider');
      if (!display || !slider) return;
      const v = parseInt(value, 10);
      const dollars = (v / 100).toFixed(4);
      display.textContent = dollars;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (v - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }

    function updateProbAdjDisplay(value){
      const display = document.getElementById('probAdjValueDisplay');
      const slider = document.getElementById('probAdjSlider');
      if (!display || !slider) return;
      display.textContent = `${parseFloat(value).toFixed(1)}%`;
      const min = parseFloat(slider.min), max = parseFloat(slider.max);
      const percent = (parseFloat(value) - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateSliderDisplay(value){
      const display = document.getElementById('sliderValueDisplay');
      const slider = document.getElementById('autoStopProbabilitySlider');
      if (!display || !slider) return;
      display.textContent = value + '%';
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateMomentumSpikeThresholdDisplay(value){
      const display = document.getElementById('momentumSpikeThresholdValueDisplay');
      const slider = document.getElementById('momentumSpikeThresholdSlider');
      if (!display || !slider) return;
      display.textContent = `±${value}`;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateVerificationPeriodDisplay(value){
      const display = document.getElementById('verificationPeriodValueDisplay');
      const slider = document.getElementById('verificationPeriodSlider');
      if (!display || !slider) return;
      display.textContent = value;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateDashboardStopLossBubblesFromInt(rawValue) {
      const n = Math.min(99, Math.max(0, parseInt(rawValue, 10) || 0));
      const text = (n / 100).toFixed(2);
      [['stopLossPriceSlider', 'stopLossPriceValueDisplay'], ['stopLossPriceSliderMs', 'stopLossPriceValueDisplayMs']].forEach(([sid, did]) => {
        const slider = document.getElementById(sid);
        const display = document.getElementById(did);
        if (!slider || !display) return;
        display.textContent = text;
        const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
        const percent = (n - min) / (max - min);
        display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
      });
    }
    function syncDashboardStopLossPair(changedSlider) {
      const v = changedSlider.value;
      const otherId = changedSlider.id === 'stopLossPriceSliderMs' ? 'stopLossPriceSlider' : 'stopLossPriceSliderMs';
      const other = document.getElementById(otherId);
      if (other && other.value !== v) other.value = v;
      updateDashboardStopLossBubblesFromInt(v);
    }
    
    // MOMENTUM SCALP value bubble update functions
    function updateMSAutoEntryMinVolumeDisplay(value){
      const display = document.getElementById('msAutoEntryMinVolumeValueDisplay');
      const slider = document.getElementById('msAutoEntryMinVolumeSlider');
      if (!display || !slider) return;
      const raw = parseInt(value, 10);
      const num = Number.isFinite(raw) ? raw : 0;
      display.textContent = Math.max(25, num);
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (num - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateMSAutoEntryProbabilityDisplay(value){
      const display = document.getElementById('msAutoEntrySliderValueDisplay');
      const slider = document.getElementById('msAutoEntryProbabilitySlider');
      if (!display || !slider) return;
      display.textContent = value + '%';
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateMSAutoEntryWinStreakThresholdDisplay(value){
      const display = document.getElementById('msAutoEntryWinStreakThresholdValueDisplay');
      const slider = document.getElementById('msAutoEntryWinStreakThresholdSlider');
      if (!display || !slider) return;
      display.textContent = value;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateMSMomentumThresholdDisplay(value){
      const display = document.getElementById('msMomentumScalpEntryThresholdValueDisplay');
      const slider = document.getElementById('msMomentumScalpEntryThresholdSlider');
      if (!display || !slider) return;
      display.textContent = `±${value}`;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateMSTrailingStopDisplay(value){
      const display = document.getElementById('msMomentumScalpTrailingStopValueDisplay');
      const slider = document.getElementById('msMomentumScalpTrailingStopSlider');
      if (!display || !slider) return;
      const dollars = (parseFloat(value) / 100).toFixed(2);
      display.textContent = dollars;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    function updateMSProfitTargetDisplay(value){
      const display = document.getElementById('msMomentumScalpProfitTargetValueDisplay');
      const slider = document.getElementById('msMomentumScalpProfitTargetSlider');
      if (!display || !slider) return;
      // Convert from slider value (1-50) to decimal (0.01-0.50) for display
      const dollars = (parseFloat(value) / 100).toFixed(2);
      display.textContent = dollars;
      const min = parseInt(slider.min, 10), max = parseInt(slider.max, 10);
      const percent = (value - min) / (max - min);
      display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
    }
    
    // MOMENTUM SCALP Time Window Slider Variables and Functions
    let dashboardMSSliderWidth = 0;
    let dashboardMSMinTimeSeconds = 0;
    let dashboardMSMaxTimeSeconds = 3600;
    let dashboardMSIsDragging = false;
    let dashboardMSCurrentHandle = null;
    
    function initDashboardMSTimeWindowSlider() {
      const container = document.getElementById('msTimeWindowSliderContainer');
      if (!container) return;
      dashboardMSSliderWidth = container.offsetWidth;
      dashboardMSMinTimeSeconds = dashboardMinTimeSeconds;
      dashboardMSMaxTimeSeconds = dashboardMaxTimeSeconds;
      updateDashboardMSTimeWindowSlider();
    }
    
    function updateDashboardMSTimeWindowSlider() {
      if (!dashboardMSSliderWidth) return;
      
      const minHandle = document.getElementById('msMinTimeHandle');
      const maxHandle = document.getElementById('msMaxTimeHandle');
      const range = document.getElementById('msTimeWindowRange');
      const minDisplay = document.getElementById('msTimeWindowMinDisplay');
      const maxDisplay = document.getElementById('msTimeWindowMaxDisplay');
      
      if (!minHandle || !maxHandle || !range || !minDisplay || !maxDisplay) return;
      
      const minPercent = (dashboardMSMinTimeSeconds / 3600) * 100;
      const maxPercent = (dashboardMSMaxTimeSeconds / 3600) * 100;
      
      minHandle.style.left = `${minPercent}%`;
      maxHandle.style.left = `${maxPercent}%`;
      
      range.style.left = `${minPercent}%`;
      range.style.width = `${maxPercent - minPercent}%`;
      
      minDisplay.textContent = formatSecondsToMMSS(dashboardMSMinTimeSeconds);
      maxDisplay.textContent = formatSecondsToMMSS(dashboardMSMaxTimeSeconds);
      
      minDisplay.style.left = `${minPercent}%`;
      maxDisplay.style.left = `${maxPercent}%`;
      
      // Sync with global variables
      dashboardMinTimeSeconds = dashboardMSMinTimeSeconds;
      dashboardMaxTimeSeconds = dashboardMSMaxTimeSeconds;
    }
    
    function handleDashboardMSTimeWindowMouseDown(e) {
      dashboardMSIsDragging = true;
      dashboardMSCurrentHandle = e.target;
      document.addEventListener('mousemove', handleDashboardMSTimeWindowMouseMove);
      document.addEventListener('mouseup', handleDashboardMSTimeWindowMouseUp);
      e.preventDefault();
    }
    
    function handleDashboardMSTimeWindowMouseMove(e) {
      if (!dashboardMSIsDragging || !dashboardMSCurrentHandle) return;
      
      const container = document.getElementById('msTimeWindowSliderContainer');
      if (!container) return;
      
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const percent = Math.max(0, Math.min(100, (x / rect.width) * 100));
      
      const intervalIndex = Math.round((percent / 100) * 240);
      const snappedSeconds = Math.max(0, Math.min(3600, intervalIndex * 15));
      
      const minHandle = document.getElementById('msMinTimeHandle');
      const maxHandle = document.getElementById('msMaxTimeHandle');
      
      if (dashboardMSCurrentHandle === minHandle) {
        if (snappedSeconds >= dashboardMSMaxTimeSeconds) return;
        dashboardMSMinTimeSeconds = snappedSeconds;
        dashboardMinTimeSeconds = snappedSeconds;
      } else if (dashboardMSCurrentHandle === maxHandle) {
        if (snappedSeconds <= dashboardMSMinTimeSeconds) return;
        dashboardMSMaxTimeSeconds = snappedSeconds;
        dashboardMaxTimeSeconds = snappedSeconds;
      }
      
      updateDashboardMSTimeWindowSlider();
    }
    
    function handleDashboardMSTimeWindowMouseUp() {
      dashboardMSIsDragging = false;
      dashboardMSCurrentHandle = null;
      document.removeEventListener('mousemove', handleDashboardMSTimeWindowMouseMove);
      document.removeEventListener('mouseup', handleDashboardMSTimeWindowMouseUp);
    }
    
    // MOMENTUM SCALP Min TTC Controls
    function setupDashboardMSMinTTCControls() {
      const minTTCDisplay = document.getElementById('msAutoStopMinTTCDisplay');
      const minTTCInput = document.getElementById('msAutoStopMinTTCInput');
      const minTTCUp = document.getElementById('msAutoStopMinTTCUp');
      const minTTCDown = document.getElementById('msAutoStopMinTTCDown');
      
      if (minTTCDisplay && minTTCInput && minTTCUp && minTTCDown) {
        if (!minTTCUp._dashMSWired) {
          minTTCUp._dashMSWired = true;
          minTTCUp.addEventListener('click', function() {
            const currentVal = parseInt(minTTCInput.value, 10) || 0;
            const newVal = currentVal + 15;
            minTTCInput.value = newVal;
            minTTCDisplay.textContent = formatSecondsToMMSS(newVal);
          });
        }
        
        if (!minTTCDown._dashMSWired) {
          minTTCDown._dashMSWired = true;
          minTTCDown.addEventListener('click', function() {
            const currentVal = parseInt(minTTCInput.value, 10) || 0;
            const newVal = Math.max(0, currentVal - 30);
            minTTCInput.value = newVal;
            minTTCDisplay.textContent = formatSecondsToMMSS(newVal);
          });
        }
      }
    }

    async function openUnifiedAutoTradeSettings(tileId){
      await ensureUnifiedAutoTradeModalMounted();
      const apiId = normalizeMonitorIdForApi(tileId);
      const modal = document.getElementById('unifiedAutoTradeModal');
      if (!modal) {
        console.warn('openUnifiedAutoTradeSettings: modal missing after mount');
        return;
      }
      modal.style.display = 'flex';
      modal.setAttribute('data-tile-id', tileId); // Store for slider functions
      document.body.style.overflow = 'hidden';
      dashboardUatLoadMonitorPositionIntoModal(apiId);
      void fetchAndRenderDashboardAutoStopAccuracy(apiId);

      const monitor = uatResolveMonitorRow(tileId);
      const currentStrategy = monitor ? monitor.strategy : '';
      const isMomentumScalp = currentStrategy && (currentStrategy.toUpperCase().includes('MOMENTUM SCALP') || currentStrategy.toUpperCase().includes('MOMENTUM REVERSAL'));
      const isMomentumReversal = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM REVERSAL');
      const isMomentumBreakout = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM BREAKOUT');
      const isMomentumContain = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM CONTAIN');
      const isReverseHTC = currentStrategy && currentStrategy.toUpperCase().includes('REVERSE HTC');
      const isHourlyHTC = currentStrategy && currentStrategy.toUpperCase().includes('HOURLY HTC') && !isReverseHTC;
      const is15mHTC = currentStrategy && currentStrategy.toUpperCase().includes('15M HTC');
      const isRisingDevil = currentStrategy && currentStrategy.toUpperCase().includes('RISING DEVIL');
      window.dashboardTimeWindowMaxSeconds = is15mHTC ? 900 : 3600;

      // Update modal title with strategy name and show/hide strategy sections
      const modalTitle = document.getElementById('unifiedAutoTradeModalTitle');
      const dashboardMSStrategyLabel = document.getElementById('dashboardMSStrategyLabel');
      if (modalTitle) {
        modalTitle.textContent = formatDashboardUnifiedAutoTradeModalTitle(tileId, monitor);
      }
      const uatTfInitial = document.getElementById('uatMonitorTestFilter');
      if (uatTfInitial) {
        const mtf = monitor && monitor.test_filter;
        uatTfInitial.checked = !!(mtf === true || mtf === 'true' || mtf === 1);
      }
      
      // Update Momentum Scalp/Reversal label
      if (dashboardMSStrategyLabel) {
        if (isMomentumReversal) {
          dashboardMSStrategyLabel.textContent = 'Momentum Reversal';
        } else {
          dashboardMSStrategyLabel.textContent = 'Momentum Scalp';
        }
      }
      
      // Show/hide strategy sections
      const htcSection = document.getElementById('htcStrategySection');
      const msSection = document.getElementById('msStrategySection');
      const probAdjSpikeGroup = document.getElementById('probAdjSpikeGroup');
      if (htcSection && msSection) {
        if (isMomentumScalp) {
          htcSection.style.display = 'none';
          msSection.style.display = 'contents';
        } else {
          htcSection.style.display = 'contents';
          msSection.style.display = 'none';
        }
      }
      // Probability adjustment: strategy may show it; spike checkbox must also be on (see dashboardUatUpdateSpikeAlertSliderGroupVisibility)
      if (probAdjSpikeGroup) {
        probAdjSpikeGroup.setAttribute('data-strategy-shows-prob-adj', (isHourlyHTC || is15mHTC || isRisingDevil) ? '1' : '0');
      }
      
      // Hide Min Differential, Max Differential for Momentum Breakout and Momentum Contain
      const minDiffLabel = document.querySelector('label[for="autoEntryDifferentialSlider"]');
      const minDiffSlider = document.getElementById('autoEntryDifferentialSlider');
      const minDiffContainer = minDiffSlider ? minDiffSlider.closest('.value-bubble-container') : null;
      const maxDiffLabel = document.querySelector('label[for="autoEntryMaxDifferentialSlider"]');
      const maxDiffSlider = document.getElementById('autoEntryMaxDifferentialSlider');
      const maxDiffContainer = maxDiffSlider ? maxDiffSlider.closest('.value-bubble-container') : null;
      
      if (isMomentumBreakout || isMomentumContain) {
        if (minDiffLabel) minDiffLabel.style.display = 'none';
        if (minDiffContainer) minDiffContainer.style.display = 'none';
        if (maxDiffLabel) maxDiffLabel.style.display = 'none';
        if (maxDiffContainer) maxDiffContainer.style.display = 'none';
      } else {
        if (minDiffLabel) minDiffLabel.style.display = '';
        if (minDiffContainer) minDiffContainer.style.display = '';
        if (maxDiffLabel) maxDiffLabel.style.display = '';
        if (maxDiffContainer) maxDiffContainer.style.display = '';
      }
      
      // Change "Win Probability Window" label to "Price Window" for Momentum Breakout/Contain
      const probWindowLabel = document.querySelector('label[for="probabilityWindowSlider"]');
      if (probWindowLabel) {
        if (isMomentumBreakout || isMomentumContain) {
          probWindowLabel.textContent = 'Price Window:';
        } else {
          probWindowLabel.textContent = 'Win Probability Window:';
        }
      }
      
      // Show/hide Cooldown Window slider (Momentum Contain only)
      const cooldownWindowLabel = document.querySelector('label[for="cooldownWindowSlider"]');
      const cooldownWindowValueContainer = document.querySelector('label[for="cooldownWindowSlider"]')?.nextElementSibling;
      if (cooldownWindowLabel && cooldownWindowValueContainer) {
        if (isMomentumContain) {
          cooldownWindowLabel.style.display = '';
          cooldownWindowValueContainer.style.display = '';
        } else {
          cooldownWindowLabel.style.display = 'none';
          cooldownWindowValueContainer.style.display = 'none';
        }
      }

      const rdRising = document.getElementById('risingDevilMinAskRangeSection');
      if (rdRising) rdRising.style.display = isRisingDevil ? 'block' : 'none';

      const populate = (data) => {
        const setVal = (id,v) => { 
          const el=document.getElementById(id); 
          if (el!=null && v!=null) {
            el.value=v;
            el.dispatchEvent(new Event('input', { bubbles: true }));
          }
        };
        const setChk = (id,v) => { const el=document.getElementById(id); if (el) el.checked=!!v; };
        
          // Regime Monitor settings (common across strategies)
          setChk('regimeMonitorEnabled', data.regime_monitor_enabled ?? false);
          setVal('regimeWindowSelect', data.regime_window ?? '30d');
          {
            const v = data.test_filter;
            setChk('uatMonitorTestFilter', v !== undefined && v !== null ? !!v : !!(monitor && (monitor.test_filter === true || monitor.test_filter === 'true' || monitor.test_filter === 1)));
          }
          {
            const ot = data.order_type;
            const tif = data.time_in_force;
            const otEl = document.getElementById('uatKalshiOrderType');
            const tifEl = document.getElementById('uatKalshiTimeInForce');
            const validOt = ot === 'limit' || ot === 'market' ? ot : 'market';
            const validTif = tif === 'fill_or_kill' || tif === 'immediate_or_cancel' || tif === 'good_till_canceled' ? tif : 'fill_or_kill';
            if (otEl) otEl.value = validOt;
            if (tifEl) tifEl.value = validTif;
          }

          const regimeCb = document.getElementById('regimeMonitorEnabled');
          const regimeSel = document.getElementById('regimeWindowSelect');
          dashboardUatUpdateRegimeWindowPickerVisibility();
          if (regimeCb && !regimeCb._regimeWindowWired) {
            regimeCb._regimeWindowWired = true;
            regimeCb.addEventListener('change', dashboardUatUpdateRegimeWindowPickerVisibility);
          }

        // Determine which strategy section to populate (use the strategy from monitor data)
        const isMomentumScalp = currentStrategy && (currentStrategy.toUpperCase().includes('MOMENTUM SCALP') || currentStrategy.toUpperCase().includes('MOMENTUM REVERSAL'));
      const isMomentumReversal = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM REVERSAL');
      const isMomentumBreakout = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM BREAKOUT');
      const isMomentumContain = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM CONTAIN');
        
        // Common settings (both strategies) — 15m HTC uses 0:00–15:00 (900s)
        const timeMax = (currentStrategy && currentStrategy.toUpperCase().includes('15M HTC')) ? 900 : 3600;
        dashboardMinTimeSeconds = data.min_time !== undefined ? Math.max(0, Math.min(timeMax, data.min_time)) : 0;
        dashboardMaxTimeSeconds = data.max_time !== undefined ? Math.max(0, Math.min(timeMax, data.max_time)) : timeMax;
        
        // Probability window (for Hourly HTC) or Ask Price window (for Momentum Breakout/Contain)
        if (isMomentumBreakout || isMomentumContain) {
          // Load min_ask/max_ask for Momentum Breakout/Contain
          dashboardContainMinAsk = data.min_ask !== undefined ? parseFloat(data.min_ask) : 0.0000;
          dashboardContainMaxAsk = data.max_ask !== undefined ? parseFloat(data.max_ask) : 0.9800;
          
          // Enforce minimum separation (0.01 = 1 cent) when loading from database
          const MIN_ASK_SEPARATION = 0.01;
          if (dashboardContainMaxAsk - dashboardContainMinAsk < MIN_ASK_SEPARATION) {
            if (dashboardContainMaxAsk < 1.0) {
              dashboardContainMaxAsk = parseFloat((dashboardContainMinAsk + MIN_ASK_SEPARATION).toFixed(4));
            } else {
              dashboardContainMinAsk = parseFloat((dashboardContainMaxAsk - MIN_ASK_SEPARATION).toFixed(4));
            }
          }
          
          // Load cooldown timer window values (Momentum Contain only)
          if (isMomentumContain) {
            dashboardMinCooldownTimerSeconds = data.min_cooldown_timer !== undefined && data.min_cooldown_timer !== null ? parseInt(data.min_cooldown_timer, 10) : 300;
            dashboardMaxCooldownTimerSeconds = data.max_cooldown_timer !== undefined && data.max_cooldown_timer !== null ? parseInt(data.max_cooldown_timer, 10) : 3300;
            
            // Initialize slider after values are loaded
            setTimeout(() => {
              if (typeof initDashboardCooldownWindowSlider === 'function') {
                initDashboardCooldownWindowSlider();
              }
            }, 100);
          }
        } else {
          // Probability window (for Hourly HTC)
          dashboardMinProbability = data.min_probability !== undefined ? parseFloat(data.min_probability) : 95.00;
          dashboardMaxProbability = data.max_probability !== undefined ? parseFloat(data.max_probability) : 100.00;
          
          // Enforce minimum separation (0.5%) when loading from database
          const MIN_SEPARATION = 0.5;
          if (dashboardMaxProbability - dashboardMinProbability < MIN_SEPARATION) {
            // If too close, adjust max to maintain minimum separation
            if (dashboardMaxProbability < 100) {
              dashboardMaxProbability = parseFloat((dashboardMinProbability + MIN_SEPARATION).toFixed(1));
            } else {
              // If max is at 100, adjust min down
              dashboardMinProbability = parseFloat((dashboardMaxProbability - MIN_SEPARATION).toFixed(1));
            }
          }
        }
        
        if (isMomentumScalp) {
          // MOMENTUM SCALP settings
          setVal('msAutoEntryMinVolumeSlider', data.min_volume ?? 1000);
          setVal('msAutoEntryWinStreakThresholdSlider', data.win_streak_threshold ?? 22);
          const msLossPreventionToggle = document.getElementById('msAutoEntryLossPreventionToggle');
          const msWinStreakSlider = document.getElementById('msAutoEntryWinStreakThresholdSlider');
          const msWinStreakValueDisplay = document.getElementById('msAutoEntryWinStreakThresholdValueDisplay');
          if (msLossPreventionToggle) {
            msLossPreventionToggle.checked = data.loss_prevention_toggle !== undefined ? data.loss_prevention_toggle : true;
            // Enable/disable slider based on checkbox state
            if (msWinStreakSlider) {
              msWinStreakSlider.disabled = !msLossPreventionToggle.checked;
              msWinStreakSlider.style.opacity = msLossPreventionToggle.checked ? '1' : '0.5';
              msWinStreakSlider.style.cursor = msLossPreventionToggle.checked ? 'pointer' : 'not-allowed';
            }
            // Hide/show value bubble based on checkbox state
            if (msWinStreakValueDisplay) {
              msWinStreakValueDisplay.style.display = msLossPreventionToggle.checked ? 'block' : 'none';
            }
            // Add event listener to update slider state when checkbox changes
            msLossPreventionToggle.addEventListener('change', function() {
              if (msWinStreakSlider) {
                msWinStreakSlider.disabled = !this.checked;
                msWinStreakSlider.style.opacity = this.checked ? '1' : '0.5';
                msWinStreakSlider.style.cursor = this.checked ? 'pointer' : 'not-allowed';
              }
              if (msWinStreakValueDisplay) {
                msWinStreakValueDisplay.style.display = this.checked ? 'block' : 'none';
              }
            });
          }
          
          // Ask window (min_ask and max_ask)
          dashboardMSMinAsk = data.min_ask !== undefined ? parseFloat(data.min_ask) : 0.0000;
          dashboardMSMaxAsk = data.max_ask !== undefined ? parseFloat(data.max_ask) : 0.9800;
          
          // Enforce minimum separation (0.01 = 1 cent) when loading from database
          const MIN_ASK_SEPARATION = 0.01;
          if (dashboardMSMaxAsk - dashboardMSMinAsk < MIN_ASK_SEPARATION) {
            // If too close, adjust max to maintain minimum separation
            if (dashboardMSMaxAsk < 1.0) {
              dashboardMSMaxAsk = parseFloat((dashboardMSMinAsk + MIN_ASK_SEPARATION).toFixed(4));
            } else {
              // If max is at 1.0, adjust min down
              dashboardMSMinAsk = parseFloat((dashboardMSMaxAsk - MIN_ASK_SEPARATION).toFixed(4));
            }
          }
          
          // Momentum Threshold: stored as absolute value (0-100)
          setVal('msMomentumScalpEntryThresholdSlider', data.momentum_scalp_entry_threshold ?? 35);
          
          // Max Price Spread: convert from database (0.0000-0.2000) to slider (0-20)
          const maxPriceSpread = data.max_price_spread !== undefined ? parseFloat(data.max_price_spread) : 0.0300;
          const maxPriceSpreadSliderValue = (maxPriceSpread * 100).toFixed(1); // Convert 0.0300 to 3.0
          setVal('msMaxPriceSpreadSlider', maxPriceSpreadSliderValue);
          // Initialize value display
          const msMaxPriceSpreadValueDisplay = document.getElementById('msMaxPriceSpreadValueDisplay');
          const msMaxPriceSpreadSlider = document.getElementById('msMaxPriceSpreadSlider');
          if (msMaxPriceSpreadValueDisplay && msMaxPriceSpreadSlider) {
            msMaxPriceSpreadValueDisplay.textContent = maxPriceSpreadSliderValue;
            const min = parseFloat(msMaxPriceSpreadSlider.min), max = parseFloat(msMaxPriceSpreadSlider.max);
            const percent = (parseFloat(maxPriceSpreadSliderValue) - min) / (max - min);
            msMaxPriceSpreadValueDisplay.style.left = uatRangeBubbleLeftPx(msMaxPriceSpreadSlider, percent) + 'px';
          }
          
          // Auto Stop
          const msMinTTC = data.min_ttc_seconds !== undefined ? data.min_ttc_seconds : 60;
          const msMinTTCInput = document.getElementById('msAutoStopMinTTCInput');
          const msMinTTCDisplay = document.getElementById('msAutoStopMinTTCDisplay');
          if (msMinTTCInput) msMinTTCInput.value = msMinTTC;
          if (msMinTTCDisplay) msMinTTCDisplay.textContent = formatSecondsToMMSS(msMinTTC);
          
          // Trailing Stop: convert from decimal (0.00-1.00) to slider value (0-100)
          const trailingStop = data.momentum_scalp_trailing_stop_amount ?? 0.10;
          const trailingStopSliderValue = Math.round(trailingStop * 100);
          setVal('msMomentumScalpTrailingStopSlider', trailingStopSliderValue);
          
          // Profit Target: convert from decimal (0.01-0.50) to slider value (1-50)
          const profitTarget = data.momentum_scalp_profit_target ?? 0.10;
          const profitTargetSliderValue = Math.round(profitTarget * 100);
          setVal('msMomentumScalpProfitTargetSlider', profitTargetSliderValue);
        } else {
          // HOURLY HTC settings
        setVal('autoEntryMinVolumeSlider', data.min_volume ?? 1000);
        setVal('autoEntryDifferentialSlider', data.min_differential ?? 0);
        setVal('autoEntryMaxDifferentialSlider', data.max_differential ?? 0);
        setVal('autoEntryWinStreakThresholdSlider', data.win_streak_threshold ?? 22);
          const lossPreventionToggle = document.getElementById('autoEntryLossPreventionToggle');
          const winStreakSlider = document.getElementById('autoEntryWinStreakThresholdSlider');
          const winStreakValueDisplay = document.getElementById('autoEntryWinStreakThresholdValueDisplay');
          if (lossPreventionToggle) {
            lossPreventionToggle.checked = data.loss_prevention_toggle !== undefined ? data.loss_prevention_toggle : true;
            // Enable/disable slider based on checkbox state
            if (winStreakSlider) {
              winStreakSlider.disabled = !lossPreventionToggle.checked;
              winStreakSlider.style.opacity = lossPreventionToggle.checked ? '1' : '0.5';
              winStreakSlider.style.cursor = lossPreventionToggle.checked ? 'pointer' : 'not-allowed';
            }
            // Hide/show value bubble based on checkbox state
            if (winStreakValueDisplay) {
              winStreakValueDisplay.style.display = lossPreventionToggle.checked ? 'block' : 'none';
            }
            // Add event listener to update slider state when checkbox changes
            lossPreventionToggle.addEventListener('change', function() {
              if (winStreakSlider) {
                winStreakSlider.disabled = !this.checked;
                winStreakSlider.style.opacity = this.checked ? '1' : '0.5';
                winStreakSlider.style.cursor = this.checked ? 'pointer' : 'not-allowed';
              }
              if (winStreakValueDisplay) {
                winStreakValueDisplay.style.display = this.checked ? 'block' : 'none';
              }
            });
          }
          
        setVal('probAdjSlider', data.prob_adj ?? 5.00);
        if (currentStrategy && currentStrategy.toUpperCase().includes('RISING DEVIL')) {
          const raw = data.min_ask_range;
          let c = 70;
          if (raw != null && raw !== undefined && !isNaN(parseFloat(raw))) {
            c = Math.min(100, Math.max(0, Math.round(parseFloat(raw) * 100)));
          }
          const rds = document.getElementById('risingDevilMinAskRangeSlider');
          if (rds) {
            rds.value = c;
            if (typeof updateDashboardRisingDevilMinAskRangeDisplay === 'function') {
              updateDashboardRisingDevilMinAskRangeDisplay(String(c));
            }
          }
        }
          
          // Auto Stop settings
        setVal('autoStopProbabilitySlider', data.current_probability ?? 40);
        const minTTC = data.min_ttc_seconds !== undefined ? data.min_ttc_seconds : 60;
        const minTTCInput = document.getElementById('autoStopMinTTCInput');
        const minTTCDisplay = document.getElementById('autoStopMinTTCDisplay');
        if (minTTCInput) minTTCInput.value = minTTC;
        if (minTTCDisplay) minTTCDisplay.textContent = formatSecondsToMMSS(minTTC);
          
        setChk('momentumSpikeEnabled', data.momentum_spike_enabled ?? true);
        setVal('momentumSpikeThresholdSlider', data.momentum_spike_threshold ?? 35);
        setChk('verificationPeriodEnabled', data.verification_period_enabled ?? false);
        setVal('verificationPeriodSlider', data.verification_period_seconds ?? 15);
        setChk('performanceBasedAllocation', data.performance_based_allocation ?? false);
        }
        uatApplySymbolWideFromApi(data);
        setChk('spikeAlertEnabled', data.spike_alert_enabled ?? true);
        setVal('spikeAlertMomentumSlider', data.spike_alert_momentum_threshold ?? 60);
        setVal('spikeAlertCooldownSlider', data.spike_alert_cooldown_threshold ?? 55);
        setVal('spikeAlertTimeSlider', data.spike_alert_cooldown_minutes ?? 15);
        dashboardUatUpdateSpikeAlertSliderGroupVisibility();
        const dashSpikeDetailCb = document.getElementById('spikeAlertEnabled');
        if (dashSpikeDetailCb && !dashSpikeDetailCb._dashboardSpikeDetailVisWired) {
          dashSpikeDetailCb._dashboardSpikeDetailVisWired = true;
          dashSpikeDetailCb.addEventListener('change', dashboardUatUpdateSpikeAlertSliderGroupVisibility);
        }
        dashboardUatApplyFlipRow('uatFlipSellProbabilityStop', data.flip_sell_prob, data.flip_sell_prob_mult);
        dashboardUatApplyFlipRow('uatFlipSellStopLossFloor', data.flip_sell_floor, data.flip_sell_floor_mult);
        dashboardUatApplyFlipRow('uatFlipSellStopLossFloorMs', data.flip_sell_floor, data.flip_sell_floor_mult);
        const slpRaw = data.stop_loss_price !== undefined && data.stop_loss_price !== null
          ? parseFloat(data.stop_loss_price) : 0;
        const slpCents = Math.min(99, Math.max(0, Math.round(slpRaw * 100)));
        const slp1 = document.getElementById('stopLossPriceSlider');
        const slp2 = document.getElementById('stopLossPriceSliderMs');
        if (slp1) slp1.value = String(slpCents);
        if (slp2) slp2.value = String(slpCents);
        
        // Initialize time window slider
        setTimeout(() => {
          if (isMomentumScalp) {
            if (typeof initDashboardMSTimeWindowSlider === 'function') {
              initDashboardMSTimeWindowSlider();
            }
          } else {
            initDashboardTimeWindowSlider();
          }
          // Initialize probability window slider
          if (typeof initDashboardProbabilityWindowSlider === 'function') {
            initDashboardProbabilityWindowSlider();
            updateDashboardProbabilityWindowSlider(); // Update to show correct values based on strategy
          }
          // Initialize cooldown window slider (Momentum Contain only)
          if (typeof initDashboardCooldownWindowSlider === 'function') {
            initDashboardCooldownWindowSlider();
          }
        }, 100);
        // Update value bubbles after a short delay to ensure modal is rendered
        setTimeout(() => {
          if (isMomentumScalp) {
            // MOMENTUM SCALP value bubbles
            const msMinVolumeSlider = document.getElementById('msAutoEntryMinVolumeSlider');
            const msWinStreakSlider = document.getElementById('msAutoEntryWinStreakThresholdSlider');
            const msEntryThresholdSlider = document.getElementById('msMomentumScalpEntryThresholdSlider');
            const msTrailingStopSlider = document.getElementById('msMomentumScalpTrailingStopSlider');
            const msProfitTargetSlider = document.getElementById('msMomentumScalpProfitTargetSlider');
            
            if (msMinVolumeSlider) updateMSAutoEntryMinVolumeDisplay(msMinVolumeSlider.value);
            if (msWinStreakSlider) updateMSAutoEntryWinStreakThresholdDisplay(msWinStreakSlider.value);
            if (msEntryThresholdSlider) updateMSMomentumThresholdDisplay(msEntryThresholdSlider.value);
            if (msTrailingStopSlider) updateMSTrailingStopDisplay(msTrailingStopSlider.value);
            if (msProfitTargetSlider) updateMSProfitTargetDisplay(msProfitTargetSlider.value);
            
            // Initialize MS probability window slider
            if (typeof initDashboardMSAskWindowSlider === 'function') {
              initDashboardMSAskWindowSlider();
            }
            
            // Setup MS Min TTC controls
            setupDashboardMSMinTTCControls();
          } else {
            // HOURLY HTC value bubbles
        updateAutoEntryMinVolumeDisplay(document.getElementById('autoEntryMinVolumeSlider').value);
        updateAutoEntryDifferentialDisplay(document.getElementById('autoEntryDifferentialSlider').value);
        updateAutoEntryMaxDifferentialDisplay(document.getElementById('autoEntryMaxDifferentialSlider').value);
        updateAutoEntryWinStreakThresholdDisplay(document.getElementById('autoEntryWinStreakThresholdSlider').value);
        updateSpikeAlertMomentumDisplay(document.getElementById('spikeAlertMomentumSlider').value);
        updateSpikeAlertCooldownDisplay(document.getElementById('spikeAlertCooldownSlider').value);
        updateSpikeAlertTimeDisplay(document.getElementById('spikeAlertTimeSlider').value);
        updateProbAdjDisplay(document.getElementById('probAdjSlider').value);
        updateSliderDisplay(document.getElementById('autoStopProbabilitySlider').value);
        updateMomentumSpikeThresholdDisplay(document.getElementById('momentumSpikeThresholdSlider').value);
        updateVerificationPeriodDisplay(document.getElementById('verificationPeriodSlider').value);

        // Setup Min TTC controls
        setupDashboardMinTTCControls();
        dashboardUatUpdateSpikeAlertSliderGroupVisibility();
          }

        // Wire up Time Window slider handles
          if (isMomentumScalp) {
            const msMinHandle = document.getElementById('msMinTimeHandle');
            const msMaxHandle = document.getElementById('msMaxTimeHandle');
            if (msMinHandle && !msMinHandle._dashWired) {
              msMinHandle._dashWired = true;
              msMinHandle.addEventListener('mousedown', handleDashboardMSTimeWindowMouseDown);
            }
            if (msMaxHandle && !msMaxHandle._dashWired) {
              msMaxHandle._dashWired = true;
              msMaxHandle.addEventListener('mousedown', handleDashboardMSTimeWindowMouseDown);
            }
          } else {
        const minHandle = document.getElementById('minTimeHandle');
        const maxHandle = document.getElementById('maxTimeHandle');
        if (minHandle && !minHandle._dashWired) {
          minHandle._dashWired = true;
          minHandle.addEventListener('mousedown', handleDashboardTimeWindowMouseDown);
        }
        if (maxHandle && !maxHandle._dashWired) {
          maxHandle._dashWired = true;
          maxHandle.addEventListener('mousedown', handleDashboardTimeWindowMouseDown);
            }
          }
          
          // Wire input listeners
          if (isMomentumScalp) {
            const msPairs = [
              ['msAutoEntryMinVolumeSlider', updateMSAutoEntryMinVolumeDisplay],
              ['msAutoEntryWinStreakThresholdSlider', updateMSAutoEntryWinStreakThresholdDisplay],
              ['msMomentumScalpEntryThresholdSlider', updateMSMomentumThresholdDisplay],
              ['msMaxPriceSpreadSlider', function(value) {
                const display = document.getElementById('msMaxPriceSpreadValueDisplay');
                const slider = document.getElementById('msMaxPriceSpreadSlider');
                if (!display || !slider) return;
                display.textContent = parseFloat(value).toFixed(1);
                const min = parseFloat(slider.min), max = parseFloat(slider.max);
                const percent = (parseFloat(value) - min) / (max - min);
                display.style.left = uatRangeBubbleLeftPx(slider, percent) + 'px';
              }],
              ['msMomentumScalpTrailingStopSlider', updateMSTrailingStopDisplay],
              ['msMomentumScalpProfitTargetSlider', updateMSProfitTargetDisplay]
            ];
            msPairs.forEach(([id, fn]) => {
              const el = document.getElementById(id);
              if (el && !el._dashUnifiedWired) {
                el._dashUnifiedWired = true;
                el.addEventListener('input', function(){ fn(this.value); });
              }
            });
          } else {
        const pairs = [
          ['autoEntryMinVolumeSlider', updateAutoEntryMinVolumeDisplay],
          ['risingDevilMinAskRangeSlider', updateDashboardRisingDevilMinAskRangeDisplay],
          ['autoEntryDifferentialSlider', updateAutoEntryDifferentialDisplay],
          ['autoEntryMaxDifferentialSlider', updateAutoEntryMaxDifferentialDisplay],
          ['autoEntryWinStreakThresholdSlider', updateAutoEntryWinStreakThresholdDisplay],
          ['spikeAlertMomentumSlider', updateSpikeAlertMomentumDisplay],
          ['spikeAlertCooldownSlider', updateSpikeAlertCooldownDisplay],
          ['spikeAlertTimeSlider', updateSpikeAlertTimeDisplay],
          ['probAdjSlider', updateProbAdjDisplay],
          ['autoStopProbabilitySlider', updateSliderDisplay],
          ['momentumSpikeThresholdSlider', updateMomentumSpikeThresholdDisplay],
          ['verificationPeriodSlider', updateVerificationPeriodDisplay]
        ];
        pairs.forEach(([id, fn]) => {
          const el = document.getElementById(id);
          if (el && !el._dashUnifiedWired) {
            el._dashUnifiedWired = true;
            el.addEventListener('input', function(){ fn(this.value); });
          }
        });
          }
          ['stopLossPriceSlider', 'stopLossPriceSliderMs'].forEach(function(sid) {
            const sl = document.getElementById(sid);
            if (sl) {
              updateDashboardStopLossBubblesFromInt(sl.value);
              if (!sl._dashUnifiedWired) {
                sl._dashUnifiedWired = true;
                sl.addEventListener('input', function(){ syncDashboardStopLossPair(this); });
              }
            }
          });
        }, 150);
      };

      const cached = dashboardSettingsCache[tileId];
      if (cached) {
        populate(cached);
      } else {
        fetch('/api/get_auto_entry_settings?monitor_id=' + apiId)
          .then(r=>r.json()).then(j=>{ if (j&&j.status!=='error'){ dashboardSettingsCache[tileId]=j; populate(j);} });
      }

      // Save
      const saveBtn = document.getElementById('unifiedAutoTradeSave');
      if (!saveBtn) {
        console.warn('openUnifiedAutoTradeSettings: unifiedAutoTradeSave button missing');
      } else saveBtn.onclick = async function(){
        if (modal.dataset.uatSaveInFlight === '1') return;
        // Determine which strategy is active (use the strategy from monitor data)
        const isMomentumScalp = currentStrategy && (currentStrategy.toUpperCase().includes('MOMENTUM SCALP') || currentStrategy.toUpperCase().includes('MOMENTUM REVERSAL'));
      const isMomentumReversal = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM REVERSAL');
      const isMomentumBreakout = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM BREAKOUT');
      const isMomentumContain = currentStrategy && currentStrategy.toUpperCase().includes('MOMENTUM CONTAIN');
      const isReverseHTC = currentStrategy && currentStrategy.toUpperCase().includes('REVERSE HTC');
      const isHourlyHTC = currentStrategy && currentStrategy.toUpperCase().includes('HOURLY HTC') && !isReverseHTC;
      const is15mHTC = currentStrategy && currentStrategy.toUpperCase().includes('15M HTC');
      const isRisingDevil = currentStrategy && currentStrategy.toUpperCase().includes('RISING DEVIL');
        
        const payload = {
          monitor_id: apiId,
          min_time: dashboardMinTimeSeconds,
          max_time: dashboardMaxTimeSeconds
        };

        const regimeMonitorEnabledEl = document.getElementById('regimeMonitorEnabled');
        const regimeWindowEl = document.getElementById('regimeWindowSelect');
        payload.regime_monitor_enabled = regimeMonitorEnabledEl ? regimeMonitorEnabledEl.checked : false;
        payload.regime_window = regimeWindowEl ? regimeWindowEl.value : '30d';
        const uatMonitorTestFilterEl = document.getElementById('uatMonitorTestFilter');
        payload.test_filter = uatMonitorTestFilterEl ? uatMonitorTestFilterEl.checked : false;
        {
          const otEl = document.getElementById('uatKalshiOrderType');
          const tifEl = document.getElementById('uatKalshiTimeInForce');
          const ot = otEl && otEl.value;
          const tif = tifEl && tifEl.value;
          payload.order_type = ot === 'limit' || ot === 'market' ? ot : 'market';
          payload.time_in_force = tif === 'fill_or_kill' || tif === 'immediate_or_cancel' || tif === 'good_till_canceled' ? tif : 'fill_or_kill';
        }
        
        if (isMomentumScalp) {
          // MOMENTUM SCALP specific fields
          const msMinVolumeSlider = document.getElementById('msAutoEntryMinVolumeSlider');
          const msMomentumThresholdSlider = document.getElementById('msMomentumScalpEntryThresholdSlider');
          const msMinTTCInput = document.getElementById('msAutoStopMinTTCInput');
          const msTrailingStopSlider = document.getElementById('msMomentumScalpTrailingStopSlider');
          const msProfitTargetSlider = document.getElementById('msMomentumScalpProfitTargetSlider');
          
          if (msMinVolumeSlider) {
            payload.min_volume = parseInt(msMinVolumeSlider.value, 10);
          }
          // Use ask window values (ensure they're floats with 4 decimal places)
          payload.min_ask = parseFloat(parseFloat(dashboardMSMinAsk).toFixed(4));
          payload.max_ask = parseFloat(parseFloat(dashboardMSMaxAsk).toFixed(4));
          // Max Price Spread: convert from slider (0-20) to database (0.0000-0.2000)
          const maxPriceSpreadSlider = document.getElementById('msMaxPriceSpreadSlider');
          if (maxPriceSpreadSlider) {
            const sliderValue = parseFloat(maxPriceSpreadSlider.value);
            payload.max_price_spread = parseFloat((sliderValue / 100).toFixed(4)); // Convert 3.0 to 0.0300
          }
          if (msMomentumThresholdSlider) {
            payload.momentum_scalp_entry_threshold = parseInt(msMomentumThresholdSlider.value, 10);
          }
          if (msMinTTCInput) {
            payload.min_ttc_seconds = parseInt(msMinTTCInput.value, 10);
          }
          if (msTrailingStopSlider) {
            // Convert from slider value (0-100) to decimal (0.00-1.00)
            payload.momentum_scalp_trailing_stop_amount = parseFloat(msTrailingStopSlider.value) / 100;
          }
          if (msProfitTargetSlider) {
            // Convert from slider value (50-100) to decimal (0.50-1.00)
            payload.momentum_scalp_profit_target = parseFloat(msProfitTargetSlider.value) / 100;
          }
          const msWinStreakSlider = document.getElementById('msAutoEntryWinStreakThresholdSlider');
          if (msWinStreakSlider) {
            payload.win_streak_threshold = parseInt(msWinStreakSlider.value, 10);
          }
          const msLossPreventionToggle = document.getElementById('msAutoEntryLossPreventionToggle');
          if (msLossPreventionToggle) {
            payload.loss_prevention_toggle = msLossPreventionToggle.checked;
          }
        } else if (isMomentumBreakout || isMomentumContain) {
          // MOMENTUM BREAKOUT/CONTAIN specific fields
          payload.min_volume = parseInt(document.getElementById('autoEntryMinVolumeSlider').value,10);
          // Use ask price window values (ensure they're floats with 4 decimal places)
          payload.min_ask = parseFloat(parseFloat(dashboardContainMinAsk).toFixed(4));
          payload.max_ask = parseFloat(parseFloat(dashboardContainMaxAsk).toFixed(4));
          // Win Streak Threshold and Loss Prevention Toggle (same as Hourly HTC)
          payload.win_streak_threshold = parseInt(document.getElementById('autoEntryWinStreakThresholdSlider').value,10);
          const lossPreventionToggle = document.getElementById('autoEntryLossPreventionToggle');
          if (lossPreventionToggle) {
            payload.loss_prevention_toggle = lossPreventionToggle.checked;
          }
          // Spike Alert settings
          payload.spike_alert_enabled = document.getElementById('spikeAlertEnabled').checked;
          payload.spike_alert_momentum_threshold = parseInt(document.getElementById('spikeAlertMomentumSlider').value,10);
          payload.spike_alert_cooldown_threshold = parseInt(document.getElementById('spikeAlertCooldownSlider').value,10);
          payload.spike_alert_cooldown_minutes = parseInt(document.getElementById('spikeAlertTimeSlider').value,10);
          // Cooldown Timer Window (Momentum Contain only)
          if (isMomentumContain) {
            payload.min_cooldown_timer = dashboardMinCooldownTimerSeconds;
            payload.max_cooldown_timer = dashboardMaxCooldownTimerSeconds;
          }
          // Auto Stop settings
          payload.current_probability = parseInt(document.getElementById('autoStopProbabilitySlider').value,10);
          payload.min_ttc_seconds = parseInt(document.getElementById('autoStopMinTTCInput') ? document.getElementById('autoStopMinTTCInput').value : '60',10);
          payload.momentum_spike_enabled = document.getElementById('momentumSpikeEnabled').checked;
          payload.momentum_spike_threshold = parseInt(document.getElementById('momentumSpikeThresholdSlider').value,10);
          payload.verification_period_enabled = document.getElementById('verificationPeriodEnabled').checked;
          payload.verification_period_seconds = parseInt(document.getElementById('verificationPeriodSlider').value,10);
          // Performance Based Allocation (same as Hourly HTC)
          payload.performance_based_allocation = document.getElementById('performanceBasedAllocation').checked;
        } else if (isRisingDevil) {
          payload.min_volume = parseInt(document.getElementById('autoEntryMinVolumeSlider').value,10);
          payload.min_probability = parseFloat(parseFloat(dashboardMinProbability).toFixed(1));
          payload.max_probability = parseFloat(parseFloat(dashboardMaxProbability).toFixed(1));
          payload.min_differential = parseFloat(document.getElementById('autoEntryDifferentialSlider').value);
          payload.max_differential = (function(){ const v=parseFloat(document.getElementById('autoEntryMaxDifferentialSlider').value); return isNaN(v)||v<=0? null:v; })();
          const rdSl = document.getElementById('risingDevilMinAskRangeSlider');
          payload.min_ask_range = rdSl ? parseInt(rdSl.value, 10) / 100 : 0.7;
          payload.win_streak_threshold = parseInt(document.getElementById('autoEntryWinStreakThresholdSlider').value,10);
          const lossPreventionToggleRD = document.getElementById('autoEntryLossPreventionToggle');
          if (lossPreventionToggleRD) {
            payload.loss_prevention_toggle = lossPreventionToggleRD.checked;
          }
          payload.current_probability = parseInt(document.getElementById('autoStopProbabilitySlider').value,10);
          payload.min_ttc_seconds = parseInt(document.getElementById('autoStopMinTTCInput') ? document.getElementById('autoStopMinTTCInput').value : '60',10);
          payload.momentum_spike_enabled = document.getElementById('momentumSpikeEnabled').checked;
          payload.momentum_spike_threshold = parseInt(document.getElementById('momentumSpikeThresholdSlider').value,10);
          payload.verification_period_enabled = document.getElementById('verificationPeriodEnabled').checked;
          payload.verification_period_seconds = parseInt(document.getElementById('verificationPeriodSlider').value,10);
          payload.spike_alert_enabled = document.getElementById('spikeAlertEnabled').checked;
          payload.spike_alert_momentum_threshold = parseInt(document.getElementById('spikeAlertMomentumSlider').value,10);
          payload.spike_alert_cooldown_threshold = parseInt(document.getElementById('spikeAlertCooldownSlider').value,10);
          payload.spike_alert_cooldown_minutes = parseInt(document.getElementById('spikeAlertTimeSlider').value,10);
          payload.prob_adj = parseFloat(document.getElementById('probAdjSlider').value);
          payload.performance_based_allocation = document.getElementById('performanceBasedAllocation').checked;
        } else {
          // HOURLY HTC specific fields
          payload.min_volume = parseInt(document.getElementById('autoEntryMinVolumeSlider').value,10);
          // Use probability window values (ensure they're floats with 1 decimal)
          payload.min_probability = parseFloat(parseFloat(dashboardMinProbability).toFixed(1));
          payload.max_probability = parseFloat(parseFloat(dashboardMaxProbability).toFixed(1));
          payload.min_differential = parseFloat(document.getElementById('autoEntryDifferentialSlider').value);
          payload.max_differential = (function(){ const v=parseFloat(document.getElementById('autoEntryMaxDifferentialSlider').value); return isNaN(v)||v<=0? null:v; })();
          payload.win_streak_threshold = parseInt(document.getElementById('autoEntryWinStreakThresholdSlider').value,10);
          const lossPreventionToggle = document.getElementById('autoEntryLossPreventionToggle');
          if (lossPreventionToggle) {
            payload.loss_prevention_toggle = lossPreventionToggle.checked;
          }
          payload.current_probability = parseInt(document.getElementById('autoStopProbabilitySlider').value,10);
          payload.min_ttc_seconds = parseInt(document.getElementById('autoStopMinTTCInput') ? document.getElementById('autoStopMinTTCInput').value : '60',10);
          payload.momentum_spike_enabled = document.getElementById('momentumSpikeEnabled').checked;
          payload.momentum_spike_threshold = parseInt(document.getElementById('momentumSpikeThresholdSlider').value,10);
          payload.verification_period_enabled = document.getElementById('verificationPeriodEnabled').checked;
          payload.verification_period_seconds = parseInt(document.getElementById('verificationPeriodSlider').value,10);
          payload.spike_alert_enabled = document.getElementById('spikeAlertEnabled').checked;
          payload.spike_alert_momentum_threshold = parseInt(document.getElementById('spikeAlertMomentumSlider').value,10);
          payload.spike_alert_cooldown_threshold = parseInt(document.getElementById('spikeAlertCooldownSlider').value,10);
          payload.spike_alert_cooldown_minutes = parseInt(document.getElementById('spikeAlertTimeSlider').value,10);
          // Include prob_adj for Hourly HTC and 15m HTC (not Reverse HTC)
          if (isHourlyHTC || is15mHTC) {
            payload.prob_adj = parseFloat(document.getElementById('probAdjSlider').value);
          }
          payload.performance_based_allocation = document.getElementById('performanceBasedAllocation').checked;
        }
        Object.assign(payload, uatReadSymbolWideForPayload(isMomentumScalp));
        const stopLossPriceSliderEl = document.getElementById(isMomentumScalp ? 'stopLossPriceSliderMs' : 'stopLossPriceSlider')
          || document.getElementById('stopLossPriceSlider');
        if (stopLossPriceSliderEl) {
          payload.stop_loss_price = parseInt(stopLossPriceSliderEl.value, 10) / 100;
        }
        if (isMomentumScalp) {
          var msFloorCb = document.getElementById('uatFlipSellStopLossFloorMs');
          if (msFloorCb) {
            payload.flip_sell_floor = msFloorCb.checked;
            payload.flip_sell_floor_mult = dashboardUatReadFlipMult('uatFlipSellStopLossFloorMs');
          }
        } else {
          var probCb = document.getElementById('uatFlipSellProbabilityStop');
          var htcFloorCb = document.getElementById('uatFlipSellStopLossFloor');
          if (probCb) {
            payload.flip_sell_prob = probCb.checked;
            payload.flip_sell_prob_mult = dashboardUatReadFlipMult('uatFlipSellProbabilityStop');
          }
          if (htcFloorCb) {
            payload.flip_sell_floor = htcFloorCb.checked;
            payload.flip_sell_floor_mult = dashboardUatReadFlipMult('uatFlipSellStopLossFloor');
          }
        }
        try {
          modal.dataset.uatSaveInFlight = '1';
          saveBtn.disabled = true;
          const resp = await fetch('/api/set_auto_entry_settings', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
          const text = await resp.text();
          let j = {};
          try {
            j = text ? JSON.parse(text) : {};
          } catch (parseErr) {
            j = { status: 'error', message: 'Invalid response from server' };
          }
          if (!resp.ok && j.status !== 'error') {
            j = { status: 'error', message: text ? text.slice(0, 200) : ('HTTP ' + resp.status) };
          }
          if (j && j.status !== 'error') {
            dashboardSettingsCache[tileId] = { ...dashboardSettingsCache[tileId], ...payload };
            const monitorObj = uatResolveMonitorRow(tileId);
            if (monitorObj) {
              monitorObj.regime_monitor_enabled = payload.regime_monitor_enabled;
              monitorObj.regime_window = payload.regime_window;
              monitorObj.test_filter = !!payload.test_filter;
              if (payload.test_filter) {
                monitorObj.paper_trade = true;
              }
              if (typeof updatePaperTradingUI === 'function') {
                updatePaperTradingUI(tileId, monitorObj.paper_trade || false);
              }
            }
            if (typeof window.__uatAfterSaveSuccess === 'function') {
              try { window.__uatAfterSaveSuccess(tileId, payload, monitorObj); } catch (e2) {}
            }
            // Do not await position persist: readFromEls runs synchronously first; a slow/hanging
            // /api/update_monitor_position must not block closing the modal.
            if (window.UatUnifiedModalPositionSize) {
              window.UatUnifiedModalPositionSize.persistModalPosition(modal, apiId, { mirrorSidebar: false })
                .catch(function (err) {
                  console.warn('persistModalPosition after save', err);
                });
            }
            closeUnifiedAutoTradeSettings();
          } else {
            const msg = (j && j.message) ? String(j.message) : 'Could not save monitor settings.';
            console.error('set_auto_entry_settings', j);
            alert('Save failed: ' + msg);
          }
        } catch (e) {
          console.error('Save failed', e);
          alert('Save failed: ' + (e && e.message ? e.message : 'Network error'));
        } finally {
          delete modal.dataset.uatSaveInFlight;
          saveBtn.disabled = false;
        }
      };

      // Close handlers
      document.getElementById('unifiedAutoTradeCancel').onclick = closeUnifiedAutoTradeSettings;
      // Backdrop click intentionally does not close (avoid accidental dismiss while adjusting settings).

      // Keyboard shortcuts: ENTER saves, ESC closes
      const unifiedKeyHandler = function(e){
        if (modal.style.display === 'none') return;
        if (e.key === 'Enter') {
          e.preventDefault();
          const btn = document.getElementById('unifiedAutoTradeSave');
          if (btn) btn.click();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          closeUnifiedAutoTradeSettings();
        }
      };
      // avoid duplicate listeners
      if (!modal._keydownHandler) {
        document.addEventListener('keydown', unifiedKeyHandler);
        modal._keydownHandler = unifiedKeyHandler;
      }
    }

    function closeUnifiedAutoTradeSettings(){
      const modal = document.getElementById('unifiedAutoTradeModal');
      if (!modal) return;
      if (window.UatUnifiedModalPositionSize && modal) {
        window.UatUnifiedModalPositionSize.restoreOpenSnapshot(modal);
      }
      modal.style.display = 'none';
      document.body.style.overflow = 'auto';
      if (modal._keydownHandler) {
        document.removeEventListener('keydown', modal._keydownHandler);
        delete modal._keydownHandler;
      }
    }

    /** Mouse-following "Monitor Settings" tooltip for dashboard monitor tiles and TM NEW gear (win-streak chrome via `.uat-monitor-settings-tooltip` CSS). */
    (function uatInstallMonitorSettingsGearCursorTooltip() {
      if (window.__uatMonitorGearCursorTipInstalled) return;
      window.__uatMonitorGearCursorTipInstalled = true;

      var tipEl = null;
      var timer = null;
      var anchor = null;

      function hide() {
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        anchor = null;
        if (tipEl) tipEl.classList.remove('is-visible');
      }

      function ensureTip() {
        if (!tipEl) {
          tipEl = document.createElement('div');
          tipEl.className = 'uat-monitor-settings-tooltip';
          tipEl.setAttribute('role', 'tooltip');
          document.body.appendChild(tipEl);
        }
        return tipEl;
      }

      function position(ev) {
        if (!tipEl) return;
        var offset = 12;
        var x = ev.clientX + offset;
        var y = ev.clientY + offset;
        var maxX = window.innerWidth - tipEl.offsetWidth - 8;
        var maxY = window.innerHeight - tipEl.offsetHeight - 8;
        if (x > maxX) x = maxX;
        if (y > maxY) y = maxY;
        tipEl.style.left = Math.max(8, x) + 'px';
        tipEl.style.top = Math.max(8, y) + 'px';
      }

      function gearFromEvent(e) {
        var t = e.target;
        if (!t || !t.closest) return null;
        var img = t.closest('img.monitor-settings-icon');
        if (img) return img;
        var btn = t.closest('button.tm-new-uat-settings-btn');
        if (btn) return btn;
        return null;
      }

      document.addEventListener(
        'scroll',
        function () {
          if (anchor) hide();
        },
        true
      );
      window.addEventListener('blur', function () {
        if (anchor) hide();
      });

      document.addEventListener(
        'mousedown',
        function () {
          if (anchor) hide();
        },
        true
      );

      document.addEventListener(
        'mouseover',
        function (e) {
          var g = gearFromEvent(e);
          if (!g) return;
          if (anchor !== g) {
            anchor = g;
            ensureTip();
            tipEl.textContent = 'Monitor Settings';
            position(e);
            if (timer) clearTimeout(timer);
            timer = setTimeout(function () {
              timer = null;
              if (anchor === g) tipEl.classList.add('is-visible');
            }, 80);
          } else {
            position(e);
          }
        },
        true
      );

      document.addEventListener('mousemove', function (e) {
        if (!anchor) return;
        if (gearFromEvent(e) !== anchor) return;
        position(e);
      });

      document.addEventListener(
        'mouseout',
        function (e) {
          if (!anchor) return;
          if (!anchor.contains(e.target)) return;
          var rel = e.relatedTarget;
          if (!rel || !anchor.contains(rel)) {
            hide();
          }
        },
        true
      );
    })();

    window.openUnifiedAutoTradeSettings = openUnifiedAutoTradeSettings;
    window.closeUnifiedAutoTradeSettings = closeUnifiedAutoTradeSettings;
    window.uatApplySymbolWideFromApi = uatApplySymbolWideFromApi;
    window.uatReadSymbolWideForPayload = uatReadSymbolWideForPayload;
    window.uatSymbolWideSyncDisabledState = uatSymbolWideSyncDisabledState;
