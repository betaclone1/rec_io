# Maker Edge — strategy handoff (15m dual-rest)

**Product name:** Maker Edge  
**Audience:** operators + implementers.  
**Status:** live wiring via `maker_edge_agent` (outside TE); research backtests remain valid for edge thesis.  
**Series:** Kalshi 15m binaries for `BTC` / `ETH` / `GOLD` / `SILVER` / `WTI` (`KXBTC15M`, `KXETH15M`, `KXGOLD15M`, `KXSILVER15M`, `KXWTI15M`). Commodities use lean market capture (ticker + public trades + lifecycle; no OB/strike ladder).  
**Session context:** agent transcript [KXBTC15M longshot sweeps](50be246f-d7ea-4e39-80ed-56ada09254d0).

This note consolidates thesis, fill models, architecture, measured results, and data plumbing. Prefer numbers from the CSV paths below over re-deriving from chat.

---

## 0. Bedrock (read first)

**Standing law:** `.cursor/rules/00-15m-cycle-bedrock.mdc` (always applied).

1. Every 15m the cycle refreshes. **Floor strike = asset price at that open.**
2. The market is only: **higher or lower than that price 15 minutes later.**
3. That is why every open is ~**50/50** and opening quotes reflect it.
4. Path + theta drive quotes toward **one extreme**; the anomalies we care about are when it **hits an extreme then reverses** and settles the **opposite** side.

Do not design or interpret Maker Edge / backtests without this frame.

---

## 1. Thesis (one paragraph)

On each 15m cycle the floor strike is the open price, so the book starts near even money. As spot moves vs that strike, one side becomes the penny longshot. A strategy that **gets filled at $0.01 on that longshot side** (and does **not** also hold the other side) wins when settlement is that side after a possible extreme-then-reverse — paying ~$0.99 per contract after a $0.01 outlay. Empirical win rates are ~1.8–2.6% depending on model and span — far above the naïve “1¢ fair” story if fills were random — so **edge is in selection + fill realism**, not in buying near $1.00. Preferred live shape (current recommendation): **rest maker bids on both sides at $0.01 at cycle open**, join **behind** opening book depth, cancel the unfilled side on first fill, hold to settlement (zero maker fees on these rests). Cap size by **liquidity** (cum tape / book depth), not by TTC filters that cut winners.

---

## 2. What we are *not* doing

| Anti-pattern | Why discarded |
|--------------|---------------|
| First-touch **≤ $0.02** “longshot” as primary | Useful for discovery; looser than exact-cent; worse risk profile vs exact $0.01 in 4m sweep |
| Buy near **$0.90–$0.99** | Sweep Jun–Sep: ~50% WR with catastrophic PnL (negative control) |
| Prefer **TTC ≥ 30s** cancel on exact-cent | 4m @ $0.01: TTC filter **hurts** PnL (~+$180.7k vs ~+$199.1k unconstrained) |
| Fabricate fills from spot / strike math | Violates no-fallbacks; venue tape + book only |
| Seal packages with guessed `market_result` | NULL until Kalshi lifecycle / API |

---

## 3. Fill models (paper → live ladder)

### 3.1 Exact-cent first-touch (tape oracle)

**Rule:** On each market ticker’s public tape, find the first trade where `round(yes_price_dollars, 2) == L` or same for NO. Enter that side for full `contracts` at price `L`. Score vs `market_result`.

- **Pros:** Fast offline; clear; strong 4-month headline at `L=0.01`.
- **Cons:** Assumes you get the first print size; ignores queue ahead; optimistic vs maker reality.

**Checked-in CLI (cum gate):** `scripts/backtest/kxbtc15m_exact_cent_cum_size_span.py`  
**Ad-hoc session scripts** wrote the exact-cent / TTC CSVs (not all promoted to CLI).

### 3.2 Cum-volume gate (liquidity realism on tape model)

Same as 3.1, but after choosing side at first touch of `L`, require **cumulative tape volume on that side at `L` over the whole cycle ≥ `contracts`**. Else skip (cannot support full size).

- Week Aug 30–Sep 5 @ 2000 / $0.01: unconstrained +$20,720 (17W) → with cum≥2000: **+$14,780** (14W) — drops three thin winners.
- **YTD @ 2500** queued while Jan–May+Oct day tapes finish (expected out path under §8).

