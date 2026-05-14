#!/usr/bin/env python3
"""
Kalshi Market Positions WebSocket Test
Connects to market positions websocket to receive real-time position updates
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

class KalshiMarketPositionsTest:
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
    
    def convert_centi_cents_to_dollars(self, centi_cents):
        """Convert centi-cents to dollars (divide by 10,000)"""
        if centi_cents is None:
            return None
        return centi_cents / 10000.0
    
    async def connect(self):
        """Connect to Kalshi Market Positions WebSocket API"""
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
            
            print(f"[{datetime.now(EST)}] 🔐 Attempting Market Positions WebSocket connection...")
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
            
            print(f"[{datetime.now(EST)}] ✅ Connected to Kalshi Market Positions WebSocket API")
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to connect to Market Positions WebSocket: {e}")
            return False
    
    async def subscribe_to_market_positions(self):
        """Subscribe to market positions channel"""
        if not self.websocket:
            return False
        
        try:
            # Try to get available channels first
            print("🔍 Attempting to discover available channels...")
            
            # Try different subscription formats and channel names
            test_subscriptions = [
                {"channels": ["market_positions"]},
                {"channels": ["positions"]},
                {"channels": ["position"]},
                {"channels": ["portfolio"]},
                {"channels": ["portfolio_positions"]},
                {"channels": ["user_positions"]},
                {"channels": ["account_positions"]},
                {"channels": ["market_position"]},  # Try singular
                {"channels": ["user_position"]},    # Try singular
                {"channels": ["account_position"]}, # Try singular
                {"channels": ["portfolio_position"]}, # Try singular
                {"channels": ["market_positions"], "market_ticker": "KXBTCD-25JUL2419-T118499.99"},  # Try with market
                {"channels": ["positions"], "market_ticker": "KXBTCD-25JUL2419-T118499.99"},  # Try with market
                {"channels": ["position"], "market_ticker": "KXBTCD-25JUL2419-T118499.99"},  # Try with market
            ]
            
            for i, params in enumerate(test_subscriptions):
                try:
                    test_subscription = {
                        "id": self.command_id,
                        "cmd": "subscribe",
                        "params": params
                    }
                    print(f"🧪 Testing subscription {i+1}: {params}")
                    await self.websocket.send(json.dumps(test_subscription))
                    
                    # Wait for response
                    response = await asyncio.wait_for(self.websocket.recv(), timeout=2.0)
                    response_data = json.loads(response)
                    print(f"📡 Response for subscription {i+1}: {response_data}")
                    
                    if response_data.get('type') == 'error':
                        print(f"❌ Subscription {i+1} failed: {response_data}")
                    else:
                        print(f"✅ Subscription {i+1} might work!")
                        break
                        
                except asyncio.TimeoutError:
                    print(f"⏰ Timeout testing subscription {i+1}")
                except Exception as e:
                    print(f"❌ Error testing subscription {i+1}: {e}")
            
            # Now try the actual subscription
            subscription_message = {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["market_positions"]
                }
            }
            
            await self.websocket.send(json.dumps(subscription_message))
            print(f"[{datetime.now(EST)}] 📡 Sent market positions subscription: {json.dumps(subscription_message)}")
            
            # Wait for subscription confirmation
            response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            response_data = json.loads(response)
            
            if response_data.get("type") == "subscribed":
                self.subscription_id = response_data.get("msg", {}).get("sid")
                print(f"[{datetime.now(EST)}] ✅ Subscribed to market positions with SID: {self.subscription_id}")
                return True
            else:
                print(f"[{datetime.now(EST)}] ❌ Market positions subscription failed: {response_data}")
                return False
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to subscribe to market positions: {e}")
            return False
    
    async def handle_position_message(self, message):
        """Handle incoming market position messages"""
        try:
            data = json.loads(message)
            
            if data.get("type") == "market_position":
                position_data = data.get("msg", {})
                
                print(f"\n[{datetime.now(EST)}] 📊 MARKET POSITION UPDATE!")
                print(f"   User ID: {position_data.get('user_id')}")
                print(f"   Market: {position_data.get('market_ticker')}")
                print(f"   Position: {position_data.get('position')}")
                
                # Convert monetary values from centi-cents to dollars
                position_cost = self.convert_centi_cents_to_dollars(position_data.get('position_cost'))
                realized_pnl = self.convert_centi_cents_to_dollars(position_data.get('realized_pnl'))
                fees_paid = self.convert_centi_cents_to_dollars(position_data.get('fees_paid'))
                
                print(f"   Position Cost: ${position_cost:.2f}" if position_cost else "   Position Cost: None")
                print(f"   Realized P&L: ${realized_pnl:.2f}" if realized_pnl else "   Realized P&L: None")
                print(f"   Fees Paid: ${fees_paid:.2f}" if fees_paid else "   Fees Paid: None")
                print(f"   Volume: {position_data.get('volume')}")
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
        print(f"[{datetime.now(EST)}] 🔌 Starting Kalshi Market Positions WebSocket Test...")
        
        # Connect to WebSocket
        if not await self.connect():
            print(f"[{datetime.now(EST)}] ❌ Failed to connect, exiting")
            return
        
        # Subscribe to market positions
        if not await self.subscribe_to_market_positions():
            print(f"[{datetime.now(EST)}] ❌ Failed to subscribe, exiting")
            return
        
        print(f"[{datetime.now(EST)}] 🎧 Listening for market position updates...")
        print(f"[{datetime.now(EST)}] 💡 Place a trade on Kalshi to see real-time position updates!")
        print(f"[{datetime.now(EST)}] 📊 All position changes will be displayed in real-time")
        print(f"[{datetime.now(EST)}] ⏹️  Press Ctrl+C to stop")
        
        try:
            # Listen for messages
            async for message in self.websocket:
                await self.handle_position_message(message)
                
        except KeyboardInterrupt:
            print(f"\n[{datetime.now(EST)}] ⏹️  Stopping market positions test...")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ WebSocket error: {e}")
        finally:
            if self.websocket:
                await self.websocket.close()
                print(f"[{datetime.now(EST)}] 🔌 WebSocket connection closed")

async def main():
    """Main entry point"""
    test = KalshiMarketPositionsTest()
    await test.run()

if __name__ == "__main__":
    asyncio.run(main()) 