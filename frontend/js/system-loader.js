// === SYSTEM LOADER ===
// Coordinates all frontend initialization and ensures everything is ready before displaying UI
// This prevents race conditions and ensures system-agnostic loading

// fetch() has no built-in timeout; use AbortController so requests cannot hang forever.
function fetchWithTimeout(url, options = {}, ms) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), ms);
    return fetch(url, { ...options, signal: controller.signal }).finally(() => clearTimeout(id));
}

class SystemLoader {
    constructor() {
        this.loadingStates = {
            portConfig: false,
            backendServices: false,
            databaseConnections: false,
            frontendAssets: false,
            dataInitialization: false
        };
        this.loadingScreen = this.createLoadingScreen();
        this.progressBar = null;
        this.statusText = null;
        this.retryCount = 0;
        this.maxRetries = 30; // 60 seconds total
    }

    createLoadingScreen() {
        // Remove existing loading screen if present
        const existing = document.getElementById('systemLoadingScreen');
        if (existing) {
            existing.remove();
        }

        const loadingScreen = document.createElement('div');
        loadingScreen.id = 'systemLoadingScreen';
        loadingScreen.className = 'system-loading-screen';
        loadingScreen.innerHTML = `
            <div class="loading-content">
                <img src="/images/rec_logo_1.png" alt="REC.IO" class="loading-logo">
                <div class="loading-title">REC.IO Trading Platform</div>
                <div class="loading-status" id="loadingStatus">Initializing system...</div>
                <div class="loading-progress">
                    <div class="loading-progress-bar" id="loadingProgressBar"></div>
                </div>
                <div class="loading-spinner"></div>
                <div class="loading-details" id="loadingDetails"></div>
            </div>
        `;

        // Add styles
        const style = document.createElement('style');
        style.textContent = `
            .system-loading-screen {
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                background: #1a1a1a;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 9999;
                color: white;
                font-family: 'IBM Plex Sans', sans-serif;
            }
            
            .loading-content {
                display: flex;
                flex-direction: column;
                align-items: center;
                text-align: center;
            }
            
            .loading-logo {
                width: 80px;
                height: 80px;
                margin-bottom: 30px;
            }
            
            .loading-title {
                font-size: 24px;
                font-weight: 600;
                margin-bottom: 20px;
                color: #45d34a;
            }
            
            .loading-status {
                font-size: 16px;
                margin-bottom: 30px;
                text-align: center;
                max-width: 400px;
            }
            
            .loading-progress {
                width: 300px;
                height: 4px;
                background: #333;
                border-radius: 2px;
                overflow: hidden;
                margin-bottom: 20px;
            }
            
            .loading-progress-bar {
                height: 100%;
                background: #45d34a;
                width: 0%;
                transition: width 0.3s ease;
            }
            
            .loading-spinner {
                width: 40px;
                height: 40px;
                border: 3px solid #333;
                border-top: 3px solid #45d34a;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin-bottom: 20px;
            }
            
            .loading-details {
                font-size: 12px;
                color: #888;
                max-width: 400px;
                text-align: center;
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        `;
        document.head.appendChild(style);

        document.body.appendChild(loadingScreen);
        
        this.progressBar = document.getElementById('loadingProgressBar');
        this.statusText = document.getElementById('loadingStatus');
        this.detailsText = document.getElementById('loadingDetails');
        
        return loadingScreen;
    }

    updateProgress(step, total, status, details = '') {
        const progress = (step / total) * 100;
        if (this.progressBar) {
            this.progressBar.style.width = `${progress}%`;
        }
        if (this.statusText) {
            this.statusText.textContent = status;
        }
        if (this.detailsText && details) {
            this.detailsText.textContent = details;
        }
        console.log(`[SYSTEM LOADER] ${status} (${step}/${total})`);
    }