### 3.3 Dual-side maker from open (preferred live analogue)

**Rule (sim):** At cycle open, rest `contracts` @ $0.01 on YES **and** NO. Queue position = opening book depth at 0.01 (join behind). Consume public tape prints at exact 0.01 against that queue. On first fill of either side, **cancel the other**. Hold to settlement. Assume **$0 maker fee**.

**Script:** `scripts/backtest/kxbtc15m_week_maker_book_tape_sim.py`  
**Inputs:** sealed cycle packages (opening snapshot depth) + day public-trade CSVs.

Week Aug 30–Sep 5:

| Size | Markets | Wins | WR | PnL | Max DD (peak→trough) |
|-----:|--------:|-----:|---:|----:|---------------------:|
| 2000 | 649 | 14 | 2.16% | **+$14,417** | ~$3,600 |
| 2500 | 649 | 14 | 2.16% | **+$17,677** | (same win set; larger outlay/win) |

Close to cum-gated tape model on the same week — supports “maker + depth + cancel other side” as the implementation target, not taker IOC chasing first print.

### 3.4 First-≤$0.02 monthly longshot (legacy discovery)

Month scripts: `run_kxbtc15m_longshot_month.py`. Jun was flat/negative; Jul–Sep profitable at 2000@$0.02. **Do not** treat as the production rule; use as historical context only.

---

## 4. Headline backtest results (durable files)

Base directory: `backend/data/historical_data/kalshi_public_trades/`  
Default bankroll **$10,000** unless noted. Outlay = `contracts * L` (e.g. 2000 × $0.01 = **$20**).

### 4.1 Exact-cent sweep — 2026-06-01 … 2026-09-30 (no TTC, 2000 ct)

**File:** `KXBTC15M_longshot_exact_cent_sweep_2026-06-01_2026-09-30_et.csv`

| limit | scored | W | L | wr% | pnl | equity_end | min_eq | max_dd |
|------:|-------:|--:|--:|----:|----:|-----------:|-------:|-------:|
| **0.01** | **11544** | **215** | **11329** | **1.86** | **+199,120** | **209,120** | **7,580** | **4,700** |
| 0.02 | 11544 | 314 | 11230 | 2.72 | +166,240 | 176,240 | 6,160 | 8,960 |
| 0.03 | 11545 | 424 | 11121 | 3.67 | +155,300 | 165,300 | 4,240 | 14,880 |
| 0.05 | 11546 | 638 | 10908 | 5.53 | +121,400 | 131,400 | −17,700 | 29,600 |
| 0.10 | 11545 | 1174 | 10371 | 10.17 | +39,000 | 49,000 | −42,600 | 54,800 |

**Takeaway:** `$0.01` dominates risk-adjusted (highest PnL, smallest DD). Higher cents inflate WR but destroy equity path.

### 4.2 Exact-cent + TTC ≥ 30s — same 4 months @ $0.01

**File:** `KXBTC15M_exact_cent_ttc30s_limit0.01_2026-06-01_2026-09-30_et.csv` (event-level)  
Approx aggregate: scored **10,766**, W **198**, wr **~1.84%**, pnl **~+$180,680**, max_dd **~$4,560**.  
**Takeaway:** Prefer **no TTC filter** for this edge.

### 4.3 Week exact-cent (Aug 30–Sep 5)

**File:** `KXBTC15M_longshot_exact_cent_sweep_2026-08-30_2026-09-05_et.csv` — @0.01: 664 scored, 17W, **+$20,720**, max_dd $2,200.

### 4.4 Week maker book+tape

**Files:**  
- `KXBTC15M_week_maker_book_tape_2026-08-30_2026-09-05.csv` (2000)  
- `KXBTC15M_week_maker_book_tape_2500_2026-08-30_2026-09-05.csv` (2500)

See §3.3. Nearly every market with a package got a fill; win count matches cum-gated tape (14).

### 4.5 Negative control — first-≤ $0.90–$0.99

**File:** `KXBTC15M_longshot_limit_sweep_2026-06-01_2026-09-30_et.csv` — do not implement.

