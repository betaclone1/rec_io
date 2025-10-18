# Kalshi API Standalone Demo

This is a completely independent script that demonstrates Kalshi API integration for advanced API access applications.

## Requirements

- Python 3.7+
- Required packages: `requests`, `python-dotenv`, `cryptography`

Install dependencies:
```bash
pip install requests python-dotenv cryptography
```

## Setup

1. Create a credentials directory with your Kalshi API credentials:
   ```
   credentials/
   ├── .env
   └── kalshi.pem
   ```

2. The `.env` file should contain:
   ```
   KALSHI_API_KEY_ID=your_api_key_id_here
   ```

3. The `kalshi.pem` file should contain your private key in PEM format.

## Usage

```bash
python3 kalshi_standalone_demo.py <credentials_directory>
```

Example:
```bash
python3 kalshi_standalone_demo.py ./credentials
```

## What it does

1. **Queries market data** for the NYC weather market (KXRAINNYC-25SEP29-T0)
2. **Queries the order book** for that market
3. **Displays formatted results** showing market information and order book data

## Output

The script will display:
- Market information (title, status, prices, volume, liquidity)
- Order book with YES/NO bids in dollar amounts
- Real-time market data from Kalshi API

## Independence

This script is completely standalone and does not depend on any system infrastructure. It only requires:
- Kalshi API credentials
- Python standard library
- The specified Python packages

Perfect for demonstrating Kalshi API integration capabilities.




