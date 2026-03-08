# Coinbase Symbol Feed API Contract Reference

## Overview
This document provides the complete API contract for Coinbase integration, specifically for Bitcoin price data and symbol feed functionality used in the REC.IO trading system.

**Last Verified**: 2025-01-27  
**API Version**: v2  
**Base URL**: https://api.coinbase.com/v2

---

## Authentication

### Public API Access
Coinbase public API endpoints do not require authentication for basic price data access.

### Rate Limiting
- **Requests per minute**: 1000
- **Requests per second**: 10
- **IP-based limiting**: Yes

### Headers
```python
headers = {
    'User-Agent': 'REC.IO Trading System/1.0',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}
```

---

## REST API Endpoints

### 1. Price Data

#### Get Current Price
```http
GET /prices/{currency_pair}/spot
```

**Parameters**:
- `currency_pair`: BTC-USD, ETH-USD, etc.

**Response Example**:
```json
{
  "data": {
    "base": "BTC",
    "currency": "USD",
    "amount": "43251.23"
  }
}
```

**Error Codes**:
- `400`: Invalid currency pair
- `404`: Currency pair not found
- `429`: Rate limit exceeded
- `500`: Internal server error

#### Get Historical Prices
```http
GET /products/{product_id}/candles
```

**Parameters**:
- `product_id`: BTC-USD
- `start`: ISO 8601 timestamp
- `end`: ISO 8601 timestamp
- `granularity`: 60, 300, 900, 3600, 21600, 86400 (seconds)

**Response Example**:
```json
[
  [1640995200, 46250.12, 46300.45, 46100.78, 46250.12, 1250.5],
  [1640995260, 46250.12, 46350.67, 46200.34, 46300.45, 980.2]
]
```

**Data Format**: [timestamp, open, high, low, close, volume]

### 2. Product Information

#### Get Products
```http
GET /products
```

**Response Example**:
```json
{
  "data": [
    {
      "id": "BTC-USD",
      "base_currency": "BTC",
      "quote_currency": "USD",
      "base_min_size": "0.00000001",
      "base_max_size": "1000",
      "quote_increment": "0.01",
      "display_name": "Bitcoin",
      "status": "online",
      "status_message": "",
      "cancel_only": false,
      "limit_only": false,
      "post_only": false,
      "trading_disabled": false,
      "fx_stablecoin": false,
      "max_slippage_percentage": "0.03000000",
      "auction_mode": false
    }
  ]
}
```

#### Get Product Details
```http
GET /products/{product_id}
```

**Response Example**:
```json
{
  "data": {
    "id": "BTC-USD",
    "base_currency": "BTC",
    "quote_currency": "USD",
    "base_min_size": "0.00000001",
    "base_max_size": "1000",
    "quote_increment": "0.01",
    "display_name": "Bitcoin",
    "status": "online",
    "status_message": "",
    "cancel_only": false,
    "limit_only": false,
    "post_only": false,
    "trading_disabled": false,
    "fx_stablecoin": false,
    "max_slippage_percentage": "0.03000000",
    "auction_mode": false
  }
}
```

### 3. Market Data

#### Get Product Ticker
```http
GET /products/{product_id}/ticker
```

**Response Example**:
```json
{
  "data": {
    "trade_id": 123456,
    "price": "46250.12",
    "size": "0.1",
    "time": "2024-01-27T10:30:00.000000Z",
    "bid": "46245.67",
    "ask": "46255.23",
    "volume": "1250.5"
  }
}
```

#### Get Product Stats
```http
GET /products/{product_id}/stats
```

**Response Example**:
```json
{
  "data": {
    "open": "46100.78",
    "high": "46500.45",
    "low": "45800.12",
    "last": "46250.12",
    "volume": "1250.5",
    "volume_30d": "45000.2"
  }
}
```

---

## WebSocket Feed (Advanced)

### Connection
```python
# WebSocket connection URL
ws_url = "wss://ws-feed.pro.coinbase.com"
```

### Subscription Messages

