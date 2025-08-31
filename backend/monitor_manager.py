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
            
            # Update bankroll allotments for active monitors (includes total_position calculation)
            allotment_result = self.update_monitor_bankroll_allotments(0)  # bankroll parameter not used anymore
            
            # Combine results
            combined_result = {
                "status": "success",
                "allotment_update": allotment_result,
                "message": "Bankroll update processed successfully"
            }
            
            self.log_event("BANKROLL_UPDATE", "Bankroll update processed successfully", combined_result)
            return combined_result
            
        except Exception as e:
            self.log_event("ERROR", f"Bankroll update failed: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    # DEPRECATED: update_total_position method removed - monitor_manager now only works with monitor_list table

    def update_monitor_bankroll_allotments(self, bankroll: float) -> Dict[str, Any]:
        """
        Update bankroll_allotment_total for all active monitors based on current bankroll
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                # Get current bankroll in cents
                cursor.execute("SELECT bankroll_current FROM users.account_balance_0001 ORDER BY timestamp DESC LIMIT 1")
                bankroll_result = cursor.fetchone()
                if not bankroll_result:
                    return {"status": "error", "message": "No bankroll data found"}
                
                bankroll_cents = bankroll_result[0]  # Already in cents
                
                # Get all active monitors
                cursor.execute("""
                    SELECT id, name, bankroll_allotment_pct 
                    FROM users.monitor_list_0001 
                    WHERE status = 'active'
                """)
                
                monitors = cursor.fetchall()
                updated_count = 0
                
                for monitor_id, monitor_name, allotment_pct in monitors:
                    if allotment_pct is None:
                        continue
                    
                    # Simple calculation: allotment_pct * bankroll_cents
                    allotment_total_cents = int(allotment_pct * bankroll_cents)
                    
                    # Update bankroll_allotment_total
                    cursor.execute("""
                        UPDATE users.monitor_list_0001 
                        SET bankroll_allotment_total = %s 
                        WHERE id = %s
                    """, (allotment_total_cents, monitor_id))
                    
                    # Update total_position for all monitors
                    cursor.execute("""
                        SELECT position_size, position_type, multiplier 
                        FROM users.monitor_list_0001 
                        WHERE id = %s
                    """, (monitor_id,))
                    
                    pos_result = cursor.fetchone()
                    if pos_result:
                        position_size, position_type, multiplier = pos_result
                        
                        if position_type == 'percent':
                            # For percent: round((position_size * allotment_dollars / 100) * multiplier)
                            allotment_dollars = allotment_total_cents / 100
                            new_total_position = int(round((position_size * allotment_dollars / 100) * float(multiplier)))
                        else:
                            # For contracts: position_size * multiplier
                            new_total_position = int(position_size * float(multiplier))
                        
                        cursor.execute("""
                            UPDATE users.monitor_list_0001 
                            SET total_position = %s 
                            WHERE id = %s
                        """, (new_total_position, monitor_id))
                        
                        # Send WebSocket notification to frontend about total_position update
                        try:
                            import requests
                            requests.post('http://localhost:3000/api/broadcast_monitor_total_position', json={
                                'monitor_id': monitor_id,
                                'total_position': new_total_position
                            }, timeout=1)
                        except Exception as e:
                            self.log_event("WEBSOCKET_ERROR", f"Failed to send total_position update notification: {str(e)}")
                    
                    updated_count += 1
                
                conn.commit()
                
                return {
                    "status": "success",
                    "message": f"Updated {updated_count} monitors",
                    "updated_count": updated_count,
                    "bankroll_cents": bankroll_cents
                }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()
    
    # DEPRECATED: push_frontend_updates method removed - monitor_manager now only works with monitor_list table
    
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

    def initialize_bankroll_allotments(self) -> Dict[str, Any]:
        """
        Initialize bankroll allotments on first launch
        """
        return self.update_monitor_bankroll_allotments(0)  # bankroll parameter not used anymore

    def update_monitor_position_variables(self, monitor_id: int, position_size: int = None, position_type: str = None, multiplier: float = None) -> Dict[str, Any]:
        """
        Update monitor position variables and recalculate total_position
        Called when frontend sends position variable updates
        """
        import time
        start_time = time.time()
        conn = None
        try:
            conn = self.get_database_connection()
            self.log_event("TIMING", f"DB connection: {time.time() - start_time:.3f}s")
            
            with conn.cursor() as cursor:
                # Build update query for position variables
                update_fields = []
                values = []
                
                if position_size is not None:
                    update_fields.append("position_size = %s")
                    values.append(position_size)
                
                if position_type is not None:
                    update_fields.append("position_type = %s")
                    values.append(position_type)
                
                if multiplier is not None:
                    update_fields.append("multiplier = %s")
                    values.append(multiplier)
                
                if not update_fields:
                    return {"status": "error", "message": "No position variables to update"}
                
                # Update position variables
                values.append(monitor_id)
                update_start = time.time()
                cursor.execute(f"""
                    UPDATE users.monitor_list_0001 
                    SET {', '.join(update_fields)}
                    WHERE id = %s AND status = 'active'
                """, values)
                self.log_event("TIMING", f"Position update: {time.time() - update_start:.3f}s")
                
                if cursor.rowcount == 0:
                    return {"status": "error", "message": "Monitor not found or not active"}
                
                # Get current monitor settings for calculation
                fetch_start = time.time()
                cursor.execute("""
                    SELECT position_size, position_type, multiplier, bankroll_allotment_total 
                    FROM users.monitor_list_0001 
                    WHERE id = %s
                """, (monitor_id,))
                self.log_event("TIMING", f"Fetch settings: {time.time() - fetch_start:.3f}s")
                
                result = cursor.fetchone()
                if not result:
                    return {"status": "error", "message": "Failed to retrieve monitor settings"}
                
                position_size, position_type, multiplier, bankroll_allotment_total = result
                
                # Calculate new total_position
                if position_type == 'percent':
                    # For percent: round((position_size * allotment_dollars / 100) * multiplier)
                    if bankroll_allotment_total is not None:
                        allotment_dollars = bankroll_allotment_total / 100
                        new_total_position = int(round((position_size * allotment_dollars / 100) * float(multiplier)))
                    else:
                        new_total_position = 0  # No bankroll allotment
                else:
                    # For contracts: position_size * multiplier
                    new_total_position = int(position_size * float(multiplier))
                
                # Update total_position
                total_update_start = time.time()
                cursor.execute("""
                    UPDATE users.monitor_list_0001 
                    SET total_position = %s 
                    WHERE id = %s
                """, (new_total_position, monitor_id))
                self.log_event("TIMING", f"Total position update: {time.time() - total_update_start:.3f}s")
                
                commit_start = time.time()
                conn.commit()
                self.log_event("TIMING", f"Commit: {time.time() - commit_start:.3f}s")
                
                # Send WebSocket notification to frontend
                try:
                    import requests
                    requests.post('http://localhost:3000/api/broadcast_monitor_total_position', json={
                        'monitor_id': monitor_id,
                        'total_position': new_total_position
                    }, timeout=1)
                except Exception as e:
                    self.log_event("WEBSOCKET_ERROR", f"Failed to send total_position update notification: {str(e)}")
                
                total_time = time.time() - start_time
                self.log_event("TIMING", f"Total function time: {total_time:.3f}s")
                
                return {
                    "status": "success",
                    "message": "Monitor position variables updated and total_position recalculated",
                    "monitor_id": monitor_id,
                    "total_position": new_total_position
                }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def recalculate_monitor_total_positions(self) -> Dict[str, Any]:
        """
        Recalculate total_position for all monitors based on their current settings
        Called when position variables (size, type, multiplier) change
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                # Get all active monitors
                cursor.execute("""
                    SELECT id, name, position_size, position_type, multiplier, bankroll_allotment_total 
                    FROM users.monitor_list_0001 
                    WHERE status = 'active'
                """)
                
                monitors = cursor.fetchall()
                updated_count = 0
                
                for monitor_id, monitor_name, position_size, position_type, multiplier, bankroll_allotment_total in monitors:
                    if position_size is None or position_type is None or multiplier is None:
                        continue
                    
                    # Calculate new total_position based on current settings
                    if position_type == 'percent':
                        # For percent: round((position_size * allotment_dollars / 100) * multiplier)
                        if bankroll_allotment_total is not None:
                            allotment_dollars = bankroll_allotment_total / 100
                            new_total_position = int(round((position_size * allotment_dollars / 100) * float(multiplier)))
                        else:
                            # If no bankroll allotment, skip this monitor
                            continue
                    else:
                        # For contracts: position_size * multiplier
                        new_total_position = int(position_size * float(multiplier))
                    
                    # Update total_position in monitor table
                    cursor.execute("""
                        UPDATE users.monitor_list_0001 
                        SET total_position = %s 
                        WHERE id = %s
                    """, (new_total_position, monitor_id))
                    
                    # Send WebSocket notification to frontend about total_position update
                    try:
                        import requests
                        requests.post('http://localhost:3000/api/broadcast_monitor_total_position', json={
                            'monitor_id': monitor_id,
                            'total_position': new_total_position
                        }, timeout=1)
                    except Exception as e:
                        self.log_event("WEBSOCKET_ERROR", f"Failed to send total_position update notification: {str(e)}")
                    
                    updated_count += 1
                
                conn.commit()
                
                return {
                    "status": "success",
                    "message": f"Recalculated total_position for {updated_count} monitors",
                    "updated_count": updated_count
                }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

# Global instance
monitor_manager = MonitorManager()

# Initialize bankroll allotments on startup
try:
    monitor_manager.log_event("STARTUP", "Monitor manager starting up, initializing bankroll allotments")
    init_result = monitor_manager.initialize_bankroll_allotments()
    monitor_manager.log_event("STARTUP", f"Startup initialization completed: {init_result}")
except Exception as e:
    monitor_manager.log_event("STARTUP_ERROR", f"Failed to initialize on startup: {str(e)}")

# === API ENDPOINTS (Starting Point) ===

@app.route('/api/bankroll_updated', methods=['POST'])
def bankroll_updated():
    """Endpoint called by kalshi_account_sync when bankroll changes"""
    return jsonify(monitor_manager.handle_bankroll_update())

@app.route('/api/update_monitor_position', methods=['POST'])
def update_monitor_position():
    """Endpoint to update monitor position variables and recalculate total_position"""
    try:
        data = request.get_json()
        monitor_id = data.get('monitor_id')
        position_size = data.get('position_size')
        position_type = data.get('position_type')
        multiplier = data.get('multiplier')
        
        if not monitor_id:
            return jsonify({"status": "error", "message": "monitor_id is required"})
        
        return jsonify(monitor_manager.update_monitor_position_variables(monitor_id, position_size, position_type, multiplier))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/initialize_allotments', methods=['POST'])
def initialize_allotments():
    """Endpoint to recalculate total_position for all monitors when position variables change"""
    return jsonify(monitor_manager.recalculate_monitor_total_positions())

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "service": "monitor_manager",
        "version": "1.0.0",
        "capabilities": ["bankroll_updates", "position_calculation", "monitor_allotments", "frontend_sync"]
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
