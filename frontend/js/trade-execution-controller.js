
// === CENTRALIZED TRADE EXECUTION CONTROLLER ===
// This file centralizes ALL trade execution to prevent multiple functions
// and add proper safety controls for live money trading

// Global configuration (Kalshi is always prod; internal paper uses trading_mode + paper_trade rows.)
window.TRADE_CONFIG = {
  MAX_POSITION_SIZE: 1000,
  ENABLE_SOUNDS: function() { return window.isSoundEnabled ? window.isSoundEnabled() : true; },
  ENABLE_POPUPS: true
};

// Trade execution state
window.TRADE_STATE = {
  isExecuting: false,
  lastTradeId: null,
  pendingTrades: new Set(),
  executedTrades: new Set()
};

function _positiveNumberOrNull(v) {
  if (v === '' || v === null || v === undefined) return null;
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

function _serverErrorMessage(result) {
  if (!result || typeof result !== 'object') return null;
  if (typeof result.error === 'string' && result.error.trim()) return result.error.trim();
  const d = result.detail;
  if (typeof d === 'string' && d.trim()) return d.trim();
  if (Array.isArray(d) && d.length) {
    return d
      .map(function (x) {
        if (!x) return '';
        if (typeof x === 'string') return x;
        if (typeof x.msg === 'string') return x.msg;
        return JSON.stringify(x);
      })
      .filter(Boolean)
      .join('; ');
  }
  return null;
}

/** Optional hook (e.g. trade-monitor-new ``tmNewApiFetch``) for same auth/CORS as the rest of the tab. */
function _recTradesTransportFetch(url, init) {
  if (typeof window.__recTradesFetch === 'function') {
    return window.__recTradesFetch(url, init);
  }
  return fetch(url, init);
}

// === CENTRALIZED CLOSE TRADE FUNCTION ===
// This is the ONLY function that should close trades
window.closeTrade = async function(tradeId, sellPrice, event) {
  
  // Audio is already played in trade_monitor.html when button was clicked
  
  // Prevent multiple simultaneous executions
  if (window.TRADE_STATE.isExecuting) {
    return { success: false, error: 'Trade already executing' };
  }

  if (!tradeId) {
    return { success: false, error: 'Invalid close trade parameters: missing trade id' };
  }

  // Generate unique ticket ID
  const ticket_id = 'TICKET-' + Math.random().toString(36).substr(2, 9) + '-' + Date.now();
  
  // Add to pending trades
  window.TRADE_STATE.pendingTrades.add(ticket_id);
  window.TRADE_STATE.isExecuting = true;

  try {
    // Fetch open trades only (same rows the UI lists for Close)
    const trades = await recFetchTradesMerged(window.location.origin + '/trades?status=open', {
      cache: 'no-store',
      customFetch: _recTradesTransportFetch,
    });
    
    // Find the specific trade by ID
    const trade = trades.find(t => t.id == tradeId);
    if (!trade) {
      throw new Error(`Trade with ID ${tradeId} not found among open trades (still pending or already closed?)`);
    }

    // === Get the ACTUAL position count from the trade data ===
    let count = trade.position;
    
    // Validate that we have a valid position count
    if (count === null || count === undefined || isNaN(count) || count <= 0) {
      throw new Error(`Invalid position count: ${count}. Trade ID: ${tradeId}`);
    }

    // Invert side
    let invertedSide = null;
    if (trade.side === 'Y' || trade.side === 'YES') invertedSide = 'N';
    else if (trade.side === 'N' || trade.side === 'NO') invertedSide = 'Y';
    else invertedSide = trade.side;

    // Spot for symbol_close (prefer symbol strip price, same as open flow)
    let symSpot = null;
    if (typeof getCurrentSymbolTickerPrice === 'function') {
      symSpot = _positiveNumberOrNull(getCurrentSymbolTickerPrice());
    }
    if (symSpot === null && typeof getCurrentBTCTickerPrice === 'function') {
      symSpot = _positiveNumberOrNull(getCurrentBTCTickerPrice());
    }
    const symbolClose = symSpot;

    let finalSellPrice = _positiveNumberOrNull(sellPrice);

    const isPaper =
      trade.paper_trade === true ||
      trade.paper_trade === 1 ||
      (typeof trade.paper_trade === 'string' && trade.paper_trade.toLowerCase() === 'true');

    // For paper trades, fetch current_close_price from active trades and calculate sell_price = 1 - current_close_price
    if (isPaper) {
      try {
        // Get current monitor name for monitor-specific active trades
        const currentMonitorName = window.currentMonitorName;
        if (currentMonitorName) {
          const activeTradesUrl = window.location.origin + `/api/active_trades/${currentMonitorName}`;
          const activeTradesRes = await _recTradesTransportFetch(activeTradesUrl, { cache: 'no-store' });
          if (activeTradesRes.ok) {
            const activeTradesData = await activeTradesRes.json();
            if (activeTradesData.active_trades && Array.isArray(activeTradesData.active_trades)) {
              const activeTrade = activeTradesData.active_trades.find(t => t.trade_id == tradeId);
              if (activeTrade && activeTrade.current_close_price !== null && activeTrade.current_close_price !== undefined) {
                // sell_price = 1 - current_close_price (current_close_price is the opposite side's ask)
                const currentClosePrice = parseFloat(activeTrade.current_close_price);
                finalSellPrice = 1 - currentClosePrice;
                console.log(`[PAPER TRADE] current_close_price: ${currentClosePrice}, calculated sell_price: ${finalSellPrice}`);
              }
            }
          }
        }
      } catch (error) {
        console.warn(`[PAPER TRADE] Could not fetch current_close_price from active trades: ${error}, using provided sellPrice`);
      }
    }

    if (isPaper) {
      if (finalSellPrice === null || !Number.isFinite(finalSellPrice) || finalSellPrice <= 0 || finalSellPrice >= 1) {
        throw new Error('Paper close needs a valid contract sell price (spot or active-trades quote)');
      }
    } else {
      // Live IOC/market close: trade_manager + executor use aggressive limit; placeholder if spot strip is empty
      if (finalSellPrice === null) {
        finalSellPrice = 0.99;
      }
    }

    // Compose payload to match open ticket, plus intent: 'close' (count_fp for full-chain consistency)
    const payload = {
      id:               tradeId,  // Include the specific trade_id
      ticket_id:        ticket_id,
      intent:           'close',
      ticker:           trade.ticker,
      side:             invertedSide,
      count:            count,
      count_fp:         Number(count).toFixed(2),
      action:           'close',
      type:             'market',
      time_in_force:    'IOC',
      buy_price:        finalSellPrice,  // Use finalSellPrice (current_close_price for paper trades)
      symbol_close:     symbolClose,
      close_method:     'manual'
    };

    // Execute the actual close trade
    const response = await _recTradesTransportFetch(window.location.origin + '/trades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const rawText = await response.text();
    let result;
    try {
      result = rawText ? JSON.parse(rawText) : {};
    } catch (parseErr) {
      throw new Error('Close failed: server returned non-JSON (HTTP ' + response.status + ')');
    }

    const errMsg = _serverErrorMessage(result);
    if (!response.ok) {
      throw new Error(errMsg || 'Close trade execution failed: HTTP ' + response.status);
    }
    if (errMsg) {
      throw new Error(errMsg);
    }
    
    // Add to executed trades
    window.TRADE_STATE.executedTrades.add(ticket_id);
    window.TRADE_STATE.lastTradeId = ticket_id;

    // Audio and popup already handled in trade_monitor.html when button was clicked

    return { 
      success: true, 
      ticket_id: ticket_id, 
      result: result
    };

  } catch (error) {
    return { 
      success: false, 
      error: error.message,
      ticket_id: ticket_id
    };
  } finally {
    // Remove from pending trades
    window.TRADE_STATE.pendingTrades.delete(ticket_id);
    window.TRADE_STATE.isExecuting = false;
  }
};

// === CENTRALIZED TRADE DATA PREPARATION ===
// This function extracts all necessary trade data from a button element
// and prepares it for sending to the trade_manager service

window.prepareTradeData = async function(target) {


  // Extract trade data from the button element - use current symbol if not specified
  const symbol = target.getAttribute('data-symbol') || (typeof getCurrentSymbol === 'function' ? getCurrentSymbol() : 'BTC');
  
  if (target?.disabled) {
    return null;
  }

  // Get the actual ask price from data attribute (not the display text)
  const askPrice = target?.dataset?.askPrice;
  
  let buy_price = 0;
  if (askPrice) {
    // Use ask price directly as dollars (no conversion needed)
    buy_price = parseFloat(askPrice);
  }

  // Get total_position from monitor-specific configuration (like auto_entry_supervisor) - NO FALLBACKS
  let position = null;
  try {
    const currentMonitorId = window.currentMonitorId;
    if (!currentMonitorId) {
      console.error('No current monitor ID available - cannot create trade');
      return null;
    }
    
    console.log('DEBUG: Fetching monitor data for ID:', currentMonitorId);
    const response = await fetch(window.location.origin + `/api/monitor/${currentMonitorId}`);
    console.log('DEBUG: Monitor API response status:', response.status);
    if (response.ok) {
      const data = await response.json();
      console.log('DEBUG: Monitor API response data:', data);
      if (data.status === 'ok' && data.monitor) {
        position = data.monitor.total_position;
        if (!position) {
          console.error('No total_position found in monitor configuration');
          return null;
        }
        console.log(`Position size loaded from monitor ${currentMonitorId}: ${position}`);
      } else {
        console.error('Failed to get monitor data:', data.message);
        return null;
      }
    } else {
      console.error('Failed to get monitor data from API');
      return null;
    }
  } catch (error) {
    console.error('Error fetching monitor position size:', error);
    return null;
  }

  // Get strike and side from button context
  let strike = null;
  let side = null;
  let row = target.closest('tr');
  
  if (row) {
    const strikeCell = row.querySelector('td');
    if (strikeCell) {
      strike = parseFloat(strikeCell.textContent.replace(/\$|,/g, ''));
    }
    
    // Side is ONLY the active_side from the watchlist JSON
    if (target.dataset.side) {
      side = target.dataset.side;
  
    } else {
      console.error('No data-side attribute found - cannot determine trade side');
      console.error('btn.dataset.side value:', target.dataset.side);
      console.error('btn element:', target);
      return null;
    }
  }

  // Get ticker
  let kalshiTicker = target.dataset.ticker || null;
  if (!kalshiTicker && target.parentElement && target.parentElement.dataset.ticker) {
    kalshiTicker = target.parentElement.dataset.ticker;
  }

  // Contract: prefer strike-panel title; if parse failed ('SYMBOL Unknown') but we have a Kalshi ticker, omit so backend derives from ticker.
  let contract = typeof getTruncatedMarketTitle === 'function' ? getTruncatedMarketTitle() : 'BTC Market';
  if (kalshiTicker && contract && /(?:^|\s)Unknown\s*$/i.test(String(contract).trim())) {
    contract = '';
  }

  // Get diff value from data attribute
  let diff = null;
  if (target.dataset.diff) {
    diff = parseFloat(target.dataset.diff);
  }

  // Get other data - use current symbol instead of hardcoded BTC
  const symbol_open = typeof getCurrentSymbolTickerPrice === 'function' ? getCurrentSymbolTickerPrice() : null;
  
  // Get momentum from API instead of DOM element - use current symbol
  let momentum = null;
  try {
    const currentSymbol = typeof getCurrentSymbol === 'function' ? getCurrentSymbol() : 'BTC';
    const momentumResponse = await fetch(window.location.origin + `/api/momentum?symbol=${currentSymbol}`);
    if (momentumResponse.ok) {
      const momentumData = await momentumResponse.json();
      momentum = momentumData.momentum_score;
    }
  } catch (error) {
    console.error('Failed to fetch momentum from API:', error);
  }

  // Get the PROB value from the strike table for this specific strike
  let prob = null;
  if (strike) {
    const strikeFormatted = '$' + Number(strike).toLocaleString();
    
    const strikeTableRows = document.querySelectorAll('#strike-table tbody tr');
    
    for (const row of strikeTableRows) {
      const firstTd = row.querySelector('td');
      if (!firstTd) continue;
      const firstTdText = firstTd.textContent.trim();
      
      if (firstTdText === strikeFormatted) {
        const tds = row.querySelectorAll('td');
        
        if (tds.length > 3) {
          const probText = tds[3].textContent.trim(); // FIXED: Use the Prob column
          
          if (probText && probText !== '—') {
            prob = probText; // Keep as string (e.g., "97.6")
          }
        }
        break;
      }
    }
  }

  if (!prob) {
    return null;
  }

  // Get trade strategy and paper_trade from monitor configuration (like auto_entry_supervisor) - NO FALLBACKS
  let tradeStrategy = null;
  let paperTrade = false;
  try {
    const currentMonitorId = window.currentMonitorId;
    if (!currentMonitorId) {
      console.error('No current monitor ID available - cannot create trade');
      return null;
    }
    
    const response = await fetch(window.location.origin + `/api/monitor/${currentMonitorId}`);
    if (response.ok) {
      const data = await response.json();
      if (data.status === 'ok' && data.monitor) {
        tradeStrategy = data.monitor.strategy;
        paperTrade = data.monitor.paper_trade || false;
        if (!tradeStrategy) {
          console.error('No strategy found in monitor configuration');
          return null;
        }
        console.log(`Trade strategy loaded from monitor ${currentMonitorId}: ${tradeStrategy}, paper_trade: ${paperTrade}`);
      } else {
        console.error('Failed to get monitor data:', data.message);
        return null;
      }
    } else {
      console.error('Failed to get monitor data from API');
      return null;
    }
  } catch (error) {
    console.error('Error fetching monitor strategy:', error);
    return null;
  }
  
  // Allow manual override via picker if available
  const tradeStrategyPicker = document.getElementById('trade-strategy-picker');
  if (tradeStrategyPicker && tradeStrategyPicker.value) {
    tradeStrategy = tradeStrategyPicker.value;
  }

  // Get current monitor name - NO FALLBACKS
  const currentMonitorName = window.currentMonitorName;
  console.log('DEBUG: currentMonitorName =', currentMonitorName);
  console.log('DEBUG: window.currentMonitorName =', window.currentMonitorName);
  console.log('DEBUG: window.currentMonitorId =', window.currentMonitorId);
  
  if (!currentMonitorName) {
    console.error('No current monitor name available - cannot create trade');
    return null;
  }

  const tradeData = {
    symbol: symbol,
    contract: contract,
    strike: `$${Number(strike).toLocaleString()}`,
    side: side,
    ticker: kalshiTicker,
    buy_price: buy_price,
    position: position,
    symbol_open: symbol_open,
    momentum: momentum,
    
    prob: prob,
    diff: diff,  // Add diff value
    trade_strategy: tradeStrategy,
    entry_method: "manual",
    monitor: currentMonitorName,  // Add monitor field
    paper_trade: paperTrade  // Add paper_trade from monitor config
  };

  return tradeData;
};

// === SAFETY CONTROLS ===

window.toggleDemoMode = function() {
  console.warn('toggleDemoMode is deprecated; use dashboard trading account (LIVE / PAPER).');
  return false;
};

window.getTradeState = function() {
  return {
    tradingMode: (typeof localStorage !== 'undefined' && localStorage.getItem('rec_trading_mode')) || 'live',
    isExecuting: window.TRADE_STATE.isExecuting,
    pendingTrades: Array.from(window.TRADE_STATE.pendingTrades),
    executedTrades: Array.from(window.TRADE_STATE.executedTrades),
    lastTradeId: window.TRADE_STATE.lastTradeId
  };
};

// Initialize the controller 
document.addEventListener('DOMContentLoaded', function() {
  // Controller initialized silently
}); 
