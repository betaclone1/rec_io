#!/usr/bin/env python3
"""
Kalshi Market Ticker WebSocket Test
Connects to market ticker websocket to receive real-time ticker updates
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

class KalshiMarketTickerTest:
    def __init__(self):
        self.websocket = None
        self.command_id = 1
        self.account_mode = get_account_mode()
        print(f"🔐 Account Mode: {self.account_mode}")
        
        # Load credentials based on account mode
        from backend.util.paths import get_kalshi_credentials_dir
        creds_dir = Path(get_kalshi_credentials_dir()) / self.account_mode
        env_file = creds_dir / ".env"
        
        if not env_file.exists():
            raise FileNotFoundError(f"Credentials file not found: {env_file}")
        
        # Load environment variables
        env_vars = dotenv_values(env_file)
        self.api_key_id = env_vars.get("KALSHI_API_KEY_ID")
        self.private_key_path = creds_dir / "kalshi.pem"
        
        if not self.private_key_path.exists():
            raise FileNotFoundError(f"Private key file not found: {self.private_key_path}")
        
        print(f"🔑 Using API Key: {self.api_key_id[:8]}...")
        print(f"🔑 Private Key: {self.private_key_path}")

    def generate_signature(self, timestamp_ms):
        """Generate Kalshi API signature using the correct method"""
        try:
            with open(self.private_key_path, 'rb') as f:
                private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                    backend=default_backend()
                )
            
            # Create signature text using the correct format
            signature_text = timestamp_ms + "GET" + "/trade-api/ws/v2"
            
            # Sign the signature text using PSS padding
            signature = private_key.sign(
                signature_text.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Return base64 encoded signature
            return base64.b64encode(signature).decode('utf-8')
        except Exception as e:
            print(f"❌ Error generating signature: {e}")
            return None

    async def connect_and_subscribe(self):
        """Connect to WebSocket and subscribe to market ticker"""
        try:
            # Generate authentication headers using the correct method
            timestamp_ms = str(int(time.time() * 1000))
            signature = self.generate_signature(timestamp_ms)
            
            if not signature:
                print("❌ Failed to generate signature")
                return
            
            # Use the correct Kalshi header names
            headers = {
                "KALSHI-ACCESS-KEY": self.api_key_id,
                "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
                "KALSHI-ACCESS-SIGNATURE": signature
            }
            
            print("🔐 Attempting WebSocket connection with proper Kalshi authentication...")
            
            # Connect with authentication headers
            self.websocket = await websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=10,
                ping_timeout=10,
                close_timeout=10
            )
            
            print("✅ Connected to Kalshi WebSocket API")
            
            # Get current BTC market tickers from the latest market snapshot
            # These are the EXACT market tickers for the current BTC hourly market
            btc_markets = [
                "KXBTCD-25JUL2419-T118999.99",  # $109,000 or above
                "KXBTCD-25JUL2419-T119249.99",  # $109,250 or above
                "KXBTCD-25JUL2419-T119499.99",  # $109,500 or above
                "KXBTCD-25JUL2419-T119749.99",  # $109,750 or above
                "KXBTCD-25JUL2419-T119999.99"   # $110,000 or above
            ]
            
            print(f"📊 Subscribing to {len(btc_markets)} BTC markets...")
            
            # Subscribe to market ticker for specific markets
            subscription_message = {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["ticker_v2"],
                    "market_tickers": btc_markets
                }
            }
            
            print(f"📡 Sending subscription: {json.dumps(subscription_message, indent=2)}")
            await self.websocket.send(json.dumps(subscription_message))
            
            # Wait for subscription response
            response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
            response_data = json.loads(response)
            print(f"📡 Subscription response: {json.dumps(response_data, indent=2)}")
            
            if response_data.get('type') == 'subscribed':
                print("✅ Successfully subscribed to market ticker")
                print(f"📊 Subscription ID: {response_data.get('sid')}")
            else:
                print(f"❌ Subscription failed: {response_data}")
                return
            
            # Listen for ticker updates
            print("🎧 Listening for market ticker updates...")
            print("=" * 80)
            
            start_time = time.time()
            update_count = 0
            
            while True:
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=30.0)
                    data = json.loads(message)
                    
                    if data.get('type') == 'ticker' or data.get('type') == 'ticker_v2':
                        update_count += 1
                        ticker_data = data.get('msg', {})
                        
                        # Format the ticker update nicely
                        market_ticker = ticker_data.get('market_ticker', 'Unknown')
                        price = ticker_data.get('price', 0) / 100  # Convert from cents
                        yes_bid = ticker_data.get('yes_bid', 0) / 100
                        yes_ask = ticker_data.get('yes_ask', 0) / 100
                        volume = ticker_data.get('volume', 0)
                        open_interest = ticker_data.get('open_interest', 0)
                        ts = ticker_data.get('ts', 0)
                        
                        # Convert timestamp to readable time
                        timestamp_str = datetime.fromtimestamp(ts, EST).strftime('%H:%M:%S')
                        
                        print(f"📊 Ticker Update #{update_count} ({timestamp_str})")
                        print(f"   Market: {market_ticker}")
                        print(f"   Price: ${price:.2f}")
                        print(f"   Bid/Ask: ${yes_bid:.2f} / ${yes_ask:.2f}")
                        print(f"   Volume: {volume:,}")
                        print(f"   Open Interest: {open_interest:,}")
                        print("-" * 40)
                        
                        # Continue running to show live feed (removed 10 update limit)
                        # if update_count >= 10:
                        #     print(f"✅ Received {update_count} ticker updates in {time.time() - start_time:.1f} seconds")
                        #     break
                    
                    elif data.get('type') == 'error':
                        print(f"❌ WebSocket error: {data}")
                        break
                    
                    else:
                        # Print the full message for debugging
                        print(f"📡 Message: {json.dumps(data, indent=2)}")
                
                except asyncio.TimeoutError:
                    print("⏰ No messages received for 30 seconds, continuing to listen...")
                    continue
                except Exception as e:
                    print(f"❌ Error receiving message: {e}")
                    break
            
        except Exception as e:
            print(f"❌ Connection error: {e}")
        finally:
            if self.websocket:
                await self.websocket.close()
                print("🔌 WebSocket connection closed")

async def main():
    """Main test function"""
    print("🚀 Starting Kalshi Market Ticker WebSocket Test")
    print("=" * 80)
    
    try:
        test = KalshiMarketTickerTest()
        await test.connect_and_subscribe()
    except Exception as e:
        print(f"❌ Test failed: {e}")
    
    print("=" * 80)
    print("🏁 Market Ticker WebSocket Test completed")

if __name__ == "__main__":
    asyncio.run(main()) 