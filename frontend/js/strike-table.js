
// Add no-op definitions for missing functions to prevent ReferenceError
if (typeof window.updateClickHandlersForReco !== 'function') {
  window.updateClickHandlersForReco = function() {};
}

// === STRIKE TABLE MODULE ===
// This module handles middle column data: strike table, TTC, market title
// All data now comes from unified backend endpoints

// --- Row Flash CSS ---
if (!window._rowFlashStyleInjected) {
  const rowFlashStyle = document.createElement('style');
  rowFlashStyle.innerHTML = `
.strike-row-flash {
  animation: strike-row-flash-anim 0.55s linear;
}
@keyframes strike-row-flash {
  0% { background-color: #fff700; color: #222 !important; }
  80% { background-color: #fff700; color: #222 !important; }
  100% { background-color: inherit; color: inherit; }
}
`;
  document.head.appendChild(rowFlashStyle);
  window._rowFlashStyleInjected = true;
}

// Global strike table state
window.strikeRowsMap = new Map();

// Last seen market identity (symbol|market|market_title) — when this changes (e.g. rollover), redraw strike table
let lastSeenMarketKey = '';

// === UNIFIED DATA FETCHING ===

// Get current symbol from monitor context (read-only display / body.dataset), not from an editable control
function getCurrentSymbol() {
  const fromBody = document.body && document.body.dataset && document.body.dataset.currentSymbol;
  if (fromBody && fromBody.trim()) return fromBody.trim();
  const display = document.getElementById('monitor-symbol-display');
  if (display && display.textContent && display.textContent.trim() && display.textContent.trim() !== '—') return display.textContent.trim();
  const picker = document.getElementById('monitor-picker');
  if (picker && picker.value && picker.selectedOptions && picker.selectedOptions[0] && picker.selectedOptions[0].dataset.symbol) return picker.selectedOptions[0].dataset.symbol;
  return 'BTC';
}

// Current market from monitor: body.dataset (trade_monitor), picker option, then window.currentMarket (set on monitor load; avoids empty table before dataset sync).
function getCurrentMarket() {
  const bodyMarket = document.body && document.body.dataset && document.body.dataset.currentMarket;
  if (bodyMarket === '15m' || bodyMarket === 'hourly') return bodyMarket;
  const picker = document.getElementById('monitor-picker');
  if (picker && picker.value && picker.selectedOptions && picker.selectedOptions[0]) {
    const m = picker.selectedOptions[0].dataset.market;
    if (m === '15m' || m === 'hourly') return m;
  }
  if (typeof window !== 'undefined' && (window.currentMarket === '15m' || window.currentMarket === 'hourly')) {
    return window.currentMarket;
  }
  return null;
}

// Fetch unified TTC data. Requires market from monitor (hourly or 15m).
async function fetchUnifiedTTC(symbol = 'BTC', market = null) {
  const m = market || getCurrentMarket();
  if (!m || (m !== '15m' && m !== 'hourly')) return 0;
  try {
    const url = `/api/unified_ttc/${symbol.toLowerCase()}?market=${encodeURIComponent(m)}`;
    const response = await apiCall(url);
    const data = await response.json();
    return data.ttc_seconds || 0;
  } catch (error) {
    console.error('Error fetching unified TTC:', error);
    return 0;
  }
}

// System-agnostic API endpoint detection
async function getApiBaseUrl() {
  // Probe must include market= — endpoint returns 200 JSON with error if market is missing (undetectable as "working").
  const probeMarket = 'hourly';
  // Try current origin first
  try {
    const currentSymbol = getCurrentSymbol();
    const testUrl = window.location.origin + `/api/postgresql/strike_table/${currentSymbol.toLowerCase()}?market=${encodeURIComponent(probeMarket)}`;
    const response = await fetch(testUrl);
    if (response.ok) {
      const data = await response.json();
      if (data && data.symbol === currentSymbol && !data.error) {
        return window.location.origin;
      }
    }
  } catch (error) {
    // Current origin doesn't have API, try alternatives
  }
  
  // Try main app port (3000) - this has all the APIs
  const mainAppUrl = `${window.location.protocol}//${window.location.hostname}:3000`;
  try {
    const currentSymbol = getCurrentSymbol();
    const testUrl = mainAppUrl + `/api/postgresql/strike_table/${currentSymbol.toLowerCase()}?market=${encodeURIComponent(probeMarket)}`;
    const response = await fetch(testUrl);
    if (response.ok) {
      const data = await response.json();
      if (data && data.symbol === currentSymbol && !data.error) {
        return mainAppUrl;
      }
    }
  } catch (error) {
    // Main app not available
  }
  
  // Fallback to current origin (will show errors but won't break)
  return window.location.origin;
}

// Cache the API base URL to avoid repeated detection
let cachedApiBaseUrl = null;

// Helper function to make API calls with system-agnostic base URL
async function apiCall(endpoint, options = {}) {
  try {
    // Get the correct API base URL (cached after first detection)
    if (!cachedApiBaseUrl) {
      cachedApiBaseUrl = await getApiBaseUrl();
    }
    
    const response = await fetch(cachedApiBaseUrl + endpoint, options);
    return response;
  } catch (error) {
    console.error(`Error making API call to ${endpoint}:`, error);
    throw error;
  }
}

/** Parse strike / price from API (number, string, or numeric string with commas). */
function numStrike(v) {
  if (v == null || v === '') return NaN;
  if (typeof v === 'number') return Number.isFinite(v) ? v : NaN;
  const s = String(v).replace(/,/g, '').trim();
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : NaN;
}

/**
 * Find ladder row for a UI row key. Exact match first; otherwise closest strike within a tier-based
 * tolerance (ladder often uses 67599.99 while the grid shows 67600).
 */