### 4.6 YTD 2026 exact-cent cum2500

Landed: Jan 1–Oct 17, +$213,550 / 1.35% WR. Detail: `KXBTC15M_exact_cent_cum2500_limit0.01_2026-01-01_2026-10-17_et*.csv` under public-trades / artifacts (not committed).

---

## 5. Product / live architecture (Maker Edge)

### 5.1 Strategy identity

**Name:** Maker Edge. New `strategy_list` row (migration `20261017_1500_maker_edge_strategy`). Do not overload High Water Scalp or Expiration Scalp.

| Concern | Implementation |
|---------|----------------|
| Process | Dedicated `maker_edge_agent` per tenant (outside TE); AES/ATS exclude Maker Edge monitors |
| Symbols | `MAKER_EDGE_SYMBOLS`: BTC, ETH, GOLD, SILVER, WTI (`15m`). Co-opening windows place in one fire. |
| Entry | At Kalshi ``open_time``: place **two** post-only GTC at monitor limit `L` — **BID @ L** and **ASK @ L** (yes/no constructs). Arming is open_time-driven, not TTC. |
| Size | Standard bankroll pct/contracts from `monitor_list.subaccount` (v3.12.12) |
| TTC | `min_time` used only to cancel **unfilled** rests near expiry; not a place gate |
| One-fill rule | First fill → cancel sibling; book into TM `intent=maker_edge_fill` |
| Paper fill | First chronological **exact-L** public tape print hits that side’s virtual bid (not ask-touch ≤ L). Live uses venue fill counts on resting order ids. |
| Hold | TM monitors like any other trade; settlement via `market_result` only |
| Subaccount | Same routing as all strats on every place/cancel/book |

### 5.2 Why not reuse High Water Scalp

HWS fires when the **active-side ask prints** a target cent (often high cents), then rests a GTC **close**. Exact Cent Maker:

- fires / rests at **cycle open** on **both** sides at **$0.01**;
- **cancels** the other side on first fill;
- **holds to settlement** (no 0.99 close target as the primary exit).

Closest existing plumbing: trade_manager GTC / resting orders, account-sync fill wakes, maker fee assumptions in HWS paper path — reuse **order infrastructure**, not HWS gates.

### 5.3 Process sketch

```
prediscover next open_time (Kalshi /markets)
    → arm waiter; prefetch: floor, monitor plan, price map, JSON bodies, PEM + TLS warm
    → re-warm ~1s before open; busy-spin into open_ts
    → hot path: parallel BID+ASK sign+POST only (no DB / foreign cancel)
    → book DualRestState; foreign-cycle cleanup after wire
    → on first fill: cancel sibling; trades_* row open on filled side
    → settlement / market_result → win_loss_confirmed (authoritative only)
```

**Latency target (ours):** minimize ``open_time → first byte on the wire`` (`fire_lag_ms`, `send_lag_ms`, `prep_after_fire_ms` in agent logs). Venue ACK RTT (`bid_rtt_ms` / `ask_rtt_ms`, typically ~200–370 ms) is out of our control.

**Queue position (ops law):** Older rests beat newer ones at the same price. If duplicate rests exist, **cancel the newer** ids and keep the oldest. Never cancel the older pair to “clean up” after a mistaken re-place. **No mid-cycle live recovery place** — restart during an open cycle skips that cycle; next `open_time` arms normally.

**No fallbacks:** if book depth unknown, do not place; if fill ambiguous, do not invent side; `market_result` NULL until venue.

### 5.4 Data plane (already shipping)

Live capture → hot PG → hourly `cycle_packager` → `backtesting_data/.../{TICKER}.tar.xz` → Drive (`CYCLE_GDRIVE_UPLOAD`).

**Schema v4** (`PACKAGE_SCHEMA_VERSION = 4`):

| Member | Notes |
|--------|--------|
| `meta.json` | `variant=full`, `proprietary_members` |
| `market_meta.json` | floor/result + seal enrich |
| `snapshot.csv` / `deltas.csv` | OB |
| `price_ring.csv` | shareable underlying |
| `public_trades.csv` | tape at seal |
| `volume_path.csv` | cum tape vs time |
| `quality.json` | capture QA |
| `strike_table.csv` | **PROPRIETARY** |
| `metrics_ring.csv` | **PROPRIETARY** |

