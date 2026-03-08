# Trading System Architecture

## Overview

This trading system is built on a modular, agent-based architecture designed for scalability, fault tolerance, and maintainability. The system consists of multiple specialized agents that communicate through a centralized event bus.

## Core Architecture

### Key Components

1. **Main Agent** - Backbone and switchboard operator
2. **Symbol Price Watchdog** - Maintains price data connections
3. **Market Watchdog** - Maintains market data connections  
4. **Trade Monitor** - Main client interface and data visualization
5. **Trade Manager** - Trade clearing house and database management
6. **Trade Executor** - Market execution interface
7. **Account Sync** - Portfolio and account data synchronization

### Core Systems

- **Configuration Management** - Centralized config for all agents
- **Event Bus** - Inter-agent communication system
- **Health Monitoring** - Agent status and system health tracking
- **Data Layer** - Unified data access and storage

## Directory Structure

```
backend/
├── agents/                    # Agent implementations
│   ├── main/                 # Main agent (backbone)
│   ├── symbol_watchdog/      # Price data agent
│   ├── market_watchdog/      # Market data agent
│   ├── trade_monitor/        # UI and visualization agent
│   ├── trade_manager/        # Trade management agent
│   ├── trade_executor/       # Execution agent
│   └── account_sync/         # Account sync agent
├── core/                     # Core system components
│   ├── agent.py             # Base agent class
│   ├── config/              # Configuration management
│   ├── events/              # Event bus system
│   ├── health/              # Health monitoring
│   ├── data/                # Data access layer
│   └── api/                 # API gateway
├── services/                 # Shared services
│   ├── providers/           # External API providers
│   ├── indicators/          # Technical indicators
│   └── strategies/          # Trading strategies
└── data/                    # Data storage
    ├── trade_history/       # Trade database
    ├── price_history/       # Price data
    ├── accounts/           # Account data
    └── logs/               # System logs
```

## Agent Communication

### Event Bus

All agents communicate through a centralized event bus using typed events:

- **Price Events** - Price updates and history
- **Market Events** - Market data and snapshots
- **Trade Events** - Trade creation, updates, execution
- **Account Events** - Balance, position, fill updates
- **System Events** - Agent status and health updates
- **Indicator Events** - Technical indicator updates

### Event Flow Example

1. Symbol Watchdog receives price update
2. Publishes `PRICE_UPDATE` event
3. Trade Monitor subscribes and updates UI
4. Indicators calculate new values
5. Publishes `INDICATOR_UPDATE` events
6. Trade Monitor updates charts and displays

## Configuration

The system uses a centralized configuration system with:

- **Agent-specific configs** - Ports, intervals, providers
- **Provider configs** - API endpoints, credentials
- **Indicator configs** - Calculation parameters
- **Trading configs** - Position sizes, risk limits

## Health Monitoring

Each agent reports its status to the health monitor:

- **Heartbeat tracking** - Regular status updates
- **Error monitoring** - Error count and last error
- **Performance metrics** - Uptime and performance data
- **System health** - Overall system status

## Data Management

### Databases

- **trades.db** - Trade history and active trades
- **price_history/** - Time-series price data
- **accounts/** - Account balances and positions
- **logs/** - System and agent logs

### Data Access

All data access goes through the core data layer for:
- Consistent data formats
- Caching and optimization
- Backup and recovery
- Data validation

## Starting the System

```bash
# Start the entire system
python backend/run_system.py

# Or start individual agents (for development)
python -m backend.agents.main.main_agent
```

## API Endpoints

The main agent provides system-wide APIs:

- `/health` - System health check
- `/system/status` - Overall system status
- `/agents/status` - Individual agent status
- `/events/history` - Event history
- `/config` - Configuration access

## Development

### Adding a New Agent

1. Create agent directory in `backend/agents/`
2. Inherit from `BaseAgent`
3. Implement `initialize()`, `run()`, `cleanup()`
4. Register with `agent_manager`
5. Add configuration in `config.json`

### Adding a New Provider

1. Create provider in `backend/services/providers/`
2. Implement provider interface
3. Add configuration in `config.json`
4. Update relevant agents to use provider

### Adding a New Indicator

1. Create indicator in `backend/services/indicators/`
2. Implement calculation logic
3. Add configuration in `config.json`
4. Subscribe to relevant events
5. Publish indicator updates

## Fault Tolerance

- **Agent isolation** - One agent failure doesn't affect others
- **Event persistence** - Event history for recovery
- **Health monitoring** - Automatic detection of issues
- **Graceful degradation** - System continues with reduced functionality

## Scalability

- **Modular design** - Easy to add new agents
- **Event-driven** - Loose coupling between components
- **Configuration-driven** - Easy to modify behavior
- **Provider abstraction** - Easy to add new data sources

## Future Enhancements

- **WebSocket support** - Real-time data streaming
- **Automated trading** - Strategy execution agents
- **Backtesting** - Historical analysis agents
- **Machine learning** - ML-based indicator agents
- **Multi-market support** - Additional exchange integrations 