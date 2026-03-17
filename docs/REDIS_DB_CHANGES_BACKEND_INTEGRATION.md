# Backend integration: Redis DB change notifications

Backend services receive the **same** DB change events as the frontend (WebSocket) by subscribing to the Redis channel. Same payload shape, same logical stream names. No separate API or protocol.

**Canonical architecture and contract:** [REALTIME_BACKBONE.md](REALTIME_BACKBONE.md). Stream registry: `backend/core/stream_registry.py`.

## Channel and payload

- **Redis channel:** `rec_io:db_changes` (override with env `REDIS_CHANNEL_DB_CHANGES` where the switchboard runs).
- **Message:** One JSON object per DB change (after the switchboard maps the table to a logical name).

Payload shape (same as WebSocket):

```json
{
  "type": "db_change",
  "database": "<logical_name>",
  "data": {
    "timestamp": null,
    "change_data": {
      "schema": "<schema>",
      "table": "<table>",
      "op": "INSERT" | "UPDATE" | "DELETE"
    }
  },
  "timestamp": "<ISO8601 UTC>"
}
```

- **`database`** is the logical name the switchboard assigns (e.g. `trades`, `fills`, `positions`, `settlements`, `redis_basic_test`). Use this to filter.
- **`data.change_data`** gives the physical table and operation if you need it.

## Minimal Python subscriber

Requires `redis` (in project requirements). Uses the same env as the rest of the stack (`REDIS_URL` or `REDIS_HOST`/`REDIS_PORT`).

```python
import os
import json
import redis

REDIS_URL = os.getenv("REDIS_URL")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CHANNEL = os.getenv("REDIS_CHANNEL_DB_CHANGES", "rec_io:db_changes")

def main():
    r = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        decode_responses=True
    ) if not REDIS_URL else redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    pubsub.subscribe(CHANNEL)
    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        msg = json.loads(message["data"])
        if msg.get("type") != "db_change":
            continue
        database = msg.get("database")
        change_data = msg.get("data", {}).get("change_data", {})
        # React: refetch, invalidate cache, enqueue job, etc.
        print("db_change", database, change_data)

if __name__ == "__main__":
    main()
```

A runnable example lives in the repo:

```bash
PYTHONPATH=$(pwd) ./venv/bin/python scripts/redis_db_changes_subscriber_example.py
```

Run with Redis and the switchboard up; trigger a change (e.g. randomizer or POST to switchboard `/api/redis_basic_test`) and you should see the same event as the test UI.

## Integration pattern

- **Frontend:** Connects to `/ws/db_changes` (served by main app or switchboard). Receives the same JSON; filters on `data.database` and refetches.
- **Backend:** Subscribes to Redis `rec_io:db_changes`. Same JSON; filter on `database` and run your logic (refetch, invalidate cache, enqueue, call another service).
- **Switchboard:** Single writer to Redis (LISTEN → publish). Run one instance; frontend can be served by main app and main app can subscribe to Redis to broadcast to its WS clients, or WS can be on the switchboard depending on deployment.

No extra APIs or different payloads: one pipeline for the whole system.
