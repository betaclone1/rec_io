#!/usr/bin/env python3
"""
Test script for Kalshi subaccount endpoints
Based on kalshi_account_sync_ws.py structure
"""

import sys
import os

# Set up Python path to ensure imports work correctly
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)
os.environ['PYTHONPATH'] = project_root

from backend.util.paths import get_project_root
from backend.account_mode import get_account_mode
import requests
import json
import time
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes

# Add project root to path for imports
sys.path.insert(0, get_project_root())

from backend.util.paths import get_kalshi_credentials_dir

# Dynamically select API base URL based on account mode
def get_base_url():
    BASE_URLS = {
        "prod": "https://api.elections.kalshi.com/trade-api/v2",
        "demo": "https://demo-api.kalshi.co/trade-api/v2"
    }
    return BASE_URLS.get(get_account_mode(), BASE_URLS["prod"])

print(f"Using base URL: {get_base_url()} for mode: {get_account_mode()}")

# Load credentials
CREDENTIALS_DIR = Path(get_kalshi_credentials_dir()) / get_account_mode()
ENV_VARS = dotenv_values(CREDENTIALS_DIR / ".env")

KEY_ID = ENV_VARS.get("KALSHI_API_KEY_ID")
KEY_PATH = CREDENTIALS_DIR / "kalshi.pem"

def generate_kalshi_signature(method, full_path, timestamp, key_path):
    """Generate Kalshi API signature for authentication"""
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    import base64

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
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )

    return base64.b64encode(signature).decode("utf-8")

def make_api_request(method, path, body=None):
    """Make an authenticated API request to Kalshi"""
    if not KEY_ID or not KEY_PATH.exists():
        print("❌ Missing Kalshi API credentials or PEM file.")
        return None
    
    url = f"{get_base_url()}{path}"
    timestamp = str(int(time.time() * 1000))  # milliseconds
    
    full_path_for_signature = f"/trade-api/v2{path}"
    signature = generate_kalshi_signature(method, full_path_for_signature, timestamp, str(KEY_PATH))
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "KalshiWatcher/1.0",
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            if body is not None:
                headers["Content-Type"] = "application/json"
                response = requests.post(url, headers=headers, json=body, timeout=10)
            else:
                response = requests.post(url, headers=headers, timeout=10)
        else:
            print(f"❌ Unsupported method: {method}")
            return None
        
        print(f"\n{'='*60}")
        print(f"🔗 {method} {path}")
        print(f"📊 Status Code: {response.status_code}")
        
        try:
            data = response.json()
            print(f"📄 Response:")
            print(json.dumps(data, indent=2))
            
            if "error" in data:
                print(f"⚠️ API error: {data['error']}")
            else:
                print(f"✅ Request successful")
            
            return data
        except json.JSONDecodeError:
            print(f"⚠️ Response is not JSON:")
            print(response.text)
            return None
            
    except Exception as e:
        print(f"❌ Failed to make request: {e}")
        return None

def test_get_subaccount_balances():
    """Test GET /portfolio/subaccounts/balances"""
    print("\n" + "="*60)
    print("TEST 1: GET /portfolio/subaccounts/balances")
    print("="*60)
    return make_api_request("GET", "/portfolio/subaccounts/balances")

def test_get_subaccount_transfers():
    """Test GET /portfolio/subaccounts/transfers"""
    print("\n" + "="*60)
    print("TEST 2: GET /portfolio/subaccounts/transfers")
    print("="*60)
    return make_api_request("GET", "/portfolio/subaccounts/transfers")

def test_create_subaccount():
    """Test POST /portfolio/subaccounts - Create a new subaccount.
    See https://docs.kalshi.com/api-reference/portfolio/create-subaccount
    No request body; subaccounts are numbered 1-32, max 32 per user."""
    print("\n" + "="*60)
    print("TEST 3: POST /portfolio/subaccounts (Create subaccount)")
    print("="*60)
    # API expects application/json; send empty object when spec has no request body
    return make_api_request("POST", "/portfolio/subaccounts", body={})

def test_transfer_between_subaccounts():
    """Test POST /portfolio/subaccounts/transfer - Transfer funds"""
    print("\n" + "="*60)
    print("TEST 4: POST /portfolio/subaccounts/transfer")
    print("="*60)
    # Note: This requires actual subaccount IDs and will perform a real transfer
    # We'll use placeholder data to test if the endpoint exists
    # The user should replace these with actual subaccount IDs if they want to test transfers
    body = {
        "from_subaccount_id": "test_from_id",
        "to_subaccount_id": "test_to_id",
        "amount_cents": 1000,
        "client_transfer_id": f"test_{int(time.time())}"
    }
    print("⚠️ Using placeholder data - replace with actual subaccount IDs to test real transfers")
    return make_api_request("POST", "/portfolio/subaccounts/transfer", body)

def main():
    print("🧪 Testing Kalshi Subaccount Endpoints")
    print(f"📅 Test started at: {datetime.now()}")
    print(f"🔐 Account Mode: {get_account_mode()}")
    
    # Test GET endpoints first (safe, read-only)
    balances_result = test_get_subaccount_balances()
    transfers_result = test_get_subaccount_transfers()
    
    # Create a new subaccount (POST with no body per API spec)
    create_result = test_create_subaccount()
    
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    print(f"✅ GET /portfolio/subaccounts/balances: {'PASS' if balances_result and 'error' not in balances_result else 'FAIL'}")
    print(f"✅ GET /portfolio/subaccounts/transfers: {'PASS' if transfers_result and 'error' not in transfers_result else 'FAIL'}")
    create_ok = create_result and "error" not in create_result and "subaccount_number" in create_result
    print(f"✅ POST /portfolio/subaccounts (create): {'PASS' if create_ok else 'FAIL'}")
    if create_ok:
        print(f"   → New subaccount_number: {create_result.get('subaccount_number')}")
    print("="*60)

if __name__ == "__main__":
    main()
