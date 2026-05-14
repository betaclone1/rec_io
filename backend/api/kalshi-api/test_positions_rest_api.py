#!/usr/bin/env python3
"""
Kalshi Market Positions REST API Test
Tests getting positions through REST API since websocket may not be available
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import dotenv_values
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import base64

# Import from backend modules
from backend.account_mode import get_account_mode

# Configuration
API_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
EST = ZoneInfo("America/New_York")

class KalshiPositionsRestTest:
    def __init__(self):
        self.account_mode = get_account_mode()
        self.api_key_id = None
        self.private_key = None
        self.session = None
        
    def load_credentials(self):
        """Load credentials based on account mode"""
        print(f"📊 Account Mode: {self.account_mode}")
        
        # Load credentials from the appropriate directory
        from backend.util.paths import get_kalshi_credentials_dir
        creds_dir = Path(get_kalshi_credentials_dir()) / self.account_mode
        env_file = creds_dir / ".env"
        
        if not env_file.exists():
            raise FileNotFoundError(f"Credentials file not found: {env_file}")
            
        # Load environment variables
        env_vars = dotenv_values(env_file)
        self.api_key_id = env_vars.get("KALSHI_API_KEY_ID")
        
        if not self.api_key_id:
            raise ValueError("API Key ID not found in credentials")
            
        print(f"🔑 Using API Key: {self.api_key_id[:8]}...")
        
        # Load private key
        private_key_path = creds_dir / "kalshi.pem"
        if not private_key_path.exists():
            raise FileNotFoundError(f"Private key not found: {private_key_path}")
            
        with open(private_key_path, 'rb') as f:
            self.private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
            
    def create_signature(self, timestamp, method, path, body=""):
        """Create Kalshi API signature"""
        message = f"{timestamp}{method}{path}{body}"
        signature = self.private_key.sign(
            message.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
        
    async def make_authenticated_request(self, method, endpoint, data=None):
        """Make authenticated request to Kalshi API"""
        timestamp = str(int(time.time()))
        path = f"/trade-api/v2{endpoint}"
        body = json.dumps(data) if data else ""
        
        signature = self.create_signature(timestamp, method, path, body)
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key_id}",
            "Kalshi-Api-Signature": signature,
            "Kalshi-Api-Timestamp": timestamp
        }
        
        url = f"{API_BASE_URL}{endpoint}"
        
        async with self.session.request(method, url, headers=headers, json=data) as response:
            return await response.json(), response.status
            
    async def test_positions_endpoints(self):
        """Test various positions-related endpoints"""
        print("🔍 Testing Kalshi REST API positions endpoints...")
        
        # Test 1: Get user positions
        print("\n📊 Test 1: Getting user positions...")
        try:
            positions_data, status = await self.make_authenticated_request("GET", "/positions")
            print(f"📡 Positions endpoint response (status {status}):")
            print(json.dumps(positions_data, indent=2))
        except Exception as e:
            print(f"❌ Error getting positions: {e}")
            
        # Test 2: Get specific market positions
        print("\n📊 Test 2: Getting specific market positions...")
        try:
            market_positions_data, status = await self.make_authenticated_request(
                "GET", "/positions?market_id=KXBTCD-25JUL2419-T118499.99"
            )
            print(f"📡 Market positions endpoint response (status {status}):")
            print(json.dumps(market_positions_data, indent=2))
        except Exception as e:
            print(f"❌ Error getting market positions: {e}")
            
        # Test 3: Get account balance
        print("\n💰 Test 3: Getting account balance...")
        try:
            balance_data, status = await self.make_authenticated_request("GET", "/account/balance")
            print(f"📡 Balance endpoint response (status {status}):")
            print(json.dumps(balance_data, indent=2))
        except Exception as e:
            print(f"❌ Error getting balance: {e}")
            
        # Test 4: Get user fills (which might include position info)
        print("\n📋 Test 4: Getting user fills...")
        try:
            fills_data, status = await self.make_authenticated_request("GET", "/fills")
            print(f"📡 Fills endpoint response (status {status}):")
            print(json.dumps(fills_data, indent=2))
        except Exception as e:
            print(f"❌ Error getting fills: {e}")
            
    async def run(self):
        """Main test runner"""
        print("🔌 Starting Kalshi Positions REST API Test...")
        
        try:
            # Load credentials
            self.load_credentials()
            
            # Create session
            async with aiohttp.ClientSession() as session:
                self.session = session
                
                # Test positions endpoints
                await self.test_positions_endpoints()
                
        except Exception as e:
            print(f"❌ Test failed: {e}")
            raise

async def main():
    """Main entry point"""
    test = KalshiPositionsRestTest()
    await test.run()

if __name__ == "__main__":
    asyncio.run(main()) 