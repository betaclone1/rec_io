"""
Centralized configuration management for the trading system.
All agents use this configuration system.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from backend.core.port_config import get_port

class ConfigManager:
    """Centralized configuration management for all trading system agents."""
    
    def __init__(self, config_path: str = "backend/core/config/config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._validate_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    config_data = json.load(f)
                return config_data
            except (json.JSONDecodeError, IOError) as e:
                print(f"⚠️  Warning: Failed to load config from {self.config_path}: {e}")
                print("🔄 Falling back to default configuration...")
                return self._get_default_config()
        return self._get_default_config()
    
    def _validate_config(self) -> None:
        """Validate configuration and fix common issues."""
        try:
            # Validate required sections exist
            required_sections = ["system", "agents", "data"]
            for section in required_sections:
                if section not in self.config:
                    print(f"⚠️  Warning: Missing required config section '{section}', adding defaults...")
                    if section == "system":
                        self.config[section] = {"name": "Trading System", "version": "1.0.0", "environment": "development"}
                    elif section == "agents":
                        self.config[section] = self._get_default_agents_config()
                    elif section == "data":
                        self.config[section] = self._get_default_data_config()
            
            # Validate agent configurations
            agents = self.config.get("agents", {})
            for agent_name, agent_config in agents.items():
                if not isinstance(agent_config, dict):
                    print(f"⚠️  Warning: Invalid agent config for '{agent_name}', using defaults...")
                    agents[agent_name] = self._get_default_agent_config(agent_name)
                else:
                    # Ensure required fields exist
                    if "enabled" not in agent_config:
                        agent_config["enabled"] = True
                    if "port" in agent_config and not isinstance(agent_config["port"], int):
                        try:
                            agent_config["port"] = int(agent_config["port"])
                        except (ValueError, TypeError):
                            print(f"⚠️  Warning: Invalid port for agent '{agent_name}', using default...")
                            agent_config["port"] = self._get_default_port(agent_name)
            
            # Config validation complete (no auto-save to preserve portability)
            
        except Exception as e:
            print(f"❌ Error validating configuration: {e}")
            print("🔄 Using default configuration...")
            self.config = self._get_default_config()
    
    def _get_default_port(self, agent_name: str) -> int:
        """Get default port for an agent using centralized port management."""
        # Legacy config.json agent keys → MASTER_PORT_MANIFEST service names
        manifest_key = {
            "main": "main_app",
            "market_watchdog": "market_watchdog_ws_kalshi",
            "trade_monitor": "main_app",
        }.get(agent_name, agent_name)
        return get_port(manifest_key)
    
    def _get_default_agent_config(self, agent_name: str) -> Dict[str, Any]:
        """Get default configuration for an agent."""
        from backend.util.paths import get_host
        base_config = {"enabled": True, "host": get_host()}
        
        # Add port if it's a service that needs one
        if agent_name in ["main", "trade_manager", "trade_executor", "active_trade_supervisor", "market_watchdog", "trade_monitor"]:
            base_config["port"] = self._get_default_port(agent_name)
        
        # Add specific configurations
        if agent_name == "symbol_watchdog":
            base_config.update({"update_interval": 1.0, "providers": ["coinbase"]})
        elif agent_name == "market_watchdog":
            base_config.update({"update_interval": 2.0, "providers": ["kalshi"]})
        elif agent_name == "account_sync":
            base_config.update({"update_interval": 30.0, "providers": ["kalshi"]})
        
        return base_config
    
    def _get_default_agents_config(self) -> Dict[str, Any]:
        """Get default agents configuration."""
        return {
            "main": self._get_default_agent_config("main"),
            "symbol_watchdog": self._get_default_agent_config("symbol_watchdog"),
            "market_watchdog": self._get_default_agent_config("market_watchdog"),
            "trade_monitor": self._get_default_agent_config("trade_monitor"),
            "trade_manager": self._get_default_agent_config("trade_manager"),
            "trade_executor": self._get_default_agent_config("trade_executor"),
            "active_trade_supervisor": self._get_default_agent_config("active_trade_supervisor"),
            "account_sync": self._get_default_agent_config("account_sync")
        }
    
    def _get_default_data_config(self) -> Dict[str, Any]:
        """Get default data configuration."""
        return {
            "base_path": "backend/data",
            "databases": {
                "prices": "price_history/",
                "accounts": "accounts/",
                "logs": "logs/"
            }
        }
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            "system": {
                "name": "Trading System",
                "version": "1.0.0",
                "environment": "development"
            },
            "agents": self._get_default_agents_config(),
            "data": self._get_default_data_config(),
            "providers": {
                "coinbase": {
                    "base_url": "https://api.coinbase.com/v2",
                    "timeout": 10
                },
                "kalshi": {
                    "base_url": "https://external-api.kalshi.com/trade-api/v2",
                    "timeout": 10,
                    "credentials_path": "backend/data/users/user_0001/credentials/kalshi-credentials",
                    "security_note": "Credentials stored ONLY in user-based location for security"
                }
            },
            "indicators": {
                "momentum": {
                    "enabled": True,
                    "periods": [1, 2, 3, 4, 15, 30],
                    "weights": [0.3, 0.25, 0.2, 0.15, 0.05, 0.05]
                }
            },
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot notation key."""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """Set configuration value by dot notation key."""
        keys = key.split('.')
        config = self.config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def save(self) -> None:
        """Save configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

# Global config instance
config = ConfigManager() 