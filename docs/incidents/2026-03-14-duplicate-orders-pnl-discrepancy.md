# Incident Report: Duplicate Fills / PnL Discrepancy (March 14, 2026)

**Date of incident:** March 13, 2026 (evening PST) / March 14, 2026 (UTC)  
**Report date:** March 2026  
**Purpose:** Supporting document for Kalshi support inquiry regarding duplicate executed orders that appear in our account and fills feed but were not submitted by our trading system.

---

## Summary

We observed a ~$170 discrepancy between our internal trade-log PnL and the Kalshi account balance for March 2026. Investigation showed **three executed orders** (same contract, side, and size as three trades we *do* track) that appear in our synced `orders` and `fills` data but were **not** submitted by our API client. Our system has exactly one trade record per contract leg for that window and only ever received two order IDs from Kalshi for the BTC 9pm legs and one for the ETH 15m leg. The three “extra” orders appear to be duplicates of those trades, leading to double credit in the account for the same economic intent.

---

## Affected Orders (Duplicate Fills)

All three orders below are **executed**, **non-canceled**, and have **no corresponding trade row** in our database (we track one trade per leg; these are the “extra” fills).

### 1. BTC Daily 9pm — NO leg (T70749.99)

| Field | Value |
|-------|--------|
| **Orders table id** | **16358** |
| **Kalshi order_id** | **437f27c9-8eec-4cac-a314-c424523cd167** |
| Client order id | d15d7516-1a0e-41b3-b8b0-b67165539c20 |
| Ticker | KXBTCD-26MAR1321-T70749.99 |
| Side | no |
| Fill size | 551 (fill_count_fp) |
| Created (UTC) | 2026-03-14T00:51:05.921081Z |
| **Trade we track for same leg** | Trade id **11017**, order_id_open **7280af19-ea26-44c7-b341-7524ab4868ed**. |

### 2. BTC Daily 9pm — YES leg (T70499.99)

| Field | Value |
|-------|--------|
| **Orders table id** | **16359** |
| **Kalshi order_id** | **56e00a07-9fcf-44f8-81c4-dde7ee6e9662** |
| Client order id | bf8cb644-adef-4f1b-aa03-8f930c75d472 |
| Ticker | KXBTCD-26MAR1321-T70499.99 |
| Side | yes |
| Fill size | 551 (fill_count_fp) |
| Created (UTC) | 2026-03-14T00:51:10.247516Z |
| **Trade we track for same leg** | Trade id **11018**, order_id_open **4140f187-9e39-41d3-8333-4a4e2381a2eb**. |

### 3. ETH 15m (12:15am) — YES leg

| Field | Value |
|-------|--------|
| **Orders table id** | **16403** |
| **Kalshi order_id** | **6b0cd0dc-8028-4753-89d1-9fcb059ffb69** |
| Client order id | d93a48fd-d1b9-4066-89dc-26c94277784b |
| Ticker | KXETH15M-26MAR140015-15 |
| Side | yes |
| Fill size | 1344 (fill_count_fp) |
| Created (UTC) | 2026-03-14T04:11:18.685916Z |
| **Trade we track for same leg** | Trade id **11051**, order_id_open **af04510c-763c-4477-8994-836aa0f4c7a9** (our orders table id **16402**). |

*Note: “Orders table id” refers to our internal `users.orders_0001.id` from synced data; the identifiers that matter for Kalshi are the **order_id** UUIDs.*

---

## Timeline (UTC and PST)

- **2026-03-14 00:51:05 UTC** (2026-03-13 17:51 PST): First duplicate NO fill (order_id 437f27c9…).  
- **2026-03-14 00:51:06 UTC**: Our system submitted and received order_id 7280af19… for the same NO leg (trade 11017).  
- **2026-03-14 00:51:10 UTC**: Second duplicate YES fill (order_id 56e00a07…).  
- **2026-03-14 00:51:11 UTC**: Our system submitted and received order_id 4140f187… for the same YES leg (trade 11018).  
- **2026-03-14 04:11:18 UTC** (2026-03-13 21:11 PST): Third duplicate YES fill (order_id 6b0cd0dc…). Our system had already submitted and received order_id af04510c… for the same ETH 15m leg (trade 11051) at 04:11:10 UTC.

In each case, the “duplicate” order’s created_time is at or before the order our system received from the API for the same contract/side/size.

---

## What We Verified

- **Auto-entry (AES):** One trigger per leg for BTC 9pm and one for ETH 15m; no duplicate sends.  
- **Trade manager:** Single open-ticket flow per trade; stored only 7280af19… and 4140f187… for the BTC 9pm legs and af04510c… for the ETH 15m leg.  
- **Trade executor:** One HTTP request per ticket; one Kalshi response per request; only the order_ids above (7280af19…, 4140f187…, af04510c…) appear in our executor logs.  
- **Orders/fills sync:** The three order_ids 437f27c9…, 56e00a07…, and 6b0cd0dc… appear in our synced `orders_0001` and `fills_0001` but **never** appear in our trade_manager or trade_executor logs as sent or received.

We have no record of submitting 437f27c9…, 56e00a07…, or 6b0cd0dc… through our API client. We are asking Kalshi to confirm whether these orders could have been created by the same API credentials (e.g. duplicate request handling or retries) or by another source (e.g. UI, other client).

---

## Request for Kalshi

1. Confirm origin of the three orders (order_ids above): same API key, UI, or other.  
2. Whether any known duplicate-submission or retry behavior could have created them.  
3. Whether any adjustment or clarification can be provided for our account so that PnL aligns with a single fill per intended leg.

---

## Reference: Order and Trade IDs (Quick Copy)

| Our orders table id | Kalshi order_id (duplicate / untracked) | Our trade id (tracked) | Our order_id_open (tracked) |
|--------------------|----------------------------------------|------------------------|-----------------------------|
| 16358 | 437f27c9-8eec-4cac-a314-c424523cd167 | 11017 | 7280af19-ea26-44c7-b341-7524ab4868ed |
| 16359 | 56e00a07-9fcf-44f8-81c4-dde7ee6e9662 | 11018 | 4140f187-9e39-41d3-8333-4a4e2381a2eb |
| 16403 | 6b0cd0dc-8028-4753-89d1-9fcb059ffb69 | 11051 | af04510c-763c-4477-8994-836aa0f4c7a9 |