    async initializeSystem() {
        console.log('[SYSTEM LOADER] Starting system initialization...');
        
        try {
            // Step 1: Load port configuration
            this.updateProgress(1, 5, 'Loading port configuration...');
            await this.loadPortConfiguration();
            
            // Step 2: Validate backend services
            this.updateProgress(2, 5, 'Validating backend services...');
            await this.validateBackendServices();
            
            // Step 3: Test database connections
            this.updateProgress(3, 5, 'Testing database connections...');
            await this.testDatabaseConnections();
            
            // Step 4: Load frontend assets
            this.updateProgress(4, 5, 'Loading frontend assets...');
            await this.loadFrontendAssets();
            
            // Step 5: Initialize data
            this.updateProgress(5, 5, 'Initializing data...');
            await this.initializeData();
            
            // All systems ready
            this.updateProgress(5, 5, 'System ready!', 'All services verified and running');
            
            // Wait a moment to show completion
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // Show main interface
            this.showMainInterface();
            
        } catch (error) {
            console.error('[SYSTEM LOADER] Initialization failed:', error);
            this.showErrorState(error.message);
        }
    }

    async loadPortConfiguration() {
        const maxAttempts = 10;
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                const response = await fetchWithTimeout(window.location.origin + '/api/ports', {}, 5000);
                if (response.ok) {
                    const config = await response.json();
                    console.log('[SYSTEM LOADER] Port configuration loaded:', config);
                    this.loadingStates.portConfig = true;
                    return;
                }
            } catch (error) {
                console.log(`[SYSTEM LOADER] Port config attempt ${attempt}/${maxAttempts} failed:`, error.message);
            }
            
