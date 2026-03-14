"""
TRADE EXECUTOR - UNIVERSAL CENTRALIZED PORT SYSTEM
Uses the single centralized port configuration system.
"""

# TEST FAILURE - REMOVE AFTER TESTING
# Syntax error removed for normal operation

from flask import Flask, request, jsonify
import logging
import os
import sys
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
from backend.util.paths import get_accounts_data_dir, get_host, get_logs_dir
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

# Standalone log for insufficient-resting-volume rejections (liquidity ceiling tracking)
INSUFFICIENT_VOLUME_LOG_NAME = "insufficient_resting_volume_rejections.jsonl"


def _log_insufficient_resting_volume_rejection(
    data: Dict[str, Any],
    response_status: int,
    response_text: str,
    count_fp: str,
) -> None:
    """Append one JSONL record to logs/insufficient_resting_volume_rejections.jsonl.
    Rotates monthly: when the current month changes, the existing file is renamed to
    insufficient_resting_volume_rejections_YYYY-MM.jsonl and a fresh .jsonl is used.
    Used to track when we hit liquidity ceilings (position size vs available resting volume)."""
    try:
        est = datetime.now(ZoneInfo("America/New_York"))
        utc = datetime.now(timezone.utc)
        current_month = est.strftime("%Y-%m")
        error_code = None
        try:
            rj = json.loads(response_text)
            if isinstance(rj.get("error"), dict):
                error_code = rj["error"].get("code") or rj["error"].get("message")
            elif isinstance(rj.get("error"), str):
                error_code = rj["error"]
        except (json.JSONDecodeError, TypeError):
            error_code = "unknown" if not response_text else response_text[:80]
        record = {
            "timestamp_utc": utc.isoformat(),
            "timestamp_est": est.isoformat(),
            "intent": data.get("intent", "open"),
            "ticker": data.get("ticker"),
            "contract": data.get("contract"),
            "symbol": data.get("symbol"),
            "monitor": data.get("monitor"),
            "position_count_fp": count_fp,
            "position": data.get("position"),
            "side": data.get("side", "yes"),
            "trade_id": data.get("id"),
            "ticket_id": data.get("ticket_id"),
            "kalshi_error_code": error_code,
            "response_status": response_status,
        }
        log_dir = get_logs_dir()
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        path = Path(log_dir) / INSUFFICIENT_VOLUME_LOG_NAME
        if path.exists():
            mtime = path.stat().st_mtime
            file_month = datetime.fromtimestamp(mtime, tz=ZoneInfo("America/New_York")).strftime("%Y-%m")
            if file_month != current_month:
                archive_path = Path(log_dir) / f"insufficient_resting_volume_rejections_{file_month}.jsonl"
                try:
                    path.rename(archive_path)
                except OSError as e:
                    _te_logger.warning("Monthly rotation of rejection log failed (rename): %s", e)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        _te_logger.warning("Failed to write insufficient_resting_volume rejection log: %s", e)


