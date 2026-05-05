/**
 * MONITOR HISTORY DISPLAY
 *
 * Preferred path: ``performance_rollups_snapshot.tiles_matrix`` (``GET /api/dashboard/performance-snapshot``
 * on load, then /ws/db_changes). Live + paper + test are combined server-side; independent of the LIVE/PAPER
 * strip toggle. Legacy dashboards without ``window.__dashboardPerformanceRedisRequired`` may fall back to
 * ``GET /api/performance/monitor-tiles``. When Redis is required (dashboard_NEW), there is no HTTP fallback.
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
        /** Bumps on rollup tile reload paths; stale async completions skip ``updateMonitorTiles`` (avoids interleaved ``clear``/paint races). */
        this._rollupTilesReloadGen = 0;
        
        // Bind methods
        this.init = this.init.bind(this);
        this.calculateMonitorStats = this.calculateMonitorStats.bind(this);
        this.updateMonitorTiles = this.updateMonitorTiles.bind(this);
        this.fetchTradesData = this.fetchTradesData.bind(this);
        this.fetchMonitorsData = this.fetchMonitorsData.bind(this);
        this.refreshFromServer = this.refreshFromServer.bind(this);
        this.fetchMonitorTilesFromRollups = this.fetchMonitorTilesFromRollups.bind(this);
        this.applyTilesFromHydratedMatrix = this.applyTilesFromHydratedMatrix.bind(this);
        this.applyRollupTilesFromCacheSync = this.applyRollupTilesFromCacheSync.bind(this);
    }

    /** Match dashboard TD/PREV toggle (``window.__dashboardPerformanceRollupView``). */
    _dashboardRollupViewParam() {
        if (typeof window !== 'undefined' && window.__dashboardPerformanceRollupView === 'prev') {
            return 'prev';
        }
        return 'td';
    }

    /** False on dashboard_NEW / mobile_NEW: never call ``/api/performance/monitor-tiles``. */
    _monitorTilesHttpFallbackAllowed() {
        return !(typeof window !== 'undefined' && window.__dashboardPerformanceRedisRequired === true);
    }

    /**
     * Synchronously repopulate ``monitorStats`` from in-memory ``tiles_matrix`` and paint tiles.
     * Use when TD/PREV or chart window changes so tiles do not wait on portfolio HTTP or race async ``refresh``.
     * @returns {boolean} true if the matrix had data for this period (paint may be skipped if superseded by a newer gen).
     */
    applyRollupTilesFromCacheSync(timeFilter) {
        if (!this.isInitialized || !timeFilter) {
            return false;
        }
        const gen = ++this._rollupTilesReloadGen;
        if (!this.applyTilesFromHydratedMatrix(timeFilter)) {
            return false;
        }
        if (gen !== this._rollupTilesReloadGen) {
            return true;
        }
        this.updateMonitorTiles();
        return true;
    }

    /**
     * Apply tile metrics from ``window.__perfRollupsTilesMatrix`` (period × td/prev), if present.
     * @param {string} period
     * @returns {boolean} true if matrix had data for this period
     */
    applyTilesFromHydratedMatrix(period) {
        const m = typeof window !== 'undefined' ? window.__perfRollupsTilesMatrix : null;
        if (!m || typeof m !== 'object') return false;
        const p = String(period || 'all').toLowerCase();
        const bucket = m[p];
        if (!bucket || typeof bucket !== 'object') return false;
        const rv = this._dashboardRollupViewParam();
        const tiles = bucket[rv];
        if (!Array.isArray(tiles)) return false;
        this.monitorStats.clear();
        for (const t of tiles) {
            if (!t || !t.id) continue;
            this.monitorStats.set(t.id, {
                trades: t.trades,
                win_streak: 0,
                win_loss: t.win_loss,
                ret_pct: t.ret_pct,
                pnl: t.pnl,
            });
        }
        console.log(`[MONITOR_HISTORY] tiles_matrix (${p}, ${rv}): ${tiles.length} monitors`);
        return true;
    }

    /**
     * Load per-monitor tile metrics from PostgreSQL rollups (``performance_monitors``).
     * @param {string} period - '1d' | '1w' | '1m' | '1y' | 'all'
     */
    async fetchMonitorTilesFromRollups(period) {
        const p = period || 'all';
        const rv = this._dashboardRollupViewParam();
        const u = new URL('/api/performance/monitor-tiles', window.location.origin);
        u.searchParams.set('period', p);
        u.searchParams.set('rollup_view', rv);
        const res = await fetch(u.pathname + u.search, {
            method: 'GET',
            headers: { 'Cache-Control': 'no-cache' },
            cache: 'no-store',
        });
        if (!res.ok) {
            throw new Error(`monitor-tiles HTTP ${res.status}`);
        }
        const data = await res.json();
        if (!data || data.status !== 'ok' || !Array.isArray(data.tiles)) {
            throw new Error((data && data.message) ? data.message : 'monitor-tiles invalid payload');
        }
        this.monitorStats.clear();
        for (const t of data.tiles) {
            if (!t || !t.id) continue;
            this.monitorStats.set(t.id, {
                trades: t.trades,
                win_streak: 0,
                win_loss: t.win_loss,
                ret_pct: t.ret_pct,
                pnl: t.pnl,
            });
        }
        console.log(`[MONITOR_HISTORY] Rollup tiles (${p}, ${rv}): ${data.tiles.length} monitors`);
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

    /** Monitor tiles always include test_filter (UAT) rows alongside live and paper. */
    _includeTestFilterTradesForMonitorTiles() {
        return true;
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

            if (!this.applyTilesFromHydratedMatrix(timeFilter)) {
                if (this._monitorTilesHttpFallbackAllowed()) {
                    await this.fetchMonitorTilesFromRollups(timeFilter);
                } else {
                    console.error(
                        '[MONITOR_HISTORY] tiles_matrix required but missing; skipping HTTP monitor-tiles (Redis-only dashboard)',
                    );
                    this.monitorStats.clear();
                }
            }
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

    /** Eastern calendar YYYY-MM-DD for "now" in America/New_York (matches backend chart windows). */
    _easternYmdNow() {
        return new Date().toLocaleString('sv-SE', { timeZone: 'America/New_York' }).slice(0, 10);
    }

    _ymdAddDays(ymd, deltaDays) {
        const parts = ymd.split('-').map(Number);
        const ms = Date.UTC(parts[0], parts[1] - 1, parts[2]) + deltaDays * 86400000;
        const nd = new Date(ms);
        const y = nd.getUTCFullYear();
        const mo = String(nd.getUTCMonth() + 1).padStart(2, '0');
        const d = String(nd.getUTCDate()).padStart(2, '0');
        return `${y}-${mo}-${d}`;
    }

    _easternSundayYmd() {
        const ymd = this._easternYmdNow();
        const short = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short' }).format(new Date());
        const idx = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[short];
        if (idx === undefined) return ymd;
        return this._ymdAddDays(ymd, -idx);
    }

    _easternMonthFirstYmd() {
        const ymd = this._easternYmdNow();
        const y = ymd.slice(0, 4);
        const mo = ymd.slice(5, 7);
        return `${y}-${mo}-01`;
    }

    _easternYearFirstYmd() {
        return this._easternYmdNow().slice(0, 4) + '-01-01';
    }

    _tradeDateYmd(trade) {
        if (!trade || trade.date == null) return '';
        return String(trade.date).trim().slice(0, 10);
    }

    _tradeCloseMs(trade) {
        if (!trade) return NaN;
        if (trade.closed_at) {
            const t = Date.parse(trade.closed_at);
            if (!Number.isNaN(t)) return t;
        }
        if (trade.timestamp) {
            const t = Date.parse(trade.timestamp);
            if (!Number.isNaN(t)) return t;
        }
        if (trade.date && trade.time) {
            const ds = String(trade.date).slice(0, 10);
            const tpart = String(trade.time).split('.')[0];
            const t = Date.parse(`${ds}T${tpart}`);
            if (!Number.isNaN(t)) return t;
        }
        const ds = this._tradeDateYmd(trade);
        if (ds) {
            const t = Date.parse(`${ds}T12:00:00`);
            if (!Number.isNaN(t)) return t;
        }
        return NaN;
    }

    _rollupViewMode() {
        if (typeof window !== 'undefined' && window.__dashboardPerformanceRollupView === 'prev') {
            return 'prev';
        }
        return 'td';
    }

    /**
     * Filter trades by time period (aligned with portfolio / PnL chart rollup_view).
     * @param {Array} trades - Array of trade objects
     * @param {string} timeFilter - Time filter ('1d', '1w', '1m', '1y', 'all')
     * @returns {Array} Filtered trades array
     */
    filterTradesByTime(trades, timeFilter) {
        const rv = this._rollupViewMode();
        if (timeFilter === 'all') {
            const today = this._easternYmdNow();
            const lo = '2020-01-01';
            if (rv === 'td') {
                return trades.filter(trade => {
                    const ymd = this._tradeDateYmd(trade);
                    return ymd && ymd >= lo && ymd <= today;
                });
            }
            const startMs = Date.UTC(2020, 0, 1);
            return trades.filter(trade => {
                const t = this._tradeCloseMs(trade);
                return !Number.isNaN(t) && t >= startMs;
            });
        }

        if (rv === 'td') {
            const today = this._easternYmdNow();
            let lo = today;
            let hi = today;
            switch (timeFilter) {
                case '1d':
                    lo = hi = today;
                    break;
                case '1w':
                    lo = this._easternSundayYmd();
                    hi = today;
                    break;
                case '1m':
                    lo = this._easternMonthFirstYmd();
                    hi = today;
                    break;
                case '1y':
                    lo = this._easternYearFirstYmd();
                    hi = today;
                    break;
                default:
                    return trades;
            }
            return trades.filter(trade => {
                const ymd = this._tradeDateYmd(trade);
                return ymd && ymd >= lo && ymd <= hi;
            });
        }

        const nowMs = Date.now();
        let startMs;
        switch (timeFilter) {
            case '1d':
                startMs = nowMs - 24 * 3600000;
                break;
            case '1w':
                startMs = nowMs - 7 * 24 * 3600000;
                break;
            case '1m':
                startMs = nowMs - 30 * 24 * 3600000;
                break;
            case '1y':
                startMs = nowMs - 365 * 24 * 3600000;
                break;
            default:
                return trades;
        }

        return trades.filter(trade => {
            const t = this._tradeCloseMs(trade);
            return !Number.isNaN(t) && t >= startMs;
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
        console.log('[MONITOR_HISTORY] Updating monitor tiles from rollup stats...');
        
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
     * Refetch rollup tile stats for the portfolio chart time window (1d / 1w / …).
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
        console.log(`[MONITOR_HISTORY] Reloading rollup tiles for time filter: ${timeFilter}...`);
        void this._reloadTilesFromRollupsAsync(timeFilter);
    }

    async _reloadTilesFromRollupsAsync(timeFilter) {
        const gen = ++this._rollupTilesReloadGen;
        try {
            if (this.applyTilesFromHydratedMatrix(timeFilter)) {
                if (gen !== this._rollupTilesReloadGen) {
                    return;
                }
                this.updateMonitorTiles();
                console.log('[MONITOR_HISTORY] Tile stats updated from tiles_matrix');
                return;
            }
            if (this._monitorTilesHttpFallbackAllowed()) {
                await this.fetchMonitorTilesFromRollups(timeFilter);
                if (gen !== this._rollupTilesReloadGen) {
                    return;
                }
                this.updateMonitorTiles();
                console.log('[MONITOR_HISTORY] Tile stats updated from rollups');
            } else {
                console.error(
                    '[MONITOR_HISTORY] tiles_matrix required but missing; skipping HTTP monitor-tiles (Redis-only dashboard)',
                );
                this.monitorStats.clear();
                if (gen !== this._rollupTilesReloadGen) {
                    return;
                }
                this.updateMonitorTiles();
            }
        } catch (e) {
            console.error('[MONITOR_HISTORY] Rollup tile refresh failed:', e);
        }
    }

    /**
     * Refetch rollup tile stats from the server (debounced). Use after db_changes, soft poll, mode switch.
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
        const rg = ++this._rollupTilesReloadGen;
        console.log(`[MONITOR_HISTORY] Server refresh with time filter: ${timeFilter}...`);
        try {
            let updated = false;
            if (this.applyTilesFromHydratedMatrix(timeFilter)) {
                updated = true;
            } else if (this._monitorTilesHttpFallbackAllowed()) {
                await this.fetchMonitorTilesFromRollups(timeFilter);
                updated = true;
            } else {
                console.error(
                    '[MONITOR_HISTORY] tiles_matrix required but missing; skipping HTTP monitor-tiles (Redis-only dashboard)',
                );
                this.monitorStats.clear();
                updated = true;
            }
            if (gen !== this._refreshSerial) {
                console.log('[MONITOR_HISTORY] Server refresh superseded; skipping tile update');
                return;
            }
            if (rg !== this._rollupTilesReloadGen) {
                console.log('[MONITOR_HISTORY] Server refresh stale vs rollup tile gen; skipping tile update');
                return;
            }
            if (updated) {
                this.updateMonitorTiles();
                console.log('[MONITOR_HISTORY] Server refresh complete');
            }
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
     * Get tile stats for a monitor id (e.g. ``mon_0001_10002``) from the last rollup load.
     * Undefined if the monitor has no row in ``performance_monitors`` yet — callers fall back to /api/monitors.
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
