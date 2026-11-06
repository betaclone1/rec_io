# Zero-latency pipeline (VER4 pillar)

```yaml
doc_id: ZERO_LATENCY_PIPELINE
status: active_pillar
initiative: VER4_DEVELOPMENT
owner_direction: V4_DIRECTION.md
rule: .cursor/rules/00-zero-latency-baseline.mdc
agent: .cursor/rules/ver4.mdc (@ver4)
started: 2026-11-06
not: strategy redesign of Exp Scalp / HTC verification product
```

External market data must traverse Rec **without ambient internal delay**. Confirmation waits are strategy product (verification dwell), not shared-pipe culture.

## Why this is a v4 pillar

v3 grew verification loops, coalesce, and 1 Hz caps as “good citizenship” under CPU pressure and confirmation-first strategies. That was valid for Exp Scalp / HTC-style gates. It became harmful when first-touch paths (Upper Tail rail mimic, honest venue→consumer latency) needed wire speed on the **same** pipe.

The OB live cutover (dedicated `kalshi_orderbook_live`, raw venue stamps, rail detect on apply) proved the venue floor is ~tens of ms; remaining lag was mostly **ours**. VER4 makes zero internal latency the default system posture so host-split and 15m expansion do not re-bake 50–200ms–1s habits into new tiers.

## Baseline (non-negotiable)

1. Wire → apply → Redis/live_state → consumers as fast as the source allows.
2. No strategy-specific pipeline cutouts that keep the shared feed slow “for Exp Scalp.”
3. Intentional delay = monitor/strategy columns (`entry_verification_*`, `stop_verification_*`, busy-book reset). Not `TRADEFLOW_*_TRIGGER_MIN_SEC` defaults.
4. Raising coalesce / Hz / regen env vars is an **explicit ops override** after measuring CPU/flood — document why.

## Code defaults (as of 2026-11-06)

| Knob | Default | Notes |
|------|---------|--------|
| `TRADEFLOW_LIVE_STATE_TRIGGER_MIN_SEC` | `0` | AES/ATS wake coalesce |
| `TRADEFLOW_ORDERBOOK_TRIGGER_MIN_SEC` | `0` | OB wake coalesce |
| `MARKET_WATCHDOG_PUBLISH_COALESCE_MS` | `0` | Fallback when immediate flush off |
| `SYMBOL_HOT_PUBLISH_MAX_HZ` | `0` | Uncapped symbol live_state publish |
| `STRIKE_REGEN_MIN_INTERVAL_SEC` | `0` | Regen as inputs change |
| UT rail emit | on **apply** | Flush only persists depth + live_state hint |
| `UPPER_TAIL_POLL_SEC` | `0.25` | Housekeeping only; crypto place is rail-evented |

Immediate OB flush remains default **on**. Dedicated crypto 15m OB owner: `REC_KALSHI_OB_LIVE_OWNER` (default on) → `kalshi_orderbook_live`.

## Still valid (not “latency bias”)

| Mechanism | Role |
|-----------|------|
| Entry/stop verification dwell | Strategy product (Exp Scalp, HTC, HWS, …) |
| Exp Scalp busy-book verify reset | Anti-chop on that strategy |
| Failsafe polls (`AES_FAILSAFE_*`, LT failsafe) | Reliability if events miss |
| `TRADEFLOW_LANE_REEVAL_SEC` (default 1s) | Quiet-book **clock** re-check for window opens |
| Venue/network floor | Outside process control |
| Latest-wins drop of intermediate states | Prefer newest; do not FIFO-delay |

## Related system docs

- `.cursor/rules/00-zero-latency-baseline.mdc`
- `docs/REALTIME_BACKBONE.md` §0.1
- `docs/ORDERBOOK_HOT_CACHE.md`
- `docs/UNIFIED_AES_TICK_CONTRACT.md`
- `docs/UPPER_TAIL_STRATEGY.md` (rail path)

## Open for later VER4 design

- Latency budget when `live_data_collection_and_archiving` and `automated_trading` split across hosts (`V4_DIRECTION.md` §1) — split must not reintroduce ambient coalesce.
- Whether strike regen / symbol publish need **measured** prod caps under higher 15m symbol count (opt-in env only).
- Commodity tape paths remain source-bound; do not fake OB speed.

## Agent duty (@ver4)

When implementing or reviewing market-data / tradeflow / ingest changes: reject new non-zero defaults on the shared pipe; keep verification on strategy settings; update this file if defaults or ownership paths change.
