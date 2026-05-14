#!/usr/bin/env python3
"""
Kalshi API Sample Script for Advanced API Access Application
Demonstrates querying market data and order book for NYC weather market
"""

import sys
import os
import json
import time
import base64
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import dotenv_values
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import requests

# Add project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Import from backend modules
from backend.account_mode import get_account_mode
from backend.util.paths import get_kalshi_credentials_dir

# Configuration
API_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
EST = ZoneInfo("America/New_York")

class KalshiAPIDemo:
    def __init__(self):
        self.account_mode = get_account_mode()
        self.api_key_id = None
        self.private_key = None
        
    def load_credentials(self):
        """Load Kalshi API credentials"""
        print(f"📊 Account Mode: {self.account_mode}")
        
        # Load credentials from the appropriate directory
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
        
    def make_authenticated_request(self, method, endpoint, data=None):
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
        
        response = requests.request(method, url, headers=headers, json=data)
        return response.json(), response.status_code
        
    def get_market_data(self, ticker):
        """Get market data for a specific ticker"""
        print(f"\n📊 Getting market data for ticker: {ticker}")
        try:
            data, status = self.make_authenticated_request("GET", f"/markets/{ticker}")
            if status == 200:
                print("✅ Market data retrieved successfully")
                return data
            else:
                print(f"❌ Error getting market data: {status}")
                print(json.dumps(data, indent=2))
                return None
        except Exception as e:
            print(f"❌ Exception getting market data: {e}")
            return None
            
    def get_market_orderbook(self, ticker):
        """Get market order book for a specific ticker"""
        print(f"\n📊 Getting order book for ticker: {ticker}")
        try:
            data, status = self.make_authenticated_request("GET", f"/markets/{ticker}/orderbook")
            if status == 200:
                print("✅ Order book retrieved successfully")
                return data
            else:
                print(f"❌ Error getting order book: {status}")
                print(json.dumps(data, indent=2))
                return None
        except Exception as e:
            print(f"❌ Exception getting order book: {e}")
            return None
            
    def format_orderbook_display(self, orderbook_data):
        """Format and display the order book in a readable way"""
        if not orderbook_data or 'orderbook' not in orderbook_data:
            print("❌ No order book data to display")
            return
            
        orderbook = orderbook_data['orderbook']
        
        print("\n" + "="*60)
        print("📊 ORDER BOOK DISPLAY")
        print("="*60)
        
        # Display YES side using dollar amounts
        print("\n🟢 YES BIDS:")
        if 'yes_dollars' in orderbook and orderbook['yes_dollars']:
            for i, level in enumerate(orderbook['yes_dollars'][:10]):  # Show top 10 levels
                if len(level) >= 2:
                    price_dollars = level[0]
                    quantity = level[1]
                    print(f"  {i+1:2d}. ${price_dollars} - {quantity} contracts")
        else:
            print("  No YES bids available")
            
        # Display NO side using dollar amounts
        print("\n🔴 NO BIDS:")
        if 'no_dollars' in orderbook and orderbook['no_dollars']:
            for i, level in enumerate(orderbook['no_dollars'][:10]):  # Show top 10 levels
                if len(level) >= 2:
                    price_dollars = level[0]
                    quantity = level[1]
                    print(f"  {i+1:2d}. ${price_dollars} - {quantity} contracts")
        else:
            print("  No NO bids available")
        
        print("\n" + "="*60)
        
    def display_market_info(self, market_data):
        """Display key market information"""
        if not market_data or 'market' not in market_data:
            print("❌ No market data to display")
            return
            
        market = market_data['market']
        
        print("\n" + "="*60)
        print("📊 MARKET INFORMATION")
        print("="*60)
        print(f"Ticker: {market.get('ticker', 'N/A')}")
        print(f"Title: {market.get('title', 'N/A')}")
        print(f"Status: {market.get('status', 'N/A')}")
        print(f"Market Type: {market.get('market_type', 'N/A')}")
        
        # Price information
        if 'yes_bid_dollars' in market:
            print(f"YES Bid: ${market['yes_bid_dollars']}")
        if 'yes_ask_dollars' in market:
            print(f"YES Ask: ${market['yes_ask_dollars']}")
        if 'no_bid_dollars' in market:
            print(f"NO Bid: ${market['no_bid_dollars']}")
        if 'no_ask_dollars' in market:
            print(f"NO Ask: ${market['no_ask_dollars']}")
        if 'last_price_dollars' in market:
            print(f"Last Price: ${market['last_price_dollars']}")
            
        # Volume and liquidity
        if 'volume' in market:
            print(f"Volume: {market['volume']}")
        if 'liquidity_dollars' in market:
            print(f"Liquidity: ${market['liquidity_dollars']}")
            
        # Time information
        if 'open_time' in market:
            print(f"Open Time: {market['open_time']}")
        if 'close_time' in market:
            print(f"Close Time: {market['close_time']}")
        if 'expiration_time' in market:
            print(f"Expiration Time: {market['expiration_time']}")
            
        print("="*60)
        
    def run_demo(self, ticker):
        """Run the complete demo"""
        print("🚀 Starting Kalshi API Demo")
        print(f"📅 {datetime.now(EST).strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"🎯 Target Ticker: {ticker}")
        
        try:
            # Load credentials
            self.load_credentials()
            
            # Step 1: Get market data
            print("\n" + "="*50)
            print("STEP 1: GET MARKET DATA")
            print("="*50)
            market_data = self.get_market_data(ticker)
            if market_data:
                self.display_market_info(market_data)
            
            # Step 2: Get order book
            print("\n" + "="*50)
            print("STEP 2: GET ORDER BOOK")
            print("="*50)
            orderbook_data = self.get_market_orderbook(ticker)
            if orderbook_data:
                self.format_orderbook_display(orderbook_data)
            
            print("\n✅ Demo completed successfully!")
            
        except Exception as e:
            print(f"\n❌ Demo failed: {e}")
            import traceback
            traceback.print_exc()

def main():
    """Main function"""
    # Use the specified ticker for NYC weather
    ticker = "KXRAINNYC-25SEP29-T0"
    
    demo = KalshiAPIDemo()
    demo.run_demo(ticker)

if __name__ == "__main__":
    main()
