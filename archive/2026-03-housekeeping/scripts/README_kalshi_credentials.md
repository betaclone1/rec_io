# Kalshi Credentials Generator

This script creates a complete set of Kalshi credential files for both production and demo environments.

## Usage

### Interactive Mode (Recommended for first-time setup)

```bash
python3 scripts/create_kalshi_credentials.py
```

The script will prompt you for:
- Kalshi account email
- Kalshi API key
- PEM file path (optional)
- Custom environment variables (optional)

### Command-Line Mode (For automation)

```bash
# Create both prod and demo environments
python3 scripts/create_kalshi_credentials.py \
  --email "your-email@example.com" \
  --api-key "your-api-key-here" \
  --pem-file "/path/to/your/private-key.pem" \
  --env-file "/path/to/your/env-vars.txt"

# Create only production environment
python3 scripts/create_kalshi_credentials.py \
  --email "your-email@example.com" \
  --api-key "your-api-key-here" \
  --environments prod

# Create only demo environment
python3 scripts/create_kalshi_credentials.py \
  --email "your-email@example.com" \
  --api-key "your-api-key-here" \
  --environments demo
```

## Files Created

For each environment (`prod` and/or `demo`), the script creates:

### 1. `kalshi-auth.txt`
Contains your email and API key:
```
email:your-email@example.com
key:your-api-key-here
```

### 2. `kalshi-auth.pem` (if provided)
Your private key file with proper permissions (600).

### 3. `kalshi.env`
Environment-specific variables:
- **Production**: Points to production API endpoints
- **Demo**: Points to demo/sandbox API endpoints

## Directory Structure

```
backend/api/kalshi-api/kalshi-credentials/
├── prod/
│   ├── kalshi-auth.txt
│   ├── kalshi-auth.pem (optional)
│   └── kalshi.env
└── demo/
    ├── kalshi-auth.txt
    ├── kalshi-auth.pem (optional)
    └── kalshi.env
```

## Security Notes

- PEM files are automatically set to 600 permissions (owner read/write only)
- Credentials are stored in the project's credential directory
- Never commit credential files to version control

## Getting Your Kalshi Credentials

1. **API Key**: Generate from your Kalshi account dashboard
2. **PEM File**: Download your private key from Kalshi
3. **Email**: Your Kalshi account email address

## Example Workflow

```bash
# 1. Generate credentials interactively
python3 scripts/create_kalshi_credentials.py

# 2. Verify files were created
ls -la backend/api/kalshi-api/kalshi-credentials/prod/
ls -la backend/api/kalshi-api/kalshi-credentials/demo/

# 3. Test the system
./scripts/MASTER_RESTART.sh
```

## Troubleshooting

- **Permission Denied**: Ensure the script is executable (`chmod +x scripts/create_kalshi_credentials.py`)
- **File Not Found**: Check that your PEM and ENV file paths are correct
- **Invalid API Key**: Verify your Kalshi API key is correct and active 