/**
 * MONITOR HISTORY DISPLAY
 * 
 * Calculates monitor statistics dynamically from raw trade data
 * Performs the same calculations as monitor_manager.py but in frontend
 * Populates monitor tiles with calculated values instead of reading from DB
 */

class MonitorHistoryDisplay {
    constructor() {
        this.monitorStats = new Map(); // Cache for calculated stats
        this.tradesData = []; // Raw trades data
        this.monitorsData = []; // Monitor configuration data
        this.isInitialized = false;
        
        // Bind methods
        this.init = this.init.bind(this);
        this.calculateMonitorStats = this.calculateMonitorStats.bind(this);
        this.updateMonitorTiles = this.updateMonitorTiles.bind(this);
        this.fetchTradesData = this.fetchTradesData.bind(this);
        this.fetchMonitorsData = this.fetchMonitorsData.bind(this);
    }

    /**
     * Initialize the monitor history display system
     * @param {string} timeFilter - REQUIRED time filter ('1d', '1w', '1m', '1y', 'all')
     */
    async init(timeFilter) {
        if (!timeFilter) {
            console.error('[MONITOR_HISTORY] ERROR: init() requires timeFilter parameter. Cannot initialize without portfolio view setting.');
            return;
        }
        
        try {
            console.log(`[MONITOR_HISTORY] Initializing monitor history display with time filter: ${timeFilter}...`);
            
            // Fetch raw data
            await this.fetchTradesData();
            await this.fetchMonitorsData();
            
            // Calculate stats for all monitors with the specified time filter
            this.calculateAllMonitorStats(timeFilter);
            
            // Update monitor tiles with calculated values
            this.updateMonitorTiles();
            
            this.isInitialized = true;
            console.log('[MONITOR_HISTORY] Monitor history display initialized successfully');
            
        } catch (error) {
            console.error('[MONITOR_HISTORY] Error initializing:', error);
        }
    }

    /**
     * Fetch raw trades data from the API
     */
    async fetchTradesData() {
        try {
            const response = await fetch('/trades', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'Cache-Control': 'no-cache'
                }
            });
            
            if (!response.ok) {
                throw new Error(`Failed to fetch trades: ${response.status}`);
            }
            