function findStrikeDataForRow(strikes, rowStrikeKey, strikeTierHint) {
  if (!strikes || !strikes.length) return null;
  const row = numStrike(rowStrikeKey);
  if (!Number.isFinite(row)) return null;

  let best = null;
  let bestDist = Infinity;
  for (const s of strikes) {
    const sv = numStrike(s.strike);
    if (!Number.isFinite(sv)) continue;
    if (sv === row) return s;
    const d = Math.abs(sv - row);
    if (d < bestDist) {
      bestDist = d;
      best = s;
    }
  }
  const tier = numStrike(strikeTierHint);
  const tol =
    Number.isFinite(tier) && tier > 0
      ? Math.min(Math.max(tier * 0.51, 5), 500)
      : 150;
  if (best && bestDist <= tol) return best;
  return null;
}

function hasAskDollar(v) {
  if (v == null) return false;
  const s = String(v).trim();
  if (s === '') return false;
  const p = parseFloat(s.replace(/,/g, ''));
  return Number.isFinite(p);
}

// Fetch strike table data from PostgreSQL. Requires market from monitor (hourly or 15m).
async function fetchStrikeTableData(symbol = 'BTC', market = null) {
  const m = market || getCurrentMarket();
  if (!m || (m !== '15m' && m !== 'hourly')) return null;
  try {
    const url = `/api/postgresql/strike_table/${symbol.toLowerCase()}?market=${encodeURIComponent(m)}`;
    const response = await apiCall(url);
    const data = await response.json();
    if (!response.ok || (data && data.error)) {
      if (data && data.error) console.error('Strike table API error:', data.error);
      return null;
    }
    return data;
  } catch (error) {
    console.error('Error fetching PostgreSQL strike table data:', error);
    return null;
  }
}

