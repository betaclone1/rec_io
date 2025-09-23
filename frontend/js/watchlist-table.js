// === WATCHLIST TABLE MODULE ===
// This module handles the watchlist table - shows exactly what's in the watchlist DB table

// === WATCHLIST DATA FETCHING ===

// Fetch watchlist data from the PostgreSQL endpoint
async function fetchWatchlistData() {
  try {
    const currentMonitorName = window.currentMonitorName;
    const url = window.location.origin + `/api/watchlist/${currentMonitorName}`;
    const response = await fetch(url);
    
    if (!response.ok) {
      console.warn(`[WATCHLIST] Server error ${response.status} for monitor ${currentMonitorName}`);
      return null;
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('[WATCHLIST] Error fetching watchlist data:', error);
    return null;
  }
}

// === WATCHLIST TABLE INITIALIZATION ===

function initializeWatchlistTable() {
  console.log('[WATCHLIST] Initializing watchlist table...');
  // Initial load
  updateWatchlistTable();
  
  // Set up periodic updates (every 1 second)
  setInterval(updateWatchlistTable, 1000);
  console.log('[WATCHLIST] Watchlist table initialized and periodic updates set up');
}

// === WATCHLIST TABLE UPDATES ===

async function updateWatchlistTable() {
  try {
    const data = await fetchWatchlistData();
    if (!data || !data.strikes) {
      console.warn('[WATCHLIST] No watchlist data available');
      return;
    }
    
    const watchlistTableBody = document.querySelector('#watchlist-table tbody');
    if (!watchlistTableBody) return;
    
    // COMPLETELY REBUILD THE TABLE FROM SCRATCH
    watchlistTableBody.innerHTML = '';
    
    // Sort strikes by probability (highest to lowest)
    const sortedStrikes = data.strikes.sort((a, b) => b.probability - a.probability);
    
    // Limit to only the top 5 strikes
    const top5Strikes = sortedStrikes.slice(0, 5);
    
    // Show only the top 5 strikes
    top5Strikes.forEach((strikeData) => {
      const row = document.createElement('tr');
      const strike = strikeData.strike;
      
      // Strike cell
      const strikeTd = document.createElement('td');
      strikeTd.textContent = '$' + strike.toLocaleString();
      strikeTd.classList.add('center');
      row.appendChild(strikeTd);
      
      // Buffer cell
      const bufferTd = document.createElement('td');
      bufferTd.textContent = strikeData.buffer.toLocaleString(undefined, {maximumFractionDigits: 0});
      bufferTd.classList.add('center');
      row.appendChild(bufferTd);
      
      // B/M cell
      const bmTd = document.createElement('td');
      bmTd.textContent = strikeData.buffer_pct.toFixed(2);
      bmTd.classList.add('center');
      row.appendChild(bmTd);
      
      // Probability cell
      const probTd = document.createElement('td');
      const prob = strikeData.probability;
      probTd.textContent = prob.toFixed(1);
      probTd.classList.add('center');
      row.appendChild(probTd);
      
      // Side cell
      const sideTd = document.createElement('td');
      const activeSide = strikeData.active_side;
      sideTd.textContent = activeSide ? activeSide.toUpperCase() : '—';
      sideTd.classList.add('center');
      row.appendChild(sideTd);
      
      // Buy button cell
      const buyTd = document.createElement('td');
      buyTd.setAttribute('data-ticker', strikeData.ticker || '');
      buyTd.classList.add('center');
      const buySpan = document.createElement('span');
      buyTd.appendChild(buySpan);
      row.appendChild(buyTd);
      
      // Risk color coding
      row.classList.remove('ultra-safe', 'safe', 'caution', 'high-risk', 'danger-stop');
      let riskClass = '';
      if (prob >= 98) riskClass = 'ultra-safe';
      else if (prob >= 95) riskClass = 'safe';
      else if (prob >= 80) riskClass = 'caution';
      else riskClass = 'high-risk';
      row.classList.add(riskClass);
      
      // Update buy button - use _dollars values when available
      const yesAsk = strikeData.yes_ask_dollars ? Math.round(parseFloat(strikeData.yes_ask_dollars) * 100) : strikeData.yes_ask;
      const noAsk = strikeData.no_ask_dollars ? Math.round(parseFloat(strikeData.no_ask_dollars) * 100) : strikeData.no_ask;
      const yesDiff = strikeData.yes_diff;
      const noDiff = strikeData.no_diff;
      const volume = strikeData.volume;
      const ticker = strikeData.ticker;
      
      let activeAsk = null;
      let activeDiff = null;
      let activeEnabled = false;
      
      if (activeSide === 'yes') {
        activeAsk = yesAsk;
        activeDiff = yesDiff;
        // Get min_volume from current monitor settings (default to 1000 if not available)
        const minVolume = window.currentMonitorMinVolume || 1000;
        activeEnabled = yesAsk <= 98 && parseInt(volume) >= minVolume;
      } else if (activeSide === 'no') {
        activeAsk = noAsk;
        activeDiff = noDiff;
        // Get min_volume from current monitor settings (default to 1000 if not available)
        const minVolume = window.currentMonitorMinVolume || 1000;
        activeEnabled = noAsk <= 98 && parseInt(volume) >= minVolume;
      }
      
      updateWatchlistBuyButton(buySpan, strike, activeSide, activeAsk, activeEnabled, ticker, activeDiff);
      
      // Update position indicator
      updateWatchlistPositionIndicator(strikeTd, strike);
      
      // Add row to table
      watchlistTableBody.appendChild(row);
    });
    
  } catch (error) {
    console.error('Error updating watchlist table:', error);
  }
}

// === WATCHLIST BUY BUTTON FUNCTION ===

function updateWatchlistBuyButton(spanEl, strike, side, askPrice, isActive, ticker = null, diffValue = null) {
  // Get current diff mode state
  const diffMode = window.diffMode || false;
  
  // Determine display value based on diff mode
  let displayValue = '—';
  if (diffMode && diffValue !== null && diffValue !== undefined) {
    // Show diff value in diff mode with proper formatting
    displayValue = diffValue > 0 ? `+${Math.round(diffValue)}` : `${Math.round(diffValue)}`;
  } else if (askPrice && askPrice !== '—' && askPrice !== 0) {
    // Show price value in price mode
    displayValue = askPrice;
  }
  
  spanEl.textContent = displayValue;
  spanEl.className = isActive ? 'price-box' : 'price-box disabled';
  spanEl.style.cursor = isActive ? 'pointer' : 'default';
  
  // Set data attributes
  if (spanEl.parentElement && ticker) {
    spanEl.parentElement.setAttribute('data-ticker', ticker);
  }
  if (ticker) {
    spanEl.setAttribute('data-ticker', ticker);
  }
  spanEl.setAttribute('data-strike', strike);
  spanEl.setAttribute('data-side', side);
  if (askPrice && askPrice !== '—' && askPrice !== 0) {
    spanEl.setAttribute('data-ask-price', askPrice);
  } else {
    spanEl.removeAttribute('data-ask-price');
  }

  if (isActive) {
    spanEl.onclick = debounce(async function(event) {
      try {
        const tradeData = await prepareTradeData(spanEl);
        
        if (!tradeData) {
          console.error('Missing trade data for watchlist button');
          return;
        }
        
        const response = await fetch(window.location.origin + '/api/trigger_open_trade', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            strike: tradeData.strike,
            side: tradeData.side,
            ticker: tradeData.ticker,
            buy_price: tradeData.buy_price,
            prob: tradeData.prob,
            symbol_open: tradeData.symbol_open,
            momentum: tradeData.momentum,
            contract: tradeData.contract,
            symbol: tradeData.symbol,
            position: tradeData.position,
            trade_strategy: tradeData.trade_strategy
          })
        });
        
        if (response.ok) {
          const result = await response.json();
          
          // Refresh panels to show new trade
          if (typeof fetchAndRenderTrades === 'function') {
            fetchAndRenderTrades();
          }
          if (typeof fetchAndRenderRecentTrades === 'function') {
            fetchAndRenderRecentTrades();
          }
        } else {
          console.error('Watchlist trade initiation failed:', response.status);
        }
      } catch (error) {
        console.error('Error initiating watchlist trade:', error);
      }
    }, 300);
  } else {
    spanEl.onclick = null;
  }
}