def _te_est_formatter():
    class _ESTF(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return _ESTF(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _TeFlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_te_logging():
    logr = logging.getLogger("trade_executor")
    if logr.handlers:
        return logr
    h = _TeFlushHandler(sys.stdout)
    h.setFormatter(_te_est_formatter())
    logr.addHandler(h)
    logr.setLevel(logging.INFO)
    return logr


_te_logger = _configure_te_logging()


def log_event(ticket_id, message, trade_id=None):
    """
    Log trade events to stdout and PostgreSQL. Include trade_id (hero id from trades table)
    when present so the full pipeline is traceable by grep for that id.
    """
    try:
        prefix = f"trade_id={trade_id} " if trade_id is not None else ""
        message_with_id = f"{prefix}{message}"
        _te_logger.info("%s", message_with_id)
        log_trade_event(ticket_id, message_with_id, service="trade_executor")
    except Exception as e:
        _te_logger.error("Error in log_event: %s", e)

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
        trade_id = data.get("id")  # Hero id from users.trades_0001 for full pipeline traceability
        # Normalize ticket_id to avoid double "TICKET-" prefixing
        if ticket_id.count("TICKET-") > 1:
            ticket_id = ticket_id.split("TICKET-")[-1]
            ticket_id = f"TICKET-{ticket_id}"
        log_event(ticket_id, "RECEIVED TICKET", trade_id=trade_id)

        ticker = data.get("ticker")
        raw_side = data.get("side", "yes")
        side = "yes" if raw_side in ["Y", "yes"] else "no"
        # Kalshi fixed-point: send only count_fp (legacy count deprecated). Accept count_fp from caller or derive from count/position.
        count_fp_in = data.get("count_fp")
        if count_fp_in is not None and str(count_fp_in).strip() != "":
            try:
                count_fp = f"{float(count_fp_in):.2f}"
            except (TypeError, ValueError):
                count_fp = f"{float(data.get('count', data.get('position', 1))):.2f}"
        else:
            count_val = data.get("count", data.get("position", 1))
            count_fp = f"{float(count_val):.2f}"
        # Always use limit orders - Kalshi no longer accepts market orders
        order_type = "limit"
        buy_price = data.get("buy_price")
        
        order_payload = {
            "ticker": ticker,
            "side": side,
            "type": order_type,
            "count_fp": count_fp,
            "time_in_force": "fill_or_kill",
            "action": "buy",
            "client_order_id": str(uuid.uuid4())
        }
        
        # Add price field based on side (hardcoded to 99 for market-like behavior)
        if side == "yes":
            order_payload["yes_price_dollars"] = "0.9900"
        else:
            order_payload["no_price_dollars"] = "0.9900"
        

        timestamp = str(int(time.time() * 1000))
        path = "/portfolio/orders"
        full_path = f"/trade-api/v2{path}"
        
        # Refresh credentials at trade time
        KEY_ID, KEY_PATH = get_current_credentials()
        log_event(ticket_id, f"🔑 CREDENTIALS: KEY_ID={KEY_ID[:8]}..., KEY_PATH={KEY_PATH}", trade_id=trade_id)
        
        signature = generate_kalshi_signature("POST", full_path, timestamp, str(KEY_PATH))
        log_event(ticket_id, f"🔐 SIGNATURE: timestamp={timestamp}, path={full_path}", trade_id=trade_id)
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
        log_event(ticket_id, f"🌐 SENDING TO KALSHI: {url}", trade_id=trade_id)
        log_event(ticket_id, f"📤 REQUEST HEADERS: {json.dumps(headers, indent=2)}", trade_id=trade_id)
        log_event(ticket_id, f"📤 REQUEST PAYLOAD: {json.dumps(order_payload, indent=2)}", trade_id=trade_id)
        
        try:
            response = requests.post(url, headers=headers, json=order_payload, timeout=10)
            
            # Log the complete response details
            log_event(ticket_id, f"📥 RESPONSE STATUS: {response.status_code}", trade_id=trade_id)
            log_event(ticket_id, f"📥 RESPONSE HEADERS: {dict(response.headers)}", trade_id=trade_id)
            log_event(ticket_id, f"📥 RESPONSE BODY: {response.text}", trade_id=trade_id)
        except requests.exceptions.RequestException as e:
            log_event(ticket_id, f"❌ REQUEST FAILED: {type(e).__name__}: {str(e)}", trade_id=trade_id)
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
            intent = data.get("intent", "open")
            log_event(ticket_id, f"❌ TRADE REJECTED (intent={intent}) - Status: {response.status_code}, Response: {response.text}", trade_id=trade_id)
            if "insufficient_resting_volume" in response.text.lower():
                _log_insufficient_resting_volume_rejection(data, response.status_code, response.text, count_fp)
            # Use the trade ID if provided, otherwise use ticket_id
            trade_id = data.get("id")
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
            log_event(ticket_id, f"✅ TRADE SUCCESS - Status: {response.status_code}, Response: {response.text}", trade_id=trade_id)
            
            # Extract order_id from Kalshi response
            order_id = None
            try:
                response_json = response.json()
                if "order" in response_json and "order_id" in response_json["order"]:
                    order_id = response_json["order"]["order_id"]
                    log_event(ticket_id, f"📋 EXTRACTED ORDER_ID: {order_id}", trade_id=trade_id)
            except Exception as e:
                log_event(ticket_id, f"⚠️ Failed to extract order_id: {e}", trade_id=trade_id)
            
            # Use the trade ID if provided, otherwise use ticket_id
            trade_id = data.get("id")
            intent = data.get("intent", "open")  # Get the intent to determine which order_id field to use
            if trade_id:
                status_payload = {"id": trade_id, "status": "accepted", "success_message": response.text, "order_id": order_id, "intent": intent}
            else:
                status_payload = {"ticket_id": ticket_id, "status": "accepted", "success_message": response.text, "order_id": order_id, "intent": intent}
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
        try:
            log_event(ticket_id, f"❌ ERROR: {e}", trade_id=trade_id)
        except NameError:
            log_event("UNKNOWN", f"❌ ERROR: {e}", trade_id=None)
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
        _te_logger.error("Error getting system status: %s", e)
        return {"error": str(e)}

# Main entry point
if __name__ == "__main__":
    # print(f"[TRADE_EXECUTOR] 🚀 Launching trade executor on static port {TRADE_EXECUTOR_PORT}")
    app.run(host="0.0.0.0", port=TRADE_EXECUTOR_PORT, debug=False)