// Update TTC display from strike table data
function updateTTCDisplay(ttcSeconds) {
  const ttcEl = document.getElementById('strikePanelTTC');
  if (!ttcEl) return;

  // Format TTC for display
  const formatTTC = (seconds) => {
    if (seconds === null || seconds === undefined || isNaN(seconds)) {
      return '--:--';
    }
    
    const totalMinutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    
    if (totalMinutes >= 60) {
      const hours = Math.floor(totalMinutes / 60);
      const minutes = totalMinutes % 60;
      return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    } else {
      return `${totalMinutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }
  };

  ttcEl.textContent = formatTTC(ttcSeconds);

  // Apply color coding
  ttcEl.style.backgroundColor = '';
  ttcEl.style.color = '';
  ttcEl.style.borderRadius = '';
  ttcEl.style.padding = '';

  if (ttcSeconds >= 0 && ttcSeconds <= 180) {
    ttcEl.style.backgroundColor = '#d2372b';
    ttcEl.style.color = '#fff';
    ttcEl.style.borderRadius = '6px';
    ttcEl.style.padding = '0 10px';
  } else if (ttcSeconds <= 300) {
    ttcEl.style.backgroundColor = '#ffc107';
    ttcEl.style.color = '#fff';
    ttcEl.style.borderRadius = '6px';
    ttcEl.style.padding = '0 10px';
  } else if (ttcSeconds <= 720) {
    ttcEl.style.backgroundColor = '#45d34a';
    ttcEl.style.color = '#fff';
    ttcEl.style.borderRadius = '6px';
    ttcEl.style.padding = '0 10px';
  } else if (ttcSeconds <= 900) {
    ttcEl.style.backgroundColor = '#45d34a';
    ttcEl.style.color = '#fff';
    ttcEl.style.borderRadius = '6px';
    ttcEl.style.padding = '0 10px';
  }
}

// Update symbol price display from strike table data
function updateSymbolPriceDisplay(currentPrice) {
  const priceEl = document.getElementById('symbol-price-value');
  if (!priceEl) return;
  
  if (currentPrice && !isNaN(currentPrice)) {
    priceEl.textContent = `$${Number(currentPrice).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  } else {
    priceEl.textContent = '$—';
  }
}

// Update market title from strike table data — display strike table market_title directly (hourly or 15m).
function updateMarketTitle(strikeTableData) {
  if (!strikeTableData) return;
  
  const cell = document.getElementById('strikePanelMarketTitleCell');
  if (!cell) return;
  
  const marketTitle = strikeTableData.market_title;
  cell.textContent = (marketTitle != null && String(marketTitle).trim() !== '') ? String(marketTitle).trim() : '—';
  cell.style.color = 'white';
}

// Main function to update middle column data
async function updateMiddleColumnData() {
  try {
    // Get current symbol
    const currentSymbol = getCurrentSymbol();
    const currentMarket = getCurrentMarket();
    
    // Fetch strike table data (includes market title)
    const strikeTableData = await fetchStrikeTableData(currentSymbol);
    
    // Update market title
    updateMarketTitle(strikeTableData);
    
    // When market ticker changes (hour rollover for hourlies, 15m for 15m), redraw strike table like the title
    const marketTitle = (strikeTableData && strikeTableData.market_title != null) ? String(strikeTableData.market_title).trim() : '';
    const marketKey = (currentSymbol || '') + '|' + (currentMarket || '') + '|' + marketTitle;
    if (marketKey !== lastSeenMarketKey) {
      lastSeenMarketKey = marketKey;
      if (typeof updateStrikeTable === 'function') {
        updateStrikeTable();
      }
    }
    
    // Update TTC display from strike table data
    if (strikeTableData && strikeTableData.ttc_seconds !== undefined) {
      updateTTCDisplay(strikeTableData.ttc_seconds);
    }
    
    // Update symbol price display from strike table data
    if (strikeTableData && strikeTableData.current_price !== undefined) {
      updateSymbolPriceDisplay(strikeTableData.current_price);
    }
    
    // Update momentum data from consolidated strike table data
    if (strikeTableData && strikeTableData.momentum) {
      // Update global momentum data
      if (window.momentumData) {
        if (strikeTableData.momentum.weighted_score !== undefined) {
          window.momentumData.weightedScore = strikeTableData.momentum.weighted_score;
        }
        if (strikeTableData.momentum.deltas) {
          Object.entries(strikeTableData.momentum.deltas).forEach(([key, value]) => {
            if (value !== undefined) {
              window.momentumData.deltas[key] = value;
            }
          });
        }
      }
      
      // Trigger momentum panel update if function exists
      if (typeof updateMomentumPanel === 'function') {
        updateMomentumPanel();
      }
    }
    
    // Update fingerprint display from consolidated strike table data
    if (strikeTableData && strikeTableData.fingerprint) {
      const fingerprintEl = document.getElementById('fingerprint-display');
      if (fingerprintEl) {
        fingerprintEl.textContent = `Fingerprint: ${strikeTableData.fingerprint}`;
      }
    }
    
  } catch (error) {
    console.error('Error updating middle column data:', error);
    // Show error state in market title
    const cell = document.getElementById('strikePanelMarketTitleCell');
    if (cell) {
      cell.textContent = 'SYSTEM ERROR';
      cell.style.color = '#dc3545';
    }
  }
}

// === STRIKE TABLE INITIALIZATION ===
// Uses dynamic strike_tier from market data - no hardcoded values

// Generate the complete strike table HTML structure
function generateStrikeTableHTML() {
  return `
    <div style="display: flex; align-items: flex-start;">
      <table id="strike-table" class="strike-table" style="width: 100%; table-layout: fixed;">
        <colgroup>
          <col class="col-strike">
          <col class="col-buffer">
          <col class="col-bm">
          <col class="col-risk">
          <col class="col-yes">
          <col class="col-no">
        </colgroup>
        <thead>
          <tr>
            <th>STRIKE</th>
            <th>BUFFER</th>
            <th>%</th>
            <th>Prob</th>
            <th>YES</th>
            <th>NO</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  `;
}

async function buildStrikeTableRows(basePrice) {
  const currentSymbol = getCurrentSymbol();
  const strikeTableData = await fetchStrikeTableData(currentSymbol);
  
  // Use actual strikes from API response but limit to 14 total (7 above + 7 below current price)
  if (strikeTableData && strikeTableData.strikes && strikeTableData.strikes.length > 0) {
    const currentPrice = numStrike(strikeTableData.current_price);
    const allStrikes = strikeTableData.strikes
      .map((s) => numStrike(s.strike))
      .filter((n) => Number.isFinite(n))
      .sort((a, b) => a - b);
    
    if (!Number.isFinite(currentPrice) || allStrikes.length === 0) {
      // fall through to synthetic grid
    } else {
      const strikesBelow = allStrikes.filter((s) => s < currentPrice).slice(-7);
      const strikesAbove = allStrikes.filter((s) => s >= currentPrice).slice(0, 7);
      return [...strikesBelow, ...strikesAbove];
    }
  }
  
  // Fallback: synthetic grid when API strikes missing or unusable
  const cp = strikeTableData ? numStrike(strikeTableData.current_price) : NaN;
  const strikeTier = strikeTableData ? numStrike(strikeTableData.strike_tier) : NaN;
  const step =
    Number.isFinite(strikeTier) && strikeTier > 0
      ? strikeTier
      : Number.isFinite(cp) && cp > 0
        ? Math.max(Math.round(cp * 0.0005), 25)
        : 100;
  const center = Number.isFinite(basePrice) ? basePrice : Number.isFinite(cp) ? Math.round(cp / step) * step : step * 675;
  const rows = [];
  for (let i = center - 7 * step; i <= center + 7 * step; i += step) {
    rows.push(i);
  }
  return rows;
}

function createSpannerRow(currentPrice) {
  const spannerRow = document.createElement("tr");
  spannerRow.className = "spanner-row";
  const spannerTd = document.createElement("td");
  spannerTd.colSpan = 6; // Match the number of columns in strike table
  // SVGs for straight arrows (no margin)
  const svgDown = `<svg width="16" height="16" style="vertical-align:middle;" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 2v12M8 14l4-4M8 14l-4-4" stroke="#45d34a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  const svgUp = `<svg width="16" height="16" style="vertical-align:middle;" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 14V2M8 2l4 4M8 2l-4 4" stroke="#dc3545" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  // Helper to get current momentum score from DOM
  function getCurrentMomentumScoreForArrow() {
    const el = document.getElementById('momentum-score-display');
    if (el && el.textContent) {
      const val = parseFloat(el.textContent.replace(/[^\d\.\-]/g, ''));
      return isNaN(val) ? 0 : val;
    }
    return 0;
  }
  let momentumScore = getCurrentMomentumScoreForArrow();
  let arrowBlock = '';
  const absMomentum = Math.abs(momentumScore);
  if (absMomentum < 5) {
    arrowBlock = '-';
  } else if (absMomentum < 10) {
    arrowBlock = momentumScore > 0 ? svgDown : svgUp;
  } else if (absMomentum < 20) {
    arrowBlock = (momentumScore > 0 ? svgDown : svgUp).repeat(2);
  } else {
    arrowBlock = (momentumScore > 0 ? svgDown : svgUp).repeat(3);
  }
  spannerTd.innerHTML = `<span style=\"margin:0 12px;display:inline-block;\">${arrowBlock}</span>Current Price: $${Math.round(currentPrice).toLocaleString()}<span style=\"margin:0 12px;display:inline-block;\">${arrowBlock}</span>`;
  spannerRow.appendChild(spannerTd);
  return spannerRow;
}

async function initializeStrikeTable(basePrice) {
  const strikeTableBody = document.querySelector('#strike-table tbody');
  const strikes = await buildStrikeTableRows(basePrice);
  strikeTableBody.innerHTML = '';
  window.strikeRowsMap.clear();

  strikes.forEach((strike, idx) => {
    const row = document.createElement('tr');

    // Strike cell
    const strikeTd = document.createElement('td');
    strikeTd.textContent = '$' + strike.toLocaleString();
    strikeTd.classList.add('center');
    row.appendChild(strikeTd);

    // Buffer cell
    const bufferTd = document.createElement('td');
    row.appendChild(bufferTd);

    // B/M cell
    const bmTd = document.createElement('td');
    row.appendChild(bmTd);

    // Risk cell (now Prob Touch (%))
    const probTd = document.createElement('td');
    row.appendChild(probTd);

    // Yes button cell and span
    const yesTd = document.createElement('td');
    // Set data-ticker on the cell (will be updated later in updateYesNoButton)
    yesTd.setAttribute('data-ticker', '');
    const yesSpan = document.createElement('span');
    yesTd.appendChild(yesSpan);
    row.appendChild(yesTd);

    // No button cell and span
    const noTd = document.createElement('td');
    noTd.setAttribute('data-ticker', '');
    const noSpan = document.createElement('span');
    noTd.appendChild(noSpan);
    row.appendChild(noTd);

    // All rows are now visible (7 above + 7 below = 14 total)
    strikeTableBody.appendChild(row);

    window.strikeRowsMap.set(strike, {
      row,
      bufferTd,
      bmTd,
      probTd,
      yesSpan,
      noSpan
    });
  });
}

// === STRIKE TABLE UPDATE LOGIC ===

// Update strike table with data from unified endpoint
async function updateStrikeTable() {
  try {
    // Get current symbol
    const currentSymbol = getCurrentSymbol();
    
    // Fetch strike table data from unified endpoint
    const strikeTableData = await fetchStrikeTableData(currentSymbol);
    if (!strikeTableData || !strikeTableData.strikes) {
      console.error('No strike table data available');
      return;
    }

    const strikes = strikeTableData.strikes;
    const currentPrice = numStrike(strikeTableData.current_price);
    const symbol = strikeTableData.symbol || 'BTC';
    const resolvedTier = numStrike(strikeTableData.strike_tier);
    const gridTier =
      Number.isFinite(resolvedTier) && resolvedTier > 0
        ? resolvedTier
        : Number.isFinite(currentPrice) && currentPrice > 0
          ? Math.max(Math.round(currentPrice * 0.0005), 25)
          : 250;

    // Initialize strike table if needed
    if (!window.strikeRowsMap || window.strikeRowsMap.size === 0) {
      const base = Number.isFinite(currentPrice)
        ? Math.round(currentPrice / gridTier) * gridTier
        : gridTier * 676;
      await initializeStrikeTable(base);
    }

    // Check if we need to re-center the table due to price drift
    if (window.strikeRowsMap && window.strikeRowsMap.size > 0) {
      const currentCenterStrike = [...window.strikeRowsMap.keys()].sort((a, b) => a - b)[Math.floor(window.strikeRowsMap.size / 2)];
      const cs = numStrike(currentCenterStrike);
      const priceDrift = Number.isFinite(currentPrice) && Number.isFinite(cs) ? Math.abs(currentPrice - cs) : 0;

      if (priceDrift > 2 * gridTier) {
        const newBase = Number.isFinite(currentPrice)
          ? Math.round(currentPrice / gridTier) * gridTier
          : cs;
        await initializeStrikeTable(newBase);
        setTimeout(updateStrikeTable, 50);
        return;
      }
    }

    // Update each strike row with pre-calculated data
    window.strikeRowsMap.forEach((cells, strike) => {
      const { row, bufferTd, bmTd, probTd, yesSpan, noSpan } = cells;
      const diffMode = window.diffMode || false;

      const strikeData = findStrikeDataForRow(strikes, strike, strikeTableData.strike_tier ?? gridTier);
      
      if (strikeData) {
        const buf = numStrike(strikeData.buffer);
        bufferTd.textContent = Number.isFinite(buf) ? buf.toFixed(2) : '—';

        const bmp = numStrike(strikeData.buffer_pct);
        bmTd.textContent = Number.isFinite(bmp) ? bmp.toFixed(2) : '—';

        const prob = numStrike(strikeData.probability);
        probTd.textContent = Number.isFinite(prob) ? prob.toFixed(1) : '—';
        
        // Risk color coding
        row.classList.remove('ultra-safe', 'safe', 'caution', 'high-risk', 'danger-stop');
        let riskClass = '';
        if (Number.isFinite(prob)) {
          if (prob >= 98) riskClass = 'ultra-safe';
          else if (prob >= 95) riskClass = 'safe';
          else if (prob >= 80) riskClass = 'caution';
          else riskClass = 'high-risk';
          row.classList.add(riskClass);
        }

        // Yes/No ask prices (pre-calculated) - require parseable _dollars values
        if (!hasAskDollar(strikeData.yes_ask_dollars) || !hasAskDollar(strikeData.no_ask_dollars)) {
          updateYesNoButton(yesSpan, strike, 'yes', null, false, null, false, diffMode, null);
          updateYesNoButton(noSpan, strike, 'no', null, false, null, false, diffMode, null);
          return;
        }
        const yesAsk = Math.round(parseFloat(String(strikeData.yes_ask_dollars).replace(/,/g, '')) * 100);
        const noAsk = Math.round(parseFloat(String(strikeData.no_ask_dollars).replace(/,/g, '')) * 100);
        const yesDiff = strikeData.yes_diff;
        const noDiff = strikeData.no_diff;
        const volumeFp = strikeData.volume_fp;

        // Simplified button enabling logic (Kalshi depth from volume_fp text)
        const volumeNum = Number.isFinite(parseFloat(volumeFp)) ? parseFloat(volumeFp) : 0;
        // Get min_volume from current monitor settings (default to 1000 if not available)
        const minVolume = window.currentMonitorMinVolume || 1000;
        const volumeOk = volumeNum >= minVolume;
        const yesPriceOk = yesAsk <= 98;
        const noPriceOk = noAsk <= 98;
        const strikeNum = numStrike(strike);
        const isAboveMoneyLine =
          Number.isFinite(strikeNum) && Number.isFinite(currentPrice) && strikeNum > currentPrice;
        
        // Determine which button should be enabled
        let yesEnabled = false;
        let noEnabled = false;
        
        if (volumeOk) {
          if (isAboveMoneyLine) {
            // Above money line: Only enable NO button if price is good
            noEnabled = noPriceOk;
            yesEnabled = false; // Never enable YES above money line
          } else {
            // Below money line: Only enable YES button if price is good
            yesEnabled = yesPriceOk;
            noEnabled = false; // Never enable NO below money line
          }
        }
        
        // Update both buttons with their correct enabled state
        // Use _dollars values for trade execution (no fallback)
        const yesAskForTrade = strikeData.yes_ask_dollars;
        const noAskForTrade = strikeData.no_ask_dollars;
        
        updateYesNoButton(yesSpan, strike, "yes", yesAsk, yesEnabled, strikeData.ticker, false, diffMode, yesDiff, yesAskForTrade);
        updateYesNoButton(noSpan, strike, "no", noAsk, noEnabled, strikeData.ticker, false, diffMode, noDiff, noAskForTrade);
        
        // Update position indicator for this strike
        const strikeCell = row.querySelector('td:first-child'); // First column is strike price
        if (strikeCell) {
          updatePositionIndicator(strikeCell, strike);
        }
      } else {
        // No data for this strike, show placeholders and ensure buttons are drawn in disabled state
        bufferTd.textContent = '—';
        bmTd.textContent = '—';
        probTd.textContent = '—';
        // Always update buttons to ensure they are drawn (even in disabled state)
        updateYesNoButton(yesSpan, strike, "yes", null, false, null, false, diffMode, null);
        updateYesNoButton(noSpan, strike, "no", null, false, null, false, diffMode, null);
      }
    });

    // --- SPANNER ROW LOGIC ---
    const strikeTableBody = document.querySelector('#strike-table tbody');
    let spannerRow = strikeTableBody.querySelector('.spanner-row');
    
    // Create spanner row if it doesn't exist
    if (!spannerRow) {
      spannerRow = createSpannerRow(currentPrice);
      // Ensure the spanner row is added to the table
      strikeTableBody.appendChild(spannerRow);
    } else {
      // Update existing spanner row with current price and momentum arrows
      const spannerTd = spannerRow.querySelector('td');
      if (spannerTd) {
        // Recreate the spanner row content with updated momentum arrows
        const svgDown = `<svg width="16" height="16" style="vertical-align:middle;" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 2v12M8 14l4-4M8 14l-4-4" stroke="#45d34a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
        const svgUp = `<svg width="16" height="16" style="vertical-align:middle;" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 14V2M8 2l4 4M8 2l-4 4" stroke="#dc3545" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
        
        // Helper to get current momentum score from DOM
        function getCurrentMomentumScoreForArrow() {
          const el = document.getElementById('momentum-score-display');
          if (el && el.textContent) {
            const val = parseFloat(el.textContent.replace(/[^\d\.\-]/g, ''));
            return isNaN(val) ? 0 : val;
          }
          return 0;
        }
        
        let momentumScore = getCurrentMomentumScoreForArrow();
        let arrowBlock = '';
        const absMomentum = Math.abs(momentumScore);
        if (absMomentum < 5) {
          arrowBlock = '-';
        } else if (absMomentum < 10) {
          arrowBlock = momentumScore > 0 ? svgDown : svgUp;
        } else if (absMomentum < 20) {
          arrowBlock = (momentumScore > 0 ? svgDown : svgUp).repeat(2);
        } else {
          arrowBlock = (momentumScore > 0 ? svgDown : svgUp).repeat(3);
        }
        
        spannerTd.innerHTML = `<span style=\"margin:0 12px;display:inline-block;\">${arrowBlock}</span>Current Price: $${Math.round(currentPrice).toLocaleString()}<span style=\"margin:0 12px;display:inline-block;\">${arrowBlock}</span>`;
      }
    }

    // Position spanner row correctly
    const allRows = Array.from(strikeTableBody.children).filter(row => !row.classList.contains('spanner-row'));
    let insertIndex = allRows.length; // default to end
    
    for (let i = 0; i < allRows.length; i++) {
      const row = allRows[i];
      const strikeCell = row.querySelector('td');
      if (strikeCell && strikeCell.textContent) {
        const strikeText = strikeCell.textContent.replace(/[\$,]/g, '');
        const strike = parseFloat(strikeText);
        if (!isNaN(strike) && currentPrice < strike) {
          insertIndex = i;
          break;
        }
      }
    }

    // Remove spanner row from current position and insert at correct position
    if (spannerRow.parentNode) {
      spannerRow.remove();
    }
    
    if (insertIndex < allRows.length) {
      strikeTableBody.insertBefore(spannerRow, allRows[insertIndex]);
    } else {
      strikeTableBody.appendChild(spannerRow);
    }

    // Update fingerprint display if function exists
    if (typeof updateFingerprintDisplay === 'function') {
      updateFingerprintDisplay();
    }

    // Update momentum bucket display
    const momentumBucketDisplay = document.getElementById('momentum-bucket-display');
    if (momentumBucketDisplay && strikeTableData.momentum_bucket !== undefined) {
      const bucket = strikeTableData.momentum_bucket;
      const sign = bucket >= 0 ? '+' : '';
      momentumBucketDisplay.textContent = `${sign}${bucket}`;
      
      // Color coding based on bucket value
      momentumBucketDisplay.style.color = bucket === 0 ? '#888' : 
                                         bucket > 0 ? '#45d34a' : '#dc3545';
    }

    // Update heat band if function exists
    if (typeof updateMomentumHeatBandSegmented === 'function') {
      setTimeout(() => {
        const strikeTable = document.getElementById('strike-table');
        const heatBand = document.getElementById('momentum-heat-band');
        if (strikeTable && heatBand) {
          heatBand.style.height = strikeTable.offsetHeight + 'px';
        }
        updateMomentumHeatBandSegmented();
      }, 0);
    }

    // Reset diff mode change flag after update is complete
    window.diffModeChanged = false;
  } catch (error) {
    console.error('Error updating strike table:', error);
  }
}

// === POSITION INDICATOR ===

// Test function to manually check active trades
window.testActiveTrades = async function() {
  try {

    const tradesRes = await apiCall('/api/active_trades', { cache: 'no-store' });
    if (!tradesRes.ok) {
      console.error('[TEST] API request failed:', tradesRes.status);
      return;
    }
    
    const data = await tradesRes.json();
    const activeTrades = data.active_trades || [];

    
    activeTrades.forEach(trade => {
      const tradeStrike = parseFloat(trade.strike.replace(/[^\d.-]/g, ''));
      
    });
    
    // Test specific strikes
    const testStrikes = [115500, 114250, 115750];
    testStrikes.forEach(strike => {
      const hasPosition = activeTrades.some(trade => {
        const tradeStrike = parseFloat(trade.strike.replace(/[^\d.-]/g, ''));
        return tradeStrike === strike;
      });

    });
    
  } catch (e) {
    console.error('[TEST] Error testing active trades:', e);
  }
};

async function updatePositionIndicator(strikeCell, strike) {
  try {
    // Fetch active trades from the active_trade_supervisor API endpoint
    const tradesRes = await apiCall('/api/active_trades', { cache: 'no-store' });
    if (!tradesRes.ok) return;
    
    const data = await tradesRes.json();
    const activeTrades = data.active_trades || [];
    
    // Debug logging

    
    // Check if any active trade has this strike
    const hasPosition = activeTrades.some(trade => {
      const tradeStrike = parseFloat(trade.strike.replace(/[^\d.-]/g, ''));
      const matches = tradeStrike === strike;
      if (matches) {

      }
      return matches;
    });
    
    // Debug logging
    
    
    // Update visual indicator
    if (hasPosition) {
      strikeCell.style.backgroundColor = '#1a2a1a'; // Very subtle green tint
      strikeCell.style.borderLeft = '3px solid #45d34a'; // Green left border

    } else {
      strikeCell.style.backgroundColor = '';
      strikeCell.style.borderLeft = '';
    }
  } catch (e) {
    console.error(`[POSITION INDICATOR] Error checking position for strike ${strike}:`, e);
    strikeCell.style.backgroundColor = '';
    strikeCell.style.borderLeft = '';
  }
}

// === YES/NO BUTTON UPDATES ===

// Track last Yes/No button states
const lastButtonStates = new Map();

// Debounce helper function
function debounce(func, wait) {
  let timeout;
  return function(...args) {
    if (timeout) return;
    func.apply(this, args);
    timeout = setTimeout(() => {
      timeout = null;
    }, wait);
  };
}

// Helper function to update Yes/No button with conditional redraw
function updateYesNoButton(spanEl, strike, side, askPrice, isActive, ticker = null, forceRefresh = false, diffMode = false, diffValue = null, askPriceForTrade = null) {
  const key = `${strike}-${side}`;
  const prev = lastButtonStates.get(key);
  
  // Check if diffMode has changed (this forces redraw when switching modes)
  const diffModeChanged = prev && prev.diffMode !== diffMode;
  
  if (!forceRefresh && !window.forceButtonRefresh && !diffModeChanged && !window.diffModeChanged && prev && prev.askPrice === askPrice && prev.isActive === isActive) {
    // No change; skip update
    return;
  }

  // Determine display value based on mode
  let displayValue = '—';
  if (askPrice && askPrice !== '—' && askPrice !== 0) {
    if (diffMode && diffValue !== null) {
      // DIFF MODE: Show pre-calculated diff value (no decimals) for ALL buttons
      displayValue = diffValue > 0 ? `+${Math.round(diffValue)}` : `${Math.round(diffValue)}`;
    } else {
      // PRICE MODE: Show actual ask price for ALL buttons
      displayValue = askPrice;
    }
  }
  
  spanEl.textContent = displayValue;
  spanEl.className = isActive ? 'price-box' : 'price-box disabled';
  spanEl.style.cursor = isActive ? 'pointer' : 'default';
  
  // Force cursor style with higher specificity
  if (isActive) {
    spanEl.style.setProperty('cursor', 'pointer', 'important');
  } else {
    spanEl.style.setProperty('cursor', 'default', 'important');
  }

  // Set data-ticker on the YES/NO cell's parent td (for reference, if needed)
  if (spanEl.parentElement && ticker) {
    spanEl.parentElement.setAttribute('data-ticker', ticker);
  }
  // Also set data-ticker directly on spanEl for easier access in openTrade
            if (ticker) {
            spanEl.setAttribute('data-ticker', ticker);
          }
  // Set data-strike and data-side for easier retrieval in openTrade
  spanEl.setAttribute('data-strike', strike);
  spanEl.setAttribute('data-side', side);
  
  // Store diff value as data attribute
  if (diffValue !== null && diffValue !== undefined) {
    spanEl.setAttribute('data-diff', diffValue);
  } else {
    spanEl.removeAttribute('data-diff');
  }
  
  // Store the actual ask price for trade execution (not the display value)
  // Use the _dollars value for trade execution (no fallback)
  if (askPriceForTrade && askPriceForTrade !== '—' && askPriceForTrade !== 0) {
    spanEl.setAttribute('data-ask-price', askPriceForTrade);
  } else {
    spanEl.removeAttribute('data-ask-price');
  }

  if (isActive) {
    spanEl.onclick = debounce(async function(event) {
      // Use centralized trade execution controller via trade_manager
      try {
        const tradeData = await prepareTradeData(spanEl); // Use the centralized function
        
        if (!tradeData) {
          console.error('Missing trade data for strike table button after prepareTradeData');
          return;
        }
        
        // Call the new trade_manager endpoint with complete data
        const response = await apiCall('/api/trigger_open_trade', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            strike: tradeData.strike,
            side: tradeData.side,
            ticker: tradeData.ticker,
            buy_price: tradeData.buy_price,
            prob: tradeData.prob,
            diff: tradeData.diff,
            symbol_open: tradeData.symbol_open,
            momentum: tradeData.momentum,
            contract: tradeData.contract,
            symbol: tradeData.symbol,
            position: tradeData.position,
            trade_strategy: tradeData.trade_strategy,
            monitor: tradeData.monitor,
            entry_method: tradeData.entry_method,
            paper_trade: tradeData.paper_trade
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
          console.error('Strike table trade initiation failed:', response.status);
        }
      } catch (error) {
        console.error('Error initiating strike table trade:', error);
      }
    }, 300);
  } else {
    spanEl.onclick = null;
  }

  lastButtonStates.set(key, { askPrice, isActive, diffMode });
}

// === TRADE EXECUTION ===
// All trade execution goes through the single openTrade function in trade_monitor.html
// This ensures audio alerts and popup displays work correctly

// === IMMEDIATE DIF MODE REDRAW ===

// Global flag to force refresh on mode changes
window.forceButtonRefresh = false;
window.diffModeChanged = false;

// === UTILITY FUNCTIONS ===

// Utility function to get selected symbol from ticker panel
function getSelectedSymbol() {
  const tickerSelect = document.getElementById('ticker-picker');
  if (tickerSelect) {
    return tickerSelect.value;
  }
  return "";
}




// === STRIKE TABLE CONTAINER INITIALIZATION ===

function initializeStrikeTableContainer() {
  const container = document.getElementById('strikePanelContainer');
  if (!container) {
    console.error('Strike table container not found');
    return;
  }
  
  // Check if strike table already exists
  let existingStrikeTable = container.querySelector('#strike-table');
  
  if (!existingStrikeTable) {
    // Generate and insert the strike table HTML only if it doesn't exist
    const strikeTableHTML = generateStrikeTableHTML();
    
    // Find the existing content after the panel header and replace it
    const panelHeader = container.querySelector('.panel-header');
    if (panelHeader) {
      // Remove any existing content after the header
      let nextElement = panelHeader.nextElementSibling;
      while (nextElement) {
        const temp = nextElement.nextElementSibling;
        nextElement.remove();
        nextElement = temp;
      }
      
      // Insert the strike table after the header
      panelHeader.insertAdjacentHTML('afterend', strikeTableHTML);
    } else {
      // Fallback: replace entire container content
      container.innerHTML = strikeTableHTML;
    }
  }
}

// === CLEAN STRIKE TABLE API ===
// Expose a clean API for other modules to use
window.StrikeTable = {
  // Initialize the strike table container and structure
  initialize: function() {
    initializeStrikeTableContainer();
  },
  
  // Update the strike table with new data
  update: function() {
    return updateStrikeTable();
  },
  
  // Set diff mode (affects price display)
  setDiffMode: function(enabled) {
    window.diffMode = enabled;
    window.diffModeChanged = true;
    // Force immediate update
    if (typeof window.updateStrikeTable === 'function') {
      window.updateStrikeTable();
    }
  },
  
  // Set auto entry mode (affects button enabling)
  setAutoEntry: function(enabled) {
    window.recoEnabled = enabled;
    // Update click handlers for auto entry mode
    if (typeof window.updateClickHandlersForReco === 'function') {
      window.updateClickHandlersForReco();
    }
  },
  
  // Get current strike table data
  getData: function() {
    return fetchStrikeTableData();
  },
  
  // Get current strike tier from strike table data
  getStrikeTier: function() {
    return fetchStrikeTableData().then(data => data?.strike_tier);
  },
  
  // Update TTC display
  updateTTC: function() {
    return updateTTCDisplay();
  },
  
  // Update market title
  updateMarketTitle: function() {
    return updateMiddleColumnData();
  }
};

// === EXPORT FUNCTIONS TO WINDOW ===
// Make functions available globally for other modules to use
window.initializeStrikeTable = initializeStrikeTable;
window.updateStrikeTable = updateStrikeTable;
window.updateYesNoButton = updateYesNoButton;
window.updatePositionIndicator = updatePositionIndicator;
window.addStrikeTableRowClickHandlers = addStrikeTableRowClickHandlers;
window.updateMiddleColumnData = updateMiddleColumnData;
window.fetchUnifiedTTC = fetchUnifiedTTC;
window.fetchStrikeTableData = fetchStrikeTableData;
window.initializeStrikeTableContainer = initializeStrikeTableContainer;

// === STRIKE TABLE ROW CLICK HANDLERS ===
function addStrikeTableRowClickHandlers() {
  const strikeTable = document.getElementById('strike-table');
  if (!strikeTable) return;
  const rows = strikeTable.querySelectorAll('tbody tr');
  rows.forEach(row => {
    // Remove any previous click handler
    row.removeEventListener('click', row._strikeTableClickHandler);
    // Attach new click handler (currently no-op, can be extended later)
    const clickHandler = (event) => {
      // Click handler removed - no functionality
    };
    row._strikeTableClickHandler = clickHandler;
    row.addEventListener('click', clickHandler);
  });
}

// Load DIFF mode setting from preferences
function loadDiffModeFromPreferences() {
  // Diff mode defaults to ON and is local only
  window.diffMode = true;
}

// Interval IDs for pause-when-hidden (Trade Monitor tab)
let middleColumnIntervalId = null;
let strikeTableIntervalId = null;
/** Fallback when WS quiet; primary updates come from /ws/db_changes coalescing in orderbook-redis-ui.js */
const STRIKE_TABLE_FALLBACK_POLL_MS = 3500;

function startStrikeTablePolling() {
  if (middleColumnIntervalId != null) clearInterval(middleColumnIntervalId);
  if (strikeTableIntervalId != null) clearInterval(strikeTableIntervalId);
  middleColumnIntervalId = setInterval(updateMiddleColumnData, STRIKE_TABLE_FALLBACK_POLL_MS);
  strikeTableIntervalId = setInterval(updateStrikeTable, STRIKE_TABLE_FALLBACK_POLL_MS);
}

function stopStrikeTablePolling() {
  if (middleColumnIntervalId != null) {
    clearInterval(middleColumnIntervalId);
    middleColumnIntervalId = null;
  }
  if (strikeTableIntervalId != null) {
    clearInterval(strikeTableIntervalId);
    strikeTableIntervalId = null;
  }
}

// Attach handlers after table is rendered
if (typeof window !== 'undefined') {
  document.addEventListener('DOMContentLoaded', async () => {
    loadDiffModeFromPreferences();
    
    // Initialize strike table container first
    initializeStrikeTableContainer();
    
    // Only fetch when market is already set (e.g. by trade_monitor after populateMonitorPicker). Avoids using wrong/missing market.
    if (getCurrentMarket()) {
      await updateMiddleColumnData();
      await updateStrikeTable();
    }
    startStrikeTablePolling();
  });
} 

// === STRIKE TABLE WEBSOCKET UPDATES ===
// WebSocket connection for real-time database change notifications
let dbChangeWebSocketUnsub = null;
let strikeTableTabPaused = false;
let strikeTableTradesWsDebounceTimer = null;
const STRIKE_TABLE_TRADES_WS_DEBOUNCE_MS = 500;

function connectDbChangeWebSocket() {
  if (strikeTableTabPaused) return;
  if (dbChangeWebSocketUnsub) return;
  if (!window.recRealtimeWsCoordinator || typeof window.recRealtimeWsCoordinator.subscribe !== 'function') return;

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/db_changes`;
  dbChangeWebSocketUnsub = window.recRealtimeWsCoordinator.subscribe(wsUrl, {
    onMessage: function(event) {
      try {
        const raw = event.data;
        if (typeof recDbChangeRawMentionsStream === 'function' && !recDbChangeRawMentionsStream(raw, 'trades')) {
          return;
        }
        const data = JSON.parse(raw);
        if (data.type === 'db_change' && data.database === 'trades') {
          if (strikeTableTradesWsDebounceTimer) clearTimeout(strikeTableTradesWsDebounceTimer);
          strikeTableTradesWsDebounceTimer = setTimeout(function() {
            strikeTableTradesWsDebounceTimer = null;
            fetchAndRenderStrikeTable();
            if (typeof window.fetchAndRenderTrades === 'function') {
              window.fetchAndRenderTrades();
            }
          }, STRIKE_TABLE_TRADES_WS_DEBOUNCE_MS);
        }
      } catch (error) {
        console.error("[WEBSOCKET] Error processing message:", error);
      }
    }
  });
}

function disconnectDbChangeWebSocket() {
  if (!dbChangeWebSocketUnsub) return;
  try { dbChangeWebSocketUnsub(); } catch (e) {}
  dbChangeWebSocketUnsub = null;
}

// Function to fetch and render strike table (called by WebSocket)
function fetchAndRenderStrikeTable() {
  if (typeof window.fetchAndUpdate === 'function') {
    window.fetchAndUpdate();
  }
}

// Initialize WebSocket connection and tab-visibility pause/resume
if (typeof window !== 'undefined') {
  connectDbChangeWebSocket();

  window.addEventListener('message', function(event) {
    if (event.data && event.data.type === 'tab-visibility') {
      const visible = event.data.visible === true;
      strikeTableTabPaused = !visible;
      if (visible) {
        startStrikeTablePolling();
        connectDbChangeWebSocket();
      } else {
        stopStrikeTablePolling();
        disconnectDbChangeWebSocket();
      }
    }
  });
  
  // Add a test function to manually trigger a database change notification
  window.testWebSocketConnection = function() {

    if (dbChangeWebSocket && dbChangeWebSocket.readyState === WebSocket.OPEN) {
      
      // Send a test message to the server
      dbChangeWebSocket.send("ping");
    } else {
      
    }
  };
} 

 
