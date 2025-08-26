"""
TRADE EXECUTOR - UNIVERSAL CENTRALIZED PORT SYSTEM
Uses the single centralized port configuration system.
"""

# TEST FAILURE - REMOVE AFTER TESTING
# Syntax error removed for normal operation

from flask import Flask, request, jsonify
import os
import json
import time
import uuid
import threading
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import dotenv_values
import base64
import hashlib
import hmac
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes

# Import the universal centralized port system
from backend.core.port_config import get_port, get_port_info

# Get port from centralized system
TRADE_EXECUTOR_PORT = get_port("trade_executor")
# print(f"[TRADE_EXECUTOR] 🚀 Using centralized port: {TRADE_EXECUTOR_PORT}")

# Import centralized path utilities
from backend.util.paths import get_accounts_data_dir, get_host
from backend.account_mode import get_account_mode

# Create Flask app
app = Flask(__name__)

def get_base_url():
    BASE_URLS = {
        "prod": "https://api.elections.kalshi.com/trade-api/v2",
        "demo": "https://demo-api.kalshi.co/trade-api/v2"
    }
    return BASE_URLS.get(get_account_mode(), BASE_URLS["prod"])

# print(f"Using base URL: {get_base_url()} for mode: {get_account_mode()}")

# --- Credentials loading ---
def load_credentials():
    mode = get_account_mode()
    from backend.util.paths import get_kalshi_credentials_dir
    cred_dir = Path(get_kalshi_credentials_dir()) / mode
    env_vars = dotenv_values(cred_dir / ".env")
    return {
        "KEY_ID": env_vars.get("KALSHI_API_KEY_ID"),
        "KEY_PATH": cred_dir / "kalshi.pem"
    }

# --- Helper to get current credentials (for key rotation, etc.) ---
def get_current_credentials():
    creds = load_credentials()
    return creds["KEY_ID"], creds["KEY_PATH"]

def generate_kalshi_signature(method, full_path, timestamp, key_path):
    with open(key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )

    message = f"{timestamp}{method.upper()}{full_path}".encode("utf-8")

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )

    return base64.b64encode(signature).decode("utf-8")

from backend.util.trade_logger import log_trade_event

# --- Logging helper for trade events ---
def log_event(ticket_id, message):
    """
    Log trade events to PostgreSQL instead of text files.
    """
    try:
        # Compose log message with executor prefix
        timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M:%S")
        log_message = f"[EXECUTOR {timestamp}] {message}"
        
        # Write to console with flush
        print(log_message, flush=True)
        
        # Log to PostgreSQL
        log_trade_event(ticket_id, message, service="trade_executor")

    except Exception as e:
        print(f"Error in log_event: {e}")

def get_manager_port():
    return get_port("trade_manager")

# Health check endpoint
@app.route("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "trade_executor",
        "port": TRADE_EXECUTOR_PORT,
        "timestamp": datetime.now().isoformat(),
        "port_system": "centralized"
    }

# Port information endpoint
@app.route("/api/ports")
def get_ports():
    """Get all port assignments from centralized system."""
    return get_port_info()

