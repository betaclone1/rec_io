#!/usr/bin/env python3

import json
import time
import base64
import uuid
from pathlib import Path
from dotenv import dotenv_values
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import requests

API_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

class KalshiDemo:
    def __init__(self, credentials_dir):
        self.credentials_dir = Path(credentials_dir)
        self.api_key_id = None
        self.private_key = None
        
    def load_credentials(self):
        env_file = self.credentials_dir / ".env"
        env_vars = dotenv_values(env_file)
        self.api_key_id = env_vars.get("KALSHI_API_KEY_ID")
        
        private_key_path = self.credentials_dir / "kalshi.pem"
        with open(private_key_path, 'rb') as f:
            self.private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
            
    def create_signature(self, method, full_path, timestamp):
        message = f"{timestamp}{method.upper()}{full_path}".encode("utf-8")
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode("utf-8")
        
    def make_request(self, method, endpoint, data=None):
        timestamp = str(int(time.time() * 1000))
        path = f"/trade-api/v2{endpoint}"
        full_path = f"/trade-api/v2{endpoint}"
        
        signature = self.create_signature(method, full_path, timestamp)
        
        headers = {
            "Accept": "application/json",
            "User-Agent": "KalshiTradeExec/1.0",
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json"
        }
        
        url = f"{API_BASE_URL}{endpoint}"
        response = requests.request(method, url, headers=headers, json=data)
        return response.json(), response.status_code
        
    def get_market_data(self, ticker):
        data, status = self.make_request("GET", f"/markets/{ticker}")
        return data if status == 200 else None
            
    def get_market_orderbook(self, ticker):
        data, status = self.make_request("GET", f"/markets/{ticker}/orderbook")
        return data if status == 200 else None
            
    def display_orderbook(self, orderbook_data):
        if not orderbook_data or 'orderbook' not in orderbook_data:
            return
            
        orderbook = orderbook_data['orderbook']
        
        print("YES BIDS:")
        if 'yes_dollars' in orderbook and orderbook['yes_dollars']:
            for level in orderbook['yes_dollars']:
                if len(level) >= 2:
                    print(f"  ${level[0]} - {level[1]} contracts")
        else:
            print("  None")
            
        print("NO BIDS:")
        if 'no_dollars' in orderbook and orderbook['no_dollars']:
            for level in orderbook['no_dollars']:
                if len(level) >= 2:
                    print(f"  ${level[0]} - {level[1]} contracts")
        else:
            print("  None")
            
        return orderbook
        
    def display_market_info(self, market_data):
        if not market_data or 'market' not in market_data:
            return
            
        market = market_data['market']
        print(f"Title: {market.get('title', 'N/A')}")
        print(f"Status: {market.get('status', 'N/A')}")
        print(f"YES Bid: ${market.get('yes_bid_dollars', 'N/A')}")
        print(f"YES Ask: ${market.get('yes_ask_dollars', 'N/A')}")
        print(f"NO Bid: ${market.get('no_bid_dollars', 'N/A')}")
        print(f"NO Ask: ${market.get('no_ask_dollars', 'N/A')}")
        print(f"Last Price: ${market.get('last_price_dollars', 'N/A')}")
        print(f"Volume: {market.get('volume', 'N/A')}")
        print(f"Liquidity: ${market.get('liquidity_dollars', 'N/A')}")
        
    def create_order(self, ticker, side, price_dollars):
        order_payload = {
            "ticker": ticker,
            "side": side,
            "type": "limit",
            "count": 1,
            "action": "buy",
            "client_order_id": str(uuid.uuid4())
        }
        
        if side == "yes":
            order_payload["yes_price_dollars"] = f"{price_dollars:.4f}"
        else:
            order_payload["no_price_dollars"] = f"{price_dollars:.4f}"
        
        timestamp = str(int(time.time() * 1000))
        path = "/portfolio/orders"
        full_path = f"/trade-api/v2{path}"
        
        signature = self.create_signature("POST", full_path, timestamp)
        
        headers = {
            "Accept": "application/json",
            "User-Agent": "KalshiTradeExec/1.0",
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json"
        }
        
        url = f"{API_BASE_URL}{path}"
        response = requests.post(url, headers=headers, json=order_payload, timeout=10)
        
        if response.status_code not in [200, 201]:
            print(f"Order creation failed: {response.status_code}")
            print(f"Response: {response.text}")
        return response.json() if response.status_code in [200, 201] else None
        
    def cancel_order(self, order_id):
        data, status = self.make_request("DELETE", f"/portfolio/orders/{order_id}")
        return data if status in [200, 201] else None
        
    def run_demo(self, ticker):
        self.load_credentials()
        
        market_data = self.get_market_data(ticker)
        if market_data:
            self.display_market_info(market_data)
        
        print()
        orderbook_data = self.get_market_orderbook(ticker)
        if orderbook_data:
            orderbook = self.display_orderbook(orderbook_data)
            
            # Create order 10 cents below lowest NO bid
            if 'no_dollars' in orderbook and orderbook['no_dollars']:
                lowest_no_bid = float(orderbook['no_dollars'][0][0])
                order_price = lowest_no_bid - 0.10
                
                print()
                print(f"Creating NO order at ${order_price:.2f} (10 cents below lowest NO bid of ${lowest_no_bid:.2f})")
                
                order_result = self.create_order(ticker, "no", order_price)
                if order_result and 'order' in order_result:
                    order_id = order_result['order']['order_id']
                    print(f"Order created: {order_id}")
                    
                    print("Cancelling order...")
                    cancel_result = self.cancel_order(order_id)
                    if cancel_result:
                        print("Order cancelled successfully")
                    else:
                        print("Failed to cancel order")
                else:
                    print("Failed to create order")

def main():
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python3 kalshi_standalone_demo.py <credentials_directory>")
        sys.exit(1)
    
    credentials_dir = sys.argv[1]
    ticker = "KXRAINNYC-25SEP29-T0"
    
    demo = KalshiDemo(credentials_dir)
    demo.run_demo(ticker)

if __name__ == "__main__":
    main()
