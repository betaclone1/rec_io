"""
Optional operator alerts for system-critical conditions (e.g. ATS enrollment failure).

Set REC_CRITICAL_WEBHOOK_URL to a Discord/Slack-compatible incoming webhook POST URL.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def send_critical_alert(message: str, title: str = "rec_io CRITICAL") -> bool:
    """POST a short JSON body if REC_CRITICAL_WEBHOOK_URL is set. Best-effort; never raises."""
    url = (os.environ.get("REC_CRITICAL_WEBHOOK_URL") or "").strip()
    if not url:
        return False
    payload = {"text": f"{title}: {message}", "content": f"{title}: {message}"}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, TimeoutError):
        return False
