/**
 * MONITOR HISTORY DISPLAY
 * 
 * Calculates monitor statistics dynamically from raw trade data
 * Aligns with monitor_manager.py for live stats; when ``window.globalPaperMode`` is true,
 * ``test_filter`` trades are included so dashboard tiles match global paper semantics.
 * Populates monitor tiles with calculated values instead of reading from DB
 */

class MonitorHistoryDisplay {
    constructor() {
        this.monitorStats = new Map(); // Cache for calculated stats
        this.tradesData = []; // Raw trades data
        this.monitorsData = []; // Monitor configuration data
        this.isInitialized = false;
        /** Bumps on each refreshFromServer(); stale completions after await fetch are skipped. */
        this._refreshSerial = 0;
        /** Guardrails for expensive full /trades refetches. */
        this._serverRefreshInFlight = false;
        this._serverRefreshPendingTimeFilter = null;
        this._serverRefreshTimer = null;
        this._serverRefreshLastCompletedMs = 0;
        this._serverRefreshMinIntervalMs = 5000;
        
        // Bind methods
        this.init = this.init.bind(this);
        this.calculateMonitorStats = this.calculateMonitorStats.bind(this);
        this.updateMonitorTiles = this.updateMonitorTiles.bind(this);
        this.fetchTradesData = this.fetchTradesData.bind(this);
        this.fetchMonitorsData = this.fetchMonitorsData.bind(this);
        this.refreshFromServer = this.refreshFromServer.bind(this);
    }

    /** True when trade row is a test/UAT trade (same truthiness patterns as dashboard). */
    _tradeRowIsTestFilter(trade) {
        const tf = trade && trade.test_filter;
        return (
            tf === true ||
            tf === 'true' ||
            tf === 1 ||
            tf === '1' ||
            tf === 'True'
        );
    }

    /** Global paper mode: tile aggregates should count test_filter rows too. */
    _includeTestFilterTradesForMonitorTiles() {
        return typeof window !== 'undefined' && window.globalPaperMode === true;
    }

    _tradeIsWin(trade) {
        const w = trade && trade.win_loss;
        if (w === true || w === 1) return true;
        if (w === false || w === 0) return false;
        const u = String(w == null ? '' : w).trim().toUpperCase();
        return u === 'W' || u === 'WIN';
    }

    /** Sort key: newer trades first (id desc, then timestamp desc). */
    _tradeRecencySortKey(trade) {
        if (!trade) return [0, 0];
        const idn = Number(trade.id);
        const idPart = !Number.isNaN(idn) ? idn : 0;
        let ms = 0;
        if (trade.timestamp) {
            const t = new Date(trade.timestamp).getTime();
            if (!Number.isNaN(t)) ms = t;
        } else if (trade.date && trade.time) {
            const ds = String(trade.date).slice(0, 10);
            const tpart = String(trade.time).split('.')[0];
            const t = new Date(`${ds}T${tpart}`).getTime();
            if (!Number.isNaN(t)) ms = t;
        }
        return [idPart, ms];
    }

    /**
     * Consecutive wins from the most recent closed trade in the window (newest first).
     * Stops at the first loss or unknown outcome after counting wins.
     */
    _currentWinStreakInWindow(tradesNewestFirst) {
        if (!tradesNewestFirst || tradesNewestFirst.length === 0) return 0;
        const sorted = [...tradesNewestFirst].sort((a, b) => {
            const [ida, tsa] = this._tradeRecencySortKey(a);
            const [idb, tsb] = this._tradeRecencySortKey(b);
            if (ida !== idb) return idb - ida;
            return tsb - tsa;
        });
        let streak = 0;
        for (const t of sorted) {
            if (this._tradeIsWin(t)) streak += 1;
            else break;
        }
        return streak;
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
            this.tradesData = await recFetchTradesMerged('/trades', {
                cache: 'no-store',
            });
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
            if (!this._includeTestFilterTradesForMonitorTiles() && this._tradeRowIsTestFilter(trade)) {
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
                win_streak: 0,
                win_loss: 0.0,
                ret_pct: 0.0,
                pnl: 0.00
            };
        }

        // Filter trades by time period
        const filteredTrades = this.filterTradesByTime(trades, timeFilter);
        
