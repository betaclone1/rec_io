# Core: Tail bias probe → sized Upper / Lower Tail (v4)

```yaml
doc_id: CORE_TAIL_BIAS_STRATEGY
status: core_owner_direction
priority: main_v4_strategies
not: schema_spec, threshold_calibration, or shipped automation
source: owner chat 2026-10-31 (prod probe grid + methodology)
related:
  - PIN_UPPER_LOWER_TAIL.md          # earlier single-meter pin; this doc is the live operating model
  - SUBACCOUNT_ARCHITECTURE.md       # probe SA vs trading bankroll silos
  - docs/UPPER_TAIL_STRATEGY.md      # includes production crypto hot-path latency (2026-11-02)
  - docs/LOWER_TAIL_STRATEGY.md
  - docs/BACKTESTING.md §2.4         # UT latency baseline for new backtests
  - .cursor/rules/00-15m-cycle-bedrock.mdc
bedrock: 15m floor-strike cycle (open ≈ 50/50 → path to one extreme → possible reverse)
```

This is **CORE v4 functionality**. Upper Tail and Lower Tail, driven by a live per-asset bias meter from continuous dual-tail probing, are the **main strategies**.

Agents treat the sections below as product law for later plans and implementation. Do not invent calibrated thresholds, schema, or UI until those land in design/migration docs that cite this file.

**Live crypto UT execution latency:** see `docs/UPPER_TAIL_STRATEGY.md` § *Production crypto hot path* — dedicated priority OB socket on the **same event loop** (isolated thread hard-disabled after 2026-11-03 outage). New backtests matching that design must not assume multi-second orderbook lag (`docs/BACKTESTING.md` §2.4). Prod may still be on the priority-off emergency build until the same-loop path is deployed.

---

## 1. What we are measuring

Every tracked crypto and commodity 15m market has a **regime**: after open, the path drives quotes toward one extreme; settlement either **sticks with the favorite** or **pays the longshot** (including extreme-then-reverse anomalies). See cycle bedrock.

A **monitor pairing** on each asset — one Upper Tail + one Lower Tail — is a live readout of that regime:

| Probe side | Asks | High win rate means |
|------------|------|---------------------|
| **Upper Tail** (~$0.99) | Does the favorite rail usually settle? | Continuation / favorite-holds regime |
| **Lower Tail** (~$0.01) | Do longshots pay above the penny baseline? | Anomaly / reversal-rich regime |

The pair is **one market meter with two rails**, not two unrelated strategies. Relative win rates grade which end of that asset’s book is currently “fat.”

---

## 2. Live probe layer (instrumentation)

**Method:** For each tracked asset, run small-contract live trading on **both** tails using dedicated Kalshi subaccounts (today: 1 contract per side per asset on user `0001`).

**Purpose:** Continuous sampling of **win/loss rates** on each side. This is a **core live data function**, not a P&L book.

**Non-goals for the probe:**

- Do **not** optimize or judge the probe by returns, PnL, or bankroll growth.
- Probe capital exists only so fills and settlements are **real** (venue truth, not paper fiction).

**Capital shape (target):**

- Consolidate probe monitors onto a **dedicated probe subaccount**, apart from the trading bankroll.
- That subaccount stays **relatively static**; only occasional rebalancing to top up after probe attrition.
- Sized production capital lives on **separate trading subaccounts** (see `SUBACCOUNT_ARCHITECTURE.md`).

v3/prod interim: the current 1-lot UT/LT grid across SAs 5–18 is the working probe; consolidation onto one probe SA is later housekeeping, not a change to the methodology.

---

## 3. Bias meter (rolling windows)

From probe outcomes, compute per-asset, per-side win rates over a **combination of moving windows** (owner intent: e.g. **60d / 30d / 7d** — exact combo and weighting TBD).

**Baseline goals (order of magnitude; calibrate later):**

| Side | Approx break-even / goal WR |
|------|-----------------------------|
| Upper Tail | ~**99%** (in practice maybe ~99.2%) |
| Lower Tail | ~**1%** (in practice maybe ~1.2%) |

When an asset’s UT or LT rolling WR **exceeds its goal**, that side is graded as biased / lean-powered toward that end.

**Strength** = how far the measured WR sits above the goal (and how consistent that is across the MA combo). Exact strength function TBD; direction is clear: stronger excess → more size.

---

## 4. Production arm (sized trading)

**Activation:** When the meter grades a side above goal, that asset’s **higher-bankroll live trading monitor** for that side activates.

**Sizing:** Position size reflects **bias strength**, not probe contract size.

**While production is on:** the probe **keeps running**. The meter remains the signal; trading capital follows the grade.

**Dead / weak zone:** If neither side clears its goal (or the MA combo is mixed / flat), do not size from the meter — probe-only watch.

---

## 5. Loop (one picture)

```text
per asset:
  live 1-lot UT + LT probe  →  W/L only (ignore PnL)
        ↓
  rolling WR (e.g. 60d / 30d / 7d) vs UT~99% / LT~1% goals
        ↓
  regime grade + strength
        ↓
  activate sized UT or LT trading SA/monitor (or neither)
```

---

## 6. Relationship to earlier pin

`PIN_UPPER_LOWER_TAIL.md` (2026-10-23) framed a **single** 99¢-side win-rate meter vs 99% (above → UT, below → LT). That pin still holds as the **economic break-even intuition**.

This document is the **operating model**: dual live probes, separate WR goals on each rail, probe SA vs trading bankroll, MA combo, and strength-gated sized arms. Prefer this file when implementing v4 strategy automation.

---

## 7. Open (do not invent)

- Exact WR goals and strength → size mapping
- MA combination weights and dead-zone rules
- Schema / tables for probe outcomes and bias grades
- Probe SA number and rebalance policy details
- Which symbols are always-on in the first production set
- UI surfacing of the bias meter

Record answers in dated design/migration notes that link here.
