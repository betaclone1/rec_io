
// === ACTIVE TRADE SUPERVISOR MANAGER ===
// This module handles the Active Trade Supervisor table creation, updates, and maintenance
// Pulls data directly from PostgreSQL via the active_trade_supervisor service

// Global active trade supervisor state
window.activeTradeSupervisorRowsMap = new Map();

// Polling interval management
let activeTradeSupervisorRefreshInterval = null;
let hasPendingTrades = false;

// Helper function to insert row in correct sorted position
function insertRowInSortedPosition(tableBody, newRow, newStrike) {
  const allRows = Array.from(tableBody.children);
  let insertIndex = allRows.length; // default to end
  
  for (let i = 0; i < allRows.length; i++) {
    const row = allRows[i];
    if (row.classList.contains('spanner-row')) continue;
    
    const strikeCell = row.querySelector('td');
    if (strikeCell) {
      const strike = parseFloat(strikeCell.textContent.replace(/[\$,]/g, ''));
      if (newStrike < strike) {
        insertIndex = i;
        break;
      }
    }
  }
  
  if (insertIndex === allRows.length) {
    tableBody.appendChild(newRow);
  } else {
    tableBody.insertBefore(newRow, allRows[insertIndex]);
  }
}

// Wait for port configuration to load before initializing
async function waitForPortConfig() {
    let attempts = 0;
    const maxAttempts = 50; // 5 seconds with 100ms intervals
    
    while (attempts < maxAttempts) {
        try {
            // Check if port configuration is loaded
            if (typeof getMainAppUrl === 'function') {
                // Test if the function works
                getMainAppUrl('/test');
                return true;
            }
        } catch (error) {
            // Port config not ready yet
        }
        
        await new Promise(resolve => setTimeout(resolve, 100));
        attempts++;
    }
    
    console.warn('[ACTIVE TRADE SUPERVISOR] Port configuration not loaded after 5 seconds, using fallback');
    return false;
}

// === ACTIVE TRADE SUPERVISOR INITIALIZATION ===

function initializeActiveTradeSupervisorTable() {
  const activeTradeSupervisorTableBody = document.querySelector('#activeTradeSupervisorTable tbody');
  if (!activeTradeSupervisorTableBody) {
    console.error('[ACTIVE TRADE SUPERVISOR] Active trade supervisor table body not found');
    return;
  }
  
  // Clear existing content
  activeTradeSupervisorTableBody.innerHTML = '';
  window.activeTradeSupervisorRowsMap.clear();
  
}

// === ACTIVE TRADE SUPERVISOR UPDATE LOGIC ===

async function fetchAndRenderActiveTradeSupervisorTrades() {
  try {
    
    // Get the current monitor name for monitor-specific active trades
    const currentMonitorName = window.currentMonitorName;
    if (!currentMonitorName) {
      console.warn('[ACTIVE TRADE SUPERVISOR] No current monitor name available');
      return;
    }
    
    // Get the active trades using monitor-specific API call
    const activeTradeSupervisorUrl = window.location.origin + `/api/active_trades/${currentMonitorName}`;
    
    // Fetch active trades from the supervisor service
    const response = await fetch(activeTradeSupervisorUrl, { cache: 'no-store' });
    
    if (!response.ok) {
      console.error(`[ACTIVE TRADE SUPERVISOR] Failed to fetch active trades for monitor ${currentMonitorName}:`, response.status);
      return;
    }
    
    const data = await response.json();
    
    if (!data.active_trades || !Array.isArray(data.active_trades)) {
      console.error('[ACTIVE TRADE SUPERVISOR] Invalid data format:', data);
      return;
    }
    
    // Render the trades
    renderActiveTradeSupervisorTrades(data.active_trades);
    
  } catch (error) {
    console.error('[ACTIVE TRADE SUPERVISOR] Error fetching trades:', error);
  }
}

// === RENDER FUNCTION ===

