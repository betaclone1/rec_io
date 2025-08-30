#!/usr/bin/env python3
"""
MONITOR MANAGER - Core Monitor Management System
Foundation for comprehensive monitor state management, database synchronization,
and frontend coordination across all monitor components.

This is the starting point - will expand to handle:
- All monitor settings and preferences
- Trade state management
- Real-time frontend synchronization
- Database consistency across all monitor tables
- Event-driven updates for all monitor components
- Cross-service coordination
- Monitor lifecycle management
"""

import psycopg2
import json
import requests
from datetime import datetime
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify
from backend.core.unified_config import UnifiedConfigManager
from backend.core.port_config import get_port

app = Flask(__name__)

class MonitorManager:
    def __init__(self):
        self.unified_config = UnifiedConfigManager()
        self.db_config = self.unified_config.get_database_config()
        self.service_name = "monitor_manager"
        
        # Foundation for future expansion
        self.active_monitors = {}  # Will track all active monitors
        self.monitor_states = {}   # Will track state of all monitor components
        self.frontend_connections = set()  # Will track frontend connections
        
    def get_database_connection(self):
        """Get database connection - foundation for all DB operations"""
        # Convert config to psycopg2 format
        psycopg2_config = self.db_config.copy()
        if 'name' in psycopg2_config:
            psycopg2_config['database'] = psycopg2_config.pop('name')
        return psycopg2.connect(**psycopg2_config)
    
    def log_event(self, event_type: str, message: str, data: Optional[Dict] = None):
        """Centralized logging for monitor manager events"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{self.service_name.upper()}] {event_type}: {message}"
        if data:
            log_entry += f" | Data: {json.dumps(data)}"
        print(log_entry)
    
    # === CORE FUNCTIONALITY (Starting Point) ===
    
    def handle_bankroll_update(self) -> Dict[str, Any]:
        """
        Handle bankroll update notification from kalshi_account_sync
        This is the starting point - will expand to handle all monitor updates
        """
        try:
            self.log_event("BANKROLL_UPDATE", "Processing bankroll update notification")
            
            # Update total_position calculation
            result = self.update_total_position()
            
            # Push frontend updates
            self.push_frontend_updates()
            
            self.log_event("BANKROLL_UPDATE", "Bankroll update processed successfully", result)
            return result
            
        except Exception as e:
            self.log_event("ERROR", f"Bankroll update failed: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def update_total_position(self) -> Dict[str, Any]:
        """
        Update total_position in trade_preferences based on current bankroll
        Foundation for comprehensive position management
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            # Get current bankroll
            with conn.cursor() as cursor:
                # First check what's in the table
                cursor.execute("SELECT id, bankroll_current FROM users.account_balance_0001 ORDER BY timestamp DESC LIMIT 5")
                all_results = cursor.fetchall()
                if not all_results:
                    return {"status": "error", "message": "No bankroll data found in table"}
                
                # Get the most recent bankroll
                cursor.execute("SELECT bankroll_current FROM users.account_balance_0001 ORDER BY timestamp DESC LIMIT 1")
                bankroll_result = cursor.fetchone()
                
                if not bankroll_result:
                    return {"status": "error", "message": "No bankroll data found"}
                
                if bankroll_result[0] is None:
                    return {"status": "error", "message": "Bankroll value is None"}
                
                bankroll = float(bankroll_result[0]) / 100
                
                # Get current position settings
                cursor.execute("""
                    SELECT position_size, position_type, multiplier 
                    FROM users.trade_preferences_0001 WHERE id = 1
                """)
                pos_result = cursor.fetchone()
                
                if not pos_result:
                    return {"status": "error", "message": "No position settings found"}
                
                position_size, position_type, multiplier = pos_result
                
                if position_size is None or position_type is None or multiplier is None:
                    return {"status": "error", "message": f"Position settings contain None values: size={position_size}, type={position_type}, multiplier={multiplier}"}
                
                multiplier = float(multiplier)
                
                # Calculate new total_position
                if position_type == 'percent':
                    percentage_of_bankroll = (position_size * bankroll) / 100
                    new_total_position = int(round(percentage_of_bankroll * multiplier))
                else:
                    new_total_position = int(position_size * multiplier)
                
                new_total_position = max(1, new_total_position)
                
                # Update total_position in database
                cursor.execute("""
                    UPDATE users.trade_preferences_0001 
                    SET total_position = %s, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = 1
                """, (new_total_position,))
                
                conn.commit()
                
                result = {
                    "status": "success",
                    "total_position": new_total_position,
                    "bankroll": bankroll,
                    "position_size": position_size,
                    "position_type": position_type,
                    "multiplier": multiplier
                }
                
                self.log_event("POSITION_UPDATE", f"Total position updated: {new_total_position}", result)
                return result
                
        except Exception as e:
            self.log_event("ERROR", f"Position update failed: {str(e)}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()
    
    def push_frontend_updates(self):
        """
        Push updates to frontend components
        Foundation for comprehensive frontend synchronization
        """
        conn = None
        try:
            # Get latest data for frontend update
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT total_position FROM users.trade_preferences_0001 WHERE id = 1")
                result = cursor.fetchone()
                total_position = result[0] if result else 1
                
                cursor.execute("SELECT bankroll_current FROM users.account_balance_0001 ORDER BY timestamp DESC LIMIT 1")
                result = cursor.fetchone()
                bankroll = float(result[0]) / 100 if result and result[0] is not None else 0
            
            # Prepare update data - foundation for comprehensive updates
            update_data = {
                'total_position': total_position,
                'bankroll_current': bankroll,
                'timestamp': datetime.now().isoformat(),
                'source': self.service_name
            }
            
            # Send to main app for frontend broadcast
            response = requests.post(
                "http://localhost:8000/api/broadcast_preferences_update",
                json=update_data,
                timeout=5
            )
            
            if response.ok:
                self.log_event("FRONTEND_UPDATE", f"Frontend update sent: total_position={total_position}, bankroll=${bankroll:,.2f}")
            else:
                self.log_event("ERROR", f"Frontend update failed: {response.status_code}")
                
        except Exception as e:
            self.log_event("ERROR", f"Frontend update failed: {str(e)}")
        finally:
            if conn:
                conn.close()
    
    # === FUTURE EXPANSION FOUNDATION ===
    
    def handle_monitor_settings_update(self, monitor_id: str, settings: Dict[str, Any]):
        """Future: Handle updates to any monitor settings"""
        # TODO: Implement comprehensive monitor settings management
        pass
    
    def handle_trade_state_update(self, trade_id: str, state: Dict[str, Any]):
        """Future: Handle trade state changes"""
        # TODO: Implement trade state management
        pass
    
    def handle_frontend_connection(self, connection_id: str):
        """Future: Handle frontend connection management"""
        # TODO: Implement frontend connection tracking
        pass
    
    def sync_all_monitor_states(self):
        """Future: Synchronize all monitor states across the system"""
        # TODO: Implement comprehensive state synchronization
        pass
    
    def validate_monitor_consistency(self):
        """Future: Validate consistency across all monitor components"""
        # TODO: Implement consistency validation
        pass

# Global instance
monitor_manager = MonitorManager()

# === API ENDPOINTS (Starting Point) ===

@app.route('/api/bankroll_updated', methods=['POST'])
def bankroll_updated():
    """Endpoint called by kalshi_account_sync when bankroll changes"""
    return jsonify(monitor_manager.handle_bankroll_update())

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "service": "monitor_manager",
        "version": "1.0.0",
        "capabilities": ["bankroll_updates", "position_calculation", "frontend_sync"]
    })

# === FUTURE ENDPOINTS (Foundation) ===

@app.route('/api/monitor_settings_update', methods=['POST'])
def monitor_settings_update():
    """Future: Handle monitor settings updates"""
    # TODO: Implement comprehensive settings management
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

@app.route('/api/trade_state_update', methods=['POST'])
def trade_state_update():
    """Future: Handle trade state updates"""
    # TODO: Implement trade state management
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

@app.route('/api/sync_all_states', methods=['POST'])
def sync_all_states():
    """Future: Synchronize all monitor states"""
    # TODO: Implement comprehensive state synchronization
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

if __name__ == "__main__":
    print("[MONITOR MANAGER] 🚀 Starting Core Monitor Management System")
    print("[MONITOR MANAGER] Foundation for comprehensive monitor state management")
    print("[MONITOR MANAGER] Current capability: Bankroll-driven position updates")
    print("[MONITOR MANAGER] Future capabilities: Full monitor lifecycle management")
    monitor_port = get_port("monitor_manager")
    app.run(host='0.0.0.0', port=monitor_port, debug=False)
