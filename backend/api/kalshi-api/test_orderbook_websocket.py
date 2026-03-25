#!/usr/bin/env python3
"""
Kalshi Orderbook WebSocket Test
Tests real-time orderbook updates for BTC markets
"""

import asyncio
import json
import time
from pathlib import Path
import base64
import os
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import websockets
from dotenv import load_dotenv

class KalshiOrderbookWebSocketTest:
    def __init__(self):
        # Load production credentials
        from backend.util.paths import get_kalshi_credentials_dir
        cred_dir = Path(get_kalshi_credentials_dir()) / "prod"
        load_dotenv(cred_dir / '.env')
        
        self.api_key_id = os.getenv('KALSHI_API_KEY_ID')
        self.private_key_path = cred_dir / "kalshi.pem"
        self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        
        # Use current near-the-money BTC markets (BTC is at ~$118,450)
        self.btc_markets = [
            "KXBTCD-25JUL2419-T117999.99",  # $118,000 or above
            "KXBTCD-25JUL2419-T118249.99",  # $118,250 or above
            "KXBTCD-25JUL2419-T118499.99",  # $118,500 or above
            "KXBTCD-25JUL2419-T118749.99",  # $118,750 or above
            "KXBTCD-25JUL2419-T118999.99"   # $119,000 or above
        ]
        
        print(f"🔐 Account Mode: prod")
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
        """Connect to WebSocket and subscribe to orderbook updates"""
        try:
            # Generate authentication headers
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
            
            print(f"🔐 Attempting WebSocket connection with proper Kalshi authentication...")
            
            # Connect to WebSocket
            self.websocket = await websockets.connect(
                self.ws_url,
                additional_headers=headers
            )
            
            print("✅ Connected to Kalshi WebSocket API")
            
            # Subscribe to orderbook updates
            subscription_message = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": self.btc_markets
                }
            }
            
            print(f"📊 Subscribing to orderbook for {len(self.btc_markets)} BTC markets...")
            print(f"📡 Sending subscription: {json.dumps(subscription_message, indent=2)}")
            
            await self.websocket.send(json.dumps(subscription_message))
            
            # Wait for subscription response
            response = await self.websocket.recv()
            response_data = json.loads(response)
            
            print(f"📡 Subscription response: {json.dumps(response_data, indent=2)}")
            
            if response_data.get('type') == 'subscribed':
                print("✅ Successfully subscribed to orderbook_delta updates")
                print(f"📊 Subscription ID: {response_data.get('msg', {}).get('sid')}")
            else:
                print(f"❌ Subscription failed: {response_data}")
                return
            
            print("🎧 Listening for orderbook updates...")
            print("=" * 80)
            
            # Listen for orderbook updates
            update_count = 0
            start_time = time.time()
            
            while True:
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=30.0)
                    data = json.loads(message)
                    
                    if data.get('type') == 'orderbook_snapshot':
                        update_count += 1
                        orderbook_data = data.get('msg', {})
                        
                        print(f"📊 ORDERBOOK SNAPSHOT #{update_count} - {datetime.now().strftime('%H:%M:%S')}")
                        print(f"🎯 Market: {orderbook_data.get('market_ticker', 'Unknown')}")
                        print(f"📈 YES orders: {len(orderbook_data.get('yes', []))} levels")
                        print(f"📉 NO orders: {len(orderbook_data.get('no', []))} levels")
                        
                        # Show top YES orders (highest prices first)
                        yes_orders = orderbook_data.get('yes', [])
                        if yes_orders:
                            print("📈 Top YES orders:")
                            for i, (price, size) in enumerate(yes_orders[:5]):  # Show top 5
                                price_dollars = price / 100  # Convert cents to dollars
                                print(f"   {i+1}. ${price_dollars:.2f} ({size} contracts)")
                        
                        # Show top NO orders (lowest prices first)
                        no_orders = orderbook_data.get('no', [])
                        if no_orders:
                            print("📉 Top NO orders:")
                            for i, (price, size) in enumerate(no_orders[:5]):  # Show top 5
                                price_dollars = price / 100  # Convert cents to dollars
                                print(f"   {i+1}. ${price_dollars:.2f} ({size} contracts)")
                        
                        print("-" * 40)
                        
                    elif data.get('type') == 'orderbook_delta':
                        update_count += 1
                        delta_data = data.get('msg', {})
                        
                        print(f"🔄 RAW ORDERBOOK DELTA #{update_count} - {datetime.now().strftime('%H:%M:%S')}")
                        print(f"📡 FULL MESSAGE:")
                        print(json.dumps(data, indent=2))
                        print(f"📊 DELTA DATA:")
                        print(json.dumps(delta_data, indent=2))
                        print("=" * 80)
                        
                        # Stop after 3 updates to see the raw data
                        if update_count >= 3:
                            print(f"✅ Received {update_count} raw orderbook deltas")
                            break
                        
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
            if hasattr(self, 'websocket'):
                await self.websocket.close()
                print("🔌 WebSocket connection closed")

async def main():
    print("🚀 Starting Kalshi Orderbook WebSocket Test")
    print("=" * 80)
    
    test = KalshiOrderbookWebSocketTest()
    await test.connect_and_subscribe()

if __name__ == "__main__":
    asyncio.run(main()) 