External SKU: `scripts/backtest/export_cycle_package_variant.py` (strip proprietary only).  
Docs: `docs/HISTORICAL_CYCLE_DATA_PRODUCT.md`, `docs/MASTER_DB_SCHEMA_REFERENCE.md` (packaging section), plan `.cursor/plans/cycle-package-v4-external-sku.md`.

Offline day tapes (research): `scripts/backtest/pull_kxbtc15m_public_trades_day_csv.py` → `KXBTC15M_public_trades_YYYY-MM-DD_et.csv`; month Drive bundle `package_month_public_trades_to_drive.py`. Flush per-ticker `.cache_*` after successful day CSV (rule `09-no-duplicate-historical-artifacts`).

---

## 6. Trading logic (spec for implementer)

### 6.1 Parameters (v1 defaults from research)

| Param | Default | Notes |
|-------|---------|--------|
| `limit_px` | `0.01` | Exact cent only |
| `contracts` | `2000`–`2500` | Scale with bankroll; week maker supports 2500 |
| `sides` | YES and NO | Dual rest |
| `join_policy` | behind open depth @ 0.01 | From package / live book |
| `cancel_other_on_first_fill` | true | Mandatory |
| `ttc_min_entry` | **none** | Research: TTC filter hurts |
| `cum_vol_gate` | optional offline; live use book+partial fills | Live: allow partial; cap N by depth |
| `max_concurrent_markets` | ≥5 (one per symbol) | `MAKER_EDGE_MAX_CONCURRENT` |
| `max_outlay_usd` | `contracts * 0.01` | Hard cap |
| `order_type` | maker / post-only GTC | Prefer maker fee path |

### 6.2 Settlement / PnL

- Win: settle $1.00 on owned side → approx `contracts * (1 - 0.01)` gross before fees (paper used full `contracts` credit).
- Loss: lose outlay on filled size.
- Partial fills: score only filled qty; do not assume remainder.

### 6.3 Risk / ops

- Bankroll path can dip below start (4m min_eq ~$7.6k on $10k at 2000@$0.01) — size for drawdown.
- Burst liquidity: many cycles show ≥2000 contracts in 1s bursts at 0.01 — good for full size, also adverse selection risk.
- Adverse selection: winners may be thinner; cum gate / maker queue is the honesty layer.
- Kalshi API rate limits during bulk pulls — live path should use WS + existing broker, not day-pull scripts.

---

## 7. Relation to existing live stack (file map)

| Area | Paths |
|------|--------|
| AES unified / Exp Scalp cutout | `backend/auto_entry_supervisor.py`, `backend/core/aes_btc15m_exp_scalp_cutout.py`, `docs/UNIFIED_AES_TICK_CONTRACT.md` |
| HWS exact-cent ask fire (different product) | same AES docs; `limit_close_price` resting close |
| Monitors | `backend/core/unified_15m_monitors.py`, `backend/monitor_manager.py` |
| Orders / fills | `backend/trade_manager.py`, `backend/trade_executor.py`, kalshi account sync |
| Auto-stop | `backend/active_trade_supervisor.py` — v1 may **disable** early stop (hold to expiry) |
| Lifecycle | `docs/TRADE_LIFECYCLE_AND_AUTO_STOP_CURRENT.md` |
| Cycle packages | `backend/core/cycle_packager.py`, `cycle_package_members.py`, `cycle_package.py` |
| Drive | `backend/core/cycle_gdrive_upload.py` |

---

## 8. Tooling & artifact index

### Scripts

| Script | Role |
|--------|------|
| `scripts/backtest/pull_kxbtc15m_public_trades_day_csv.py` | Day tape pull |
| `scripts/backtest/package_month_public_trades_to_drive.py` | Month tape archive → Drive |
| `scripts/backtest/run_kxbtc15m_longshot_month.py` | First-≤$0.02 month (legacy) |
| `scripts/backtest/run_kxbtc15m_longshot_limit_sweep.py` | Multi-limit ≤ sweep |
| `scripts/backtest/kxbtc15m_exact_cent_cum_size_span.py` | Exact-cent + cum vol gate |
| `scripts/backtest/kxbtc15m_week_maker_book_tape_sim.py` | Maker book+tape week |
| `scripts/backtest/fetch_kxbtc15m_market_results_bulk.py` | Offline `market_result` cache |
| `scripts/backtest/export_cycle_package_variant.py` | Full → external package SKU |
| `scripts/backtest/package_cycles.py` | Seal due cycles |

