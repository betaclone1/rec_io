#!/usr/bin/env python3
"""
Example backend subscriber to rec_io:db_changes (same payload as WebSocket clients).

Run while Redis and the switchboard are up. Trigger a change (e.g. randomizer or
POST to switchboard /api/redis_basic_test) and you will see the same event here.

  PYTHONPATH=$(pwd) ./venv/bin/python scripts/redis_db_changes_subscriber_example.py

Optional env: REDIS_URL, or REDIS_HOST, REDIS_PORT; REDIS_CHANNEL_DB_CHANGES (default rec_io:db_changes).
"""

import os
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

REDIS_URL = os.getenv("REDIS_URL")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CHANNEL = os.getenv("REDIS_CHANNEL_DB_CHANGES", "rec_io:db_changes")


def main():
    import redis
    r = (
        redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        if not REDIS_URL
        else redis.from_url(REDIS_URL, decode_responses=True)
    )
    pubsub = r.pubsub()
    pubsub.subscribe(CHANNEL)
    print("Subscribed to", CHANNEL, "- trigger a DB change to see events (e.g. randomizer or POST /api/redis_basic_test)")
    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        msg = json.loads(message["data"])
        if msg.get("type") != "db_change":
            continue
        database = msg.get("database")
        change_data = msg.get("data", {}).get("change_data", {})
        print("db_change", database, change_data)


if __name__ == "__main__":
    main()