// === WATCHLIST POSITION INDICATOR ===

async function updateWatchlistPositionIndicator(strikeCell, strike) {
  try {
    const tradesRes = await fetch(window.location.origin + '/api/active_trades', { cache: 'no-store' });
    if (!tradesRes.ok) return;
    
    const data = await tradesRes.json();
    const activeTrades = data.active_trades || [];
    
    const hasPosition = activeTrades.some(trade => {
      const tradeStrike = parseFloat(trade.strike.replace(/[^\d.-]/g, ''));
      return tradeStrike === strike;
    });
    
    if (hasPosition) {
      strikeCell.style.backgroundColor = '#1a2a1a';
      strikeCell.style.borderLeft = '3px solid #45d34a';
    } else {
      strikeCell.style.backgroundColor = '';
      strikeCell.style.borderLeft = '';
    }
  } catch (e) {
    console.error(`[WATCHLIST POSITION INDICATOR] Error checking position for strike ${strike}:`, e);
    strikeCell.style.backgroundColor = '';
    strikeCell.style.borderLeft = '';
  }
}

// === WATCHLIST UTILITY FUNCTIONS ===

function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// === WATCHLIST INITIALIZATION ===

document.addEventListener('DOMContentLoaded', function() {
  console.log('[WATCHLIST] DOMContentLoaded event fired');
  setTimeout(() => {
    console.log('[WATCHLIST] Initializing watchlist table...');
    initializeWatchlistTable();
  }, 500);
});

// Export functions for global access
window.updateWatchlistTable = updateWatchlistTable;
window.updateWatchlistPositionIndicator = updateWatchlistPositionIndicator; 