            this.tradesData = await response.json();
            console.log(`[MONITOR_HISTORY] Fetched ${this.tradesData.length} trades`);
            
        } catch (error) {
            console.error('[MONITOR_HISTORY] Error fetching trades data:', error);
            this.tradesData = [];
        }
    }

    /**
     * Fetch monitor configuration data
     */
    async fetchMonitorsData() {
        try {
            const response = await fetch('/api/monitors', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'Cache-Control': 'no-cache'
                }
            });
            
            if (!response.ok) {
                throw new Error(`Failed to fetch monitors: ${response.status}`);
            }
            
            this.monitorsData = await response.json();
            console.log(`[MONITOR_HISTORY] Fetched ${this.monitorsData.length} monitors`);
            
        } catch (error) {
            console.error('[MONITOR_HISTORY] Error fetching monitors data:', error);
            this.monitorsData = [];
        }
    }

    /**
     * Calculate statistics for all monitors
     * Performs the same calculations as monitor_manager.py
     * @param {string} timeFilter - REQUIRED time filter ('1d', '1w', '1m', '1y', 'all')
     */
    calculateAllMonitorStats(timeFilter) {
        if (!timeFilter) {
            console.error('[MONITOR_HISTORY] ERROR: calculateAllMonitorStats() requires timeFilter parameter');
            return;
        }
        console.log('[MONITOR_HISTORY] Calculating monitor statistics...');
        
        // Clear existing stats
        this.monitorStats.clear();
        
        // Group trades by monitor
        const tradesByMonitor = new Map();
        
        for (const trade of this.tradesData) {
            // Skip test trades (same filter as monitor_manager.py)
            if (trade.test_filter === true) {
                continue;
            }
            
            // Only include closed/settled trades (same filter as monitor_manager.py)
            if (!['closed', 'settled'].includes(trade.status)) {
                continue;
            }
            
            const monitor = trade.monitor;
            if (!monitor) {
                continue;
            }
            
            if (!tradesByMonitor.has(monitor)) {
                tradesByMonitor.set(monitor, []);
            }
            tradesByMonitor.get(monitor).push(trade);
        }
        
        // Calculate stats for each monitor
        for (const [monitor, trades] of tradesByMonitor) {
            const stats = this.calculateMonitorStats(monitor, trades, timeFilter);
            this.monitorStats.set(monitor, stats);
        }
        
        console.log(`[MONITOR_HISTORY] Calculated stats for ${this.monitorStats.size} monitors`);
    }

    /**
     * Filter trades by time period (same logic as portfolio chart)
     * @param {Array} trades - Array of trade objects
     * @param {string} timeFilter - Time filter ('1d', '1w', '1m', '1y', 'all')
     * @returns {Array} Filtered trades array
     */
    filterTradesByTime(trades, timeFilter) {
        if (timeFilter === 'all') {
            return trades;
        }

        const now = new Date();
        let startDate;

        switch (timeFilter) {
            case '1d':
                // Current day starting at 06:00
                startDate = new Date(now);
                startDate.setHours(6, 0, 0, 0);
                break;
            case '1w':
                // Previous 7 days
                startDate = new Date(now);
                startDate.setDate(startDate.getDate() - 7);
                break;
            case '1m':
                // Previous 30 days
                startDate = new Date(now);
                startDate.setDate(startDate.getDate() - 30);
                break;
            case '1y':
                // Previous 365 days
                startDate = new Date(now);
                startDate.setDate(startDate.getDate() - 365);
                break;
            default:
                return trades;
        }

        return trades.filter(trade => {
            if (!trade.timestamp) return false;
            const tradeDate = new Date(trade.timestamp);
            return tradeDate >= startDate;
        });
    }

    /**
     * Calculate statistics for a specific monitor
     * Performs the exact same calculations as monitor_manager.py
     * @param {string} monitor - Monitor ID or name
     * @param {Array} trades - Array of trade objects
     * @param {string} timeFilter - REQUIRED time filter ('1d', '1w', '1m', '1y', 'all')
     */
    calculateMonitorStats(monitor, trades, timeFilter) {
        if (!trades || trades.length === 0) {
            return {
                trades: 0,
                win_loss: 0.0,
                ret_pct: 0.0,
                pnl: 0.00
            };
        }

        // Filter trades by time period
        const filteredTrades = this.filterTradesByTime(trades, timeFilter);
        
        // Count total trades (from filtered results)
        const totalTrades = filteredTrades.length;
        
        // Get monitor strategy to determine if cycle-based calculation is needed
        let strategy = null;
        if (this.monitorsData && this.monitorsData.length > 0) {
            // Extract monitor ID from monitor identifier (e.g., "mon_0001_10033" -> "10033")
            const monitorParts = monitor.split('_');
            const monitorId = monitorParts.length >= 3 ? monitorParts[2] : null;
            
            if (monitorId) {
                const monitorData = this.monitorsData.find(m => String(m.id) === String(monitorId));
                if (monitorData && monitorData.strategy) {
                    strategy = monitorData.strategy;
                }
            }
        }
        
        // Check if this is Momentum Contain or Momentum Breakout
        const isMomentumContain = strategy && strategy.includes('Momentum Contain');
        const isMomentumBreakout = strategy && strategy.includes('Momentum Breakout');
        const isCycleBasedWinLoss = isMomentumContain || isMomentumBreakout;
        
        let winLossRate = 0.0;
        
        if (isCycleBasedWinLoss) {
            // Calculate win/loss rate based on cycles (not individual trades)
            // Group trades by cycle (extract cycle_id from ticker - everything before last hyphen)
            const cyclesMap = new Map();
            
            for (const trade of filteredTrades) {
                if (!trade.ticker) continue;
                
                // Extract cycle_id from ticker (everything before last hyphen)
                let cycleId = trade.ticker;
                const lastHyphenIndex = trade.ticker.lastIndexOf('-');
                if (lastHyphenIndex > 0) {
                    cycleId = trade.ticker.substring(0, lastHyphenIndex);
                }
                
                if (!cyclesMap.has(cycleId)) {
                    cyclesMap.set(cycleId, []);
                }
                cyclesMap.get(cycleId).push(trade);
            }
            
            // Count winning cycles vs losing cycles
            let winningCycles = 0;
            let totalCycles = 0;
            
            for (const [cycleId, cycleTrades] of cyclesMap) {
                totalCycles++;
                // Check if ANY trade in this cycle is a loss
                const hasLoss = cycleTrades.some(trade => trade.win_loss === 'L');
                if (!hasLoss) {
                    // All wins in this cycle
                    winningCycles++;
                }
            }
            
            // Calculate win/loss rate based on cycles
            winLossRate = totalCycles > 0 ? Math.round((winningCycles / totalCycles) * 100 * 10) / 10 : 0.0;
        } else {
            // Original trade-based calculation for other strategies
            // Count wins and losses
            let wins = 0;
            let losses = 0;
            
            for (const trade of filteredTrades) {
                if (trade.win_loss === 'W') {
                    wins++;
                } else if (trade.win_loss === 'L') {
                    losses++;
                }
            }
            
            // Calculate win/loss rate (same as monitor_manager.py)
            winLossRate = totalTrades > 0 ? Math.round((wins / totalTrades) * 100 * 10) / 10 : 0.0;
        }
        
        // Calculate return percentage (sum of all ret_pct values - same as monitor_manager.py)
        let totalRetPct = 0;
        for (const trade of filteredTrades) {
            if (trade.ret_pct !== null && trade.ret_pct !== undefined && trade.ret_pct !== '') {
                const retPct = Number(trade.ret_pct);
                if (!isNaN(retPct)) {
                    totalRetPct += retPct;
                }
            }
        }
        
        // Calculate total PnL (sum of all PnL values - same as monitor_manager.py)
        let totalPnl = 0;
        for (const trade of filteredTrades) {
            if (trade.pnl !== null && trade.pnl !== undefined && trade.pnl !== '') {
                const pnl = Number(trade.pnl);
                if (!isNaN(pnl)) {
                    totalPnl += pnl;
                }
            }
        }
        
        return {
            trades: totalTrades,
            win_loss: winLossRate,
            ret_pct: Math.round(totalRetPct * 10) / 10, // Round to 1 decimal place
            pnl: Math.round(totalPnl * 100) / 100 // Round to 2 decimal places
        };
    }

    /**
     * Update monitor tiles with calculated statistics
     * Overrides the database values with calculated values
     */
    updateMonitorTiles() {
        console.log('[MONITOR_HISTORY] Updating monitor tiles with calculated statistics...');
        
        // Find all monitor tiles on the page
        const monitorTiles = document.querySelectorAll('.monitor-tile, .monitor-card, [data-monitor-id]');
        
        for (const tile of monitorTiles) {
            const monitorId = tile.getAttribute('data-monitor-id') || 
                             tile.getAttribute('id') || 
                             this.extractMonitorIdFromTile(tile);
            
            if (!monitorId) {
                continue;
            }
            
            // Find the monitor name/identifier for this tile
            const monitorName = this.findMonitorNameForTile(tile, monitorId);
            if (!monitorName) {
                continue;
            }
            
            // Get calculated stats for this monitor
            const stats = this.monitorStats.get(monitorName);
            if (!stats) {
                continue;
            }
            
            // Update the tile with calculated values
            this.updateTileWithStats(tile, stats);
        }
        
        console.log(`[MONITOR_HISTORY] Updated ${monitorTiles.length} monitor tiles`);
    }

    /**
     * Extract monitor ID from a tile element
     */
    extractMonitorIdFromTile(tile) {
        // Try various ways to extract monitor ID
        const id = tile.getAttribute('id');
        const dataId = tile.getAttribute('data-monitor-id');
        const className = tile.className;
        
        // Look for patterns like "monitor-10001" or "MON_0001_10001"
        const idMatch = (id || dataId || className).match(/(?:monitor-|MON_|mon_)(\d+)/i);
        return idMatch ? idMatch[1] : null;
    }

    /**
     * Find the monitor name/identifier for a tile
     */
    findMonitorNameForTile(tile, monitorId) {
        // Try to find monitor name in the tile's data attributes or text content
        const monitorName = tile.getAttribute('data-monitor-name') || 
                           tile.getAttribute('data-monitor') ||
                           this.extractMonitorNameFromContent(tile);
        
        if (monitorName) {
            return monitorName;
        }
        
        // Fallback: construct monitor name from ID
        // This assumes the monitor ID format and user number
        return `mon_${window.recSessionUserSlot()}_${monitorId}`;
    }

    /**
     * Extract monitor name from tile content
     */
    extractMonitorNameFromContent(tile) {
        const textContent = tile.textContent || '';
        const nameMatch = textContent.match(/mon_\d+_\d+/i);
        return nameMatch ? nameMatch[0] : null;
    }

    /**
     * Update a tile with calculated statistics
     */
    updateTileWithStats(tile, stats) {
        // Find and update trades count
        const tradesElement = tile.querySelector('.trades-count, .stat-trades, [data-stat="trades"]');
        if (tradesElement) {
            tradesElement.textContent = stats.trades;
        }
        
        // Find and update win/loss rate
        const winLossElement = tile.querySelector('.win-loss-rate, .stat-win-loss, [data-stat="win_loss"]');
        if (winLossElement) {
            winLossElement.textContent = `${stats.win_loss}%`;
        }
        
        // Find and update return percentage
        const retPctElement = tile.querySelector('.ret-pct, .stat-ret-pct, [data-stat="ret_pct"]');
        if (retPctElement) {
            retPctElement.textContent = `${stats.ret_pct}%`;
        }
        
        // Find and update PnL
        const pnlElement = tile.querySelector('.pnl, .stat-pnl, [data-stat="pnl"]');
        if (pnlElement) {
            const pnlValue = Math.round(stats.pnl);
            const pnlFormatted = pnlValue >= 0 ? `$${pnlValue}` : `-$${Math.abs(pnlValue)}`;
            pnlElement.textContent = pnlFormatted;
        }
        
        // Visual indicators removed - no need to show that values are calculated
    }

    /**
     * Add visual indicator that values are calculated (not from DB)
     */
    addCalculatedIndicator(tile) {
        // Add a small indicator that these are calculated values
        const indicator = document.createElement('div');
        indicator.className = 'calculated-stats-indicator';
        indicator.textContent = '📊';
        indicator.title = 'Statistics calculated from trade data';
        indicator.style.cssText = `
            position: absolute;
            top: 5px;
            right: 5px;
            font-size: 12px;
            opacity: 0.7;
            cursor: help;
        `;
        
        // Only add if not already present
        if (!tile.querySelector('.calculated-stats-indicator')) {
            tile.style.position = 'relative';
            tile.appendChild(indicator);
        }
    }

    /**
     * Refresh statistics (useful for real-time updates)
     * @param {string} timeFilter - REQUIRED time filter ('1d', '1w', '1m', '1y', 'all')
     */
    async refresh(timeFilter) {
        if (!timeFilter) {
            console.error('[MONITOR_HISTORY] ERROR: refresh() requires timeFilter parameter');
            return;
        }
        
        if (!this.isInitialized) {
            console.error('[MONITOR_HISTORY] ERROR: Cannot refresh - not initialized');
            return;
        }
        
        console.log(`[MONITOR_HISTORY] Refreshing monitor statistics with time filter: ${timeFilter}...`);
        
        // Recalculate stats with time filter
        this.calculateAllMonitorStats(timeFilter);
        
        // Update tiles
        this.updateMonitorTiles();
        
        console.log('[MONITOR_HISTORY] Monitor statistics refreshed');
    }

    /**
     * Get calculated statistics for a specific monitor
     */
    getMonitorStats(monitorName) {
        return this.monitorStats.get(monitorName) || {
            trades: 0,
            win_loss: 0.0,
            ret_pct: 0.0,
            pnl: 0.00
        };
    }

    /**
     * Get all calculated statistics
     */
    getAllStats() {
        return Object.fromEntries(this.monitorStats);
    }
}

// Global instance
window.monitorHistoryDisplay = new MonitorHistoryDisplay();

// Auto-initialization removed - let the dashboard control when to initialize
// The dashboard will call window.monitorHistoryDisplay.init() after preferences are loaded

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MonitorHistoryDisplay;
}