#### Subscribe to Ticker
```json
{
  "type": "subscribe",
  "product_ids": ["BTC-USD"],
  "channels": ["ticker"]
}
```

#### Subscribe to Heartbeat
```json
{
  "type": "subscribe",
  "product_ids": ["BTC-USD"],
  "channels": ["heartbeat"]
}
```

#### Subscribe to Level2
```json
{
  "type": "subscribe",
  "product_ids": ["BTC-USD"],
  "channels": ["level2"]
}
```

### Message Types

#### Ticker Message
```json
{
  "type": "ticker",
  "sequence": 123456789,
  "product_id": "BTC-USD",
  "price": "46250.12",
  "open_24h": "46100.78",
  "volume_24h": "1250.5",
  "low_24h": "45800.12",
  "high_24h": "46500.45",
  "volume_30d": "45000.2",
  "best_bid": "46245.67",
  "best_ask": "46255.23",
  "side": "buy",
  "time": "2024-01-27T10:30:00.000000Z",
  "trade_id": 123456,
  "last_size": "0.1"
}
```

#### Heartbeat Message
```json
{
  "type": "heartbeat",
  "sequence": 123456789,
  "product_id": "BTC-USD",
  "time": "2024-01-27T10:30:00.000000Z"
}
```

#### Level2 Snapshot
```json
{
  "type": "snapshot",
  "product_id": "BTC-USD",
  "asks": [
    ["46255.23", "0.5"],
    ["46256.78", "1.2"]
  ],
  "bids": [
    ["46245.67", "0.8"],
    ["46244.12", "1.5"]
  ]
}
```

---

## Error Handling

### HTTP Status Codes
- `200`: Success
- `400`: Bad Request - Invalid parameters
- `404`: Not Found - Product doesn't exist
- `429`: Too Many Requests - Rate limit exceeded
- `500`: Internal Server Error

### Error Response Format
```json
{
  "error": {
    "code": "INVALID_PRODUCT",
    "message": "Product not found",
    "details": {
      "product_id": "INVALID-PAIR"
    }
  }
}
```

### Common Error Codes
- `INVALID_PRODUCT`: Product doesn't exist
- `INVALID_CURRENCY`: Invalid currency pair
- `RATE_LIMIT_EXCEEDED`: Too many requests
- `SERVICE_UNAVAILABLE`: Service temporarily unavailable

---

## Retry Logic

### REST API Retry Strategy
```python
def coinbase_api_request_with_retry(url, headers, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                # Rate limit - exponential backoff
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            elif response.status_code in [400, 404]:
                # Client errors - don't retry
                return response.json()
            else:
                # Server errors - retry with backoff
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
                
        except requests.exceptions.RequestException:
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt
            time.sleep(wait_time)
    
    raise Exception("Max retries exceeded")
```

### WebSocket Reconnection Strategy
```python
def coinbase_websocket_reconnect(ws_url, product_ids, channels, max_reconnects=5):
    for attempt in range(max_reconnects):
        try:
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=lambda ws: ws.send(json.dumps({
                    "type": "subscribe",
                    "product_ids": product_ids,
                    "channels": channels
                })),
                on_message=handle_message,
                on_error=handle_error,
                on_close=handle_close
            )
            ws.run_forever()
            
        except Exception as e:
            if attempt == max_reconnects - 1:
                raise
            wait_time = min(30, 2 ** attempt)  # Cap at 30 seconds
            time.sleep(wait_time)
```

---

## Rate Limits

### REST API Limits
- **Requests per minute**: 1000
- **Requests per second**: 10
- **IP-based limiting**: Yes

### WebSocket Limits
- **Connections per IP**: 5
- **Subscriptions per connection**: 100
- **Messages per second**: 100

### Rate Limit Response
```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded",
    "retry_after": 60
  }
}
```

---

## Data Processing

### Price Data Validation
```python
def validate_price_data(data):
    """Validate Coinbase price data"""
    required_fields = ['base', 'currency', 'amount']
    
    if not all(field in data for field in required_fields):
        raise ValueError("Missing required fields")
    
    try:
        price = float(data['amount'])
        if price <= 0:
            raise ValueError("Price must be positive")
    except ValueError:
        raise ValueError("Invalid price format")
    
    return price
```

