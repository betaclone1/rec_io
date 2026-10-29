# Subaccount Architecture (v4 pillar)

```yaml
doc_id: SUBACCOUNT_ARCHITECTURE
pillar: Subaccount Architecture
status: owner_direction
not: schema migration, REBALANCE algorithm spec, or shipped UI
parent: V4_DIRECTION.md
source: owner chat 2026-10-23
v3_bones: docs/PORTFOLIO_ACCOUNT_SYNC.md, docs/KALSHI_EXCHANGE_SHARDING.md, Monitor subaccount integration chat
first_move: sub_monitor_shape
rebalance: back_burner
former_name: Subaccount Workflow
```

v4.0 pillar for how portfolio capital is held in Kalshi/internal subaccounts, weighted from MTB Base, bound to monitors, sized, and controlled in the UI. Philosophy and constraints only until a design/migration doc is written.

### Sequencing (owner, 2026-10-23)

1. **First move — sub / monitor shape.** Trading vs non-trading roles on `subaccounts_*`, MTB membership, `% of MTB Base` (and where Base lives), monitor→SA binding (1:1 or small groups), bankroll pinned to SA base. Get this shape into schema + runtime wiring + Subaccounts panel basics.
2. **Back burner — REBALANCE and its implications.** Philosophy in §3 stays as direction. Do **not** prioritize REBALANCE algorithm, transfer orchestration, open-position freezes for rebalance, or dry-run IAT plans until the sub/monitor shape is implemented and stable.

---

## 1. Scope

| In this pillar | Priority | Related but separate |
|----------------|----------|----------------------|
| Trading vs non-trading SA roles, MTB membership | **first** | Host split / which machine runs Account Manager |
| MTB Base Value + per-SA % of Base → pinned bankroll | **first** | Upper/Lower Tail meter math (`PIN_UPPER_LOWER_TAIL.md`) |
| Monitor ↔ SA binding (1:1 or small groups) | **first** | Full frontend rewrite / tech stack |
| Dashboard Subaccounts panel (replaces Allocation) — shape/controls for weights + Base | **first** (read/edit before REBALANCE) | Hourly markets (deferred) |
| REBALANCE operator function | **back burner** | Postgres droplet / PG17 gate |

v4 emphasizes the **subaccount system** as how funds are held, allocated to monitors, and risk-gated. Combination of:

- **Kalshi native** — `(exchange_index, subaccount_number)` wallets, within-shard transfers, IAT across shards, create-sub per shard before funding/orders (`docs/KALSHI_EXCHANGE_SHARDING.md`).
- **Internal** — `users_*/subaccounts_*` (and paper twins), `monitor_list.subaccount`, allotment / rake / drawdown, hero aggregates from GASB (`docs/PORTFOLIO_ACCOUNT_SYNC.md`).

---

## 2. Operating philosophy

Philosophical change; mechanics ride bones already shipped (per-monitor SA routing, per-SA halt/rake, matrix balances).

**Siloed trading capital.** Individual monitors, or small groups of monitors, get **dedicated subaccounts** with their own discrete funds. Capital is not borrowed from a single shared “trading” wallet at order time.

**Master Trading Bankroll (term change).** MTB stops meaning “Kalshi subaccount #1” / one master trading wallet. In v4, **MTB = the sum of capital currently in subaccounts tagged as trading**. It is a system aggregate, not a single Kalshi slot label.

**Wallet roles** (exact column names TBD):

| Role (intent) | In MTB? | In monitor balancing? | Examples |
|---------------|---------|------------------------|----------|
| Unallocated Cash | yes | source for funding monitor SAs; not itself a monitor book | parking / deployment cash |
| Monitor or monitor-group trading SA | yes | yes — silo for that monitor or small set | per-monitor or small cohort |
| Non-trading holdings | no | no | CASH pass-through, reserve, tax, misc |

Non-trading subs are first-class wallets but **excluded** from MTB and from monitor balancing.

**MTB Base Value.** User-set dollar target for the trading set (e.g. $10,000). Distinct from **live MTB** (sum of balances in trading-tagged SAs). Live portfolio and live MTB can be above or below Base at any time.

**Per-sub base values.** Each trading sub’s policy target = **user-defined % of MTB Base Value** (not % of live MTB, not % of full Kalshi balance). Example: BTC Tail 20% of $10k Base → $2,000 SA target.

**Bankroll / sizing — HWM demoted.** Monitor working bankroll is **pinned to the subaccount’s base allocation** (`% × MTB Base Value`). Flow: MTB Base → SA base → monitors on that SA. Live Kalshi cash on the SA still governs spendable funds and (later) REBALANCE; the **policy** bankroll is the base allocation. v3 sticky `bankroll_current` / HWM-while-open may remain as a drawdown/risk overlay, not the capital center of gravity.

---

## 3. REBALANCE (direction only — back burner)

Owner direction for later. **Not** the first implementation target; see sequencing above.

