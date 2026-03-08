# External ecosystem — broker, data, infra, payments

Single reference for Kalshi, prediction markets, Coinbase, Digital Ocean, payments, and future agent domains. All content below is researched and recorded for rec.io relevance. PM and future specialist agents should use this.

---

## Kalshi (primary broker)

rec.io’s **only broker today**. May add others later.

### Company (baseline facts)

- **What:** First federally regulated US exchange dedicated **only** to event contracts (prediction markets). [Kalshi about](https://kalshi.com/about), [docs welcome](https://docs.kalshi.com/welcome).
- **CEO:** **Tarek Mansour** — co-founder and CEO (2025–2026). MIT; ex quantitative trader Goldman Sachs, Citadel. Led Kalshi to CFTC approval and growth (e.g. $412M volume 2024 NCAA tournament).
- **COO:** **Luana Lopes Lara** — co-founder, COO. MEng CS MIT; ex researcher MIT Brain and Cognitive Sciences, quant trader Citadel Securities and Five Rings Capital. Oversees product, operations, partnerships.
- **Other leadership:** Andy Ross (Head of Institutional Business, Feb 2026, ex Standard Chartered); Weisi Duan (Head of Engineering); Jeff Bandman (Regulatory Strategy); Brandon Beckhardt (Chief of Staff / Growth Operations).
- **Company:** Kalshi Inc., founded 2018, ~195 employees, New York. Privately owned; valuation ~$11B (Jan 2026). Backing: Sequoia, Henry Kravis, Charles Schwab, Y Combinator. Robinhood integrated Kalshi contracts 2025.
- **Regulation:** CFTC Designated Contract Market (DCM); same regulatory category as CME. Event contracts under commodities regulation, not gaming.
- **Product:** Binary event contracts. YES/NO on a question; price $0.01–$0.99 (implied probability); settlement $1 if correct, $0 if wrong. Categories: economics, politics, sports, crypto, weather, policy, entertainment. No house vesting; exchange matches buyers/sellers and charges fees. Fully cash collateralized (no debt). Spread = YES + NO often > $1; tighter spread = more liquidity.

### Event contract mechanics (relevant to our trading)

- Matching: platform matches a YES buyer with a NO buyer; combined payment = $1. Price set by supply/demand. Example: YES at $0.60 vs NO at $0.40.
- Settlement: contract settles to $1 (correct) or $0 (incorrect). P&L: e.g. YES at $0.60, outcome YES → profit $0.40 per contract.
- Kalshi crypto markets: 15-minute BTC up/down (e.g. KXBTC15M), BTC range, longer-term (e.g. “Will Bitcoin hit 200k in 2026?”). We trade these via trade_executor and auto_entry_supervisor.

### Docs and changelog

- **Index (discover all pages):** https://docs.kalshi.com/llms.txt — use before deep-diving.
- **Welcome:** https://docs.kalshi.com/welcome  
- **Changelog:** https://docs.kalshi.com/changelog — **subscribe (RSS)** so we don’t miss breaking changes. RSS: https://docs.kalshi.com/changelog/rss.xml  
- **Fee schedule:** https://kalshi.com/fee-schedule — standard taker fees (e.g. $0.07–$1.75 per 100 contracts), fee multiplier 1; non-standard series vary; “Upcoming fee changes” on page.
- **Developer agreement:** https://kalshi.com/developer-agreement (binding when using API).

### API (auth, env, limits)

- **Auth:** RSA-based. API Key ID + private key (e.g. kalshi.pem). Headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP` (ms), `KALSHI-ACCESS-SIGNATURE` (RSA-PSS SHA256 over `timestamp + METHOD + path`, base64). Private key not retrievable after creation.
- **Order entry:** POST `/trade-api/v2/portfolio/orders`. Fields: ticker, action (buy/sell), side (yes/no), count (or count_fp), type (limit only — market type removed), price, optional client_order_id. Batch: BatchCreateOrders, BatchCancelOrders (each cancel = 0.2 write transactions).
- **Environments:** **Prod REST:** `https://api.elections.kalshi.com/trade-api/v2`. **Prod WebSocket:** `wss://api.elections.kalshi.com/trade-api/ws/v2`. **Demo:** https://demo.kalshi.co/ , API root `https://demo-api.kalshi.co/trade-api/v2`. **V1 (account history):** `https://api.elections.kalshi.com` (no /trade-api path). Demo has mock funds; credentials not shared with prod. Our account_mode toggles prod/demo; trade_executor and kalshi_account_sync_ws use these URLs.
- **Rate limits and tiers:**

| Tier     | Read/sec | Write/sec |
|----------|----------|-----------|
| Basic    | 20       | 10        |
| Advanced | 30       | 30        |
| Premier  | 100      | 100       |
| Prime    | 400      | 400       |

Basic = signup; Advanced = complete typeform; Premier = 3.75% of exchange traded volume in month; Prime = 7.5%. Premier/Prime also require technical competency (rate limiting, monitoring, security). Write limits apply to CreateOrder, CancelOrder, AmendOrder, DecreaseOrder, BatchCreateOrders, BatchCancelOrders.

- **Subaccounts:** Up to 32 per user. POST `/portfolio/subaccounts`, GET `/portfolio/subaccounts/balances`, POST `/portfolio/subaccounts/transfer`. Many portfolio endpoints accept `subaccount` query (0 = primary, 1–32). Netting: GET/PUT `/portfolio/subaccounts/netting` per subaccount.
- **Historical vs live:** Cutoff timestamps (GET `/historical/cutoff`): market_settled_ts, trades_created_ts, orders_updated_ts. Settled markets, old fills, canceled/executed orders move to GET /historical/*; resting orders always in GET /portfolio/orders.

### Fixed-point and fractional (critical for rec.io)

- **March 12, 2026:** Legacy integer count fields and integer cents price fields **removed**. Use `_fp` (e.g. count_fp) and `_dollars` (e.g. yes_bid_dollars) only.
- **Rec.io migration (2026-03-07):** trade_executor, kalshi_account_sync_ws, kalshi_market_watchdog, live_orderbook_snapshot, and kalshi_market_ticker_websocket updated to prefer _fp/_dollars and derive legacy when missing. See MASTER_CHANGELOG 2026-03-07 (Kalshi fixed-point migration).
- **count_fp:** String, 0–2 decimals; responses use 2. fractional_trading_enabled per market; rollout week of March 9, 2026; on fractional markets legacy integers may truncate before March 12.
- **Docs:** [Fixed-Point Migration](https://docs.kalshi.com/getting_started/fixed_point_migration), [Fee Rounding](https://docs.kalshi.com/getting_started/fee_rounding). Changelog: user_orders WebSocket adds `is_yes` (boolean); `side` ("yes"/"no") remains. Market responses: yes_bid_size_fp, yes_ask_size_fp; liquidity/liquidity_dollars deprecated (return 0). market_lifecycle_v2: settlement_value on market_determined. POST /portfolio/orders: type=market no longer offered — limit only.

### Kalshi dev Discord (optional — for @kalshi agent)

To give the @kalshi agent direct read access to the Kalshi developer Discord channel:

1. **Create a Discord bot** — [Discord Developer Portal](https://discord.com/developers/applications) → New Application → Bot. Create bot, copy token. Enable **Message Content Intent** (and Server Members Intent if the MCP needs it).
2. **Invite the bot to the Kalshi dev server** — You need **Manage Server** or **Administrator** on that server. If the Kalshi dev Discord is run by Kalshi and you don’t have that permission, you’d need Kalshi to allow or add the bot. OAuth2 URL with scopes `bot` and permissions **View Channels**, **Read Message History** (read-only is enough).
3. **Install a Discord MCP server** — Use a **bot-based** MCP (not a selfbot; selfbots violate Discord ToS). Examples: `@missionsquad/mcp-discord` (npm), or `mcp-discord` (e.g. barryyip0625/mcp-discord). Configure with the bot token; some need guild (server) ID and channel ID for the Kalshi dev channel.
4. **Add to Cursor** — In `~/.cursor/mcp.json` (or `.cursor/mcp.json` in project), add the Discord MCP with the bot token and any server/channel IDs. Restart Cursor or reload MCP. MCP tools (e.g. read-messages) are then available to the agent; @kalshi will use them when relevant if the rule tells them to.

**Full setup:** `docs/DISCORD_BOT_SETUP.md`. **Behavior:** Research only; no spam. If the agent ever posts: one short, casual message only (enforced in kalshi.mdc).

**Constraint:** Only a user with Manage Server (or Admin) on the Kalshi dev server can add the bot. If you’re a member but not an admin, Kalshi would need to approve adding your bot.

---

## Prediction market industry (future partnerships)

- **Polymarket:** Large prediction market; crypto-native (USDC, etc.); politics, sports, crypto, economics, tech. Not CFTC-regulated; different geos. **API:** Data API (public) at `https://data-api.polymarket.com` (e.g. live volume, builders volume); Retail API (US) with Ed25519 keys, REST + WebSocket for trading. Python/TypeScript SDKs. Potential partnership or second venue.
- **Metaculus:** Forecasting platform (accuracy, tournaments, no real-money trading). API at https://www.metaculus.com/api/ ; R package MetaculR. Research and calibration context.
- **Manifold Markets:** Play-money (Mana); maniswap AMM; real-money (sweepcash) discontinued Mar 2025. Not a rec execution venue.
- **PredictIt:** Market data API public (no auth): `https://www.predictit.org/api/marketdata/all/`, `.../markets/[ID]`; 60s refresh; non-commercial use, attribution. Heavily restricted; different regulatory model.
- **Partnership evaluation:** Check regulation (CFTC vs gaming vs unregulated), jurisdiction, API/contract design, and whether they support programmatic trading and crypto-related markets.

---

## rec.io trading focus and future agents

- **Current focus:** We primarily trade **crypto derivatives** — Kalshi event contracts on BTC/ETH (e.g. 15m up/down, range, milestones). Not spot-only; event outcomes tied to crypto prices. Live data from Coinbase (symbol_price_watchdog) feeds our logic; execution via Kalshi.
- **Expertise we may need:** (1) **Crypto/derivatives/options expert agent** — crypto markets, binary/option/event contracts, volatility, margin, Greeks. (2) **Analyst agents** — statistical and financial analysis plus the above. Both feed strategy and monitoring.
- **Broker:** Kalshi only for now; “might be more eventually.”

---

## Technical stack and production

- **Hosting:** rec.io runs on **Digital Ocean droplets**.
- **Production server:** **137.184.224.94** — main app, services, and **PostgreSQL** (same credentials as local: rec_io_db, rec_io_user, etc.). Referenced in force_cleanup_schemas, compare_simulated_table_schema for prod.
- **DigitalOcean (production host and domain):** **@digitalocean** agent owns DO. API: https://docs.digitalocean.com/reference/api/api-reference/ . **Snapshots (priority):** GET /v2/snapshots (list), GET/DELETE /v2/snapshots/:id; droplet snapshot via POST /v2/droplets/:id/actions type snapshot; volume snapshots via block storage API; resource_type=droplet|volume. **Backups:** Automatic droplet backups (enable/disable on droplet); backup images via Images API, delete via DELETE /v2/images/:id. doctl: `doctl compute snapshot list|get|delete`, `doctl compute image list`, droplet action snapshot. Official MCP: npx @digitalocean/mcp with DIGITALOCEAN_API_TOKEN (see .cursor/pm/DIGITALOCEAN_INTEGRATION.md). Managed PostgreSQL: GET `https://api.digitalocean.com/v2/databases/{database_cluster_uuid}`; doctl databases connection. PyDo for automation. Token in env; never commit.
- **Database specialist agent:** PostgreSQL (schemas, init_database, migrations, backups, replication, performance). Schema source: backend/core/config/database.py and docs/MASTER_DB_SCHEMA_REFERENCE.md.

---

## External financial transactions and data

- **Plaid + Chase:** Plaid has a data agreement with JPMorgan Chase. Token-based auth; Plaid accesses account info via Chase’s API (no stored banking credentials). Supports consumer and small business; read-only balances, transactions, account holder info. rec uses Plaid with Chase business banking for linking accounts and transfers. Chase AccountSafe for consent/revocation.
- **Venmo:** Used for payments. Business: PayPal Payouts API can send to Venmo (mobile, email, handle). Venmo for Business: accept via app, online checkout, Tap to Pay. Limits: unverified $2,499.99/week payment, $999.99 bank transfer; identity-verified $49,999.99/week bank transfers. Unofficial libs exist; official path is PayPal Payouts / Venmo Business.
- **Crypto exchanges (e.g. Coinbase):** For funding, withdrawals, operational cash flow — not for Kalshi order execution (Kalshi balance + API). Our **live price feed** is Coinbase Exchange (see below).

---

## Coinbase Exchange (API and WebSocket) — rec.io usage

We use **Coinbase Exchange** (not Consumer API) for (1) **live ticker** in symbol_price_watchdog, (2) **historical** symbol data via CCXT (symbol_data_fetch_pg, etc.). Config also references `https://api.coinbase.com/v2` (Consumer API) in some config files for other use.

### WebSocket (ws-feed) — our primary live data

- **Endpoint:** `wss://ws-feed.exchange.coinbase.com` (production). Alternative: `wss://ws-direct.exchange.coinbase.com` (direct).
- **Auth:** Not required for public ticker. Subscribe within 5 seconds or connection closes.
- **Subscription format:** `{ "type": "subscribe", "product_ids": ["BTC-USD", "ETH-USD"], "channels": ["ticker"] }` or channels as objects with `name` and `product_ids`. Our SYMBOL_CONFIG in symbol_price_watchdog.py: method `coinbase`, api_endpoint `wss://ws-feed.exchange.coinbase.com`, product_id BTC-USD / ETH-USD, tables live_price_log_1s_btc, live_price_log_1s_eth.
- **Channels:** ticker (our use), heartbeat, level2, status, auction, etc. Ticker = real-time price and volume; we use for 1s logs and momentum/volatility inputs.
- **Limits:** Default 10 WebSocket subscriptions per product per channel; rate limit 10 RPS / 1000 burst. Multiple connections if needed.

### REST (Exchange)

- **Base:** `https://api.exchange.coinbase.com`. Auth required for private endpoints.
- **Auth headers:** CB-ACCESS-KEY, CB-ACCESS-SIGN (base64 HMAC), CB-ACCESS-TIMESTAMP (within 30s of server), CB-ACCESS-PASSPHRASE. Prehash: `timestamp + method + requestPath + body`; HMAC-SHA256 with base64-decoded secret, then base64.
- **Key permissions:** View, Transfer, Trade, Manage. Up to 300 keys per user.
- **Deployments:** Mon/Wed/Thu 2PM ET.

### Consumer API (config references)

- **Base:** `https://api.coinbase.com/v2` in backend/core/config (config.default.json, config.json). Different product from Exchange; used for non–order-book use cases if any.

---

## Action items (PM / ops)

- **Subscribe to Kalshi changelog:** https://docs.kalshi.com/changelog/rss.xml — don’t miss March 12, 2026 or new fields (e.g. is_yes).
- **Audit codebase for _fp and _dollars:** Before March 12, 2026, all Kalshi order/fill/position handling must use fixed-point and dollar fields; remove reliance on legacy integer count and cent price fields.
- **Future agents:** Kalshi/API specialist, crypto-derivatives/options expert, analyst (stats + finance), Digital Ocean specialist, database specialist.
