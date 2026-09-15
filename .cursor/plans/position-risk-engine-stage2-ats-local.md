# Stage 2 — ATS + orderbook risk integration (local paper testing)

> **LOCAL IMPLEMENTATION AUTHORIZED in this chat only.**  
> Still forbidden: production deploy, push, release, production config/DB change, real orders, commits.  
> Canonical plan for implementation. Supersedes `.cursor/plans/position-risk-engine-stage2-local-ats-consume.md`.

## Outcome

Make the existing system-scoped `position_risk_engine` (PRE) an event-driven HWS stop-decision source while keeping `active_trade_supervisor` (ATS) the sole process allowed to authorize a close. Validate the complete path locally with paper positions and durable per-trade evidence before considering any live authority.

This deliberately combines the old roadmap's Stage 2 durable-data work with a **local paper-only authority harness**. It does not skip the dual-run evidence gate and does not grant PRE money authority.

## Ownership and event flow

```text
Kalshi watchdog (one WS owner)
  -> ordered L2 book events + public trades + health/gap/resync events
  -> durable risk stream
  -> PRE per-position actor
  -> versioned, idempotent RiskDecision
  -> ATS validates mode, lease, freshness, trade state and dedupe key
  -> TM owns cancel/close coordination
  -> TE is the only order submit/cancel process
  -> account sync/TM remain fill truth
```

- PRE never calls TM or TE and never mutates a trade close state.
- ATS remains the single stop authority and consumes at most one actionable decision generation per trade.
- Dedupe key: `(trade_id, remaining_position_generation, policy_version, decision_generation)`.
- Every state transition and rejection is durably joined to `trade_id`.
- Existing HWS profit-taking GTC remains separate. Stop processing first cancels/reconciles the GTC through TM, then liquidates only confirmed remaining quantity.

## First policy: executable liquidation value

The existing monitor `stop_loss_price` remains the operator's intended gross liquidation floor (for example `0.9000`). Stage 2 changes what is compared with it for opted-in HWS paper tests:

1. Compute the actual remaining contract count from TM/account-sync truth.
2. Walk executable whole-cent depth for that exact size.
   - Held YES consumes YES bids.
   - Held NO consumes implied NO bids derived from the canonical YES asks (`100 - YES ask`), without constructing a second independent book.
3. Emit quantity coverage, worst consumed price, gross liquidation VWAP, estimated taker fee, configured slippage reserve, and net liquidation value as separate fields.
4. The initial trigger compares **gross executable LVWAP** to `stop_loss_price`; fees and slippage are recorded and used in paper outcome analysis, not silently folded into the user's 0.9000 threshold.
5. Full-size coverage is required for the normal path. Partial coverage is not treated as a valid normal VWAP.

### Two trigger paths

- **Catastrophic:** full-size executable LVWAP is at least 3 whole cents below the floor on one valid book generation. Emit immediately. Public tape may accelerate confidence but can never veto this path.
- **Marginal:** LVWAP is below the floor but less than 3 cents below it for at least 250 ms and at least 3 distinct valid book generations. Public tape confirms when available; if tape is UNKNOWN, the policy result is `UNKNOWN` unless `book_only_enabled` is explicitly true.
- **Hysteresis:** after a marginal breach clears, require LVWAP at least 2 cents above the floor for 500 ms and 3 valid generations before rearming. A catastrophic decision remains latched until ATS accepts/rejects it or the position generation changes.
- **Coverage emergency:** insufficient full-size depth emits `DEPTH_INSUFFICIENT`, not a fabricated price. It is shadow-only in this stage and cannot close a trade.

All timing uses event timestamps plus monotonic receive time and distinct book generations—not loop counts.

## Public trades and data health

- Add Kalshi public `trade` subscription to the existing watchdog connection; PRE must not open another venue socket.
- Normalize aggressor inference, price, size, exchange timestamp, receive timestamp and sequence/cursor confidence into the same durable ordered contract as book events.
- Trade-flow clauses are three-valued: `TRUE`, `FALSE`, `UNKNOWN`. Missing or gapped tape is never zero activity.
- Book health includes source heartbeat, sequence continuity, resync generation, apply timestamp and publish timestamp.
- Any L2 gap, active resync, stale book (>500 ms initially), expired position lease, or mismatched remaining-position generation makes PRE `UNKNOWN` and prevents a new PRE-driven action.
- During local paper tests, ATS records that it would fall back to the unchanged legacy HWS floor path when PRE is `UNKNOWN`. The fallback executes only inside the paper harness. Future production fallback behavior is a separate approval decision.
- Watchdog, PRE and ATS each expose independent freshness/coverage alarms so a common-process failure cannot report itself healthy.

## Monitor settings

Add only three monitor-visible settings for HWS/High Water Test strategies:

