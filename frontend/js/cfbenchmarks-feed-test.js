(function () {
  'use strict';

  const INDICES = ['BRTI', 'ETHUSD_RTI', 'SOLUSD_RTI', 'XRPUSD_RTI', 'DOGEUSD_RTI'];
  const INDEX_TO_COIN = {
    BRTI: 'BTC',
    ETHUSD_RTI: 'ETH',
    SOLUSD_RTI: 'SOL',
    XRPUSD_RTI: 'XRP',
    DOGEUSD_RTI: 'DOGE',
  };
  const COINS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];
  const INDEX_IDS_CSV = INDICES.join(',');
  const MAX_LOG_ROWS = 120;

  const state = {
    cfPrice: {},
    cfOneMinAvg: {},
    coinPrice: {},
    coinOneMinAvg: {},
    coinMom1m: {},
    tickCount: 0,
    tickWindowStart: Date.now(),
    ticksInWindow: 0,
  };

  INDICES.forEach(function (iid) {
    state.cfPrice[iid] = null;
    state.cfOneMinAvg[iid] = null;
  });
  COINS.forEach(function (sym) {
    state.coinPrice[sym] = null;
    state.coinOneMinAvg[sym] = null;
    state.coinMom1m[sym] = null;
  });

  const el = (id) => document.getElementById(id);
  const panel = (indexId) =>
    document.querySelector('.cfb-panel[data-index="' + indexId + '"]');

  function wsUrl(path) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + window.location.host + path;
  }

  function fmtPrice(n, sym) {
    if (n == null || Number.isNaN(n)) return '—';
    const maxFrac = sym === 'XRP' || sym === 'DOGE' ? 4 : 2;
    return Number(n).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: maxFrac,
    });
  }

  function fmtMs(ms) {
    if (ms == null) return '—';
    try {
      const d = new Date(Number(ms));
      return (
        d.toLocaleTimeString('en-US', { hour12: false }) +
        '.' +
        String(d.getMilliseconds()).padStart(3, '0')
      );
    } catch (_) {
      return String(ms);
    }
  }

  function setStatus(node, text, cls) {
    if (!node) return;
    node.textContent = text;
    node.className = 'cfb-status' + (cls ? ' ' + cls : '');
  }

  function logTagClass(indexId) {
    const sym = INDEX_TO_COIN[indexId] || '';
    if (sym === 'ETH') return 'tag eth';
    if (sym === 'SOL') return 'tag sol';
    if (sym === 'XRP') return 'tag xrp';
    if (sym === 'DOGE') return 'tag doge';
    return 'tag btc';
  }

  function fmtDiffLine(label, cfVal, coinVal, sym) {
    if (cfVal == null || coinVal == null || Number.isNaN(cfVal) || Number.isNaN(coinVal)) {
      return { text: label + ': —', cls: 'cfb-diff' };
    }
    const diff = cfVal - coinVal;
    const pct = coinVal !== 0 ? (diff / coinVal) * 100 : 0;
    const frac = sym === 'XRP' || sym === 'DOGE' ? 4 : 2;
    return {
      text:
        label +
        ': ' +
        (diff >= 0 ? '+' : '') +
        diff.toFixed(frac) +
        ' (' +
        (pct >= 0 ? '+' : '') +
        pct.toFixed(4) +
        '%)',
      cls: 'cfb-diff ' + (diff >= 0 ? 'pos' : 'neg'),
    };
  }

  function setDiffEl(node, line) {
    if (!node) return;
    node.textContent = line.text;
    node.className = line.cls;
  }

  function updateComparisons(indexId) {
    const p = panel(indexId);
    if (!p) return;
    const spreadEl = p.querySelector('[data-field="spread"]');
    const avgEl = p.querySelector('[data-field="avg1m-diff"]');
    const sym = INDEX_TO_COIN[indexId];
    setDiffEl(
      spreadEl,
      fmtDiffLine('spot vs CB', state.cfPrice[indexId], state.coinPrice[sym], sym)
    );
    setDiffEl(
      avgEl,
      fmtDiffLine('1m avg vs CB', state.cfOneMinAvg[indexId], state.coinOneMinAvg[sym], sym)
    );
  }

  function fmtMom1mPct(n) {
    if (n == null || Number.isNaN(n)) return '—';
    return Number(n).toFixed(1);
  }

  function applyMom1mClasses(el, mom1m, extraClass) {
    el.className = 'cfb-mom1m' + (extraClass ? ' ' + extraClass : '');
    if (mom1m != null && !Number.isNaN(mom1m)) {
      const v = Number(mom1m);
      if (v >= 55) el.classList.add('pos');
      else if (v <= 45) el.classList.add('neg');
    }
  }

  function rowFieldFromSpotMsg(data, sym, field) {
    const rows = data.rows || [];
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (!r || String(r.symbol || '').trim().toUpperCase() !== sym) continue;
      const raw = r[field];
      if (raw != null && !Number.isNaN(Number(raw))) return Number(raw);
    }
    return null;
  }

  function oneMinAvgFromSpotMsg(data, sym) {
    const bag = data.one_minute_avg_by_symbol || {};
    let val = bag[sym];
    if (val == null) {
      Object.keys(bag).forEach(function (k) {
        if (String(k).trim().toUpperCase() === sym && val == null) val = bag[k];
      });
    }
    if (val != null && !Number.isNaN(Number(val))) return Number(val);
    return rowFieldFromSpotMsg(data, sym, 'one_minute_avg');
  }

  function cfbOneMinAvgFromTick(tick) {
    if (tick.one_minute_avg != null && !Number.isNaN(Number(tick.one_minute_avg))) {
      return Number(tick.one_minute_avg);
    }
    const inner = tick.avg_60s_data;
    if (inner && inner.value != null) {
      const v = Number(inner.value);
      if (!Number.isNaN(v)) return v;
    }
    return null;
  }

  function mom1mFromSpotMsg(data, sym) {
    const bag = data.momentum_1m_avg_by_symbol || {};
    let val = bag[sym];
    if (val == null) {
      Object.keys(bag).forEach(function (k) {
        if (String(k).trim().toUpperCase() === sym && val == null) val = bag[k];
      });
    }
    if (val != null && !Number.isNaN(Number(val))) return Number(val);
    return rowFieldFromSpotMsg(data, sym, 'momentum_1m_avg');
  }

  function renderCoin1mAvg(sym) {
    const node = el('cfb-coin-' + sym.toLowerCase() + '-1mavg');
    if (!node) return;
    const avg = state.coinOneMinAvg[sym];
    node.innerHTML =
      'CB 1m avg <strong>' + fmtPrice(avg, sym) + '</strong>';
  }

  function renderCoinMom1m(sym) {
    const elMom = el('cfb-coin-' + sym.toLowerCase() + '-mom1m');
    if (!elMom) return;
    const mom1m = state.coinMom1m[sym];
    elMom.innerHTML = 'CB Mom 1m <strong>' + fmtMom1mPct(mom1m) + '</strong>';
    applyMom1mClasses(elMom, mom1m, 'coin-mom');
  }

  function applyLiveSymbolSpot(data) {
    if (!data || data.type !== 'live_symbol_spot') return;
    COINS.forEach(function (sym) {
      const spot = data.spot_by_symbol && data.spot_by_symbol[sym];
      if (spot != null) state.coinPrice[sym] = Number(spot);
      const rowAvg = oneMinAvgFromSpotMsg(data, sym);
      if (rowAvg != null) state.coinOneMinAvg[sym] = rowAvg;
      state.coinMom1m[sym] = mom1mFromSpotMsg(data, sym);
      const node = el('cfb-coin-' + sym.toLowerCase());
      const sub = el('cfb-coin-' + sym.toLowerCase() + '-sub');
      if (node) node.textContent = fmtPrice(state.coinPrice[sym], sym);
      if (sub) sub.textContent = 'updated ' + (data.timestamp || '');
      renderCoin1mAvg(sym);
      renderCoinMom1m(sym);
    });
    INDICES.forEach(updateComparisons);
  }

  function renderMom1m(indexId, tick) {
    const p = panel(indexId);
    if (!p) return;
    const elMom = p.querySelector('[data-field="mom1m"]');
    if (!elMom) return;
    const mom1m = tick.momentum_1m_avg;
    elMom.innerHTML =
      'CFB Mom 1m <strong>' + fmtMom1mPct(mom1m) + '</strong>';
    applyMom1mClasses(elMom, mom1m);
  }

  function prependLog(tick) {
    const log = el('cfb-tick-log');
    if (!log) return;
    const iid = (tick.index_id || '').toUpperCase();
    const sym = INDEX_TO_COIN[iid];
    const row = document.createElement('div');
    row.className = 'cfb-log-row';
    row.innerHTML =
      '<span class="' +
      logTagClass(iid) +
      '">' +
      iid +
      '</span><span class="ts">' +
      (tick.published_at || '') +
      '</span> ' +
      fmtPrice(tick.price, sym) +
      (tick.momentum_1m_avg != null ? ' mom1m=' + fmtMom1mPct(tick.momentum_1m_avg) : '') +
      (tick.lag_kalshi_to_local_ms != null ? ' lag=' + tick.lag_kalshi_to_local_ms + 'ms' : '');
    log.insertBefore(row, log.firstChild);
    while (log.childNodes.length > MAX_LOG_ROWS) {
      log.removeChild(log.lastChild);
    }
  }

  function onCfTick(tick) {
    if (!tick || tick.type !== 'cfbenchmarks_tick') return;
    const iid = (tick.index_id || '').toUpperCase();
    if (INDICES.indexOf(iid) < 0) return;
    const sym = INDEX_TO_COIN[iid];

    if (tick.price != null) {
      state.cfPrice[iid] = Number(tick.price);
      const p = panel(iid);
      if (p) {
        const priceEl = p.querySelector('[data-field="price"]');
        const subEl = p.querySelector('[data-field="sub"]');
        if (priceEl) priceEl.textContent = fmtPrice(state.cfPrice[iid], sym);
        if (subEl) {
          subEl.textContent =
            'seq ' + (tick.seq != null ? tick.seq : '—') + ' · ' + (tick.published_at || '');
        }
      }
    }
    const cfbAvg = cfbOneMinAvgFromTick(tick);
    if (cfbAvg != null) state.cfOneMinAvg[iid] = cfbAvg;
    renderMom1m(iid, tick);
    prependLog(tick);
    updateComparisons(iid);
    state.tickCount += 1;
    state.ticksInWindow += 1;
  }

  function tickRateLoop() {
    const now = Date.now();
    const elapsed = (now - state.tickWindowStart) / 1000;
    if (elapsed >= 1) {
      const rate = state.ticksInWindow / elapsed;
      el('cfb-tick-rate').textContent =
        rate.toFixed(1) + ' ticks/s · total ' + state.tickCount + ' (4 indices)';
      state.tickWindowStart = now;
      state.ticksInWindow = 0;
    }
    requestAnimationFrame(tickRateLoop);
  }

  function connectCfBenchmarks() {
    const url = wsUrl('/ws/cfbenchmarks_feed?index_id=' + encodeURIComponent(INDEX_IDS_CSV));
    const ws = new WebSocket(url);
    ws.onopen = function () {
      setStatus(el('cfb-ws-status'), 'Kalshi WS · 4 indices', 'ok');
    };
    ws.onclose = function () {
      setStatus(el('cfb-ws-status'), 'Kalshi WS disconnected — retrying', 'warn');
      setTimeout(connectCfBenchmarks, 2000);
    };
    ws.onerror = function () {
      setStatus(el('cfb-ws-status'), 'Kalshi WS error', 'err');
    };
    ws.onmessage = function (ev) {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === 'cfbenchmarks_tick') {
          onCfTick(data);
        } else if (data.type === 'cfbenchmarks_recent' && Array.isArray(data.ticks)) {
          data.ticks
            .slice()
            .reverse()
            .forEach(function (t) {
              onCfTick(t);
            });
        } else if (data.type === 'cfbenchmarks_meta' && data.meta && data.meta.connected) {
          setStatus(el('cfb-ws-status'), 'watchdog connected', 'ok');
        }
      } catch (_) {
        /* ignore */
      }
    };
    setInterval(function () {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 25000);
  }

  function connectCoinbaseSpot() {
    const url = wsUrl('/ws/live_market?symbol=BTC&market=15m');
    const ws = new WebSocket(url);
    ws.onopen = function () {
      setStatus(el('cfb-coinbase-status'), 'coinbase WS connected', 'ok');
    };
    ws.onclose = function () {
      setStatus(el('cfb-coinbase-status'), 'coinbase WS disconnected', 'warn');
      setTimeout(connectCoinbaseSpot, 3000);
    };
    ws.onmessage = function (ev) {
      try {
        const data = JSON.parse(ev.data);
        applyLiveSymbolSpot(data);
      } catch (_) {
        /* ignore */
      }
    };
  }

  fetch('/api/live_symbol_spot_bootstrap', { cache: 'no-store' })
    .then(function (r) {
      return r.json();
    })
    .then(applyLiveSymbolSpot)
    .catch(function () {
      /* ignore */
    });

  fetch('/api/experiment/cfbenchmarks/status?index_id=' + encodeURIComponent(INDEX_IDS_CSV))
    .then(function (r) {
      return r.json();
    })
    .then(function (st) {
      if (st.by_index) {
        INDICES.forEach(function (iid) {
          const block = st.by_index[iid];
          if (block && block.latest) onCfTick(block.latest);
        });
        const anyConnected = INDICES.some(function (iid) {
          return st.by_index[iid] && st.by_index[iid].meta && st.by_index[iid].meta.connected;
        });
        setStatus(
          el('cfb-ws-status'),
          anyConnected
            ? 'watchdog connected (HTTP)'
            : 'start: supervisorctl restart cfbenchmarks_price_watchdog',
          anyConnected ? 'ok' : 'warn'
        );
      }
    })
    .catch(function () {
      /* ignore */
    });

  connectCfBenchmarks();
  connectCoinbaseSpot();
  requestAnimationFrame(tickRateLoop);
})();
