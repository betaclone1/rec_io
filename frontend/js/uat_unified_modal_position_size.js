/**
 * Position size row for unified auto-trade modals.
 * Modal: .uat-position-size-block; trade monitor sidebar: #positionSizeSelector + legacy IDs.
 *
 * persist: 'deferred' (default) — no API until persistModalPosition() on Save.
 * persist: 'immediate' — each change POSTs (legacy; sidebar still uses its own handlers).
 */
(function (global) {
  'use strict';

  var BLUE_BG = '#007bff';
  var BLUE_BORDER = '#0056b3';

  function elsFromBlockEl(block) {
    if (!block) return null;
    return {
      block: block,
      input: block.querySelector('.uat-pos-input'),
      percentBtn: block.querySelector('.uat-pos-toggle-percent'),
      contractsBtn: block.querySelector('.uat-pos-toggle-contracts'),
      multBtns: block.querySelectorAll('.uat-pos-mult-btn'),
      display: block.querySelector('.uat-pos-display')
    };
  }

  function elsFromTmSidebar() {
    var wrap = document.getElementById('positionSizeSelector');
    return {
      block: null,
      input: document.getElementById('position-size'),
      percentBtn: document.getElementById('toggle-percent'),
      contractsBtn: document.getElementById('toggle-contracts'),
      multBtns: wrap ? wrap.querySelectorAll('.multiplier-btn') : [],
      display: document.getElementById('position-display')
    };
  }

  function isLightThemeBlock(block) {
    return block && block.classList && block.classList.contains('uat-pos-theme-light');
  }

  function inactiveToggleBorder(els) {
    return isLightThemeBlock(els && els.block) ? '#ccc' : '#9ca3af';
  }

  function isPercentMode(els) {
    if (!els || !els.percentBtn) return false;
    var bg = els.percentBtn.style.backgroundColor;
    return bg === 'rgb(0, 123, 255)' || bg === BLUE_BG;
  }

  function readFromEls(els) {
    if (!els || !els.input) return null;
    var positionSize = parseInt(els.input.value, 10) || 1;
    if (isPercentMode(els)) {
      if (positionSize < 1) positionSize = 1;
      if (positionSize > 100) positionSize = 100;
    } else {
      if (positionSize < 1) positionSize = 1;
    }
    var positionType = isPercentMode(els) ? 'percent' : 'contracts';
    var multiplier = 1;
    els.multBtns.forEach(function (b) {
      if (b.classList.contains('active')) {
        multiplier = parseFloat(b.getAttribute('data-multiplier'));
      }
    });
    if (Number.isNaN(multiplier)) multiplier = 1;
    return { position_size: positionSize, position_type: positionType, multiplier: multiplier };
  }

  function sendUpdate(monitorId, els) {
    if (monitorId == null || monitorId === '') return Promise.resolve();
    var payload = readFromEls(els);
    if (!payload) return Promise.resolve();
    return fetch('/api/update_monitor_position', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        monitor_id: monitorId,
        position_size: payload.position_size,
        position_type: payload.position_type,
        multiplier: payload.multiplier
      })
    })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .catch(function (e) {
        console.error('uat_unified_modal_position_size sendUpdate', e);
      });
  }

  function setToggleVisual(percentBtn, contractsBtn, mode, els) {
    if (!percentBtn || !contractsBtn) return;
    var dim = inactiveToggleBorder(els);
    if (mode === 'percent') {
      percentBtn.style.backgroundColor = BLUE_BG;
      percentBtn.style.borderColor = BLUE_BORDER;
      contractsBtn.style.backgroundColor = 'transparent';
      contractsBtn.style.borderColor = dim;
    } else {
      contractsBtn.style.backgroundColor = BLUE_BG;
      contractsBtn.style.borderColor = BLUE_BORDER;
      percentBtn.style.backgroundColor = 'transparent';
      percentBtn.style.borderColor = dim;
    }
  }

  function setPositionType(els, type, options) {
    options = options || {};
    if (!els) return;
    if (type === 'percent') {
      setToggleVisual(els.percentBtn, els.contractsBtn, 'percent', els);
      if (els.input) {
        els.input.min = 1;
        els.input.max = 100;
        if (options.applyPercentDefault) els.input.value = 10;
      }
    } else {
      setToggleVisual(els.percentBtn, els.contractsBtn, 'contracts', els);
      if (els.input) {
        els.input.min = 1;
        els.input.max = '';
      }
    }
  }

  function applyMonitorToEls(els, monitor) {
    if (!els || !monitor) return;
    if (els.input && monitor.position_size !== undefined) els.input.value = monitor.position_size;
    if (monitor.position_type === 'percent') {
      setPositionType(els, 'percent', { applyPercentDefault: false });
    } else {
      setPositionType(els, 'contracts', {});
    }
    if (els.multBtns && els.multBtns.length && monitor.multiplier !== undefined) {
      var target = parseFloat(monitor.multiplier);
      els.multBtns.forEach(function (btn) {
        btn.classList.remove('active');
        if (!Number.isNaN(target) && parseFloat(btn.getAttribute('data-multiplier')) === target) {
          btn.classList.add('active');
        }
      });
    }
  }

  function mirrorEls(fromEls, toEls) {
    if (!fromEls || !toEls || !fromEls.input || !toEls.input) return;
    toEls.input.value = fromEls.input.value;
    toEls.input.min = fromEls.input.min;
    toEls.input.max = fromEls.input.max;
    if (fromEls.percentBtn && toEls.percentBtn) {
      toEls.percentBtn.style.backgroundColor = fromEls.percentBtn.style.backgroundColor;
      toEls.percentBtn.style.borderColor = fromEls.percentBtn.style.borderColor;
    }
    if (fromEls.contractsBtn && toEls.contractsBtn) {
      toEls.contractsBtn.style.backgroundColor = fromEls.contractsBtn.style.backgroundColor;
      toEls.contractsBtn.style.borderColor = fromEls.contractsBtn.style.borderColor;
    }
    var mult = readFromEls(fromEls);
    if (mult && toEls.multBtns && toEls.multBtns.length) {
      toEls.multBtns.forEach(function (b) {
        b.classList.remove('active');
        if (parseFloat(b.getAttribute('data-multiplier')) === mult.multiplier) b.classList.add('active');
      });
    }
  }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      clearTimeout(t);
      var args = arguments;
      t = setTimeout(function () {
        fn.apply(null, args);
      }, ms);
    };
  }

  function getElsFromModal(modalEl) {
    if (!modalEl || !modalEl.querySelector) return null;
    return elsFromBlockEl(modalEl.querySelector('.uat-position-size-block'));
  }

  function captureOpenSnapshot(modalEl) {
    if (!modalEl) return;
    var els = getElsFromModal(modalEl);
    var r = readFromEls(els);
    if (!r) {
      modalEl._uatPositionOpenSnapshot = null;
      return;
    }
    modalEl._uatPositionOpenSnapshot = {
      position_size: r.position_size,
      position_type: r.position_type,
      multiplier: r.multiplier,
      total_position: modalEl._uatLastTotalPosition
    };
  }

  function restoreOpenSnapshot(modalEl) {
    if (!modalEl || !modalEl._uatPositionOpenSnapshot) return;
    var snap = modalEl._uatPositionOpenSnapshot;
    var els = getElsFromModal(modalEl);
    applyMonitorToEls(els, snap);
    if (snap.total_position != null) {
      refreshAllPositionDisplays(snap.total_position);
    }
  }

  function persistModalPosition(modalEl, monitorId, opts) {
    opts = opts || {};
    var mirrorSidebar = !!opts.mirrorSidebar;
    if (monitorId == null || monitorId === '') return Promise.resolve();
    var elsModal = getElsFromModal(modalEl);
    if (!elsModal) return Promise.resolve();
    if (mirrorSidebar) {
      var side = elsFromTmSidebar();
      mirrorEls(elsModal, side);
      var r = readFromEls(side);
      if (r && global.currentMultiplier !== undefined) global.currentMultiplier = r.multiplier;
      return sendUpdate(monitorId, side);
    }
    return sendUpdate(monitorId, elsModal);
  }

  function refreshAllPositionDisplays(totalPosition) {
    if (totalPosition === undefined || totalPosition === null) return;
    var n = typeof totalPosition === 'number' ? totalPosition : parseInt(totalPosition, 10);
    if (Number.isNaN(n)) return;
    var text = n + ' ' + (n === 1 ? 'contract' : 'contracts');
    document.querySelectorAll('.uat-pos-display').forEach(function (el) {
      el.textContent = text;
    });
    var legacy = document.getElementById('position-display');
    if (legacy) legacy.textContent = text;
    var u1 = document.getElementById('unifiedAutoTradeModal');
    if (u1) u1._uatLastTotalPosition = n;
    var u2 = document.getElementById('mobileUnifiedAutoTradeModal');
    if (u2) u2._uatLastTotalPosition = n;
  }

  function bindModal(modalEl, config) {
    config = config || {};
    var getMonitorId = config.getMonitorId;
    var mirrorSidebar = !!config.mirrorSidebar;
    var persist = config.persist === 'immediate' ? 'immediate' : 'deferred';
    if (!modalEl || typeof getMonitorId !== 'function') return;
    if (modalEl._uatPosBound) return;
    modalEl._uatPosBound = true;

    var block = modalEl.querySelector('.uat-position-size-block');
    if (!block) return;

    var elsModal = elsFromBlockEl(block);
    var ignoreWs = function () {
      return !!global.ignoreWsUpdates;
    };

    var sendFromModal = debounce(function () {
      if (persist !== 'immediate') return;
      if (ignoreWs()) return;
      var mid = getMonitorId();
      if (mirrorSidebar) {
        var side = elsFromTmSidebar();
        mirrorEls(elsModal, side);
        var r = readFromEls(side);
        if (r && global.currentMultiplier !== undefined) global.currentMultiplier = r.multiplier;
        sendUpdate(mid, side);
      } else {
        sendUpdate(mid, elsModal);
      }
    }, 150);

    if (elsModal.percentBtn) {
      elsModal.percentBtn.addEventListener('click', function () {
        if (ignoreWs()) return;
        setPositionType(elsModal, 'percent', { applyPercentDefault: true });
        sendFromModal();
      });
    }
    if (elsModal.contractsBtn) {
      elsModal.contractsBtn.addEventListener('click', function () {
        if (ignoreWs()) return;
        setPositionType(elsModal, 'contracts', {});
        sendFromModal();
      });
    }
    if (elsModal.input) {
      elsModal.input.addEventListener('input', function () {
        if (ignoreWs()) return;
        var v = parseInt(elsModal.input.value, 10) || 1;
        if (isPercentMode(elsModal)) {
          if (v < 1) v = 1;
          if (v > 100) v = 100;
        } else {
          if (v < 1) v = 1;
        }
        elsModal.input.value = v;
        sendFromModal();
      });
    }
    elsModal.multBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (ignoreWs()) return;
        elsModal.multBtns.forEach(function (b) {
          b.classList.remove('active');
        });
        btn.classList.add('active');
        if (persist === 'immediate') {
          var m = parseFloat(btn.getAttribute('data-multiplier'));
          if (!Number.isNaN(m) && global.currentMultiplier !== undefined) global.currentMultiplier = m;
        }
        sendFromModal();
      });
    });

    modalEl._uatSyncModalFromSidebar = function () {
      if (!mirrorSidebar) return;
      var side = elsFromTmSidebar();
      mirrorEls(side, elsModal);
    };
  }

  global.UatUnifiedModalPositionSize = {
    bindModal: bindModal,
    getElsFromModal: getElsFromModal,
    elsFromTmSidebar: elsFromTmSidebar,
    applyMonitorToEls: applyMonitorToEls,
    mirrorEls: mirrorEls,
    sendUpdate: sendUpdate,
    readFromEls: readFromEls,
    setPositionType: setPositionType,
    refreshAllPositionDisplays: refreshAllPositionDisplays,
    captureOpenSnapshot: captureOpenSnapshot,
    restoreOpenSnapshot: restoreOpenSnapshot,
    persistModalPosition: persistModalPosition
  };
})(typeof window !== 'undefined' ? window : this);
