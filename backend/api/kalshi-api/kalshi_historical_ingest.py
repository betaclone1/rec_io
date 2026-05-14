import sys
import sqlite3
import psycopg2
import requests
import json
import time
import os
from decimal import Decimal
from dotenv import dotenv_values
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes

from backend.util.paths import get_project_root, get_accounts_data_dir
sys.path.insert(0, get_project_root())
from backend.core.config.settings import config
from backend.core.time_eastern import merge_psycopg2_connect_kwargs

# Usage: python kalshi_historical_ingest.py [prod|demo]

def _pg_connect():
    return psycopg2.connect(
        **merge_psycopg2_connect_kwargs(
            {
                "host": "localhost",
                "database": "rec_io_db",
                "user": "rec_io_user",
                "password": "rec_io_password",
            }
        )
    )

mode = "prod"
from backend.util.paths import get_kalshi_credentials_dir
CREDENTIALS_DIR = Path(get_kalshi_credentials_dir()) / "prod"
ENV_VARS = dotenv_values(CREDENTIALS_DIR / ".env")

KEY_ID = ENV_VARS.get("KALSHI_API_KEY_ID")
KEY_PATH = CREDENTIALS_DIR / Path(ENV_VARS.get("KALSHI_PRIVATE_KEY_PATH")).name


def _fp_to_numeric(v):
    """Convert API _fp string to Decimal for NUMERIC columns; None/empty -> None."""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _outcome_orderbook_from_api(obj: dict):
    if not obj:
        return None, None
    outcome = (obj.get("outcome_side") or obj.get("side") or obj.get("purchased_side") or "")
    outcome = str(outcome).strip().lower() or None
    if outcome not in ("yes", "no"):
        outcome = None
    book = (obj.get("book_side") or obj.get("orderbook_side") or "")
    book = str(book).strip().lower() or None
    if not book and outcome in ("yes", "no"):
        book = "bid" if outcome == "yes" else "ask"
    return outcome, book


def _dollars_to_cents(value):
    """
    Convert Kalshi *_dollars string/number fields to integer cents for storage in legacy columns.

    We keep both:
    - *_dollars TEXT in the DB mirroring the API field
    - integer cent columns for existing consumers.
    """
    if value is None:
        return None
    try:
        if isinstance(value, str):
            return int(round(float(value) * 100))
        if isinstance(value, (int, float, Decimal)):
            return int(round(float(value) * 100))
        return None
    except Exception:
        return None


def generate_kalshi_signature(method, full_path, timestamp, key_path):
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
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )

    return base64.b64encode(signature).decode("utf-8")

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
print(f"Using base URL: {BASE_URL} (prod)")