### Historical Data Processing
```python
def process_historical_data(candles):
    """Process historical price data from Coinbase"""
    processed_data = []
    
    for candle in candles:
        if len(candle) != 6:
            continue
            
        timestamp, open_price, high, low, close, volume = candle
        
        processed_data.append({
            'timestamp': timestamp,
            'open': float(open_price),
            'high': float(high),
            'low': float(low),
            'close': float(close),
            'volume': float(volume)
        })
    
    return processed_data
```

---

## Integration with REC.IO System

### Price Watchdog Integration
```python
# Used in btc_price_watchdog.py
def fetch_btc_price():
    """Fetch current BTC price from Coinbase"""
    url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
    headers = {
        'User-Agent': 'REC.IO Trading System/1.0',
        'Accept': 'application/json'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        price = float(data['data']['amount'])
        
        return {
            'price': price,
            'timestamp': datetime.now().isoformat(),
            'source': 'coinbase'
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch BTC price: {e}")
        return None
```

### Historical Data Integration
```python
# Used for backtesting and analysis
def fetch_historical_prices(product_id, start, end, granularity=3600):
    """Fetch historical price data from Coinbase"""
    url = f"https://api.coinbase.com/v2/products/{product_id}/candles"
    params = {
        'start': start.isoformat(),
        'end': end.isoformat(),
        'granularity': granularity
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        return process_historical_data(response.json())
        
    except Exception as e:
        logger.error(f"Failed to fetch historical data: {e}")
        return []
```

---

## Testing and Validation

### Test Environment
- **Base URL**: https://api.coinbase.com/v2 (same as production)
- **Test Products**: BTC-USD, ETH-USD
- **Rate Limits**: Same as production

### Validation Checklist
- [ ] Price data retrieval works
- [ ] Historical data fetching
- [ ] WebSocket connection and subscription
- [ ] Error handling for all scenarios
- [ ] Rate limit handling
- [ ] Retry logic for network failures
- [ ] Data validation and processing

---

## Security Considerations

### Network Security
- Use HTTPS for all REST API calls
- Use WSS for WebSocket connections
- Validate SSL certificates
- Implement connection timeouts

### Data Validation
- Validate all price data
- Check for reasonable price ranges
- Sanitize API responses
- Log all API interactions

### Rate Limiting
- Implement client-side rate limiting
- Respect server rate limits
- Use exponential backoff for retries
- Monitor rate limit usage

---

## Monitoring and Alerting

### Key Metrics to Monitor
- API response times
- Error rates by endpoint
- Rate limit usage
- WebSocket connection stability
- Price data accuracy

### Alert Thresholds
- API response time > 5 seconds
- Error rate > 5%
- Rate limit usage > 80%
- WebSocket disconnections > 10/hour
- Price deviation > 5% from expected

### Logging Requirements
- Log all API requests and responses
- Log WebSocket connection events
- Log price data updates
- Log rate limit violations
- Log data validation failures

---

## Performance Optimization

### Caching Strategy
```python
# Cache price data for 1 second to reduce API calls
@lru_cache(maxsize=1)
def get_cached_price(timestamp_key):
    return fetch_btc_price()

# Use timestamp rounded to nearest second as cache key
timestamp_key = int(time.time())
price_data = get_cached_price(timestamp_key)
```

### Connection Pooling
```python
# Use session for connection pooling
session = requests.Session()
session.headers.update({
    'User-Agent': 'REC.IO Trading System/1.0',
    'Accept': 'application/json'
})

# Reuse session for multiple requests
response = session.get(url)
```

### WebSocket Optimization
```python
# Implement heartbeat to maintain connection
def send_heartbeat(ws):
    heartbeat_message = {
        "type": "ping",
        "timestamp": int(time.time())
    }
    ws.send(json.dumps(heartbeat_message))
```
