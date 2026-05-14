#!/usr/bin/env python3
"""
Raw Orderbook Data Capture
Shows the exact raw data coming from the Kalshi orderbook websocket
"""

import asyncio
import json
import time
import base64
import os
import sys
from datetime import datetime
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import websockets
from dotenv import load_dotenv

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

class RawOrderbookData:
    def __init__(self):
        # Load production credentials
        from backend.util.paths import get_kalshi_credentials_dir
        cred_dir = Path(get_kalshi_credentials_dir()) / "prod"
        load_dotenv(cred_dir / '.env')
        
        self.api_key_id = os.getenv('KALSHI_API_KEY_ID')
        self.private_key_path = cred_dir / "kalshi.pem"
        self.ws_url = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
        
        # Use current near-the-money BTC markets (BTC is at ~$118,450)
        self.btc_markets = [
            "KXBTCD-25JUL2419-T117999.99",  # $118,000 or above
            "KXBTCD-25JUL2419-T118249.99",  # $118,250 or above
            "KXBTCD-25JUL2419-T118499.99",  # $118,500 or above
            "KXBTCD-25JUL2419-T118749.99",  # $118,750 or above
            "KXBTCD-25JUL2419-T118999.99"   # $119,000 or above
        ]
        
        self.websocket = None
        self.running = False

    def generate_signature(self, timestamp_ms):
        """Generate Kalshi API signature"""
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
        """Connect to websocket and subscribe to orderbook updates"""
        try:
            # Generate authentication headers
            timestamp_ms = str(int(time.time() * 1000))
            signature = self.generate_signature(timestamp_ms)
            
            if not signature:
                print("❌ Failed to generate signature")
                return False
            
            # Use the correct Kalshi header names
            headers = {
                "KALSHI-ACCESS-KEY": self.api_key_id,
                "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
                "KALSHI-ACCESS-SIGNATURE": signature
            }
            
            print(f"🔌 Connecting to Kalshi WebSocket: {self.ws_url}")
            self.websocket = await websockets.connect(
                self.ws_url,
                additional_headers=headers
            )
            
            # Subscribe to orderbook updates
            subscription_message = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": self.btc_markets
                }
            }
            
            await self.websocket.send(json.dumps(subscription_message))
            print(f"✅ Successfully subscribed to orderbook_delta updates for {len(self.btc_markets)} markets")
            
            return True
            
        except Exception as e:
            print(f"❌ Error connecting to websocket: {e}")
            return False

    async def run(self):
        """Main run loop - just capture and display raw data"""
        print("🚀 Starting Raw Orderbook Data Capture")
        print("=" * 80)
        
        if not await self.connect_and_subscribe():
            return
        
        self.running = True
        message_count = 0
        
        try:
            while self.running:
                try:
                    # Wait for messages with timeout
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=30.0)
                    message_count += 1
                    
                    # Display the raw message exactly as received
                    print(f"\n📡 RAW MESSAGE #{message_count} - {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
                    print("=" * 80)
                    print(message)
                    print("=" * 80)
                    
                    # Stop after 10 messages to see the raw data
                    if message_count >= 10:
                        print(f"\n✅ Captured {message_count} raw messages")
                        break
                    
                except asyncio.TimeoutError:
                    print("⏰ No messages received for 30 seconds, continuing to listen...")
                    continue
                    
        except websockets.exceptions.ConnectionClosed:
            print("🔌 WebSocket connection closed")
        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")
        except Exception as e:
            print(f"❌ Error in main loop: {e}")
        finally:
            self.running = False
            if self.websocket:
                await self.websocket.close()
            
            print(f"✅ Service stopped. Captured {message_count} raw messages")

async def main():
    """Main entry point"""
    service = RawOrderbookData()
    await service.run()

if __name__ == "__main__":
    asyncio.run(main()) 