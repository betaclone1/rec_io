// UNIVERSAL CENTRALIZED PORT SYSTEM
// Load service configuration from centralized port system

let serviceConfig = {};

// Load port configuration from centralized system
async function loadPortConfig() {
    try {
        const response = await fetch(window.location.origin + '/api/ports');
        if (response.ok) {
            const config = await response.json();
            // Use the server hostname from the config, not the browser hostname
            const host = config.host || window.location.hostname;
            serviceConfig = {
                mainApp: { port: config.ports.main_app, host: host },
                tradeManager: { port: config.ports.trade_manager, host: host },
                tradeExecutor: { port: config.ports.trade_executor, host: host },
                activeTradeSupervisor: { port: config.ports.active_trade_supervisor, host: host }
            };
          
        } else {
            console.error('[GLOBALS] Failed to load port config - system cannot function without centralized configuration');
            throw new Error('Centralized port configuration is required');
        }
    } catch (error) {
        console.error('[GLOBALS] Critical error loading port config:', error);
        throw new Error('System cannot start without centralized port configuration');
    }
}

// Initialize port configuration
loadPortConfig().catch(error => {
    console.error('[GLOBALS] Failed to initialize port configuration:', error);
    // Don't set any fallback values - let the system fail properly
});

// Helper functions for getting service URLs
function getMainAppUrl(endpoint = '') {
    if (!serviceConfig.mainApp) {
        throw new Error('Port configuration not loaded - system cannot function');
    }
    return `${window.location.protocol}//${serviceConfig.mainApp.host}:${serviceConfig.mainApp.port}${endpoint}`;
}

function getTradeManagerUrl(endpoint = '') {
    if (!serviceConfig.tradeManager) {
        throw new Error('Port configuration not loaded - system cannot function');
    }
    return `${window.location.protocol}//${serviceConfig.tradeManager.host}:${serviceConfig.tradeManager.port}${endpoint}`;
}

function getTradeExecutorUrl(endpoint = '') {
    if (!serviceConfig.tradeExecutor) {
        throw new Error('Port configuration not loaded - system cannot function');
    }
    return `${window.location.protocol}//${serviceConfig.tradeExecutor.host}:${serviceConfig.tradeExecutor.port}${endpoint}`;
}

function getActiveTradeSupervisorUrl(endpoint = '') {
    if (!serviceConfig.activeTradeSupervisor) {
        throw new Error('Port configuration not loaded - system cannot function');
    }
    return `${window.location.protocol}//${serviceConfig.activeTradeSupervisor.host}:${serviceConfig.activeTradeSupervisor.port}${endpoint}`;
}

/**
 * Format symbol_open / symbol_close for trade tables.
 * SOL/XRP: show full DB precision (string passthrough or up to 5 fraction digits, grouped integer part).
 * Other symbols (e.g. BTC, ETH): whole dollars with grouping (legacy behavior).
 */
function formatTradeSymbolSpot(symbol, rawValue) {
    if (rawValue === null || rawValue === undefined || rawValue === '') return '';
    const sym = (symbol || '').toString().trim().toUpperCase();
    const altCoin = sym === 'SOL' || sym === 'XRP';
    if (altCoin) {
        if (typeof rawValue === 'string') {
            const t = rawValue.trim();
            if (t === '') return '';
            return t.startsWith('$') ? t : '$' + t;
        }
        const n = Number(rawValue);
        if (Number.isNaN(n)) return '';
        return '$' + n.toLocaleString('en-US', {
            minimumFractionDigits: 0,
            maximumFractionDigits: 5,
            useGrouping: true
        });
    }
    const n = Number(rawValue);
    if (Number.isNaN(n)) return '';
    return '$' + Math.round(n).toLocaleString('en-US');
}