# Trade execution endpoint
@app.route("/trigger_trade", methods=["POST"])
def trigger_trade():
    """Execute a trade."""
    try:
        data = request.get_json()
        ticket_id = data.get("ticket_id", "UNKNOWN")
        # Normalize ticket_id to avoid double "TICKET-" prefixing
        if ticket_id.count("TICKET-") > 1:
            ticket_id = ticket_id.split("TICKET-")[-1]
            ticket_id = f"TICKET-{ticket_id}"
        log_event(ticket_id, "RECEIVED TICKET")

        ticker = data.get("ticker")
        raw_side = data.get("side", "yes")
        side = "yes" if raw_side in ["Y", "yes"] else "no"
        count = data.get("count", data.get("position", 1))
        order_type = data.get("type", "market")
        buy_price = data.get("buy_price")
        
        order_payload = {
            "ticker": ticker,
            "side": side,
            "type": order_type,
            "count": count,
            "time_in_force": "fill_or_kill",
            "action": "buy",
            "client_order_id": str(uuid.uuid4())
        }
        

        timestamp = str(int(time.time() * 1000))
        path = "/portfolio/orders"
        full_path = f"/trade-api/v2{path}"
        
        # Refresh credentials at trade time
        KEY_ID, KEY_PATH = get_current_credentials()
        log_event(ticket_id, f"🔑 CREDENTIALS: KEY_ID={KEY_ID[:8]}..., KEY_PATH={KEY_PATH}")
        
        signature = generate_kalshi_signature("POST", full_path, timestamp, str(KEY_PATH))
        log_event(ticket_id, f"🔐 SIGNATURE: timestamp={timestamp}, path={full_path}")
        headers = {
            "Accept": "application/json",
            "User-Agent": "KalshiTradeExec/1.0",
            "KALSHI-ACCESS-KEY": KEY_ID,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json"
        }

        url = f"{get_base_url()}{path}"
        
        # Log the complete request details
        log_event(ticket_id, f"🌐 SENDING TO KALSHI: {url}")
        log_event(ticket_id, f"📤 REQUEST HEADERS: {json.dumps(headers, indent=2)}")
        log_event(ticket_id, f"📤 REQUEST PAYLOAD: {json.dumps(order_payload, indent=2)}")
        
        try:
            response = requests.post(url, headers=headers, json=order_payload, timeout=10)
            
            # Log the complete response details
            log_event(ticket_id, f"📥 RESPONSE STATUS: {response.status_code}")
            log_event(ticket_id, f"📥 RESPONSE HEADERS: {dict(response.headers)}")
            log_event(ticket_id, f"📥 RESPONSE BODY: {response.text}")
        except requests.exceptions.RequestException as e:
            log_event(ticket_id, f"❌ REQUEST FAILED: {type(e).__name__}: {str(e)}")
            # Handle timeout/network errors the same as 400+ errors
            trade_id = data.get("id")
            if trade_id:
                status_payload = {"id": trade_id, "status": "error", "error_message": f"timeout: {str(e)}"}
            else:
                status_payload = {"ticket_id": ticket_id, "status": "error", "error_message": f"timeout: {str(e)}"}
            manager_port = get_manager_port()
            status_url = f"http://{get_host()}:{manager_port}/api/update_trade_status"
            def notify_error():
                try:
                    resp = requests.post(status_url, json=status_payload, timeout=5)
                except Exception as e:
                    pass
            threading.Thread(target=notify_error, daemon=True).start()
            return jsonify({"status": "rejected", "error": f"timeout: {str(e)}"}), 500

        if response.status_code >= 400:
            log_event(ticket_id, f"❌ TRADE REJECTED - Status: {response.status_code}, Response: {response.text}")
            # Use the trade ID if provided, otherwise use ticket_id
            trade_id = data.get("id")
            intent = data.get("intent", "open")  # Get the original intent
            if trade_id:
                status_payload = {"id": trade_id, "status": "error", "error_message": response.text, "intent": intent}
            else:
                status_payload = {"ticket_id": ticket_id, "status": "error", "error_message": response.text, "intent": intent}
            manager_port = get_manager_port()
            status_url = f"http://{get_host()}:{manager_port}/api/update_trade_status"
            def notify_error():
                try:
                    resp = requests.post(status_url, json=status_payload, timeout=5)
                except Exception as e:
                    pass
            threading.Thread(target=notify_error, daemon=True).start()
            return jsonify({"status": "rejected", "error": response.text}), response.status_code
        elif response.status_code in [200, 201]:
            log_event(ticket_id, f"✅ TRADE SUCCESS - Status: {response.status_code}, Response: {response.text}")
            # Use the trade ID if provided, otherwise use ticket_id
            trade_id = data.get("id")
            if trade_id:
                status_payload = {"id": trade_id, "status": "accepted", "success_message": response.text}
            else:
                status_payload = {"ticket_id": ticket_id, "status": "accepted", "success_message": response.text}
            manager_port = get_manager_port()
            status_url = f"http://{get_host()}:{manager_port}/api/update_trade_status"
            def notify_accepted():
                try:
                    resp = requests.post(status_url, json=status_payload, timeout=5)
                except Exception as e:
                    pass
            threading.Thread(target=notify_accepted, daemon=True).start()
            return jsonify({"status": "sent", "message": "Trade sent successfully"}), 200

    except Exception as e:
        log_event(ticket_id, f"❌ ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# System status endpoint (kept for health monitoring)
@app.route("/api/system_status")
def get_system_status():
    """Get system status."""
    try:
        return {
            "status": "online",
            "service": "trade_executor",
            "port": TRADE_EXECUTOR_PORT,
            "timestamp": datetime.now().isoformat(),
            "port_system": "centralized"
        }
    except Exception as e:
        print(f"Error getting system status: {e}")
        return {"error": str(e)}

# Main entry point
if __name__ == "__main__":
    # print(f"[TRADE_EXECUTOR] 🚀 Launching trade executor on static port {TRADE_EXECUTOR_PORT}")
    app.run(host="0.0.0.0", port=TRADE_EXECUTOR_PORT, debug=False)