            if (attempt < maxAttempts) {
                await new Promise(resolve => setTimeout(resolve, 2000));
            }
        }
        throw new Error('Failed to load port configuration');
    }

    async validateBackendServices() {
        const services = [
            { name: 'Main App', endpoint: '/health' },
            { name: 'Trade Manager', endpoint: '/api/health' },
            { name: 'Active Trade Supervisor', endpoint: '/api/health' },
            { name: 'System Health', endpoint: '/api/system-health' }
        ];

        for (const service of services) {
            let attempts = 0;
            const maxAttempts = 5;
            
            while (attempts < maxAttempts) {
                try {
                    const response = await fetchWithTimeout(service.endpoint, {}, 3000);
                    if (response.ok) {
                        console.log(`[SYSTEM LOADER] ${service.name} validated`);
                        break;
                    }
                } catch (error) {
                    console.log(`[SYSTEM LOADER] ${service.name} attempt ${attempts + 1}/${maxAttempts} failed`);
                }
                
                attempts++;
                if (attempts < maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, 1000));
                }
            }
            
            if (attempts >= maxAttempts) {
                throw new Error(`${service.name} failed to respond`);
            }
        }
        
        this.loadingStates.backendServices = true;
    }

    async testDatabaseConnections() {
        try {
            // Test main database
            const response = await fetchWithTimeout(window.location.origin + '/api/db/health', {}, 5000);
            if (!response.ok) {
                throw new Error('Database health check failed');
            }
            
            const healthData = await response.json();
            if (healthData.status !== 'healthy') {
                throw new Error('Database not healthy');
            }
            
            console.log('[SYSTEM LOADER] Database connections verified');
            this.loadingStates.databaseConnections = true;
            
        } catch (error) {
            throw new Error(`Database connection failed: ${error.message}`);
        }
    }

    async loadFrontendAssets() {
        // Wait for critical frontend assets to load
        const criticalAssets = [
            '/styles/global.css',
            '/js/globals.js',
            '/js/strike-table.js',
            '/js/active-trade-supervisor_panel.js'
        ];

        for (const asset of criticalAssets) {
            try {
                const response = await fetchWithTimeout(asset, { method: 'HEAD' }, 3000);
                if (!response.ok) {
                    throw new Error(`Asset ${asset} not available`);
                }
            } catch (error) {
                throw new Error(`Failed to load ${asset}: ${error.message}`);
            }
        }
        
        console.log('[SYSTEM LOADER] Frontend assets verified');
        this.loadingStates.frontendAssets = true;
    }

    async initializeData() {
        try {
            // Test that data endpoints are responding
            const dataEndpoints = [
                '/api/unified_ttc/btc',
                '/api/postgresql/strike_table/btc',
                '/api/active_trades'
            ];

            for (const endpoint of dataEndpoints) {
                const response = await fetchWithTimeout(endpoint, {}, 5000);
                if (!response.ok) {
                    console.warn(`[SYSTEM LOADER] Data endpoint ${endpoint} not ready yet`);
                }
            }
            
            console.log('[SYSTEM LOADER] Data initialization complete');
            this.loadingStates.dataInitialization = true;
            
        } catch (error) {
            console.warn('[SYSTEM LOADER] Data initialization warning:', error.message);
            // Don't fail on data initialization - some endpoints might not be ready yet
        }
    }

    showMainInterface() {
        console.log('[SYSTEM LOADER] Showing main interface');
        
        // Hide loading screen
        if (this.loadingScreen) {
            this.loadingScreen.style.opacity = '0';
            setTimeout(() => {
                this.loadingScreen.remove();
            }, 500);
        }
        
        // Dispatch event that other modules can listen for
        document.dispatchEvent(new CustomEvent('systemReady'));
        
        // Initialize all frontend modules
        this.initializeFrontendModules();
    }

    showErrorState(errorMessage) {
        if (this.statusText) {
            this.statusText.textContent = 'System initialization failed';
            this.statusText.style.color = '#dc3545';
        }
        if (this.detailsText) {
            this.detailsText.textContent = errorMessage;
            this.detailsText.style.color = '#dc3545';
        }
        
        // Add retry button
        const retryButton = document.createElement('button');
        retryButton.textContent = 'Retry';
        retryButton.className = 'retry-button';
        retryButton.onclick = () => {
            this.retryCount++;
            if (this.retryCount < 3) {
                this.initializeSystem();
            } else {
                this.detailsText.textContent = 'Maximum retries exceeded. Please refresh the page.';
            }
        };
        
        if (this.loadingScreen) {
            this.loadingScreen.querySelector('.loading-content').appendChild(retryButton);
        }
    }

    initializeFrontendModules() {
        // Initialize all frontend modules in the correct order
        console.log('[SYSTEM LOADER] Initializing frontend modules');
        
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                this.startFrontendModules();
            });
        } else {
            this.startFrontendModules();
        }
    }

    startFrontendModules() {
        // Start modules in the correct order to prevent race conditions
        const modules = [
            { name: 'Strike Table', init: () => this.initializeStrikeTable() },
            { name: 'Active Trade Supervisor', init: () => this.initializeActiveTradeSupervisor() },
            { name: 'Live Data', init: () => this.initializeLiveData() }
        ];

        modules.forEach(module => {
            try {
                module.init();
                console.log(`[SYSTEM LOADER] ${module.name} initialized`);
            } catch (error) {
                console.error(`[SYSTEM LOADER] Failed to initialize ${module.name}:`, error);
            }
        });
    }

    initializeStrikeTable() {
        if (typeof window.initializeStrikeTableWhenReady === 'function') {
            window.initializeStrikeTableWhenReady();
        } else if (typeof window.StrikeTable !== 'undefined' && typeof window.StrikeTable.initialize === 'function') {
            window.StrikeTable.initialize();
        }
    }

    initializeActiveTradeSupervisor() {
        console.log('[SYSTEM LOADER] Attempting to initialize Active Trade Supervisor');
        console.log('[SYSTEM LOADER] Available functions:', Object.keys(window).filter(key => key.includes('Active') || key.includes('Trade')));
        
        if (typeof window.initializeActiveTradeSupervisorWhenReady === 'function') {
            console.log('[SYSTEM LOADER] Calling initializeActiveTradeSupervisorWhenReady');
            window.initializeActiveTradeSupervisorWhenReady();
        } else {
            console.error('[SYSTEM LOADER] initializeActiveTradeSupervisorWhenReady function not found');
        }
    }

    initializeLiveData() {
        if (typeof window.initializeLiveDataWhenReady === 'function') {
            window.initializeLiveDataWhenReady();
        }
    }
}

// Global system loader instance
window.systemLoader = new SystemLoader();

// Start system initialization when script loads
window.systemLoader.initializeSystem();
