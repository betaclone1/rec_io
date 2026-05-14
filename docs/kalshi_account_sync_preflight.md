# Kalshi account sync preflight (REST + WS)

Checklist for migration **20260513120000_account_sync_direction_credits** and related writers. Record pass/fail when validating against live Kalshi.

## REST (Trade API v2, signed)

| Endpoint | Required fields for this rollout |
|----------|----------------------------------|
| `GET /portfolio/orders` | `outcome_side` or legacy `side`; `book_side` or derivable outcome; `order_id` |
| `GET /portfolio/fills` | Same direction fields; `trade_id` |
| `GET /portfolio/deposits` | `id`, `amount_cents`, `fee_cents`, `status`, `type`, `created_ts`, `finalized_ts` (or equivalent) |
| `GET /portfolio/withdrawals` | Same shape as deposits where applicable |

## REST (v1 user id path, unchanged host)

| Endpoint | Required fields |
|----------|-----------------|
| `GET /v1/users/{USERID}/credit_history` | `credits[]` with `credit_id`, `amount_cents`, `type`, `status`, `reason`, `created_at`; `cursor` for pagination |

## WebSocket (Trade API v2)

| Channel | Notes |
|---------|--------|
| `fill` | Payload under `msg` should map via `outcome_side` / `side` / `book_side` using the same rules as REST |
| `user_orders` | Order-shaped `msg` with `order_id` |

Idle connections may show no fill/order frames until there is trading activity; absence of frames is not a field-shape failure.

## Hosts

- v2 REST base: `https://external-api.kalshi.com/trade-api/v2`
- v2 WS: `wss://external-api-ws.kalshi.com/trade-api/ws/v2`
- v1 user path remains on `https://api.elections.kalshi.com` (signing path unchanged aside from documented v1 routes).
