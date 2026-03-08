# 📱 SMS Notification Setup Guide

## Overview

The cascading failure detector can send SMS notifications when it triggers a MASTER RESTART. This provides immediate alerts when the system detects critical failures.

## Setup Instructions

### 1. Get Twilio Account

1. **Sign up for Twilio**: Go to [twilio.com](https://www.twilio.com) and create a free account
2. **Get your credentials**:
   - Account SID (found in your Twilio Console)
   - Auth Token (found in your Twilio Console)
   - Phone number (purchase a number for ~$1/month)

### 2. Install Twilio Library

```bash
pip install twilio
```

### 3. Set Environment Variables

Add these to your environment or create a `.env` file:

```bash
# Enable SMS notifications
SMS_ENABLED=true

# Your phone number (where you want to receive alerts)
SMS_PHONE_NUMBER=+1234567890

# Twilio credentials
TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_FROM_NUMBER=+1234567890  # Your Twilio phone number
```

### 4. Test SMS Notifications

You can test the SMS functionality by running:

```bash
python -c "
import os
os.environ['SMS_ENABLED'] = 'true'
os.environ['SMS_PHONE_NUMBER'] = '+1234567890'
os.environ['TWILIO_ACCOUNT_SID'] = 'your_sid'
os.environ['TWILIO_AUTH_TOKEN'] = 'your_token'
os.environ['TWILIO_FROM_NUMBER'] = '+1234567890'

from backend.cascading_failure_detector import CascadingFailureDetector
detector = CascadingFailureDetector()
detector.send_sms_notification('Test message from REC.IO system')
"
```

## Message Types

### Alert Messages
- **Cascading Failure**: "🚨 REC.IO SYSTEM ALERT: Cascading failure detected. Triggering MASTER RESTART."
- **Recovery**: "✅ REC.IO SYSTEM: MASTER RESTART completed successfully. System recovered."

## Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SMS_ENABLED` | Enable/disable SMS notifications | `false` |
| `SMS_PHONE_NUMBER` | Your phone number for alerts | `""` |
| `TWILIO_ACCOUNT_SID` | Your Twilio Account SID | `""` |
| `TWILIO_AUTH_TOKEN` | Your Twilio Auth Token | `""` |
| `TWILIO_FROM_NUMBER` | Your Twilio phone number | `""` |

### Message Limits

- **Maximum length**: 160 characters
- **Automatic truncation**: Messages longer than 160 chars are truncated with "..."
- **Rate limiting**: Twilio has rate limits (check your plan)

## Troubleshooting

### Common Issues

1. **"Twilio not installed"**
   ```bash
   pip install twilio
   ```

2. **"Invalid phone number"**
   - Ensure phone numbers include country code (+1 for US)
   - Format: `+1234567890`

3. **"Authentication failed"**
   - Check your Account SID and Auth Token
   - Ensure credentials are correct

4. **"From number not verified"**
   - Verify your Twilio phone number in the Twilio Console
   - For trial accounts, you can only send to verified numbers

### Testing

Test the SMS functionality:

```bash
# Test from command line
curl -X POST http://localhost:3000/api/failure_detector_status | jq '.sms_enabled'
```

## Security Notes

- **Never commit credentials** to version control
- **Use environment variables** for sensitive data
- **Consider using a secrets manager** for production
- **Monitor SMS costs** - Twilio charges per message

## Cost Estimation

- **Twilio trial**: 1 free number, limited messages
- **Paid plan**: ~$1/month for phone number + $0.0075 per SMS
- **Typical usage**: 2-5 messages per month (only on failures)

## Alternative SMS Services

If you prefer other SMS services, you can modify the `send_sms_notification()` method in `backend/cascading_failure_detector.py` to use:

- **AWS SNS** (if using AWS)
- **SendGrid** (email-to-SMS)
- **Local SMS gateways** (for on-premise systems) 