function renderActiveTradeSupervisorTrades(activeTrades) {
  
  const activeTradeSupervisorTableBody = document.querySelector('#activeTradeSupervisorTable tbody');
  if (!activeTradeSupervisorTableBody) {
    console.error('[ACTIVE TRADE SUPERVISOR] Table body not found!');
    return;
  }
  
  // Sort trades by strike price in ascending order
  activeTrades.sort((a, b) => {
    const strikeA = parseFloat(a.strike.toString().replace(/[\$,]/g, ''));
    const strikeB = parseFloat(b.strike.toString().replace(/[\$,]/g, ''));
    return strikeA - strikeB;
  });
  
  // Remove rows for trades that no longer exist
  const activeTradeIds = new Set(activeTrades.map(trade => trade.trade_id));
  
  for (const [tradeId, rowObj] of window.activeTradeSupervisorRowsMap.entries()) {
    if (!activeTradeIds.has(tradeId)) {
      if (rowObj.tr && rowObj.tr.parentNode === activeTradeSupervisorTableBody) {
        activeTradeSupervisorTableBody.removeChild(rowObj.tr);
      }
      window.activeTradeSupervisorRowsMap.delete(tradeId);
    }
  }

  // Remove all existing spanner rows before rendering trade rows
  activeTradeSupervisorTableBody.querySelectorAll('.spanner-row').forEach(row => row.remove());

  // Render each active trade
  activeTrades.forEach((trade, idx) => {
    const tradeId = trade.trade_id;
    
    // Check if we already have a row for this trade
    let rowObj = window.activeTradeSupervisorRowsMap.get(tradeId);
    
    if (!rowObj) {
      const row = document.createElement("tr");
      
      // Strike
      const strikeCell = document.createElement("td");
      strikeCell.textContent = trade.strike;
      row.appendChild(strikeCell);
      
      // Side
      const sideCell = document.createElement("td");
      sideCell.textContent = trade.side;
      row.appendChild(sideCell);
      
      // Buy (price)
      const priceCell = document.createElement("td");
      priceCell.textContent = (typeof trade.buy_price === "number")
        ? trade.buy_price.toFixed(2)
        : trade.buy_price;
      row.appendChild(priceCell);
      
      // Position
      const posCell = document.createElement("td");
      posCell.textContent = trade.position ?? "";
      row.appendChild(posCell);
      
      // Buffer (from PostgreSQL)
      const bufferCell = document.createElement("td");
      if (trade.buffer_from_entry !== null) {
        const buffer = trade.buffer_from_entry;
        bufferCell.textContent = buffer.toLocaleString(undefined, {maximumFractionDigits: 0});
        
        // Apply risk color classes based on probability
        if (trade.current_probability !== null && trade.current_probability !== undefined) {
          const prob = trade.current_probability;
          if (prob >= 95) row.classList.add('ultra-safe');
          else if (prob >= 80) row.classList.add('safe');
          else if (prob >= 50) row.classList.add('caution');
          else if (prob >= 25) row.classList.add('high-risk');
          else row.classList.add('danger-stop');
        }
      } else {
        bufferCell.textContent = "N/A";
      }
      row.appendChild(bufferCell);
      
      // Probability (from PostgreSQL)
      const probCell = document.createElement("td");
      if (trade.current_probability !== null) {
        probCell.textContent = trade.current_probability.toFixed(1);
      } else {
        probCell.textContent = "N/A";
      }
      row.appendChild(probCell);
      
      // Close button with PnL display
      const closeCell = document.createElement("td");
      closeCell.style.textAlign = "center";
      const closeSpan = document.createElement("span");
      closeSpan.className = "price-box";
      closeSpan.dataset.tradeId = trade.trade_id;
      closeSpan.dataset.action = "close";
      closeSpan.style.cursor = "pointer";
      closeSpan.onclick = () => closeActiveTrade(trade.trade_id, trade.ticket_id);
      const innerDiv = document.createElement("div");
      
      // Display PnL if available, otherwise show "Close"
      if (trade.current_pnl !== null && trade.current_pnl !== undefined) {
        const pnl = parseFloat(trade.current_pnl);
        if (!isNaN(pnl)) {
          // Format PnL with white text
          const pnlText = pnl >= 0 ? `+${pnl.toFixed(2)}` : pnl.toFixed(2);
          innerDiv.textContent = pnlText;
          innerDiv.style.color = "white";
        } else {
          innerDiv.textContent = "Close";
          innerDiv.style.color = "white";
        }
      } else {
        innerDiv.textContent = "Close";
        innerDiv.style.color = "white";
      }
      
      closeSpan.appendChild(innerDiv);
      closeCell.appendChild(closeSpan);
      row.appendChild(closeCell);
      
      // Store the row object
      rowObj = { tr: row };
      window.activeTradeSupervisorRowsMap.set(tradeId, rowObj);
      
      // Apply status-based styling
      if (trade.status === 'closing') {
        row.classList.add('closing-trade');
      } else if (trade.status === 'pending') {
        // For pending trades, show placeholder values but keep normal styling
        priceCell.textContent = "Pending";
        posCell.textContent = "Pending";
        bufferCell.textContent = "Pending";
        probCell.textContent = "Pending";
        // Disable close button for pending trades
        closeSpan.style.cursor = "not-allowed";
        closeSpan.onclick = null;
        innerDiv.textContent = "Pending";
        row.classList.add('pending-trade'); // Add a class for pending trades
      }
      
      // Add the row to the table in sorted position
      const newStrike = parseFloat(trade.strike.toString().replace(/[\$,]/g, ''));
      insertRowInSortedPosition(activeTradeSupervisorTableBody, row, newStrike);
    } else {
      // Update existing row with new data
      const row = rowObj.tr;
      const cells = row.querySelectorAll('td');
      
      // Update BUY column (price)
      if (cells.length > 2 && trade.buy_price !== null && trade.buy_price !== undefined) {
        const price = parseFloat(trade.buy_price);
        if (!isNaN(price)) {
          cells[2].textContent = price.toFixed(2);
        }
      }
      
      // Update POS column (position)
      if (cells.length > 3 && trade.position !== null && trade.position !== undefined) {
        cells[3].textContent = trade.position;
      }
      
      // Update buffer
      if (cells.length > 4 && trade.buffer_from_entry !== null) {
        const buffer = trade.buffer_from_entry;
        cells[4].textContent = buffer.toLocaleString(undefined, {maximumFractionDigits: 0});
        
        // Update risk color classes based on probability
        row.classList.remove('ultra-safe', 'safe', 'caution', 'high-risk', 'danger-stop');
        if (trade.current_probability !== null && trade.current_probability !== undefined) {
          const prob = trade.current_probability;
          if (prob >= 95) row.classList.add('ultra-safe');
          else if (prob >= 80) row.classList.add('safe');
          else if (prob >= 50) row.classList.add('caution');
          else if (prob >= 25) row.classList.add('high-risk');
          else row.classList.add('danger-stop');
        }
      }
      
      // Update probability
      if (cells.length > 5 && trade.current_probability !== null) {
        cells[5].textContent = trade.current_probability.toFixed(1);
      }
      
      // Update status-based styling and CLOSE button
      row.classList.remove('closing-trade', 'pending-trade');
      if (trade.status === 'closing') {
        row.classList.add('closing-trade');
      } else if (trade.status === 'pending') {
        row.classList.add('pending-trade');
        // For pending trades, show placeholder values
        cells[2].textContent = "Pending";
        cells[3].textContent = "Pending";
        // Disable close button for pending trades
        const closeSpan = cells[6].querySelector('.price-box');
        if (closeSpan) {
          closeSpan.style.cursor = "not-allowed";
          closeSpan.onclick = null;
          const innerDiv = closeSpan.querySelector('div');
          if (innerDiv) innerDiv.textContent = "Pending";
        }
      } else {
        // Active trade - enable close button
        const closeSpan = cells[6].querySelector('.price-box');
        if (closeSpan) {
          closeSpan.style.cursor = "pointer";
          closeSpan.onclick = () => closeActiveTrade(trade.trade_id, trade.ticket_id);
        }
      }
      
      // Update PnL on close button
      if (cells.length > 6 && trade.current_pnl !== null && trade.current_pnl !== undefined) {
        const closeButton = cells[6].querySelector('.price-box div');
        if (closeButton) {
          const pnl = parseFloat(trade.current_pnl);
          if (!isNaN(pnl)) {
            const pnlText = pnl >= 0 ? `+${pnl.toFixed(2)}` : pnl.toFixed(2);
            closeButton.textContent = pnlText;
            closeButton.style.color = "white";
          } else {
            closeButton.textContent = "Close";
            closeButton.style.color = "white";
          }
        }
      }
    }
  });

  // Add spanner row logic
  if (activeTrades.length === 0) {
    // No active trades - show "No active trades" message
    const spannerRow = document.createElement("tr");
    spannerRow.className = "spanner-row";
    const spannerCell = document.createElement("td");
    spannerCell.colSpan = 7;
    spannerCell.textContent = "No active trades";
    spannerRow.appendChild(spannerCell);
    activeTradeSupervisorTableBody.appendChild(spannerRow);
  } else {
    // There are active trades - add current price spanner row
    // Try to get current BTC price, with fallback
    let currentBTCPrice = typeof getCurrentBTCTickerPrice === 'function' ? getCurrentBTCTickerPrice() : null;
    
    // If we don't have a current price, try to get it from the first trade's strike as a fallback
    if (currentBTCPrice === null || currentBTCPrice === "") {
      if (activeTrades.length > 0 && activeTrades[0].strike) {
        // Use the first trade's strike as a rough estimate
        currentBTCPrice = parseFloat(activeTrades[0].strike.toString().replace(/[\$,]/g, ''));
      }
    }
    
    if (currentBTCPrice !== null && currentBTCPrice !== "" && !isNaN(currentBTCPrice)) {
      const spannerRow = createActiveTradeSupervisorSpannerRow(currentBTCPrice);
      
      // Find the correct position to insert the spanner row
      const allRows = Array.from(activeTradeSupervisorTableBody.children);
      let insertIndex = allRows.length; // default to end
      
      for (let i = 0; i < allRows.length; i++) {
        const row = allRows[i];
        if (row.classList.contains('spanner-row')) continue;
        const strikeCell = row.querySelector('td');
        if (strikeCell) {
          const strike = parseFloat(strikeCell.textContent.replace(/[\$,]/g, ''));
          if (currentBTCPrice < strike) {
            insertIndex = i;
            break;
          }
        }
      }
      
      if (insertIndex < allRows.length) {
        activeTradeSupervisorTableBody.insertBefore(spannerRow, allRows[insertIndex]);
      } else {
        activeTradeSupervisorTableBody.appendChild(spannerRow);
      }
    }
  }

}

