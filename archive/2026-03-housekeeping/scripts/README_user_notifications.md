# User Notification Service

## Overview
The `user_notifications.py` script serves as the core notification system for the REC.IO trading platform. It provides SMS alerts via email-to-text gateway using Gmail SMTP.

## Features
- **SMS Alerts**: Send notifications to user's phone number via email-to-text gateway
- **Multiple Carriers**: Supports Verizon, AT&T, T-Mobile, Sprint, and other carriers
- **Notification Types**: SYSTEM, ALERT, TRADE, TEST notifications with proper formatting
- **Gmail Integration**: Uses Gmail SMTP with App Password authentication
- **Centralized Service**: All system components use this service for notifications

## Configuration

### Phone Number Setup
Create the user settings file:
```bash
mkdir -p backend/data/users/user_0001
```

Create `backend/data/users/user_0001/user_info.json`:
```json
{
  "phone": "+1 (917) 586-4077"
}
```

### Gmail App Password
The service uses Gmail SMTP with App Password authentication:
- Email: `rec.io.alerts@gmail.com`
- App Password: `jfnc adxj ubfz lrtw`

## Usage

### Command Line
```bash
# Test the notification service
python scripts/user_notifications.py

# Send a custom message
python scripts/user_notifications.py "Your custom message here"

# Send a system alert
python scripts/user_notifications.py "Critical system failure detected"
```

### From Other Scripts
```python
# Import the notification service
from scripts.user_notifications import send_user_notification

# Send a notification
send_user_notification("System is operational", "SYSTEM")
send_user_notification("Trade executed successfully", "TRADE")
send_user_notification("Critical alert detected", "ALERT")
```

### From System Monitor
The system_monitor.py automatically uses this service for:
- Service restart failures
- Critical system alerts
- Automated trading safety notifications

## Notification Types
- **SYSTEM**: General system notifications
- **ALERT**: Critical alerts and failures
- **TRADE**: Trading-related notifications
- **TEST**: Test messages

## Carrier Support
- **Verizon**: `@vtext.com`
- **AT&T**: `@txt.att.net`
- **T-Mobile**: `@tmomail.net`
- **Sprint**: `@messaging.sprintpcs.com`
- **Boost**: `@myboostmobile.com`
- **Cricket**: `@sms.cricketwireless.net`
- **Metro**: `@mymetropcs.com`
- **US Cellular**: `@email.uscc.net`

## Integration
This service is integrated with:
- `system_monitor.py`: System health alerts
- `cascading_failure_detector.py`: Failure detection alerts
- Future trading components for trade notifications

## Troubleshooting
1. **No phone number configured**: Check `user_info.json` file
2. **Gmail authentication failed**: Verify App Password is correct
3. **SMS not received**: Check carrier gateway and spam folder
4. **Service not found**: Ensure script path is correct in calling code 