        // Count total trades (from filtered results)
        const totalTrades = filteredTrades.length;
        const winStreak = this._currentWinStreakInWindow(filteredTrades);
        
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
            win_streak: winStreak,
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
            const v = Number(stats.pnl);
            if (Number.isFinite(v)) {
                const rounded = Math.round(v);
                const neg = rounded < 0;
                const body = Math.abs(rounded).toLocaleString('en-US', {
                    minimumFractionDigits: 0,
                    maximumFractionDigits: 0,
                });
                pnlElement.textContent = (neg ? '-$' : '$') + body;
            }
        }

        const tradesStreakEl = tile.querySelector('.stat-win-streak');
        const tradesBox = tile.querySelector('.th-monitor-trades-box');
        if (tradesStreakEl) {
            tradesStreakEl.textContent = String(stats.trades != null ? stats.trades : 0);
            // Do not overwrite win-streak tooltip from calculated history stats.
            // Tooltip should continue reflecting canonical DB monitor_list.win_streak.
            if (!tradesBox && !tradesStreakEl.hasAttribute('data-win-streak')) {
                tradesStreakEl.setAttribute('data-win-streak', '0');
            }
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
     * Re-slice cached trades for the portfolio chart time window (no network).
     * Call from chart interval buttons (1d / 1w / all, etc.). Keeps tiles in sync with the chart view instantly.
     */
    refresh(timeFilter) {
        if (!timeFilter) {
            console.error('[MONITOR_HISTORY] ERROR: refresh() requires timeFilter parameter');
            return;
        }
        if (!this.isInitialized) {
            console.error('[MONITOR_HISTORY] ERROR: Cannot refresh - not initialized');
            return;
        }
        console.log(`[MONITOR_HISTORY] Recalculating tile stats for time filter: ${timeFilter} (cached trades)...`);
        this.calculateAllMonitorStats(timeFilter);
        this.updateMonitorTiles();
        console.log('[MONITOR_HISTORY] Tile stats updated for view');
    }

    /**
     * Refetch trades + monitor config from the server, then recalculate for timeFilter.
     * Use for db_changes, periodic soft refresh, trading mode switch — not for chart-interval-only changes.
     */
    async refreshFromServer(timeFilter) {
        if (!timeFilter) {
            console.error('[MONITOR_HISTORY] ERROR: refreshFromServer() requires timeFilter parameter');
            return;
        }
        if (!this.isInitialized) {
            console.error('[MONITOR_HISTORY] ERROR: Cannot refreshFromServer - not initialized');
            return;
        }
        if (this._serverRefreshInFlight) {
            // Coalesce bursty triggers (db_changes + periodic poll + manual flows) into one follow-up refresh.
            this._serverRefreshPendingTimeFilter = timeFilter;
            return;
        }
        const nowMs = Date.now();
        const remainingMs =
            this._serverRefreshMinIntervalMs - (nowMs - this._serverRefreshLastCompletedMs);
        if (remainingMs > 0) {
            this._serverRefreshPendingTimeFilter = timeFilter;
            if (!this._serverRefreshTimer) {
                this._serverRefreshTimer = setTimeout(() => {
                    this._serverRefreshTimer = null;
                    const nextTf = this._serverRefreshPendingTimeFilter || timeFilter;
                    this._serverRefreshPendingTimeFilter = null;
                    void this.refreshFromServer(nextTf);
                }, remainingMs);
            }
            return;
        }
        this._serverRefreshInFlight = true;
        const gen = ++this._refreshSerial;
        console.log(`[MONITOR_HISTORY] Server refresh with time filter: ${timeFilter}...`);
        try {
            await this.fetchTradesData();
            await this.fetchMonitorsData();
            if (gen !== this._refreshSerial) {
                console.log('[MONITOR_HISTORY] Server refresh superseded; skipping calculate/update');
                return;
            }
            this.calculateAllMonitorStats(timeFilter);
            this.updateMonitorTiles();
            console.log('[MONITOR_HISTORY] Server refresh complete');
        } finally {
            this._serverRefreshInFlight = false;
            this._serverRefreshLastCompletedMs = Date.now();
            if (this._serverRefreshPendingTimeFilter) {
                const nextTf = this._serverRefreshPendingTimeFilter;
                this._serverRefreshPendingTimeFilter = null;
                void this.refreshFromServer(nextTf);
            }
        }
    }

    /**
     * Get calculated statistics for a specific monitor.
     * Returns undefined when this monitor has no entry (e.g. no closed trades in the fetched
     * trade list, or key mismatch). Callers must fall back to /api/monitors aggregates — do not
     * return a synthetic zero object or dashboard tiles show 0 even when the API has real stats.
     */
    getMonitorStats(monitorName) {
        if (monitorName == null || monitorName === '') {
            return undefined;
        }
        return this.monitorStats.get(monitorName);
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