// === CLOSE TRADE FUNCTION ===

async function closeActiveTrade(tradeId, ticketId) {
  try {

    
    // Use the centralized closeTrade function from the trade execution controller
    if (typeof window.closeTrade === 'function') {
      // Get current BTC price for sell price
      const currentPrice = typeof getCurrentBTCTickerPrice === 'function' ? getCurrentBTCTickerPrice() : 0.5;

      
      // Create a mock event object since we don't have the actual event
      const mockEvent = {
        target: document.createElement('button'),
        preventDefault: () => {},
        stopPropagation: () => {}
      };
      
      // Call the centralized close trade function - let it handle all notifications
      
      await window.closeTrade(tradeId, currentPrice, mockEvent);
      
    } else {
      console.error('[ACTIVE TRADE SUPERVISOR] Centralized closeTrade function not available');
    }
  } catch (error) {
    console.error(`[ACTIVE TRADE SUPERVISOR] Error closing trade ${tradeId}:`, error);
  }
}



// === AUTO REFRESH SETUP ===

function startActiveTradeSupervisorRefresh() {
  // Initial load
  fetchAndRenderActiveTradeSupervisorTrades();
  
  // Set up periodic refresh with dynamic interval
  function startRefresh() {
    // Clear any existing interval
    if (activeTradeSupervisorRefreshInterval) {
      clearInterval(activeTradeSupervisorRefreshInterval);
    }
    
    // Set interval based on whether we have pending trades
    const interval = hasPendingTrades ? 500 : 1000; // 500ms if pending, 1000ms if not
    activeTradeSupervisorRefreshInterval = setInterval(() => {
      fetchAndRenderActiveTradeSupervisorTrades();
    }, interval);
  }
  
  // Start initial refresh
  startRefresh();
  
  // Also check for pending trades and adjust interval accordingly
  setInterval(() => {
    const currentHasPending = window.activeTradeSupervisorRowsMap.size > 0 && 
      Array.from(window.activeTradeSupervisorRowsMap.values()).some(rowObj => 
        rowObj.tr.classList.contains('pending-trade')
      );
    
    if (currentHasPending !== hasPendingTrades) {
      hasPendingTrades = currentHasPending;
      startRefresh(); // Restart with new interval
    }
  }, 2000); // Check every 2 seconds
}

// === INITIALIZATION ===

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(() => {
    console.log('[ACTIVE TRADE SUPERVISOR] DOM ready, initializing...');
    
    // Check if the table exists
    const table = document.querySelector('#activeTradeSupervisorTable');
    if (!table) {
      console.error('[ACTIVE TRADE SUPERVISOR] Table not found');
      return;
    }
    
    // Initialize the table
    initializeActiveTradeSupervisorTable();
    
    // Start the refresh loop
    startActiveTradeSupervisorRefresh();
    
    console.log('[ACTIVE TRADE SUPERVISOR] Initialization complete');
  }, 500);
});

// Export functions for global access
window.fetchAndRenderActiveTradeSupervisorTrades = fetchAndRenderActiveTradeSupervisorTrades;
window.closeActiveTrade = closeActiveTrade;

// === Spanner Row Helper for Active Trade Supervisor ===
function createActiveTradeSupervisorSpannerRow(currentPrice) {
  const spannerRow = document.createElement("tr");
  spannerRow.className = "spanner-row";
  const spannerTd = document.createElement("td");
  spannerTd.colSpan = 7; // Match the number of columns in active trade supervisor table
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
