
// === LIVE DATA POLLING MODULE ===
// This module handles left column data fetching for the trade monitor
// Left column: BTC price, price changes, momentum score (all from endpoints)

// Global data holders
window.momentumData = {
  weightedScore: null,
  deltas: {}, // New: to store individual minute deltas
  momentumPercentile: null, // New: to store momentum percentile
  rollingPercentiles: [], // New: to store rolling momentum percentiles for chart
};

// === UTILITY FUNCTIONS ===

// Helper function to format numbers as $XX,XXX.XX
function formatUSD(val) {
  if (typeof val !== "number" || isNaN(val)) return "—";
  return "$" + val.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

// Helper: decorate change cell with color and triangle
function decorateChange(el, val) {
  const num = parseFloat(val);
  if (isNaN(num)) {
    el.textContent = "—";
    el.style.backgroundColor = "";
    el.style.color = "";
    return;
  }
  const triangle = num >= 0 ? " ▲" : " ▼";
  el.textContent = `${Math.abs(num).toFixed(2)}%${triangle}`;
  el.style.color = "#fff";
  el.style.backgroundColor = num >= 0 ? "#28a745" : "#dc3545";
  el.style.padding = "2px 6px";
  el.style.borderRadius = "4px";
  el.style.display = "inline-block";
}

// === CORE DATA FETCHING FUNCTIONS ===

// Fetch core data (momentum score only - BTC price now handled by strike table)
function fetchCore(symbol = 'BTC') {
  fetch(window.location.origin + `/core?symbol=${symbol}`)
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    })
    .then(data => {
      // Update weighted momentum score
      window.momentumData.weightedScore = data.weighted_momentum_score;

      // Update individual momentum deltas
      if (data.delta_1m !== undefined) window.momentumData.deltas['1m'] = data.delta_1m;
      if (data.delta_2m !== undefined) window.momentumData.deltas['2m'] = data.delta_2m;
      if (data.delta_3m !== undefined) window.momentumData.deltas['3m'] = data.delta_3m;
      if (data.delta_4m !== undefined) window.momentumData.deltas['4m'] = data.delta_4m;
      if (data.delta_15m !== undefined) window.momentumData.deltas['15m'] = data.delta_15m;
      if (data.delta_30m !== undefined) window.momentumData.deltas['30m'] = data.delta_30m;

      // Update momentum percentile (now using 5s average)
      console.log('Received momentum_5s_avg from API:', data.momentum_5s_avg);
      if (data.momentum_5s_avg !== undefined) {
        window.momentumData.momentumPercentile = data.momentum_5s_avg;
        console.log('Set window.momentumData.momentumPercentile to (5s avg):', data.momentum_5s_avg);
      }

      // Trigger momentum panel update if function exists
      if (typeof updateMomentumPanel === 'function') {
        console.log('Calling updateMomentumPanel()');
        updateMomentumPanel();
      } else {
        console.log('updateMomentumPanel function not found');
      }
    })
    .catch(error => {
      console.error('Error fetching momentum data:', error);
    });
}

// Fetch symbol price changes from backend API and update ticker panel
async function fetchSymbolPriceChanges(symbol = 'BTC') {
  try {
    const res = await fetch(window.location.origin + `/${symbol.toLowerCase()}_price_changes`);
    if (!res.ok) throw new Error(`Failed to fetch ${symbol} price changes`);
    const data = await res.json();
    
    // Update 1h, 3h, 1d change numbers in the price panel
    if ('change1h' in data) {
      const el = document.getElementById('change-1h');
      if (el) decorateChange(el, data.change1h);
    }
    if ('change3h' in data) {
      const el = document.getElementById('change-3h');
      if (el) decorateChange(el, data.change3h);
    }
    if ('change1d' in data) {
      const el = document.getElementById('change-1d');
      if (el) decorateChange(el, data.change1d);
    }
  } catch (error) {
    console.error(`Error fetching ${symbol} price changes:`, error);
  }
}

// Legacy function name for backward compatibility
async function fetchBTCPriceChanges() {
  return fetchSymbolPriceChanges('BTC');
}

// === AUTO ENTRY INDICATOR FUNCTIONS ===

// Update the auto entry indicator display
function updateAutoEntryIndicator(data) {
  const indicator = document.getElementById('autoEntryIndicator');
  if (!indicator) {
    console.error('Auto entry indicator element not found');
    return;
  }
  
  // Get the indicator elements
  const indicatorDot = indicator.querySelector('div');
  const indicatorText = indicator.querySelector('span');
  
  // Check for SPIKE ALERT state first
  if (data.spike_alert_active) {
    // SPIKE ALERT MODE - Show red indicator
    indicator.style.display = 'flex';
    indicator.style.backgroundColor = '#dc3545'; // Red background
    indicator.style.border = '1px solid #c82333';
    
    if (indicatorDot) {
      indicatorDot.style.background = '#ff6b6b'; // Red dot
    }
    
    if (indicatorText) {
      const recoveryCountdown = data.spike_alert_recovery_countdown;
      if (recoveryCountdown !== null && recoveryCountdown > 0) {
        indicatorText.textContent = `SPIKE ALERT - AUTO TRADING PAUSED (${recoveryCountdown.toFixed(1)}m)`;
      } else {
        indicatorText.textContent = 'SPIKE ALERT - AUTO TRADING PAUSED';
      }
    }
    
    
    return;
  }
  
  // Use the new scanning_active field as the primary condition
  // This provides the true system-wide scanning status
  if (data.scanning_active) {
    // Show the indicator when scanning is actually active
    indicator.style.display = 'flex';
    indicator.style.backgroundColor = ''; // Reset background
    indicator.style.border = ''; // Reset border
    
    if (indicatorDot) {
      indicatorDot.style.background = '#00ff2f'; // Green dot
    }
    
    if (indicatorText) {
      indicatorText.textContent = 'Automated Trading ON';
    }
    
    
  } else {
    // Hide the indicator when scanning is not active
    indicator.style.display = 'none';
    
  }
}

// === POLLING SETUP ===

// Initialize polling when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  // Get current symbol and fetch price changes
  const getCurrentSymbol = () => {
    const symbolPicker = document.getElementById('ticker-picker');
    return symbolPicker ? symbolPicker.value : 'BTC';
  };
  
  // Initial data fetches
  fetchCore(getCurrentSymbol());
  
  // Initial price changes fetch
  fetchSymbolPriceChanges(getCurrentSymbol());

  // Set up polling intervals
  setInterval(() => fetchCore(getCurrentSymbol()), 5000);                 // Momentum data every 5 seconds for live updates
  setInterval(() => fetchSymbolPriceChanges(getCurrentSymbol()), 60000);    // Price changes every minute with current symbol
});

// Export functions for use by other modules
window.liveData = {
  fetchCore,
  fetchSymbolPriceChanges,
  fetchBTCPriceChanges // Legacy compatibility
}; 
