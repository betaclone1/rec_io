#!/usr/bin/env python3
"""
Kalshi Public Trades WebSocket Test
Connects to public trades websocket to receive real-time trade notifications
"""

import asyncio
import websockets
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
WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
EST = ZoneInfo("America/New_York")

class KalshiPublicTradesTest:
    def __init__(self):
        self.websocket = None
        self.subscription_id = None
        self.command_id = 1
        
    def load_kalshi_credentials(self):
        """Load Kalshi API credentials"""
        account_mode = get_account_mode()
        from backend.util.paths import get_kalshi_credentials_dir
        cred_dir = Path(get_kalshi_credentials_dir()) / account_mode
        
        if not cred_dir.exists():
            print(f"❌ No {account_mode} credentials found at {cred_dir}")
            return None
        
        env_vars = dotenv_values(cred_dir / ".env")
        key_path = cred_dir / "kalshi.pem"
        
        if not key_path.exists():
            print(f"❌ No private key file found at {key_path}")
            return None
        
        return {
            "KEY_ID": env_vars.get("KALSHI_API_KEY_ID"),
            "KEY_PATH": key_path
        }
    
    async def connect(self):
        """Connect to Kalshi Public Trades WebSocket API"""
        try:
            # Load credentials
            credentials = self.load_kalshi_credentials()
            if not credentials:
                print(f"[{datetime.now(EST)}] ❌ No credentials available")
                return False
            
            # Generate signature using the same method as REST API
            timestamp_ms = str(int(time.time() * 1000))
            signature_text = timestamp_ms + "GET" + "/trade-api/ws/v2"
            
            # Load private key and sign
            with open(credentials["KEY_PATH"], "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
            
            # Sign the signature text
            signature = private_key.sign(
                signature_text.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Base64 encode the signature
            signature_b64 = base64.b64encode(signature).decode('utf-8')
            
            # Use the correct Kalshi header names
            headers = {
                "KALSHI-ACCESS-KEY": credentials["KEY_ID"],
                "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
                "KALSHI-ACCESS-SIGNATURE": signature_b64
            }
            
            print(f"[{datetime.now(EST)}] 🔐 Attempting Public Trades WebSocket connection...")
            print(f"[{datetime.now(EST)}] 📊 Account Mode: {get_account_mode()}")
            print(f"[{datetime.now(EST)}] 🔑 Using API Key: {credentials['KEY_ID'][:8]}...")
            
            # Connect with authentication headers
            self.websocket = await websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=10,
                ping_timeout=10,
                close_timeout=10
            )
            
            print(f"[{datetime.now(EST)}] ✅ Connected to Kalshi Public Trades WebSocket API")
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to connect to Public Trades WebSocket: {e}")
            return False
    
    async def subscribe_to_public_trades(self):
        """Subscribe to public trades channel"""
        if not self.websocket:
            return False
        
        try:
            # Subscribe to public trades channel (no market specification = all trades)
            subscription_message = {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["trade"]
                }
            }
            
            await self.websocket.send(json.dumps(subscription_message))
            print(f"[{datetime.now(EST)}] 📡 Sent public trades subscription: {json.dumps(subscription_message)}")
            
            # Wait for subscription confirmation
            response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            response_data = json.loads(response)
            
            if response_data.get("type") == "subscribed":
                self.subscription_id = response_data.get("msg", {}).get("sid")
                print(f"[{datetime.now(EST)}] ✅ Subscribed to public trades with SID: {self.subscription_id}")
                return True
            else:
                print(f"[{datetime.now(EST)}] ❌ Public trades subscription failed: {response_data}")
                return False
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to subscribe to public trades: {e}")
            return False
    
    async def handle_trade_message(self, message):
        """Handle incoming public trade messages"""
        try:
            data = json.loads(message)
            
            if data.get("type") == "trade":
                trade_data = data.get("msg", {})
                
                print(f"\n[{datetime.now(EST)}] 💰 PUBLIC TRADE EXECUTED!")
                print(f"   Market: {trade_data.get('market_ticker')}")
                print(f"   Yes Price: {trade_data.get('yes_price')}")
                print(f"   No Price: {trade_data.get('no_price')}")
                print(f"   Count: {trade_data.get('count')}")
                print(f"   Taker Side: {trade_data.get('taker_side')}")
                print(f"   Timestamp: {trade_data.get('ts')}")
                print("=" * 50)
                
            elif data.get("type") == "subscribed":
                print(f"[{datetime.now(EST)}] ✅ Subscription confirmed: {data}")
                
            elif data.get("type") == "error":
                print(f"[{datetime.now(EST)}] ❌ WebSocket error: {data}")
                
            else:
                print(f"[{datetime.now(EST)}] 📨 Other message: {data}")
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error handling message: {e}")
    
    async def run(self):
        """Main run loop"""
        print(f"[{datetime.now(EST)}] 🔌 Starting Kalshi Public Trades WebSocket Test...")
        
        # Connect to WebSocket
        if not await self.connect():
            print(f"[{datetime.now(EST)}] ❌ Failed to connect, exiting")
            return
        
        # Subscribe to public trades
        if not await self.subscribe_to_public_trades():
            print(f"[{datetime.now(EST)}] ❌ Failed to subscribe, exiting")
            return
        
        print(f"[{datetime.now(EST)}] 🎧 Listening for public trade notifications...")
        print(f"[{datetime.now(EST)}] 💡 All trades happening on Kalshi will be displayed in real-time!")
        print(f"[{datetime.now(EST)}] 📊 This is a live feed of all public trading activity")
        print(f"[{datetime.now(EST)}] ⏹️  Press Ctrl+C to stop")
        
        try:
            # Listen for messages
            async for message in self.websocket:
                await self.handle_trade_message(message)
                
        except KeyboardInterrupt:
            print(f"\n[{datetime.now(EST)}] ⏹️  Stopping public trades test...")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ WebSocket error: {e}")
        finally:
            if self.websocket:
                await self.websocket.close()
                print(f"[{datetime.now(EST)}] 🔌 WebSocket connection closed")

async def main():
    """Main entry point"""
    test = KalshiPublicTradesTest()
    await test.run()

if __name__ == "__main__":
    asyncio.run(main()) 