def sync_settlements():
    print("⏱ Syncing all settlements...")
    method = "GET"
    path = "/portfolio/settlements"
    all_settlements = []
    cursor = ""

    while True:
        print(f"➡️ Cursor: {cursor}")
        timestamp = str(int(time.time() * 1000))
        query = f"?limit=100"
        if cursor:
            query += f"&cursor={cursor}"
        url = f"{BASE_URL}{path}{query}"
        print(f"🔗 Requesting: {url}")

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
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            print("Response keys:", data.keys())
            if "error" in data:
                print("⚠️ API error:", data["error"])
            all_settlements.extend(data.get("settlements", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception as e:
            print(f"❌ Failed to fetch settlements: {e}")
            break

    output_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "settlements.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({"settlements": all_settlements}, f, indent=2)
    print(f"💾 All settlements written to {output_path}")

def sync_fills():
    print("⏱ Syncing all fills...")
    method = "GET"
    path = "/portfolio/fills"
    all_fills = []
    cursor = ""

    while True:
        print(f"➡️ Cursor: {cursor}")
        timestamp = str(int(time.time() * 1000))
        query = f"?limit=100"
        if cursor:
            query += f"&cursor={cursor}"
        url = f"{BASE_URL}{path}{query}"
        print(f"🔗 Requesting: {url}")

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
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            print("Response keys:", data.keys())
            if "error" in data:
                print("⚠️ API error:", data["error"])
            all_fills.extend(data.get("fills", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception as e:
            print(f"❌ Failed to fetch fills: {e}")
            break

    output_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "fills.json")
    if all_fills:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump({"fills": all_fills}, f, indent=2)
        print(f"💾 All fills written to {output_path}")
    else:
        print("⚠️ No fills found, skipping file write.")

    # PostgreSQL insertion via write_fills_to_db()


def sync_orders():
    """Paginate through all orders from API and save to orders.json."""
    print("⏱ Syncing all orders...")
    method = "GET"
    path = "/portfolio/orders"
    all_orders = []
    cursor = ""

    while True:
        print(f"➡️ Orders cursor: {cursor or '(start)'}")
        timestamp = str(int(time.time() * 1000))
        query = "?limit=100"
        if cursor:
            query += f"&cursor={cursor}"
        url = f"{BASE_URL}{path}{query}"
        print(f"🔗 Requesting: {url}")

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
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                print("⚠️ API error:", data["error"])
                break
            orders = data.get("orders", [])
            all_orders.extend(orders)
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception as e:
            print(f"❌ Failed to fetch orders: {e}")
            break

    output_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "orders.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({"orders": all_orders}, f, indent=2)
    print(f"💾 All orders ({len(all_orders)}) written to {output_path}")


def write_settlements_to_db():
    global mode
    print("💾 Writing settlements to PostgreSQL database...")
    settlements_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "settlements.json")

    with open(settlements_path, "r") as f:
        data = json.load(f)
        settlements = data.get("settlements", [])

    try:
        conn = _pg_connect()
        c = conn.cursor()

        # Create settlements table if it doesn't exist (fixed-point counts and *_total_cost_dollars)
        c.execute("""
            CREATE TABLE IF NOT EXISTS users.settlements_0001 (
                id SERIAL PRIMARY KEY,
                ticker TEXT,
                market_result TEXT,
                revenue DECIMAL(10,2),
                settled_time TEXT,
                raw_json TEXT,
                yes_count_fp NUMERIC(12,2),
                no_count_fp NUMERIC(12,2),
                yes_total_cost_dollars DECIMAL(10,2),
                no_total_cost_dollars DECIMAL(10,2),
                UNIQUE(ticker, settled_time)
            )
        """)

        for s in settlements:
            ticker = s.get("ticker")
            market_result = s.get("market_result")
            yes_count_fp = _fp_to_numeric(s.get("yes_count_fp"))
            no_count_fp = _fp_to_numeric(s.get("no_count_fp"))
            revenue = s.get("revenue")
            settled_time = s.get("settled_time")
            raw_json = json.dumps(s)

            yes_total_cost_dollars = s.get("yes_total_cost_dollars")
            if yes_total_cost_dollars is None and s.get("yes_total_cost") is not None:
                yes_total_cost_dollars = float(s["yes_total_cost"]) / 100
            no_total_cost_dollars = s.get("no_total_cost_dollars")
            if no_total_cost_dollars is None and s.get("no_total_cost") is not None:
                no_total_cost_dollars = float(s["no_total_cost"]) / 100

            try:
                revenue = float(revenue) / 100 if revenue is not None else None
                if yes_total_cost_dollars is not None and not isinstance(yes_total_cost_dollars, (int, float)):
                    yes_total_cost_dollars = float(yes_total_cost_dollars)
                if no_total_cost_dollars is not None and not isinstance(no_total_cost_dollars, (int, float)):
                    no_total_cost_dollars = float(no_total_cost_dollars)
            except Exception as e:
                print(f"⚠️ Error formatting cost fields for {ticker} at {settled_time}: {e}")
                continue

            try:
                c.execute("""
                    INSERT INTO users.settlements_0001
                    (ticker, market_result, revenue, settled_time, raw_json,
                     yes_count_fp, no_count_fp, yes_total_cost_dollars, no_total_cost_dollars)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, settled_time) DO NOTHING
                """, (ticker, market_result, revenue, settled_time, raw_json,
                      yes_count_fp, no_count_fp, yes_total_cost_dollars, no_total_cost_dollars))
            except Exception as e:
                print(f"❌ Failed to insert settlement {ticker} at {settled_time}: {e}")

        conn.commit()
        conn.close()
        print(f"✅ Settlements written to PostgreSQL database")
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")

def write_fills_to_db():
    global mode
    print("💾 Writing fills to PostgreSQL database...")
    fills_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "fills.json")

    with open(fills_path, "r") as f:
        data = json.load(f)
        fills = data.get("fills", [])

    try:
        conn = _pg_connect()
        c = conn.cursor()

        # Create fills table if it doesn't exist (columns align with Kalshi API _dollars)
        c.execute("""
            CREATE TABLE IF NOT EXISTS users.fills_0001 (
                trade_id TEXT PRIMARY KEY,
                ticker TEXT,
                order_id TEXT,
                outcome_side TEXT,
                orderbook_side TEXT,
                action TEXT,
                count_fp NUMERIC(12,2),
                yes_price_dollars TEXT,
                no_price_dollars TEXT,
                is_taker BOOLEAN,
                created_time TEXT,
                raw_json TEXT
            )
        """)

        for fill in fills:
            trade_id = fill.get("trade_id")
            ticker = fill.get("ticker")
            order_id = fill.get("order_id")
            out_side, ob_side = _outcome_orderbook_from_api(fill)
            action = fill.get("action")
            count_fp = _fp_to_numeric(fill.get("count_fp"))
            yes_price_dollars = fill.get("yes_price_dollars") or fill.get("yes_price_fixed")
            no_price_dollars = fill.get("no_price_dollars") or fill.get("no_price_fixed")
            is_taker = fill.get("is_taker")
            created_time = fill.get("created_time")
            raw_json = json.dumps(fill)

            try:
                c.execute("""
                    INSERT INTO users.fills_0001
                    (trade_id, ticker, order_id, outcome_side, orderbook_side, action, count_fp, yes_price_dollars, no_price_dollars, is_taker, created_time, raw_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (trade_id) DO NOTHING
                """, (trade_id, ticker, order_id, out_side, ob_side, action, count_fp, yes_price_dollars, no_price_dollars, is_taker, created_time, raw_json))
            except Exception as e:
                print(f"❌ Failed to insert fill {trade_id}: {e}")

        conn.commit()
        conn.close()
        print(f"✅ Fills written to PostgreSQL database")
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")

def write_positions_to_db():
    global mode
    print("💾 Writing positions to PostgreSQL database...")
    method = "GET"
    path = "/portfolio/positions"
    cursor = ""
    all_positions = []

    while True:
        print(f"➡️ Cursor: {cursor}")
        timestamp = str(int(time.time() * 1000))
        query = f"?limit=100"
        if cursor:
            query += f"&cursor={cursor}"
        url = f"{BASE_URL}{path}{query}"
        print(f"🔗 Requesting: {url}")

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
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            print("🔍 Full response from positions endpoint:", json.dumps(data, indent=2))
            print("Response keys:", data.keys())
            if "error" in data:
                print("⚠️ API error:", data["error"])
            market_positions = data.get("market_positions", [])
            event_positions = data.get("event_positions", [])
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception as e:
            print(f"❌ Failed to fetch positions: {e}")
            return

    positions = market_positions
    # Save positions JSON to file
    json_output_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "positions.json")
    os.makedirs(os.path.dirname(json_output_path), exist_ok=True)
    with open(json_output_path, "w") as f:
        json.dump({"market_positions": market_positions, "event_positions": event_positions}, f, indent=2)
    print(f"💾 All positions written to {json_output_path}")

    try:
        conn = _pg_connect()
        c = conn.cursor()

        # Create positions table if it doesn't exist (fixed-point / dollars only)
        c.execute("""
            CREATE TABLE IF NOT EXISTS users.positions_0001 (
                id SERIAL PRIMARY KEY,
                ticker TEXT,
                last_updated_ts TEXT,
                raw_json TEXT,
                total_traded_dollars TEXT,
                market_exposure_dollars TEXT,
                realized_pnl_dollars TEXT,
                fees_paid_dollars TEXT,
                total_traded_fp NUMERIC(12,2),
                position_fp NUMERIC(12,2)
            )
        """)

        # Clear existing positions data
        c.execute("DELETE FROM users.positions_0001")

        for p in positions:
            try:
                ticker = p.get("ticker")
                last_updated_ts = p.get("last_updated_ts")
                raw_json = json.dumps(p)

                total_traded_dollars = p.get("total_traded_dollars")
                market_exposure_dollars = p.get("market_exposure_dollars")
                realized_pnl_dollars = p.get("realized_pnl_dollars")
                fees_paid_dollars = p.get("fees_paid_dollars")
                total_traded_fp = _fp_to_numeric(p.get("total_traded_fp"))
                position_fp = _fp_to_numeric(p.get("position_fp"))

                c.execute("""
                    INSERT INTO users.positions_0001
                    (ticker, last_updated_ts, raw_json,
                     total_traded_dollars, market_exposure_dollars, realized_pnl_dollars, fees_paid_dollars,
                     total_traded_fp, position_fp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (ticker, last_updated_ts, raw_json,
                      total_traded_dollars, market_exposure_dollars, realized_pnl_dollars, fees_paid_dollars,
                      total_traded_fp, position_fp))
            except Exception as e:
                print(f"❌ Failed to insert position {p.get('ticker')}: {e}")

        conn.commit()
        conn.close()
        print(f"✅ Positions written to PostgreSQL database")
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")


def write_orders_to_db():
    """Read orders.json and upsert into users.orders_0001 (fixed-point / *_dollars only)."""
    global mode
    print("💾 Writing orders to PostgreSQL database...")
    orders_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "orders.json")
    if not os.path.exists(orders_path):
        print("⚠️ No orders.json found; run sync_orders() first.")
        return
    with open(orders_path, "r") as f:
        data = json.load(f)
    orders = data.get("orders", [])

    try:
        conn = _pg_connect()
        c = conn.cursor()

        for order in orders:
            order_id = order.get("order_id")
            if not order_id:
                continue
            out_side, ob_side = _outcome_orderbook_from_api(order)
            try:
                c.execute("""
                    INSERT INTO users.orders_0001
                    (order_id, user_id, ticker, status, action, outcome_side, orderbook_side, type,
                     yes_price_dollars, no_price_dollars,
                     initial_count_fp, remaining_count_fp, fill_count_fp,
                     created_time, expiration_time, last_update_time, client_order_id, order_group_id, queue_position,
                     self_trade_prevention_type,
                     maker_fees_dollars, taker_fees_dollars, maker_fill_cost_dollars, taker_fill_cost_dollars,
                     raw_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s, %s, %s,
                            %s,
                            %s, %s, %s, %s,
                            %s)
                    ON CONFLICT (order_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        fill_count_fp = EXCLUDED.fill_count_fp,
                        remaining_count_fp = EXCLUDED.remaining_count_fp,
                        last_update_time = EXCLUDED.last_update_time,
                        outcome_side = EXCLUDED.outcome_side,
                        orderbook_side = EXCLUDED.orderbook_side,
                        maker_fees_dollars = EXCLUDED.maker_fees_dollars,
                        taker_fees_dollars = EXCLUDED.taker_fees_dollars,
                        maker_fill_cost_dollars = EXCLUDED.maker_fill_cost_dollars,
                        taker_fill_cost_dollars = EXCLUDED.taker_fill_cost_dollars,
                        queue_position = EXCLUDED.queue_position,
                        raw_json = EXCLUDED.raw_json
                """, (
                    order_id,
                    order.get("user_id"),
                    order.get("ticker"),
                    order.get("status"),
                    order.get("action"),
                    out_side,
                    ob_side,
                    order.get("type"),
                    order.get("yes_price_dollars"),
                    order.get("no_price_dollars"),
                    _fp_to_numeric(order.get("initial_count_fp")),
                    _fp_to_numeric(order.get("remaining_count_fp")),
                    _fp_to_numeric(order.get("fill_count_fp")),
                    order.get("created_time"),
                    order.get("expiration_time"),
                    order.get("last_update_time"),
                    order.get("client_order_id"),
                    order.get("order_group_id"),
                    order.get("queue_position"),
                    order.get("self_trade_prevention_type"),
                    order.get("maker_fees_dollars"),
                    order.get("taker_fees_dollars"),
                    order.get("maker_fill_cost_dollars"),
                    order.get("taker_fill_cost_dollars"),
                    json.dumps(order),
                ))
            except Exception as e:
                print(f"❌ Failed to insert/update order {order_id}: {e}")

        conn.commit()
        conn.close()
        print(f"✅ Orders written to PostgreSQL database")
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")


def get_settlements_data():
    """Fetch settlements from Kalshi API. Stub until wired to API (was undefined)."""
    return {"settlements": []}


def get_fills_data():
    """Fetch fills from Kalshi API. Stub until wired to API (was undefined)."""
    return {"fills": []}


def get_positions_data():
    """Fetch positions from Kalshi API. Stub until wired to API (was undefined)."""
    return {"positions": []}


def ingest_settlements():
    """Ingest settlements data."""
    print(f"🔄 Ingesting settlements for mode: {mode}")
    
    try:
        # Get settlements data
        settlements_data = get_settlements_data()
        if not settlements_data:
            print("❌ No settlements data available")
            return
        
        # Save to JSON file
        output_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "settlements.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(settlements_data, f, indent=2)
        
        print(f"✅ Settlements saved to: {output_path}")
        
        # Save to SQLite database
        settlements_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "settlements.json")
        db_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "settlements.db")
        
        # Create database and table
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settlements (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                market_id TEXT,
                amount INTEGER,
                created_time TEXT,
                updated_time TEXT
            )
        """)
        
        # Insert settlements data
        for settlement in settlements_data.get("settlements", []):
            cursor.execute("""
                INSERT OR REPLACE INTO settlements 
                (id, user_id, market_id, amount, created_time, updated_time)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                settlement.get("id"),
                settlement.get("user_id"),
                settlement.get("market_id"),
                settlement.get("amount"),
                settlement.get("created_time"),
                settlement.get("updated_time")
            ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Settlements database updated: {db_path}")
        
    except Exception as e:
        print(f"❌ Error ingesting settlements: {e}")

def ingest_fills():
    """Ingest fills data."""
    print(f"🔄 Ingesting fills for mode: {mode}")
    
    try:
        # Get fills data
        fills_data = get_fills_data()
        if not fills_data:
            print("❌ No fills data available")
            return
        
        # Save to JSON file
        output_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "fills.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(fills_data, f, indent=2)
        
        print(f"✅ Fills saved to: {output_path}")
        
        # Save to SQLite database
        fills_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "fills.json")
        db_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "fills.db")
        
        # Create database and table
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                market_id TEXT,
                order_id TEXT,
                side TEXT,
                count INTEGER,
                price INTEGER,
                created_time TEXT
            )
        """)
        
        # Insert fills data
        for fill in fills_data.get("fills", []):
            cursor.execute("""
                INSERT OR REPLACE INTO fills 
                (id, user_id, market_id, order_id, side, count, price, created_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fill.get("id"),
                fill.get("user_id"),
                fill.get("market_id"),
                fill.get("order_id"),
                fill.get("side"),
                fill.get("count"),
                fill.get("price"),
                fill.get("created_time")
            ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Fills database updated: {db_path}")
        
    except Exception as e:
        print(f"❌ Error ingesting fills: {e}")

def ingest_positions():
    """Ingest positions data."""
    print(f"🔄 Ingesting positions for mode: {mode}")
    
    try:
        # Get positions data
        positions_data = get_positions_data()
        if not positions_data:
            print("❌ No positions data available")
            return
        
        # Save to JSON file
        json_output_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "positions.json")
        os.makedirs(os.path.dirname(json_output_path), exist_ok=True)
        
        with open(json_output_path, 'w') as f:
            json.dump(positions_data, f, indent=2)
        
        print(f"✅ Positions saved to: {json_output_path}")
        
        # Save to SQLite database
        db_path = os.path.join(get_accounts_data_dir(), "kalshi", mode, "positions.db")
        
        # Create database and table
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                market_id TEXT,
                side TEXT,
                count INTEGER,
                average_price INTEGER,
                created_time TEXT,
                updated_time TEXT
            )
        """)
        
        # Insert positions data
        for position in positions_data.get("positions", []):
            cursor.execute("""
                INSERT OR REPLACE INTO positions 
                (id, user_id, market_id, side, count, average_price, created_time, updated_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position.get("id"),
                position.get("user_id"),
                position.get("market_id"),
                position.get("side"),
                position.get("count"),
                position.get("average_price"),
                position.get("created_time"),
                position.get("updated_time")
            ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Positions database updated: {db_path}")
        
    except Exception as e:
        print(f"❌ Error ingesting positions: {e}")

def main():
    sync_settlements()
    write_settlements_to_db()
    sync_fills()
    write_fills_to_db()
    sync_orders()
    write_orders_to_db()
    write_positions_to_db()

if __name__ == "__main__":
    main()