Operator function. Snapshot live MTB and each trading SA vs its base. Move capital **only among trading-tagged SAs**; when live MTB exceeds MTB Base Value, push aggregate excess to **CASH (#0)**.

| Rule | Behavior |
|------|----------|
| Never auto-pull from non-trading | CASH, Reserve, Tax, Misc are not REBALANCE sources |
| Fund trading from non-trading | **Manual** operator transfer into a trading SA (typically Unallocated) |
| Live MTB ≥ Base | Aim each trading SA at `% × Base`; surplus → CASH #0 |
| Live MTB &lt; Base | Do not invent capital. Redistribute available live MTB toward relative weights — including **zeroing Unallocated** if needed — to max out monitor silos from what trading capital exists |

---

## 4. Hypothetical layout (example only — not shipping shape)

Illustrative snapshot:

| | |
|--|--|
| Kalshi total | $15,000 |
| Tax Savings (#2) | $1,000 (non-trading) |
| Reserve (#1) | $1,000 (non-trading) |
| CASH (#0) | $0 |
| Live MTB (implied) | $13,000 |
| **MTB Base Value** | **$10,000** |

Trading SA targets = % × $10k Base:

| # | Name | % of Base | Target $ | Notes |
|---|------|-----------|----------|--------|
| 4 | Unallocated Cash | (user / residual) | — | Excess buffer inside MTB |
| 5 | BTC Expiration Scalp | 25% | $2,500 | Exp Scalp kin + Exp Reversal |
| 6 | BTC Tail | 20% | $2,000 | BTC Tail mon |
| 7 | ETH Tail | 10% | $1,000 | |
| 8 | SOL Tail | 10% | $1,000 | |
| 9 | XRP Tail | 10% | $1,000 | |
| 10 | GOLD Tail | 5% | $500 | |
| 11 | SILVER Tail | 5% | $500 | |
| 12 | WTI Tail | 5% | $500 | |

REBALANCE in this snapshot (later): redistribute toward those targets; move **$3,000** live-MTB surplus over Base to CASH #0. Tax/Reserve/CASH never drained automatically.

Implications of the example:

- One SA can back a **small group** of related monitors (row 5).
- Tail rows are natural Upper/Lower Tail capital silos per underlying.
- Targets anchored to Base → profits above Base eligible to leave trading set without rewriting % weights.
- Legacy UI “Master Trading Bankroll” on Kalshi #1 does not match this map; slot numbers are free in the example.

---

## 5. UI — Subaccounts panel (replaces Allocation)

Primary operator control surface for this pillar.

v3 dashboard **Allocation** panel (desktop + mobile: `allocation-panel`, pie/bar of monitor allotment) is **replaced by a Subaccounts panel** that:

- Keeps the **same panel shape and graphic treatment**.
- Focuses on **trading-bankroll subaccounts** (the MTB set).
- **First-slice controls:** trading SA list, **% weights**, **MTB Base Value**, live-vs-target readouts, which monitors sit on which SA.
- **Later:** **REBALANCE** (back burner — §3).

Non-trading wallets may appear in a secondary view; they are not the primary dashboard control. Desktop and mobile both have Allocation today — **parity expected** unless a later note scopes one surface first.

Broader UI overhaul (tech stack, other pages) remains a separate top-line priority in `V4_DIRECTION.md`; this panel is the capital-architecture slice of that priority.

---

## 6. v3 bones this builds on

`monitor_list.subaccount`, Account Manager per-SA rake and drawdown, GASB as cash matrix source, reserved `category` / `base_value_format` / `base_value_factor`. Sticky HWM / `bankroll_current` exists but is not the v4 capital center of gravity (§2).

Host adjacency: trading hosts must speak Kalshi addresses correctly; Postgres remains system of record for internal SA parameters and aggregates.

---

## 7. Decisions and remaining open

### Closed (first-move capital shape — `20261027_0630` / `20261027_0700`)

| Question | Decision |
|----------|----------|
| MTB membership | `subaccounts_*.in_mtb BOOLEAN NOT NULL DEFAULT FALSE`. CASH / PRIMARY (and `id = 0`) stay out; other existing rows seeded in. |
| Weight | `subaccounts_*.mtb_weight_pct DOUBLE PRECISION NULL` — percent points of MTB Base (`20` = 20%). `NULL` = unweighted / residual Unallocated inside MTB. |
| Where MTB Base lives | `system_settings_*.mtb_base_value_cents INTEGER NULL` — portfolio-level. Distinct from per-SA `base_value` (rake HWM). |
| SA policy target $ | Derived: `round(mtb_base_value_cents * mtb_weight_pct / 100)` when both set (`mtb_target_cents` on `/api/subaccounts`). |
| Create default | New trading SAs insert with `in_mtb = TRUE` (never for id 0). |
| Account Manager | Desktop + mobile: portfolio MTB Base edit; per-SA in_mtb + weight; list shows Weight % / Target. |

### Still open — first move remainder

- Monitor ↔ SA binding for 1:1 and small groups.
- How monitor `bankroll` / allotment / `base_value_*` bind to SA policy target; demote sticky HWM for sizing.
- Whether drawdown halt keys off SA base / % of base (vs leftover HWM).
- Subaccounts panel: monitor membership chrome; richer live-vs-target UI.
- Paper vs live SA hygiene beyond column parity; multi-tenant ops polish.
- Shard provision for every trading SA on the relevant `exchange_index`.

### Back burner — REBALANCE

- Transfer order, open-position cash locks, pro-rata when live MTB &lt; Base.
- Interaction with automatic per-SA rake; dry-run / execute IAT path.
- REBALANCE chrome on the Subaccounts panel.