### Result CSVs (authoritative)

Under `backend/data/historical_data/kalshi_public_trades/`:

- `KXBTC15M_longshot_exact_cent_sweep_2026-06-01_2026-09-30_et.csv`
- `KXBTC15M_exact_cent_ttc30s_limit0.01_2026-06-01_2026-09-30_et.csv`
- `KXBTC15M_longshot_exact_cent_sweep_2026-08-30_2026-09-05_et.csv`
- `KXBTC15M_week_maker_book_tape_2026-08-30_2026-09-05.csv`
- `KXBTC15M_week_maker_book_tape_2500_2026-08-30_2026-09-05.csv`
- `KXBTC15M_longshot_limit_sweep_2026-06-01_2026-09-30_et.csv` (negative control)
- Month winners: `KXBTC15M_longshot_winners_2026-0{6,7,8,9}_et.csv`
- Cache: `.cache_market_result_by_ticker.json`

YTD cum2500 (done):  
`KXBTC15M_exact_cent_cum2500_limit0.01_2026-01-01_2026-10-17_et*.csv` (local / artifacts; not committed).

### Packages

`backend/data/historical_data/backtesting_data/KXBTC15M/2026/{YYYY_MM_MON}/{TICKER}.tar.xz`

---

## 9. Open questions / decisions for the building agent

1. **New strategy row vs monitor-only flags** — recommend new strategy name + seed migration (tenant schema parity).
2. **Cutout process vs unified pool** — dual resting + cancel-other is stateful; cutout may be cleaner.
3. **Partial fills** — live must handle; paper week was mostly full size.
4. **ETH (`KXETH15M`)** — tapes exist for sample weeks; do not assume same edge without a dedicated sweep.
5. **Legal / ToS** if selling cycle packages externally — see `docs/HISTORICAL_CYCLE_DATA_PRODUCT.md` (gate before commercial SKU).
6. **YTD @ 2500** — wait for CSV before locking production size; week maker already scales 2000→2500 with same win count.

---

## 10. Suggested implementation phases

### Phase A — Spec lock (this doc + YTD CSV)

- Confirm v1 params after YTD cum2500 lands.
- Write monitor column defaults + strategy seed migration plan (no live money).

### Phase B — Paper / shadow on live books

- Shadow: compute what dual-rest would have done each cycle from live OB + public trades WS (no orders).
- Compare to sealed packages for the same tickers.

### Phase C — Paper trades through TM/TE

- Place paper GTCs; exercise cancel-other; settlement path with real `market_result` only.

### Phase D — Live soak (real money — requires explicit owner approval)

- One market, capped `N`, maker only, kill switch via existing drawdown / system_state.
- Log queue depth, time-to-first-fill, partial rate, fee reality.

### Phase E — Backtest harness promotion

- Promote exact-cent + TTC grids into checked-in CLIs (parity with cum-size + maker scripts).
- Point `scripts/backtest/README.md` at this strategy family.

---

## 11. Non-goals for first ship

- Cross-symbol portfolio optimization / shared bankroll caps across underlyings.
- Using proprietary strike probs as entry filter for this edge (tape/book only for v1; lean commodities leave prob/diff NULL when ladder absent).
- Selling data until ToS review complete.
- Replacing Expiration Scalp / HWS — parallel product.

---

## 12. Revision

| Date | Note |
|------|------|
| 2026-10-17 | Initial handoff from exact-cent / maker / package-v4 research session. YTD cum2500 still in flight. |
| 2026-10-19 | Live place path: open_time arm + prefetch/rewarm + parallel dual post; log fire/send/ack lags. |
| 2026-10-20 | Multi-symbol: ETH + GOLD/SILVER/WTI commodities; co-opening place; cutout `MAKER_EDGE_SYMBOLS`. |
