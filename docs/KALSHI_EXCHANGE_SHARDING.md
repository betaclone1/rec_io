# Kalshi exchange sharding

Canonical reference for Kalshi matching-engine shards and how REC.IO addresses balances and orders. Official Kalshi docs: [Exchange Sharding](https://docs.kalshi.com/getting_started/exchange_sharding), [Create Subaccount](https://docs.kalshi.com/api-reference/portfolio/create-subaccount), [Intra Account Transfer](https://docs.kalshi.com/api-reference/portfolio/intra-account-transfer), [Transfer Between Subaccounts](https://docs.kalshi.com/api-reference/portfolio/transfer-between-subaccounts), [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2), [Get All Subaccount Balances](https://docs.kalshi.com/api-reference/portfolio/get-all-subaccount-balances).

## Why this exists

Kalshi splits trading across multiple matching engines (**exchange indexes / shards**). Collateral checks run **inside** each shard. Cash on shard 0 cannot collateralize an order on shard 2. Balances are reported as **`(exchange_index, subaccount_number)`** pairs.

## Shard map (first rollout)

| Shard (`exchange_index`) | Category | REC.IO relevance |
|--------------------------|----------|------------------|
| **0** | Catch-all (everything not listed below) | Legacy home of crypto before cutover; CASH / IAT hop still uses primary on 0 when moving across shards |
| **1** | Exotics (combos) | Not required for current product; probed in prep tests only |
| **2** | **Crypto** | **All crypto markets live exclusively here** after cutover (e.g. `KXBTC15M`, other `KX*15M` / crypto series) |
| **3** | Sports (Tennis, Baseball tags) | Future / unused today |

Timeline (Kalshi / ops): shard **2 funding** expected live around **2026-08-20** (IAT smoke tests); crypto **new** events on shard 2 from **2026-08-24**. Live markets are **not** migrated mid-flight; only newly created crypto events land on 2.

**Current trading scope:** REC.IO trades **crypto only**. Operational home for Master Trading Bankroll (MTB) after cutover is **`(2, 1)`**. Keep the full matrix model so other shards can be added later without redesign.

## Address model: `(exchange_index, subaccount)`

Think of portfolio cash as a 2D matrix, not a flat subaccount list.

![Kalshi exchange sharding: within-shard subaccount transfers vs cross-shard IAT only via subaccount 0](images/kalshi_exchange_sharding_matrix.png)

- **Solid edges:** within-shard `POST /portfolio/subaccounts/transfer` (any subaccounts on the same `exchange_index`).
- **Dashed edges:** cross-shard IAT — **subaccount 0 only** (`(0,0) ↔ (1,0) ↔ (2,0)`). Order `exchange_index: -1` auto-routes **orders** by market ticker; it does **not** move cash along these edges.

| Subaccount | Role (REC naming) |
|------------|-------------------|
| **0** | Primary / **CASH** on that shard (IAT endpoint; deposits to a shard land here) |
| **1** | **Master Trading Bankroll (MTB)** on that shard — orders default to this via `trade_executor` |
| **2+** | Ancillary (`Reserve` / `undefined_N`, …) |

Examples:

- `(0, 1)` — MTB on shard 0 (pre-cutover crypto collateral)
- `(2, 1)` — MTB on shard 2 (**post-cutover crypto trading bankroll**)
- `(2, 0)` — primary on shard 2 (staging for IAT and for funding `(2, 1)`)

`GET /portfolio/subaccounts/balances` returns one row per populated pair (`subaccount_number`, `exchange_index`, `balance`, `updated_ts`).  
`GET /portfolio/balance` includes `balance_breakdown[]` with per-`exchange_index` totals.

### Schema plan (least destructive)

**Do not** rename tables to `subaccount_balance_<slot>_<exchange>_<n>`. Keep one table / row family per Kalshi **subaccount number**.

Add fixed shard cash columns on **both**:

1. Live snapshot: `users` / `users_NNNN`.`subaccounts_*`
2. History: `users` / `users_NNNN`.`subaccount_balance_*_<n>`

| Column | Meaning |
|--------|---------|
| `exchange_0_balance` | Cash on shard 0 for this subaccount (cents) |
| `exchange_1_balance` | Cash on shard 1 |
| `exchange_2_balance` | Cash on shard 2 (crypto MTB home after cutover) |
| `exchange_3_balance` | Cash on shard 3 (optional but cheap; known Kalshi map) |
| `balance` | **Sum** of the `exchange_*_balance` columns (existing readers keep working) |

Poll from `GET /portfolio/subaccounts/balances` (matrix). Unprovisioned pairs → treat as 0 for that shard column. Historical pre-sharding rows: backfill `exchange_0_balance = balance`, other shard cols 0.

**Semantics:**

- **`balance` (sum)** — portfolio display, hero aggregates, charts  
- **`exchange_2_balance` on subaccount 1** — post-cutover MTB collateral / automatic rake source; Kalshi transfer must pass `exchange_index=2`

Same migration should touch live `subaccounts_*` and history `subaccount_balance_*_*` together so rake and history do not diverge.

## Funding and transfers

### Within one shard

`POST /portfolio/subaccounts/transfer` with `exchange_index` set (default `0`):

- Move cash between subaccounts **on that shard only**
- Example: `(2, 0) → (2, 1)` with `exchange_index=2`

### Across shards (IAT only)

`POST /portfolio/intra_exchange_instance_transfer` ([IAT](https://docs.kalshi.com/api-reference/portfolio/intra-account-transfer)):

- Moves funds **between shard primaries** — effectively `(source_shard, 0) ↔ (dest_shard, 0)`
- Request uses `source` / `destination` = `event_contract` (prediction markets), `amount` in **centicents** ($1 = `10000`), plus `source_exchange_shard` / `destination_exchange_shard`
- Processed **asynchronously**; poll balances until destination primary shows the credit
- **Cannot** IAT directly from `(0, 1)` to `(2, 1)`

### Provisioning a new shard

Kalshi order of operations ([sharding guide](https://docs.kalshi.com/getting_started/exchange_sharding)):

1. **IAT** user-level funds onto the target shard → primary **`(E, 0)`** appears once funded  
2. **`POST /portfolio/subaccounts`** with `exchange_index=E` → creates numbered subs **1, 2, …** on that shard (you do **not** create 0; create returns the next `subaccount_number`)  
3. Subaccount transfer on `exchange_index=E` to place trading cash on **`(E, 1)`** (MTB)

Create without prior funding on that shard fails (e.g. `user_not_found` / server error). Shard 2 was unavailable on prod until Kalshi exposed it in `balance_breakdown` (demo already had indexes 0–3 for prep).

### Crypto MTB cutover hop (canonical)

To move MTB from shard 0 to shard 2:

1. `(0, 1) → (0, 0)` — subaccount transfer, `exchange_index=0`  
2. `(0, 0) → (2, 0)` — IAT  
3. Ensure `(2, 1)` exists (create on `exchange_index=2` if needed)  
4. `(2, 0) → (2, 1)` — subaccount transfer, `exchange_index=2`

Reverse path for returning cash to shard-0 CASH, etc.

## Orders (`trade_executor`)

Create Order V2 (`POST /portfolio/events/orders`) includes:

- `subaccount` — default **1** (MTB)  
- `exchange_index` — default **`-1`** (auto-route by market ticker)

Auto-route picks the shard where that market lives. It does **not** move collateral. The debit still comes from **`(market’s shard, subaccount)`**. For crypto on shard 2, cash must already be on **`(2, 1)`**.

Kalshi notes automatic routing adds some latency vs pinning a known `exchange_index`.

## Market data (ingest / rollover)

**No change expected** to ticker construction, WS subscribe filters, or 15m rollover for sharding:

- Market ticker strings are unchanged (e.g. `KXBTC15M-26AUG131630-30`)
- `market_watchdog` locates BTC 15m by EST wall clock and subscribes with `market_tickers: […]` on `ticker` / `orderbook_delta`
- `exchange_index` on `GET /markets` / events is metadata; subscribe path does not require it today
- Production ingest uses prod `external-api` REST/WS (not demo)

After cutover, **new** crypto markets should report `exchange_index: 2`. Smoke-check that REST shows 2 and WS still delivers ticker/orderbook for the clock-built ticker. See [KALSHI_MARKET_INGEST.md](KALSHI_MARKET_INGEST.md).

## Verified prep notes (2026-08-13)

| Check | Result |
|-------|--------|
| Prod `GET /portfolio/subaccounts/balances` | Rows are `(exchange_index, subaccount)` pairs |
| Demo: IAT $0.01 → shard 2, then create 1/2/3 | Matrix `(2,0)…(2,3)` visible |
| Prod: $1 three-hop `(0,1) → (0,0) → IAT → (1,0) → create → (1,1)` | Confirmed in API + Kalshi UI |
| Prod create on shard 2 (pre-cutover) | Failed (shard 2 not in prod `balance_breakdown` yet) |
| Current `KXBTC15M` clock ticker | Identical on demo + prod; still `exchange_index: 0` pre-cutover |

## Implementation status (REC.IO)

| Area | Status |
|------|--------|
| `trade_executor` order `exchange_index` default `-1` | Done |
| Balance poll / `subaccount_balance_*` + `subaccounts_*` shard columns | Migration **`20260813_1448_subaccount_exchange_balances`** + poller writes `exchange_0..3_balance` from matrix API |
| IAT + shard-aware transfer helpers in bookkeeper | **Not done** (manual/scripted in prep) |
| Docs (this file) | Canonical reference |
| Multi-shard non-crypto trading | Future — use same matrix; pin or auto-route per product |

## Related docs

- [PORTFOLIO_ACCOUNT_SYNC.md](PORTFOLIO_ACCOUNT_SYNC.md) — balance sync and subaccount roles  
- [KALSHI_MARKET_INGEST.md](KALSHI_MARKET_INGEST.md) — WS ingest and rollover  
- [ARCHITECTURE.md](ARCHITECTURE.md) — system overview  