| Setting | Type | Default | Allowed | Purpose |
|---|---|---:|---|---|
| `position_risk_mode` | enum | `legacy` | `legacy`, `shadow`, `paper` | Select legacy-only, durable comparison, or explicitly armed local paper authority. `paper` is rejected outside local environment and also requires the global paper kill-switch arm. |
| `position_risk_policy` | enum | `hws_lvw_v1` | versioned allowlist | Pins the policy contract used for replay and audit. |
| `position_risk_book_only_enabled` | bool | `false` | false/true | Allows marginal L2-only decisions when public tape is UNKNOWN; catastrophic valid-L2 path is unaffected. |

Retain existing `stop_loss_price`, `stop_verification_period`, `stop_verification_max_price`, `paper_trade`, HWS limit-close settings and size settings. For the new policy, the old verification fields are logged for comparison but do not control PRE persistence. Do not expose the 250 ms/3-generation/3-cent/2-cent/500 ms constants as monitor knobs in the first build; they belong to the versioned policy so testing stays comparable.

Required surfaces: schema migration (local apply OK), settings API validation, desktop and mobile controls with HWS-only visibility, trade snapshotting of all resolved values, and readable audit display. `paper` must require both monitor `paper_trade=true` and a local-only global arm; either off means no PRE action.

## Durable audit contract

For every open HWS trade, persist append-only events for enrollment, lease state, each material risk-state transition, legacy ATS evaluation, PRE evaluation, decision emit, ATS accept/reject/fallback, TM cancel/close command, TE paper order, partial/late fill, remaining-quantity generation, expiry and final outcome.

Each event includes trade/monitor/tenant/ticker IDs, policy version/hash, source sequence/resync generation, source/apply/evaluate/enqueue timestamps, L2 coverage and levels consumed, LVWAP fields, tape state/features, data-health reason, current floor, legacy result, PRE result, decision/dedupe IDs and downstream correlation IDs. Retention must outlive trade closure and be exportable in the cycle-recon package.

## Current HWS behavior matrix

| Mechanism | Stage 2 treatment |
|---|---|
| ATS sole stop authority | Retained |
| TM coordination and TE-only I/O | Retained and enforced for new path |
| Profit-taking GTC | Retained; cancel/reconcile before stop liquidation |
| Best-bid/broad mark floor comparison | Retained in `legacy`; compared durably in `shadow`; bypassed only in explicitly armed local `paper` mode |
| Interval/failsafe loop as primary decision driver | Replaced for PRE decisions by ordered book/trade events; low-rate reconciliation watchdog retained |
| Old stop verification fields | Retained for legacy; audit-only for `hws_lvw_v1` |
| Probability stop | Legacy/shadow only; not part of v1 L2 authority |
| AES `auto_trade` and STG pipeline gate controlling protection | Legacy unchanged; PRE paper protection uses independent health/arming gates |
| Flip-sell | Out of scope |
| Expiration Scalp, Momentum and other strategies | Completely unchanged |

## Local rollout sequence

1. **Durable shadow:** write the ordered risk stream and per-trade timelines; ATS records accept/reject/fallback but does not alter its current decisions.
2. **Replay:** run 59597, 59721, 81783, 82105 and 82098 where source fidelity exists, 59863 as supplemental, all frozen winning controls, plus synthetic gap/resync/stale/crash/duplicate/partial-fill/late-GTC scenarios.
3. **Paper dual-run:** ATS feeds both legacy and PRE decisions through the full TM/TE paper lifecycle, with only one selected as the simulated authority per run.
4. **Local live-market paper:** explicitly arm selected HWS paper monitors; prove every open position has a healthy lease and durable timeline. No real-account order is permitted.
5. Stop at the evidence report. Production or real-money authority requires a separate plan and explicit approval.

## Acceptance gates

- 100% of open HWS positions across tenants have a current lease; TM-open to protected p99 <=250 ms.
- Applied-book to PRE decision p95 <=15 ms and p99 <=30 ms; decision to durable enqueue p95 <=10 ms.
- No unrecorded L2 gaps/resyncs; stale or gapped input produces zero PRE actionable decisions.
- Zero duplicate ATS close authorizations across crash/retry/redelivery tests.
- Zero PRE/TM/TE real-order calls and zero changes to non-HWS strategy behavior.
- 100% of tested trades have a complete durable PRE-versus-legacy timeline through final outcome.
- On frozen loss fixtures, paper PRE reduces realized loss versus legacy without worsening the intended 0.9000 threshold breach latency; report fill feasibility rather than claiming a 0.9000 fill.
- On winning controls, PRE false-stop count is zero for the initial gate. If sample size is insufficient, remain shadow-only.
- Kill switch disables PRE consumption in ATS within one event cycle; ATS reverts to unchanged legacy evaluation and records the transition.
- PRE/watchdog/stream restart recovery restores coverage p99 <=2 seconds without duplicate intent.

## Paper-trade gate (local)

Before arming PRE consume: every local `monitor_list_*` row must be `paper_trade=TRUE`. Evidence under `backend/data/position_risk/monitor_paper_trade_audit_{before,after}_fix.json`. Production/remote DB must never be mutated.
